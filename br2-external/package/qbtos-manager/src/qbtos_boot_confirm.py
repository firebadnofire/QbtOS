#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Confirm a healthy RAUC slot without depending on Internet or VPN reachability."""

import json
import os
import shutil
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

import qbtos_update


def run(argv, timeout=20):
    return subprocess.run(
        argv, text=True, timeout=timeout, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False)


def state_is_writable():
    try:
        marker = qbtos_update.STATE_ROOT / "state/.boot-write-test"
        qbtos_update.atomic_write(marker, "ok\n")
        marker.unlink()
        return os.path.ismount(qbtos_update.STATE_ROOT.parent)
    except OSError:
        return False


def manager_is_healthy():
    address = run(["/sbin/ip", "-4", "-o", "addr", "show", "dev", "eth0"], 5)
    if address.returncode != 0:
        return False
    fields = address.stdout.split()
    try:
        host = fields[fields.index("inet") + 1].split("/", 1)[0]
    except (ValueError, IndexError):
        return False
    context = ssl._create_unverified_context()
    request = urllib.request.Request(f"https://{host}:8080/api/health")
    try:
        with urllib.request.urlopen(request, timeout=5, context=context) as response:
            value = json.loads(response.read(4096).decode("utf-8"))
        return response.status == 200 and value.get("ok") is True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def firewall_is_healthy():
    return run(["/usr/sbin/nft", "list", "table", "ip", "qbtos"]).returncode == 0


def qbittorrent_is_safe():
    status = run(["/usr/libexec/qbtos-control", "status"])
    try:
        value = json.loads(status.stdout)
    except json.JSONDecodeError:
        return False
    if not value.get("qbittorrent_running", False):
        return True
    return run(["/usr/libexec/qbtos-control", "vpn-check"]).returncode == 0


def local_health_checks():
    schema = qbtos_update.target_schema()
    checks = {
        "state_mounted_writable": state_is_writable(),
        "configuration_valid": False,
        "manager_local_response": manager_is_healthy(),
        "traffic_lock_loaded": firewall_is_healthy(),
        "qbittorrent_safe": qbittorrent_is_safe(),
    }
    try:
        checks["configuration_valid"] = qbtos_update.validate_state(
            qbtos_update.STATE_ROOT.resolve(), schema)
    except qbtos_update.UpdateError:
        pass
    return checks


def _pending():
    path = qbtos_update.UPDATE_ROOT / "pending.json"
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path, None


def _complete_pending(path, pending):
    if pending:
        if pending.get("phase") != "rolled-back":
            pending["phase"] = "confirmed"
        qbtos_update.write_json(qbtos_update.UPDATE_ROOT / "last-update.json", pending)
        path.unlink(missing_ok=True)
    backup_link = qbtos_update.STATE_CONTAINER / "pre-update"
    if backup_link.is_symlink():
        backup = backup_link.resolve()
        backup_link.unlink()
        if backup.parent == qbtos_update.STATE_CONTAINER / "generations":
            shutil.rmtree(backup, ignore_errors=True)


def confirm_current_slot():
    active = qbtos_update.active_slot()
    if active not in {"A", "B"}:
        raise qbtos_update.UpdateError("current RAUC slot is unknown")
    checks = local_health_checks()
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise qbtos_update.UpdateError("boot health checks failed: " + ", ".join(failed))
    pending_path, pending = _pending()
    release = qbtos_update.read_release()
    if pending and pending.get("target_slot") == active and \
            pending.get("version") != release["version"]:
        raise qbtos_update.UpdateError("pending update version does not match the booted system")
    result = run([qbtos_update.RAUC, "status", "mark-good"], 30)
    if result.returncode != 0:
        raise qbtos_update.UpdateError("RAUC could not mark the slot good")
    if pending and pending.get("target_slot") != active:
        pending["phase"] = "rolled-back"
    _complete_pending(pending_path, pending)
    phase = "rolled-back" if pending and pending.get("phase") == "rolled-back" else "confirmed"
    qbtos_update.set_update_status(
        phase, 100, f"Slot {active} passed local boot health checks")
    return checks


def main():
    if not Path(qbtos_update.RAUC).exists():
        return 0
    delay = int(os.environ.get("QBTOS_BOOT_CONFIRM_DELAY", "60"))
    time.sleep(max(0, min(delay, 300)))
    try:
        confirm_current_slot()
        return 0
    except (OSError, ValueError, qbtos_update.UpdateError) as error:
        qbtos_update.set_update_status("boot-failed", 0, str(error))
        _, pending = _pending()
        active = qbtos_update.active_slot()
        if pending and pending.get("target_slot") == active:
            run(["/sbin/reboot", "-f"], 10)
        print(f"qbtOS boot confirmation failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
