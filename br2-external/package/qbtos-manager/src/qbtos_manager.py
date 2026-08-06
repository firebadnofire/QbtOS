#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTPS-only setup and status service for the qbtOS development image."""

import base64
import binascii
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
import pwd
import re
import secrets
import ssl
import subprocess
import tempfile
import time
from pathlib import Path

import qbtos_update

STATE_ROOT = Path(os.environ.get("QBTOS_STATE_ROOT", "/config/qbtos"))
SETTINGS = STATE_ROOT / "settings.json"
INSTALLED = STATE_ROOT / "state/installed"
TLS_KEY = STATE_ROOT / "tls/manager.key"
TLS_CERT = STATE_ROOT / "tls/manager.crt"
WG_CONFIG = STATE_ROOT / "vpn/wg0.conf"
OVPN_CONFIG = STATE_ROOT / "vpn/client.ovpn"
OVPN_CREDENTIALS = STATE_ROOT / "vpn/openvpn.credentials"
QBT_CONFIG = STATE_ROOT / "qbittorrent/qBittorrent/config/qBittorrent.conf"
INDEX = Path(os.environ.get("QBTOS_INDEX", "/usr/share/qbtos-manager/index.html"))
CONTROL = os.environ.get("QBTOS_CONTROL", "/usr/libexec/qbtos-control")
MAX_BODY = 256 * 1024
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
SAFE_DATA_ROOTS = ("/data", "/media", "/mnt")
OPENVPN_FORBIDDEN = {
    "up", "down", "route-up", "route-pre-down", "ipchange", "learn-address",
    "client-connect", "client-disconnect", "plugin", "script-security", "tls-verify",
    "auth-user-pass-verify", "management", "log", "log-append", "status", "writepid",
    "daemon", "cd", "chroot",
}
OPENVPN_FILE_DIRECTIVES = {"ca", "cert", "key", "pkcs12", "tls-auth", "tls-crypt", "secret"}
WG_FORBIDDEN = {"preup", "postup", "predown", "postdown"}
UPDATE_FEED_DEFAULT = ""


class ValidationError(ValueError):
    pass


def atomic_write(path, data, mode=0o600):
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


def password_hash(password, *, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return "pbkdf2_sha256$200000${}${}".format(
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(encoded, password):
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, binascii.Error):
        return False


def qbittorrent_password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100_000, dklen=64)
    return f"{base64.b64encode(salt).decode()}:{base64.b64encode(digest).decode()}"


def qbittorrent_https_options():
    return (
        f"WebUI\\HTTPS\\CertificatePath={TLS_CERT}",
        "WebUI\\HTTPS\\Enabled=true",
        f"WebUI\\HTTPS\\KeyPath={TLS_KEY}",
    )


def add_qbittorrent_https(config):
    prefixes = tuple(f"{line.split('=', 1)[0]}=" for line in qbittorrent_https_options())
    lines = [line for line in config.splitlines()
             if not line.startswith(prefixes)]
    try:
        preferences = lines.index("[Preferences]")
    except ValueError:
        if lines and lines[-1]:
            lines.append("")
        lines.append("[Preferences]")
        preferences = len(lines) - 1
    insertion = len(lines)
    for index in range(preferences + 1, len(lines)):
        if lines[index].startswith("[") and lines[index].endswith("]"):
            insertion = index
            break
    lines[insertion:insertion] = qbittorrent_https_options()
    return "\n".join(lines).rstrip() + "\n"


def validate_account(username, password):
    if not USERNAME_RE.fullmatch(username or ""):
        raise ValidationError(
            "Username must be 3-32 letters, numbers, dots, dashes, or underscores")
    if len(password or "") < 10 or len(password) > 128:
        raise ValidationError("Password must contain 10-128 characters")


