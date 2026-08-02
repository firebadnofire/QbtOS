#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed privileged operations for qbtOS. No request data enters a shell."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STATE_ROOT = Path(os.environ.get("QBTOS_STATE_ROOT", "/config/qbtos"))
SETTINGS = STATE_ROOT / "settings.json"
WG_CONFIG = STATE_ROOT / "vpn/wg0.conf"
OVPN_CONFIG = STATE_ROOT / "vpn/client.ovpn"
INSTALLED = STATE_ROOT / "state/installed"
QBT_PID = Path("/run/qbittorrent.pid")
OVPN_PID = Path("/run/openvpn-qbtos.pid")
RESOLV = Path("/run/resolv.conf")
RESOLV_BACKUP = Path("/run/resolv.conf.before-vpn")


def run(argv, *, check=True, capture=False):
    return subprocess.run(
        argv, check=check, text=True, timeout=30,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def load_settings():
    with SETTINGS.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def process_alive(pid_file):
    try:
        os.kill(int(pid_file.read_text(encoding="ascii").strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def qbt_stop():
    if QBT_PID.exists():
        run(["/sbin/start-stop-daemon", "-K", "-q", "-p", str(QBT_PID)], check=False)
        QBT_PID.unlink(missing_ok=True)


def vpn_interface(settings):
    return "wg0" if settings.get("vpn_type") == "wireguard" else "tun0"


def vpn_check(verbose=True):
    try:
        settings = load_settings()
        interface = vpn_interface(settings)
        run(["/usr/sbin/nft", "list", "table", "inet", "qbtos"], capture=True)
        link = run(["/sbin/ip", "-o", "link", "show", "dev", interface], capture=True)
        if "UP" not in link.stdout:
            raise RuntimeError(f"{interface} is not up")
        route = run(["/sbin/ip", "-4", "route", "get", "1.1.1.1"], capture=True)
        if f"dev {interface}" not in route.stdout:
            raise RuntimeError(f"external IPv4 route does not use {interface}")
        if interface == "wg0":
            handshake = run(["/usr/bin/wg", "show", "wg0", "latest-handshakes"], capture=True)
            timestamps = [
                int(line.rsplit("\t", 1)[-1])
                for line in handshake.stdout.splitlines() if "\t" in line]
            if not timestamps or max(timestamps) <= 0 or time.time() - max(timestamps) > 300:
                raise RuntimeError("WireGuard has no recent handshake")
        if verbose:
            print(f"protected route active through {interface}")
        return True
    except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError,
            RuntimeError) as error:
        if verbose:
            print(f"protection check failed: {error}", file=sys.stderr)
        return False


def set_vpn_dns(settings):
    servers = settings.get("dns_servers", [])
    if not servers:
        return
    if RESOLV.exists() and not RESOLV_BACKUP.exists():
        shutil.copyfile(RESOLV, RESOLV_BACKUP)
    content = "".join(f"nameserver {server}\n" for server in servers)
    RESOLV.write_text(content, encoding="ascii")
    RESOLV.chmod(0o644)


def restore_dns():
    if RESOLV_BACKUP.exists():
        shutil.copyfile(RESOLV_BACKUP, RESOLV)
        RESOLV_BACKUP.unlink()


def vpn_stop():
    qbt_stop()
    run(["/usr/bin/wg-quick", "down", str(WG_CONFIG)], check=False)
    if OVPN_PID.exists():
        run(["/sbin/start-stop-daemon", "-K", "-q", "-p", str(OVPN_PID)], check=False)
        OVPN_PID.unlink(missing_ok=True)
    restore_dns()


def vpn_start():
    settings = load_settings()
    vpn_stop()
    if settings.get("vpn_type") == "wireguard":
        run(["/usr/bin/wg-quick", "up", str(WG_CONFIG)])
    elif settings.get("vpn_type") == "openvpn":
        run([
            "/usr/sbin/openvpn", "--config", str(OVPN_CONFIG),
            "--daemon", "qbtos-openvpn", "--writepid", str(OVPN_PID),
        ])
    else:
        raise RuntimeError("VPN type is not configured")

    interface = vpn_interface(settings)
    for _ in range(20):
        result = run(["/sbin/ip", "link", "show", "dev", interface], check=False)
        if result.returncode == 0:
            break
        time.sleep(1)
    set_vpn_dns(settings)
    run(["/bin/ping", "-c", "1", "-W", "5", "1.1.1.1"], check=False)
    if not vpn_check():
        vpn_stop()
        raise RuntimeError("VPN did not pass route, interface, firewall, and handshake checks")


def qbt_start():
    if not INSTALLED.exists():
        print("qBittorrent remains disabled until setup is complete")
        return
    if not vpn_check():
        qbt_stop()
        raise RuntimeError("qBittorrent refused: VPN protection is unavailable")
    if process_alive(QBT_PID):
        return
    run([
        "/sbin/start-stop-daemon", "-S", "-q", "-b", "-m",
        "-p", str(QBT_PID), "-c", "qbtos-qbt", "-x", "/usr/bin/qbittorrent-nox",
        "--", "--profile=/config/qbtos/qbittorrent", "--webui-port=8081",
        "--confirm-legal-notice",
    ])


def status():
    protected = vpn_check(verbose=False)
    print(json.dumps({"vpn_protected": protected, "qbittorrent_running": process_alive(QBT_PID)}))


def main():
    operations = {
        "vpn-start": vpn_start,
        "vpn-stop": vpn_stop,
        "vpn-check": vpn_check,
        "qbt-start": qbt_start,
        "qbt-stop": qbt_stop,
        "status": status,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in operations:
        print(
            "usage: qbtos-control "
            "{vpn-start|vpn-stop|vpn-check|qbt-start|qbt-stop|status}",
            file=sys.stderr)
        return 2
    result = operations[sys.argv[1]]()
    return 0 if result is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
