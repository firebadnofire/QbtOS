#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed update, release metadata, and state-generation support for qbtOS."""

import datetime
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

STATE_ROOT = Path(os.environ.get("QBTOS_STATE_ROOT", "/config/qbtos"))
STATE_CONTAINER = STATE_ROOT.parent / "qbtos-state"
BACKUP_LINK = STATE_CONTAINER / "pre-update"
UPDATE_ROOT = STATE_ROOT / "updates"
RELEASE_FILE = Path(os.environ.get("QBTOS_RELEASE_FILE", "/etc/qbtos-release"))
SCHEMA_FILE = Path(os.environ.get("QBTOS_SCHEMA_FILE", "/usr/share/qbtos/state-schema"))
RAUC = os.environ.get("QBTOS_RAUC", "/usr/bin/rauc")
RAUC_KEYRING = Path(os.environ.get("QBTOS_RAUC_KEYRING", "/etc/rauc/keyring.pem"))
GPGV = os.environ.get("QBTOS_GPGV", "/usr/bin/gpgv")
GPG_KEYRING = Path(os.environ.get(
    "QBTOS_GPG_KEYRING", "/etc/qbtos/update-signing.gpg"))
FW_PRINTENV = os.environ.get("QBTOS_FW_PRINTENV", "/usr/sbin/fw_printenv")
MAX_FEED_BYTES = 128 * 1024
MAX_CHECKSUM_BYTES = 256 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
VERSION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-rev([1-9][0-9]*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    pass


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_write_bytes(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_json(path, value):
    atomic_write(path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def read_release(path=RELEASE_FILE):
    values = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    except OSError:
        pass
    try:
        revision = int(values.get("QBTOS_REVISION", "0"))
    except ValueError:
        revision = 0
    return {
        "version": values.get("QBTOS_VERSION", "development"),
        "build_date": values.get("QBTOS_BUILD_DATE", "unknown"),
        "revision": revision,
        "source_tag": values.get("QBTOS_SOURCE_TAG", "unreleased"),
        "commit": values.get("QBTOS_COMMIT", "unknown"),
        "compatible": values.get("QBTOS_COMPATIBLE", "qbtos-rpi4"),
        "channel": values.get("QBTOS_CHANNEL", "stable"),
    }


def _https_url(value, filename):
    if not isinstance(value, str) or len(value) > 2048:
        raise UpdateError("update URL is invalid")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise UpdateError("update URLs must be HTTPS and must not contain credentials")
    if parsed.fragment or Path(parsed.path).name != filename:
        raise UpdateError("update URL filename does not match the manifest")
    return value


def validate_feed_url(value):
    return _https_url(value, "latest.json")


def validate_feed(document, current=None, *, allow_downgrade=False):
    if not isinstance(document, dict) or document.get("schema") != 1:
        raise UpdateError("unsupported update-feed schema")
    current = current or read_release()
    required_strings = (
        "version", "build_date", "source_tag", "commit", "compatible", "channel",
        "bundle_filename", "image_filename", "checksum_filename",
        "bundle_sha256", "image_sha256", "bundle_url", "image_url",
        "checksum_url",
    )
    if any(not isinstance(document.get(key), str) for key in required_strings):
        raise UpdateError("update feed has missing or invalid string fields")
    if not isinstance(document.get("revision"), int) or document["revision"] <= 0:
        raise UpdateError("update revision must be a positive integer")
    match = VERSION_RE.fullmatch(document["version"])
    if not match:
        raise UpdateError("update version is malformed")
    try:
        datetime.date.fromisoformat(document["build_date"])
    except ValueError as error:
        raise UpdateError("update build date is invalid") from error
    if match.group(1) != document["build_date"] or int(match.group(2)) != document["revision"]:
        raise UpdateError("update version fields disagree")
    if document["source_tag"] != f"revision-{document['revision']}":
        raise UpdateError("update source tag disagrees with revision")
    if not re.fullmatch(r"[0-9a-f]{40}", document["commit"]):
        raise UpdateError("update commit is not a full SHA")
    if document["compatible"] != current.get("compatible", "qbtos-rpi4"):
        raise UpdateError("update is for an incompatible board")
    if document["channel"] != current.get("channel", "stable"):
        raise UpdateError("update channel does not match")
    version = document["version"]
    if document["bundle_filename"] != f"{version}.raucb" or \
            document["image_filename"] != f"{version}.img.zst" or \
            document["checksum_filename"] != f"{version}.sha256":
        raise UpdateError("update artifact filename is malformed")
    if not SHA256_RE.fullmatch(document["bundle_sha256"]) or \
            not SHA256_RE.fullmatch(document["image_sha256"]):
        raise UpdateError("update checksum is malformed")
    for key in ("bundle_size", "image_size"):
        if not isinstance(document.get(key), int) or document[key] <= 0:
            raise UpdateError(f"{key} must be a positive integer")
    if document["bundle_size"] > MAX_BUNDLE_BYTES:
        raise UpdateError("update bundle exceeds the download limit")
    _https_url(document["bundle_url"], document["bundle_filename"])
    _https_url(document["image_url"], document["image_filename"])
    _https_url(document["checksum_url"], document["checksum_filename"])
    if not allow_downgrade and document["revision"] < int(current.get("revision", 0)):
        raise UpdateError("update downgrade refused")
    return dict(document)


def fetch_feed(url, *, opener=urllib.request.urlopen):
    _https_url(url, "latest.json")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    context = ssl.create_default_context()
    try:
        response = opener(request, timeout=20, context=context)
        data = response.read(MAX_FEED_BYTES + 1)
    except (OSError, ValueError) as error:
        raise UpdateError(f"unable to fetch update feed: {error}") from error
    if len(data) > MAX_FEED_BYTES:
        raise UpdateError("update feed is too large")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise UpdateError("update feed is not valid JSON") from error


def _status_path(root=UPDATE_ROOT):
    return Path(root) / "status.json"


def update_status(root=UPDATE_ROOT):
    try:
        return json.loads(_status_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"phase": "idle", "progress": 0, "message": "No update operation running"}


def set_update_status(phase, progress, message, *, root=UPDATE_ROOT, **extra):
    value = {"phase": phase, "progress": int(progress), "message": str(message)[:500]}
    previous = update_status(root)
    for key in ("last_checked_at", "available_version", "available_revision"):
        if key in previous:
            value[key] = previous[key]
    value.update(extra)
    write_json(_status_path(root), value)


def verify_release_checksums(document, *, root=UPDATE_ROOT,
                             opener=urllib.request.urlopen,
                             runner=subprocess.run,
                             keyring=GPG_KEYRING):
    """Verify the supplemental OpenPGP signature and bind it to the feed."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    keyring = Path(keyring)
    if not keyring.is_file():
        raise UpdateError("OpenPGP update verification key is unavailable")
    request = urllib.request.Request(
        document["checksum_url"], headers={"Accept": "application/pgp-signature"})
    try:
        response = opener(request, timeout=20, context=ssl.create_default_context())
        signed = response.read(MAX_CHECKSUM_BYTES + 1)
    except (OSError, ValueError) as error:
        raise UpdateError(f"unable to fetch signed release checksums: {error}") from error
    if not signed or len(signed) > MAX_CHECKSUM_BYTES:
        raise UpdateError("signed release checksum file is empty or too large")

    signed_path = root / document["checksum_filename"]
    signed_pending = root / f".{document['checksum_filename']}.pending"
    atomic_write_bytes(signed_pending, signed)
    descriptor, clear_name = tempfile.mkstemp(prefix=".checksums.", dir=root)
    os.close(descriptor)
    os.unlink(clear_name)
    clear_path = Path(clear_name)
    try:
        result = runner([
            GPGV, "--keyring", str(keyring), "--output", str(clear_path),
            str(signed_pending),
        ], timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False)
        if result.returncode != 0 or not clear_path.is_file():
            signed_pending.unlink(missing_ok=True)
            raise UpdateError("OpenPGP release checksum signature verification failed")
        entries = {}
        for line in clear_path.read_text(encoding="ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", line)
            if not match or match.group(2) in entries:
                signed_pending.unlink(missing_ok=True)
                raise UpdateError("signed release checksum content is malformed")
            entries[match.group(2)] = match.group(1)
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        signed_pending.unlink(missing_ok=True)
        raise UpdateError("unable to verify signed release checksums") from error
    finally:
        clear_path.unlink(missing_ok=True)

    expected_names = {
        document["image_filename"], document["bundle_filename"],
        f"{document['version']}.manifest.json",
    }
    if set(entries) != expected_names:
        signed_pending.unlink(missing_ok=True)
        raise UpdateError("signed release checksum set is incomplete or unexpected")
    if entries[document["bundle_filename"]] != document["bundle_sha256"] or \
            entries[document["image_filename"]] != document["image_sha256"]:
        signed_pending.unlink(missing_ok=True)
        raise UpdateError("update feed disagrees with signed release checksums")
    os.replace(signed_pending, signed_path)
    set_update_status("verified", 0,
                      "OpenPGP release checksums verified", root=root)
    return entries


def download_bundle(document, *, root=UPDATE_ROOT, opener=urllib.request.urlopen):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / document["bundle_filename"]
    partial = root / f".{document['bundle_filename']}.part"
    expected_size = document["bundle_size"]
    existing = partial.stat().st_size if partial.exists() else 0
    if existing > expected_size:
        partial.unlink()
        existing = 0
    headers = {"Accept": "application/octet-stream"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(document["bundle_url"], headers=headers)
    context = ssl.create_default_context()
    try:
        response = opener(request, timeout=30, context=context)
        response_status = getattr(response, "status", None)
        if response_status is None:
            response_status = response.getcode()
        if existing and response_status != 206:
            existing = 0
        mode = "ab" if existing else "wb"
        written = existing
        with partial.open(mode) as stream:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                written += len(block)
                if written > expected_size or written > MAX_BUNDLE_BYTES:
                    raise UpdateError("update download exceeded its declared size")
                stream.write(block)
                set_update_status(
                    "downloading", written * 100 // expected_size,
                    "Downloading signed update bundle", root=root,
                    downloaded=written, total=expected_size)
            stream.flush()
            os.fsync(stream.fileno())
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except OSError as error:
        set_update_status("interrupted", existing * 100 // expected_size,
                          "Download interrupted; partial data retained", root=root)
        raise UpdateError(f"update download interrupted: {error}") from error
    if partial.stat().st_size != expected_size:
        set_update_status("interrupted", partial.stat().st_size * 100 // expected_size,
                          "Download incomplete; partial data retained", root=root)
        raise UpdateError("update download ended before its declared size")
    digest_builder = hashlib.sha256()
    with partial.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest_builder.update(block)
    digest = digest_builder.hexdigest()
    if digest != document["bundle_sha256"]:
        partial.unlink(missing_ok=True)
        set_update_status("failed", 0, "Downloaded bundle checksum mismatch", root=root)
        raise UpdateError("downloaded bundle checksum mismatch")
    os.replace(partial, final)
    set_update_status("downloaded", 100, "Bundle downloaded and checksum verified",
                      root=root, filename=final.name)
    return final


def active_slot(cmdline_path=Path("/proc/cmdline")):
    try:
        cmdline = Path(cmdline_path).read_text(encoding="ascii")
    except OSError:
        return "unknown"
    match = re.search(r"(?:^|\s)rauc\.slot=([AB])(?:\s|$)", cmdline)
    return match.group(1) if match else "unknown"


def inactive_slot(slot):
    if slot == "A":
        return "B"
    if slot == "B":
        return "A"
    raise UpdateError("active RAUC slot could not be determined")


def choose_boot_slot(order, attempts):
    """Model the checked-in U-Boot script's limited-attempt slot selection."""
    remaining = dict(attempts)
    for slot in order.split():
        if slot in {"A", "B"} and int(remaining.get(slot, 0)) > 0:
            remaining[slot] = int(remaining[slot]) - 1
            return slot, remaining
    return None, remaining


def bootloader_state(runner=subprocess.run):
    values = {}
    for name in ("BOOT_ORDER", "BOOT_A_LEFT", "BOOT_B_LEFT"):
        result = runner([FW_PRINTENV, "-n", name], text=True, timeout=10,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        values[name.lower()] = result.stdout.strip() if result.returncode == 0 else "unknown"
    return values


def _ignore_update_data(directory, names):
    del directory
    return {name for name in names if name == "updates"}


def _schema_of(root):
    try:
        return int((Path(root) / "state/schema-version").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 1


def validate_state(root, expected_schema):
    root = Path(root)
    if not root.is_dir() or _schema_of(root) != expected_schema:
        raise UpdateError("state schema validation failed")
    settings = root / "settings.json"
    if settings.exists():
        try:
            value = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UpdateError("qbtOS settings do not parse") from error
        if not isinstance(value, dict) or value.get("version") != 1:
            raise UpdateError("qbtOS settings version is unsupported")
    return True


def ensure_generation_layout(root=STATE_ROOT, container=STATE_CONTAINER):
    root = Path(root)
    container = Path(container)
    if root.is_symlink():
        generation = root.resolve()
        generations = container / "generations"
        generations.chmod(0o711)
        generation.chmod(0o711)
        return generation
    container.mkdir(parents=True, exist_ok=True)
    generations = container / "generations"
    generations.mkdir(mode=0o711, exist_ok=True)
    generations.chmod(0o711)
    generation = generations / "bootstrap"
    if generation.exists():
        raise UpdateError("bootstrap state generation already exists")
    if root.exists():
        os.replace(root, generation)
    else:
        generation.mkdir(mode=0o711)
    generation.chmod(0o711)
    temporary_link = root.parent / ".qbtos.current"
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(generation)
    os.replace(temporary_link, root)
    return generation


def prepare_state_backup(root=STATE_ROOT, container=STATE_CONTAINER):
    current = ensure_generation_layout(root, container)
    container = Path(container)
    existing = container / "pre-update"
    if existing.is_symlink() and existing.resolve().is_dir():
        return existing.resolve()
    generations = container / "generations"
    backup = Path(tempfile.mkdtemp(prefix="pre-update-", dir=generations))
    shutil.copytree(current, backup, dirs_exist_ok=True, symlinks=False,
                    ignore=_ignore_update_data)
    temporary = container / ".pre-update"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(backup)
    os.replace(temporary, container / "pre-update")
    return backup


def migrate_state(target_schema, migrations=None, *, root=STATE_ROOT,
                  container=STATE_CONTAINER):
    migrations = migrations or {}
    root = Path(root)
    container = Path(container)
    current = ensure_generation_layout(root, container)
    current_schema = _schema_of(current)
    source = current
    if current_schema == target_schema:
        (current / "state").mkdir(parents=True, exist_ok=True)
        atomic_write(current / "state/schema-version", f"{target_schema}\n")
        validate_state(current, target_schema)
        return current
    if current_schema > target_schema:
        backup_link = container / "pre-update"
        if not backup_link.is_symlink():
            raise UpdateError("rollback state backup is unavailable")
        source = backup_link.resolve()
        if _schema_of(source) > target_schema:
            raise UpdateError("rollback state backup is too new")
        current_schema = _schema_of(source)
    generations = container / "generations"
    candidate = Path(tempfile.mkdtemp(prefix="candidate-", dir=generations))
    try:
        shutil.copytree(source, candidate, dirs_exist_ok=True, symlinks=False,
                        ignore=_ignore_update_data)
        while current_schema < target_schema:
            migration = migrations.get(current_schema)
            if migration is None:
                raise UpdateError(f"missing state migration from schema {current_schema}")
            migration(candidate)
            current_schema += 1
        (candidate / "state").mkdir(parents=True, exist_ok=True)
        atomic_write(candidate / "state/schema-version", f"{target_schema}\n")
        validate_state(candidate, target_schema)
        candidate.chmod(0o711)
        temporary_link = root.parent / ".qbtos.next"
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(candidate)
        os.replace(temporary_link, root)
        return candidate
    except Exception:
        shutil.rmtree(candidate, ignore_errors=True)
        raise


def target_schema(path=SCHEMA_FILE):
    try:
        value = int(Path(path).read_text(encoding="ascii").strip())
    except (OSError, ValueError) as error:
        raise UpdateError("system state-schema version is invalid") from error
    if value <= 0:
        raise UpdateError("system state-schema version must be positive")
    return value


def install_bundle(document, *, root=UPDATE_ROOT, popen=subprocess.Popen,
                   cmdline_path=Path("/proc/cmdline")):
    root = Path(root)
    slot = active_slot(cmdline_path)
    target = inactive_slot(slot)
    if target == slot:
        raise UpdateError("active slot was selected as update target")
    bundle = root / document["bundle_filename"]
    if not bundle.is_file():
        raise UpdateError("verified update bundle has not been downloaded")
    verification = subprocess.run(
        [RAUC, "info", f"--keyring={RAUC_KEYRING}", str(bundle)],
        text=True, timeout=60, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False)
    if verification.returncode != 0:
        raise UpdateError("RAUC signature verification failed")
    prepare_state_backup()
    pending = {
        "version": document["version"], "revision": document["revision"],
        "source_slot": slot, "target_slot": target, "phase": "installing",
    }
    write_json(root / "pending.json", pending)
    set_update_status("installing", 0, f"Installing signed bundle to slot {target}", root=root)
    command = [RAUC, "install", str(bundle)]
    process = popen(command, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, bufsize=1)
    messages = []
    for line in process.stdout:
        safe = line.strip()[:500]
        if safe:
            messages.append(safe)
            messages = messages[-20:]
            set_update_status("installing", 50, safe, root=root, log=messages)
    returncode = process.wait()
    if returncode != 0:
        set_update_status("failed", 0, "RAUC rejected or failed the bundle installation",
                          root=root, log=messages)
        raise UpdateError("RAUC bundle installation failed")
    pending["phase"] = "awaiting-reboot"
    write_json(root / "pending.json", pending)
    set_update_status("awaiting-reboot", 100,
                      f"Slot {target} installed; explicit reboot required", root=root)
    return target