def validate_data_path(value, roots=SAFE_DATA_ROOTS):
    if not isinstance(value, str) or "\x00" in value or "\n" in value or "\r" in value:
        raise ValidationError("Data path is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError("Data path must be absolute")
    resolved = path.resolve(strict=True)
    if not any(resolved == Path(root) or Path(root) in resolved.parents for root in roots):
        raise ValidationError("Data path must be under /data, /media, or /mnt")
    if not resolved.is_dir() or path.is_symlink() or not os.access(resolved, os.W_OK):
        raise ValidationError("Data path must be an existing writable directory, not a symlink")
    parent = resolved
    while parent != parent.parent and not os.path.ismount(parent):
        parent = parent.parent
    if not any(parent == Path(root) or Path(root) in parent.parents for root in roots):
        raise ValidationError("Data path must be on a mounted data filesystem")
    return str(resolved)


def _full_tunnel(allowed):
    try:
        networks = [ipaddress.ip_network(item.strip(), strict=False) for item in allowed.split(",")]
    except ValueError as error:
        raise ValidationError(f"Invalid AllowedIPs: {error}") from error
    return ipaddress.ip_network("0.0.0.0/0") in networks


def validate_wireguard(text):
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 128 * 1024:
        raise ValidationError("WireGuard configuration is empty or too large")
    section = None
    found = set()
    dns_servers = []
    output = []
    for raw in text.replace("\r\n", "\n").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            output.append(raw)
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].lower()
            if section not in {"interface", "peer"}:
                raise ValidationError(f"Unsupported WireGuard section: {line}")
            output.append(line)
            continue
        if "=" not in line or section is None:
            raise ValidationError("Malformed WireGuard configuration line")
        key, value = (part.strip() for part in line.split("=", 1))
        lowered = key.lower()
        if lowered in WG_FORBIDDEN:
            raise ValidationError(f"WireGuard command directive {key} is not allowed")
        if lowered == "dns":
            for server in value.split(","):
                try:
                    address = ipaddress.ip_address(server.strip())
                except ValueError as error:
                    raise ValidationError("WireGuard DNS entries must be IP addresses") from error
                if address.version == 4:
                    dns_servers.append(str(address))
            continue
        if lowered == "table" and value.lower() not in {"auto", "main"}:
            raise ValidationError("WireGuard Table must be auto or main")
        if lowered == "address":
            addresses = []
            for address_text in value.split(","):
                try:
                    address = ipaddress.ip_interface(address_text.strip())
                except ValueError as error:
                    raise ValidationError(
                        "WireGuard Address entries must be IP interfaces") from error
                if address.version == 4:
                    addresses.append(str(address))
            if not addresses:
                raise ValidationError("WireGuard configuration requires an IPv4 Address")
            value = ", ".join(addresses)
        if section == "peer" and lowered == "allowedips":
            if not _full_tunnel(value):
                raise ValidationError(
                    "WireGuard AllowedIPs must include 0.0.0.0/0 for fail-closed setup")
            networks = [ipaddress.ip_network(item.strip(), strict=False)
                        for item in value.split(",")]
            value = ", ".join(str(network) for network in networks if network.version == 4)
        if lowered in {"privatekey", "address", "publickey", "endpoint", "allowedips"}:
            found.add((section, lowered))
        output.append(f"{key} = {value}")
    required = {
        ("interface", "privatekey"), ("interface", "address"),
        ("peer", "publickey"), ("peer", "endpoint"), ("peer", "allowedips"),
    }
    if not required.issubset(found):
        raise ValidationError(
            "WireGuard config requires Address, PrivateKey, PublicKey, Endpoint, and AllowedIPs")
    return "\n".join(output).strip() + "\n", dns_servers


def validate_openvpn(text, username="", password=""):
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 192 * 1024:
        raise ValidationError("OpenVPN configuration is empty or too large")
    lines = text.replace("\r\n", "\n").splitlines()
    directives = []
    inline_blocks = set()
    in_block = None
    output = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("<") and line.endswith(">"):
            if line.startswith("</"):
                in_block = None
            else:
                in_block = line[1:-1].lower()
                inline_blocks.add(in_block)
            output.append(raw)
            continue
        if in_block or not line or line.startswith(('#', ';')):
            output.append(raw)
            continue
        parts = line.split()
        name = parts[0].lower()
        directives.append((name, parts[1:]))
        if name in OPENVPN_FORBIDDEN:
            raise ValidationError(f"OpenVPN directive {name} is not allowed")
        if name in OPENVPN_FILE_DIRECTIVES and len(parts) > 1 and parts[1] != "[inline]":
            raise ValidationError(
                f"OpenVPN {name} must use an inline block in a single-file upload")
        if name != "auth-user-pass":
            output.append(raw)
    names = {name for name, _ in directives}
    if "remote" not in names or not ({"client", "pull"} & names):
        raise ValidationError("OpenVPN config requires client/pull and remote directives")
    dev_values = [args[0] for name, args in directives if name == "dev" and args]
    if dev_values and not all(value.startswith("tun") for value in dev_values):
        raise ValidationError("Only routed OpenVPN tun devices are supported")
    redirects = [args for name, args in directives if name == "redirect-gateway"]
    if not redirects:
        raise ValidationError("OpenVPN config requires redirect-gateway for a full tunnel")
    for required_inline in (names & OPENVPN_FILE_DIRECTIVES):
        if required_inline not in inline_blocks and required_inline != "pkcs12":
            raise ValidationError(f"OpenVPN inline block <{required_inline}> is missing")
    needs_credentials = "auth-user-pass" in names
    if needs_credentials and (not username or not password):
        raise ValidationError("This OpenVPN configuration requires VPN credentials")
    output = [line for line in output if not line.strip().lower().startswith("dev ")]
    output.extend(["dev tun0", "auth-nocache"])
    if needs_credentials:
        output.append(f"auth-user-pass {OVPN_CREDENTIALS}")
    dns_servers = []
    for name, args in directives:
        if name == "dhcp-option" and len(args) >= 2 and args[0].upper() == "DNS":
            try:
                dns_servers.append(str(ipaddress.ip_address(args[1])))
            except ValueError as error:
                raise ValidationError("OpenVPN DNS entries must be IP addresses") from error
    return "\n".join(output).strip() + "\n", dns_servers, needs_credentials


def persist_setup(payload):
    username = payload.get("qb_username", "")
    password = payload.get("qb_password", "")
    validate_account(username, password)
    data_path = validate_data_path(payload.get("data_path", ""))
    vpn_type = payload.get("vpn_type")
    vpn_text = payload.get("vpn_config", "")
    vpn_username = payload.get("vpn_username", "")
    vpn_password = payload.get("vpn_password", "")
    update_feed_url = payload.get("update_feed_url", "").strip()
    if update_feed_url:
        qbtos_update.validate_feed_url(update_feed_url)
    if vpn_type == "wireguard":
        normalized, dns_servers = validate_wireguard(vpn_text)
        atomic_write(WG_CONFIG, normalized)
        OVPN_CONFIG.unlink(missing_ok=True)
        OVPN_CREDENTIALS.unlink(missing_ok=True)
        interface = "wg0"
    elif vpn_type == "openvpn":
        normalized, dns_servers, needs_credentials = validate_openvpn(
            vpn_text, vpn_username, vpn_password)
        atomic_write(OVPN_CONFIG, normalized)
        WG_CONFIG.unlink(missing_ok=True)
        if needs_credentials:
            if "\n" in vpn_username or "\n" in vpn_password or not vpn_username or not vpn_password:
                raise ValidationError("VPN credentials are invalid")
            atomic_write(OVPN_CREDENTIALS, f"{vpn_username}\n{vpn_password}\n")
        else:
            OVPN_CREDENTIALS.unlink(missing_ok=True)
        interface = "tun0"
    else:
        raise ValidationError("Select WireGuard or OpenVPN")

    settings = {
        "version": 1,
        "qb_username": username,
        "manager_password": password_hash(password),
        "data_path": data_path,
        "vpn_type": vpn_type,
        "vpn_interface": interface,
        "dns_servers": dns_servers,
        "update_feed_url": update_feed_url,
    }
    atomic_write(SETTINGS, json.dumps(settings, indent=2, sort_keys=True) + "\n")
    return settings, qbittorrent_password_hash(password)


def write_qbittorrent_config(settings, qbt_password):
    data_path = settings["data_path"]
    for directory in (data_path, f"{data_path}/downloads", f"{data_path}/incomplete"):
        Path(directory).mkdir(parents=True, exist_ok=True)
    account = pwd.getpwnam("qbtos-qbt")
    profile_directories = (
        STATE_ROOT / "qbittorrent",
        STATE_ROOT / "qbittorrent/qBittorrent",
        STATE_ROOT / "qbittorrent/qBittorrent/config",
    )
    for directory in profile_directories:
        directory.mkdir(parents=True, exist_ok=True)
    for directory in profile_directories:
        os.chown(directory, account.pw_uid, account.pw_gid)
    for directory in (
            Path(data_path), Path(data_path) / "downloads",
            Path(data_path) / "incomplete"):
        try:
            os.chown(directory, account.pw_uid, account.pw_gid)
        except OSError:
            metadata = directory.stat()
            if metadata.st_uid != account.pw_uid or metadata.st_gid != account.pw_gid:
                raise
    interface = settings["vpn_interface"]
    config = f"""[BitTorrent]
Session\\DefaultSavePath={data_path}/downloads
Session\\Interface={interface}
Session\\InterfaceName={interface}
Session\\Port=6881
Session\\TempPath={data_path}/incomplete
Session\\TempPathEnabled=true

[LegalNotice]
Accepted=true

[Preferences]
Connection\\UPnP=false
WebUI\\Address=*
WebUI\\HTTPS\\CertificatePath={TLS_CERT}
WebUI\\HTTPS\\Enabled=true
WebUI\\HTTPS\\KeyPath={TLS_KEY}
WebUI\\Password_PBKDF2=\"@ByteArray({qbt_password})\"
WebUI\\Port=8081
WebUI\\ServerDomains=*
WebUI\\UseUPnP=false
WebUI\\Username={settings['qb_username']}
"""
    atomic_write(QBT_CONFIG, config)
    os.chown(QBT_CONFIG, account.pw_uid, account.pw_gid)


def ensure_qbittorrent_https():
    if not QBT_CONFIG.exists():
        return
    config = add_qbittorrent_https(QBT_CONFIG.read_text(encoding="utf-8"))
    atomic_write(QBT_CONFIG, config)
    account = pwd.getpwnam("qbtos-qbt")
    os.chown(QBT_CONFIG, account.pw_uid, account.pw_gid)


def control(operation):
    return subprocess.run(
        [CONTROL, operation], text=True, timeout=40,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def lan_ip():
    result = subprocess.run(
        ["/sbin/ip", "-4", "-o", "addr", "show", "dev", "eth0"],
        text=True, timeout=5, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    match = re.search(r"\binet\s+([0-9.]+)/", result.stdout)
    return match.group(1) if match else "unavailable"


def wait_for_lan_ip(timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        address = lan_ip()
        try:
            if not ipaddress.ip_address(address).is_loopback:
                return address
        except ValueError:
            pass
        time.sleep(1)
    raise RuntimeError("wired DHCP did not provide a LAN IPv4 address")


def mounted_data_paths():
    paths = []
    try:
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            device, mountpoint, filesystem, options, *_ = line.split()
            trusted_path = any(
                mountpoint == root or mountpoint.startswith(root + "/")
                for root in SAFE_DATA_ROOTS)
            if filesystem in {"ext2", "ext3", "ext4", "xfs", "btrfs"} and trusted_path:
                paths.append({"path": mountpoint, "device": device, "filesystem": filesystem,
                              "writable": "rw" in options.split(",")})
    except (OSError, ValueError):
        pass
    return paths


def status_payload():
    result = control("status")
    try:
        services = json.loads(result.stdout)
    except json.JSONDecodeError:
        services = {"vpn_protected": False, "qbittorrent_running": False}
    settings = {}
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    diagnostics = [
        ("Traffic-lock rules loaded" if control("vpn-check").returncode == 0
         else "VPN protection checks are not passing"),
        ("qBittorrent is disabled until setup and protection checks succeed"
         if not INSTALLED.exists() else "Installation settings saved"),
    ]
    release = qbtos_update.read_release()
    active = qbtos_update.active_slot()
    try:
        inactive = qbtos_update.inactive_slot(active)
    except qbtos_update.UpdateError:
        inactive = "unknown"
    update = qbtos_update.update_status()
    update.update({
        "active_slot": active,
        "inactive_slot": inactive,
        "current_version": release["version"],
        "current_revision": release["revision"],
        "feed_url": settings.get("update_feed_url", UPDATE_FEED_DEFAULT),
    })
    try:
        available = json.loads(
            (qbtos_update.UPDATE_ROOT / "latest.json").read_text(encoding="utf-8"))
        update["available_version"] = available.get("version", "unknown")
        update["available_revision"] = available.get("revision", 0)
    except (OSError, json.JSONDecodeError):
        update["available_version"] = "not checked"
        update["available_revision"] = 0
    if Path(qbtos_update.RAUC).exists():
        update["bootloader"] = qbtos_update.bootloader_state()
    else:
        update["bootloader"] = {"boot_order": "unsupported"}
    return {
        "installed": INSTALLED.exists(), "lan_ip": lan_ip(),
        "vpn_type": settings.get("vpn_type", "not configured"),
        "vpn_protected": services.get("vpn_protected", False),
        "qbittorrent_running": services.get("qbittorrent_running", False),
        "data_path": settings.get("data_path", "not selected"),
        "mounts": mounted_data_paths(), "diagnostics": diagnostics,
        "release": release, "update": update,
    }


def load_latest_update():
    try:
        document = json.loads(
            (qbtos_update.UPDATE_ROOT / "latest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError("Check the update feed before continuing") from error
    try:
        return qbtos_update.validate_feed(document, qbtos_update.read_release())
    except qbtos_update.UpdateError as error:
        raise ValidationError(str(error)) from error


def update_feed_url(payload):
    settings = {}
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    value = str(payload.get("update_feed_url", settings.get("update_feed_url", ""))).strip()
    if not value:
        raise ValidationError("Configure an HTTPS latest.json update feed first")
    try:
        return qbtos_update.validate_feed_url(value)
    except qbtos_update.UpdateError as error:
        raise ValidationError(str(error)) from error


def ensure_tls():
    TLS_KEY.parent.mkdir(parents=True, exist_ok=True)
    if TLS_KEY.exists() and TLS_CERT.exists():
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(TLS_CERT, TLS_KEY)
            secure_tls_permissions()
            return
        except (OSError, ssl.SSLError):
            pass

    # OpenSSL creates its output files before it has finished writing them.
    # Generate into a private temporary directory so an interrupted first boot
    # cannot leave apparently complete certificate paths behind.
    with tempfile.TemporaryDirectory(prefix=".tls.", dir=TLS_KEY.parent) as temporary:
        temporary_root = Path(temporary)
        temporary_key = temporary_root / "manager.key"
        temporary_cert = temporary_root / "manager.crt"
        subprocess.run([
            "/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
            "-nodes", "-days", "825", "-keyout", str(temporary_key),
            "-out", str(temporary_cert), "-subj", "/CN=qbtos",
            "-addext", "subjectAltName=DNS:qbtos",
        ], timeout=60, check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        temporary_key.chmod(0o600)
        temporary_cert.chmod(0o644)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(temporary_cert, temporary_key)
        os.replace(temporary_key, TLS_KEY)
        os.replace(temporary_cert, TLS_CERT)
    secure_tls_permissions()


def secure_tls_permissions():
    account = pwd.getpwnam("qbtos-qbt")
    os.chown(TLS_KEY.parent, 0, account.pw_gid)
    TLS_KEY.parent.chmod(0o750)
    os.chown(TLS_KEY, 0, account.pw_gid)
    TLS_KEY.chmod(0o640)
    os.chown(TLS_CERT, 0, account.pw_gid)
    TLS_CERT.chmod(0o640)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "qbtOS-manager/0.1"

    def log_message(self, format_string, *args):
        # The standard line contains only method/path/status; request bodies are never logged.
        super().log_message(format_string, *args)

    def _authorized(self):
        if not INSTALLED.exists():
            return True
        try:
            header = self.headers.get("Authorization", "")
            scheme, token = header.split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError
            username, password = base64.b64decode(token, validate=True).decode().split(":", 1)
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return hmac.compare_digest(username, settings["qb_username"]) and \
                verify_password(settings["manager_password"], password)
        except (ValueError, KeyError, OSError, UnicodeError, binascii.Error, json.JSONDecodeError):
            return False

    def _require_auth(self):
        if self._authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="qbtOS management"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send(self, status, body, content_type="application/json"):
        encoded = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        policy = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'")
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(encoded)

    def _json(self, status, value):
        self._send(status, json.dumps(value).encode())

    def do_GET(self):
        if self.path == "/api/health":
            self._json(200, {"ok": True})
            return
        if not self._require_auth():
            return
        if self.path == "/":
            self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(200, status_payload())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._require_auth():
            return
        allowed = {
            "/api/test", "/api/complete", "/api/update/config",
            "/api/update/check", "/api/update/download", "/api/update/install",
            "/api/update/reboot",
        }
        if self.path not in allowed:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY:
                raise ValidationError("Request is too large")
            payload = json.loads(self.rfile.read(length)) if length else {}
            if self.path.startswith("/api/update/"):
                self._handle_update(payload)
                return
            settings, qbt_password = persist_setup(payload)
            vpn_result = control("vpn-start")
            if vpn_result.returncode != 0:
                raise ValidationError(vpn_result.stdout.strip() or "VPN protection test failed")
            if self.path == "/api/complete":
                write_qbittorrent_config(settings, qbt_password)
                atomic_write(INSTALLED, "installed\n", 0o600)
                qbt_result = control("qbt-start")
                if qbt_result.returncode != 0:
                    raise ValidationError(qbt_result.stdout.strip() or "qBittorrent did not start")
            self._json(200, {"ok": True, "status": status_payload()})
        except (ValidationError, qbtos_update.UpdateError, json.JSONDecodeError, KeyError, OSError,
                subprocess.SubprocessError) as error:
            control("qbt-stop")
            if self.path == "/api/complete":
                INSTALLED.unlink(missing_ok=True)
            self._json(400, {"ok": False, "error": str(error)})

    def _handle_update(self, payload):
        if self.path == "/api/update/config":
            url = update_feed_url(payload)
            try:
                settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValidationError("Complete appliance setup first") from error
            settings["update_feed_url"] = url
            atomic_write(SETTINGS, json.dumps(settings, indent=2, sort_keys=True) + "\n")
            self._json(200, {"ok": True, "status": status_payload()})
        elif self.path == "/api/update/check":
            document = qbtos_update.fetch_feed(update_feed_url(payload))
            document = qbtos_update.validate_feed(document, qbtos_update.read_release())
            qbtos_update.write_json(qbtos_update.UPDATE_ROOT / "latest.json", document)
            qbtos_update.set_update_status(
                "available", 0, f"Signed update {document['version']} is available",
                available_version=document["version"])
            self._json(200, {"ok": True, "status": status_payload()})
        elif self.path == "/api/update/download":
            document = load_latest_update()
            qbtos_update.verify_release_checksums(document)
            qbtos_update.download_bundle(document)
            self._json(200, {"ok": True, "status": status_payload()})
        elif self.path == "/api/update/install":
            document = load_latest_update()
            qbtos_update.install_bundle(document)
            self._json(200, {"ok": True, "status": status_payload()})
        elif self.path == "/api/update/reboot":
            if qbtos_update.update_status().get("phase") != "awaiting-reboot":
                raise ValidationError("No installed update is awaiting reboot")
            self._json(200, {"ok": True, "message": "Rebooting into the pending slot"})
            control("reboot")


def main():
    if not Path("/config").is_mount():
        raise SystemExit("qbtOS configuration partition is not mounted; refusing ephemeral setup")
    ensure_tls()
    ensure_qbittorrent_https()
    bind_address = wait_for_lan_ip()
    server = http.server.ThreadingHTTPServer(
        (bind_address, 8080), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(TLS_CERT, TLS_KEY)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
