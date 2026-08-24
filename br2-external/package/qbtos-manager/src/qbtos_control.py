#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed privileged operations for qbtOS. No request data enters a shell."""

import json
import os
import pwd
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
QBT_CONFIG = STATE_ROOT / "qbittorrent/qBittorrent/config/qBittorrent.conf"
CLOCK_EPOCH = STATE_ROOT / "state/clock-epoch"
OVPN_PID = Path("/run/openvpn-qbtos.pid")
SMB_RUNTIME = Path("/run/qbtos-samba")
SMB_CONFIG = Path("/run/qbtos-smb.conf")
SMB_PID = SMB_RUNTIME / "smbd.pid"
NFSD_THREADS = Path("/proc/fs/nfsd/threads")
RESOLV = Path("/run/resolv.conf")
RESOLV_BACKUP = Path("/run/resolv.conf.before-vpn")
LAN_NETWORKS = (
    "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16",
    "172.16.0.0/12", "192.168.0.0/16",
)
VPN_START_TIMEOUT = 45
LAN_START_TIMEOUT = 60
WIREGUARD_MARK_SET = "wireguard_marks"
QBITTORRENT_TLS_PORT = 18444


def run(argv, *, check=True, capture=False, env=None):
    return subprocess.run(
        argv, check=check, text=True, timeout=30,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        env=env,
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


def clock_save():
    """Persist a monotonic wall-clock floor without writing on every status poll."""
    epoch = int(time.time())
    try:
        epoch = max(epoch, int(CLOCK_EPOCH.read_text(encoding="ascii").strip()))
    except (OSError, ValueError):
        pass
    CLOCK_EPOCH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CLOCK_EPOCH.with_name(f".{CLOCK_EPOCH.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="ascii") as stream:
            stream.write(f"{epoch}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, CLOCK_EPOCH)
        directory = os.open(CLOCK_EPOCH.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _unescape_mount(value):
    return (value.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def mounted_filesystem(path):
    """Return the deepest mount containing path, or None if it cannot be read."""
    resolved = Path(path).resolve()
    selected = None
    try:
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            device, mountpoint, filesystem, options, *_ = line.split()
            mount = Path(_unescape_mount(mountpoint))
            if resolved == mount or mount in resolved.parents:
                if selected is None or len(str(mount)) > len(str(selected[0])):
                    selected = (mount, device, filesystem, options.split(","))
    except (OSError, ValueError):
        return None
    return selected


def persistent_data_status(settings=None):
    try:
        if settings is None:
            settings = load_settings()
        data_path = Path(settings["data_path"]).resolve(strict=True)
    except (OSError, KeyError, json.JSONDecodeError):
        return False, "persistent data path is not configured"
    if not data_path.is_dir():
        return False, "persistent data path is not a directory"
    mounted = mounted_filesystem(data_path)
    if not mounted or str(mounted[0]) == "/":
        return False, f"{data_path} is not on a separate mounted filesystem"
    if "rw" not in mounted[3] or not os.access(data_path, os.W_OK):
        return False, f"{data_path} is not writable"
    return True, f"{data_path} is writable on {mounted[2]}"


def downloads_path(settings=None):
    """Return the configured downloads directory after storage validation."""
    if settings is None:
        settings = load_settings()
    ready, message = persistent_data_status(settings)
    if not ready:
        raise RuntimeError(f"file sharing refused: {message}")
    path = (Path(settings["data_path"]).resolve(strict=True) / "downloads")
    if not path.is_dir() or path.is_symlink() or not os.access(path, os.W_OK):
        raise RuntimeError("file sharing refused: downloads directory is unavailable")
    return path


def share_enabled(protocol, settings=None):
    if settings is None:
        settings = load_settings()
    return settings.get("shares", {}).get(f"{protocol}_enabled") is True


def write_smb_config(path):
    SMB_RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in ("lock", "state", "cache", "private"):
        (SMB_RUNTIME / directory).mkdir(mode=0o700, exist_ok=True)
    allowed = " ".join(LAN_NETWORKS)
    config = f"""[global]
bind interfaces only = yes
cache directory = {SMB_RUNTIME}/cache
disable netbios = yes
dns proxy = no
guest account = qbtos-qbt
hosts allow = {allowed}
hosts deny = 0.0.0.0/0
interfaces = lo eth0
load printers = no
lock directory = {SMB_RUNTIME}/lock
logging = file
log file = /run/qbtos-samba/log.%m
map to guest = Bad User
max log size = 256
multicast dns register = no
ntlm auth = disabled
pid directory = {SMB_RUNTIME}
printcap name = /dev/null
printing = bsd
private dir = {SMB_RUNTIME}/private
security = user
server min protocol = SMB2_02
server role = standalone server
server services = smb
smb ports = 445
state directory = {SMB_RUNTIME}/state

[downloads]
comment = qbtOS downloads
force group = qbtos-qbt
force user = qbtos-qbt
guest ok = yes
path = {path}
read only = no
"""
    SMB_CONFIG.write_text(config, encoding="utf-8")
    SMB_CONFIG.chmod(0o600)


def smb_stop():
    if SMB_PID.exists():
        run(["/sbin/start-stop-daemon", "-K", "-q", "-p", str(SMB_PID)], check=False)
    run(["/usr/bin/killall", "-q", "smbd"], check=False)
    SMB_PID.unlink(missing_ok=True)


def smb_start():
    settings = load_settings()
    if not INSTALLED.exists() or not share_enabled("smb", settings):
        smb_stop()
        return
    path = downloads_path(settings)
    if process_alive(SMB_PID):
        return
    write_smb_config(path)
    result = run(
        ["/usr/sbin/smbd", "-D", "-s", str(SMB_CONFIG)],
        check=False, capture=True)
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip()
                  or "smbd returned no diagnostic")
        raise RuntimeError(f"SMB daemon failed to start: {detail[-1000:]}")
    time.sleep(1)
    if not process_alive(SMB_PID):
        raise RuntimeError("SMB daemon exited during startup")


def nfs_running():
    try:
        return int(NFSD_THREADS.read_text(encoding="ascii").strip()) > 0
    except (OSError, ValueError):
        return False


def nfs_stop():
    run(["/usr/sbin/exportfs", "-au"], check=False)
    # Do not let rpc.nfsd fall back to NFSv3 while stopping. qbtOS does not
    # run rpcbind, so the default version negotiation fails with ECONNREFUSED.
    # Avoid invoking rpc.nfsd at all on the first start, before nfsd is mounted.
    if NFSD_THREADS.exists():
        run(["/usr/sbin/rpc.nfsd", "-N", "3", "-V", "4", "0"], check=False)
    run(["/usr/bin/killall", "-q", "rpc.mountd"], check=False)


def export_nfs_path(path, options):
    """Install each client export, retrying once after nfsd's first mount."""
    for network in LAN_NETWORKS:
        command = [
            "/usr/sbin/exportfs", "-i", "-o", options, f"{network}:{path}",
        ]
        result = run(command, check=False, capture=True)
        if result.returncode != 0:
            # Some kernels briefly reject the first export immediately after
            # the nfsd pseudo-filesystem is mounted. The operation is
            # idempotent, so one bounded retry is safe and deterministic.
            time.sleep(0.1)
            result = run(command, check=False, capture=True)
        if result.returncode != 0:
            detail = result.stderr.strip() or "exportfs returned no diagnostic"
            raise RuntimeError(f"NFS export failed for {network}: {detail}")


def nfs_start():
    settings = load_settings()
    if not INSTALLED.exists() or not share_enabled("nfs", settings):
        nfs_stop()
        return
    path = downloads_path(settings)
    nfs_stop()
    account = pwd.getpwnam("qbtos-qbt")
    options = (
        "rw,sync,no_subtree_check,all_squash,root_squash,"
        f"anonuid={account.pw_uid},anongid={account.pw_gid},fsid=0"
    )
    Path("/run/nfs/sm").mkdir(mode=0o700, parents=True, exist_ok=True)
    Path("/run/nfs/sm.bak").mkdir(mode=0o700, parents=True, exist_ok=True)
    run(["/sbin/modprobe", "nfsd"], check=False)
    if not Path("/proc/fs/nfsd/exports").exists():
        run(["/bin/mount", "-t", "nfsd", "nfsd", "/proc/fs/nfsd"])
    export_nfs_path(path, options)
    # NFSv4 clients use only TCP/2049 and do not contact mountd, but the kernel
    # still needs the local mountd process to answer export-cache upcalls.
    # Keep its network protocol set v4-only and disable UDP; the firewall does
    # not expose mountd's ancillary listeners.
    run(["/usr/sbin/rpc.mountd", "-V", "4", "-u"])
    # NFSv2 is absent from the kernel, so asking rpc.nfsd to disable it is
    # itself an error with current nfs-utils; explicitly disable only v3.
    run(["/usr/sbin/rpc.nfsd", "-N", "3", "-V", "4", "-t", "-U", "4"])
    if not nfs_running():
        nfs_stop()
        raise RuntimeError("NFS daemon exited during startup")


def shares_start():
    """Restore each independently enabled LAN share after persistent mounts."""
    errors = []
    for name, start in (("SMB", smb_start), ("NFS", nfs_start)):
        try:
            start()
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            errors.append(f"{name}: {error}")
    if errors:
        raise RuntimeError("; ".join(errors))


def shares_stop():
    smb_stop()
    nfs_stop()


def qbt_stop():
    if QBT_PID.exists():
        run(["/sbin/start-stop-daemon", "-K", "-q", "-p", str(QBT_PID)], check=False)
        deadline = time.monotonic() + 10
        while process_alive(QBT_PID) and time.monotonic() < deadline:
            time.sleep(0.1)
        if process_alive(QBT_PID):
            run([
                "/sbin/start-stop-daemon", "-K", "-q", "-s", "KILL",
                "-p", str(QBT_PID),
            ], check=False)
        QBT_PID.unlink(missing_ok=True)


def vpn_interface(settings):
    return "wg0" if settings.get("vpn_type") == "wireguard" else "tun0"


def lan_ready():
    address = run([
        "/sbin/ip", "-4", "-o", "address", "show", "dev", "eth0",
        "scope", "global",
    ], check=False, capture=True)
    route = run([
        "/sbin/ip", "-4", "route", "show", "default", "dev", "eth0",
    ], check=False, capture=True)
    return bool(address.stdout.strip() and route.stdout.strip())


def wait_for_lan_ready(timeout=LAN_START_TIMEOUT):
    """Wait for DHCP address and routing, not merely Ethernet carrier."""
    deadline = time.monotonic() + timeout
    while True:
        if lan_ready():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


def vpn_check(verbose=True):
    try:
        settings = load_settings()
        interface = vpn_interface(settings)
        run(["/usr/sbin/nft", "list", "table", "ip", "qbtos"], capture=True)
        link = run(["/sbin/ip", "-o", "link", "show", "dev", interface], capture=True)
        if "UP" not in link.stdout:
            raise RuntimeError(f"{interface} is not up")
        route = run(["/sbin/ip", "-4", "route", "get", "1.1.1.1"], capture=True)
        if f"dev {interface}" not in route.stdout:
            raise RuntimeError(f"external IPv4 route does not use {interface}")
        if interface == "wg0":
            wireguard_firewall_ready()
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


def wait_for_vpn_protection(timeout=VPN_START_TIMEOUT):
    """Allow asynchronous VPN handshakes to settle within a bounded window."""
    deadline = time.monotonic() + timeout
    while True:
        if vpn_check(verbose=False):
            return True
        if time.monotonic() >= deadline:
            return False
        # Generate tunnel traffic without treating public reachability as the
        # protection result. vpn_check remains authoritative.
        run(["/bin/ping", "-c", "1", "-W", "1", "1.1.1.1"], check=False)
        time.sleep(1)


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


def wireguard_fwmark():
    """Return wg0's validated nonzero routing mark in nftables notation."""
    result = run(["/usr/bin/wg", "show", "wg0", "fwmark"], capture=True)
    value = result.stdout.strip()
    try:
        mark = int(value, 0)
    except ValueError as error:
        raise RuntimeError(f"WireGuard reported an invalid fwmark: {value!r}") from error
    if mark <= 0 or mark > 0xFFFFFFFF:
        raise RuntimeError(f"WireGuard reported an invalid fwmark: {value!r}")
    return f"0x{mark:x}"


def clear_wireguard_firewall():
    run([
        "/usr/sbin/nft", "flush", "set", "ip", "qbtos",
        WIREGUARD_MARK_SET,
    ], check=False)


def configure_wireguard_firewall():
    """Permit only WireGuard's marked outer UDP packets for qBittorrent."""
    mark = wireguard_fwmark()
    clear_wireguard_firewall()
    run([
        "/usr/sbin/nft", "add", "element", "ip", "qbtos",
        WIREGUARD_MARK_SET, "{", mark, "}",
    ])
    return mark


def wireguard_firewall_ready():
    mark = wireguard_fwmark()
    result = run([
        "/usr/sbin/nft", "get", "element", "ip", "qbtos",
        WIREGUARD_MARK_SET, "{", mark, "}",
    ], check=False, capture=True)
    if result.returncode != 0:
        raise RuntimeError("WireGuard outer-packet traffic lock is not loaded")
    return True


def remove_lan_return_rules():
    for priority, network in enumerate(LAN_NETWORKS, start=100):
        run([
            "/sbin/ip", "-4", "rule", "delete", "priority", str(priority),
            "to", network, "table", "main",
        ], check=False)


def add_lan_return_rules():
    remove_lan_return_rules()
    for priority, network in enumerate(LAN_NETWORKS, start=100):
        run([
            "/sbin/ip", "-4", "rule", "add", "priority", str(priority),
            "to", network, "table", "main",
        ])


def vpn_stop():
    qbt_stop()
    clear_wireguard_firewall()
    remove_lan_return_rules()
    run(["/usr/bin/wg-quick", "down", str(WG_CONFIG)], check=False)
    if OVPN_PID.exists():
        run(["/sbin/start-stop-daemon", "-K", "-q", "-p", str(OVPN_PID)], check=False)
        OVPN_PID.unlink(missing_ok=True)
    restore_dns()


def vpn_start():
    settings = load_settings()
    vpn_stop()
    if not wait_for_lan_ready():
        raise RuntimeError("VPN cannot start: wired DHCP address and default route are unavailable")
    if settings.get("vpn_type") == "wireguard":
        run(["/usr/bin/wg-quick", "up", str(WG_CONFIG)])
        configure_wireguard_firewall()
    elif settings.get("vpn_type") == "openvpn":
        run([
            "/usr/sbin/openvpn", "--config", str(OVPN_CONFIG),
            "--daemon", "qbtos-openvpn", "--writepid", str(OVPN_PID),
        ])
    else:
        raise RuntimeError("VPN type is not configured")
    add_lan_return_rules()

    interface = vpn_interface(settings)
    for _ in range(20):
        result = run(["/sbin/ip", "link", "show", "dev", interface], check=False)
        if result.returncode == 0:
            break
        time.sleep(1)
    set_vpn_dns(settings)
    if not wait_for_vpn_protection():
        vpn_check()
        vpn_stop()
        raise RuntimeError("VPN did not pass route, interface, firewall, and handshake checks")
    # WireGuard rejects replayed handshakes after a wall-clock rollback. Save a
    # floor immediately after protection succeeds as well as during shutdown.
    clock_save()


def qbt_start():
    if not INSTALLED.exists():
        print("qBittorrent remains disabled until setup is complete")
        return
    if not vpn_check():
        qbt_stop()
        raise RuntimeError("qBittorrent refused: VPN protection is unavailable")
    data_ready, data_message = persistent_data_status()
    if not data_ready:
        qbt_stop()
        raise RuntimeError(f"qBittorrent refused: {data_message}")
    if not QBT_CONFIG.is_file():
        raise RuntimeError("qBittorrent refused: persistent configuration is missing")
    if process_alive(QBT_PID):
        return
    run([
        "/sbin/start-stop-daemon", "-S", "-q", "-b", "-m",
        "-p", str(QBT_PID), "-c", "qbtos-qbt", "-x", "/usr/bin/qbittorrent-nox",
        "--", "--profile=/config/qbtos/qbittorrent",
        f"--webui-port={QBITTORRENT_TLS_PORT}",
    ], env={**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    time.sleep(2)
    if not process_alive(QBT_PID):
        QBT_PID.unlink(missing_ok=True)
        raise RuntimeError("qBittorrent exited during startup")


def status():
    protected = vpn_check(verbose=False)
    running = process_alive(QBT_PID)
    data_ready, data_message = persistent_data_status()
    configured = INSTALLED.exists() and QBT_CONFIG.is_file()
    if running:
        state = "running"
        reason = "qBittorrent is running"
    elif not INSTALLED.exists():
        state = "not-installed"
        reason = "installation is not complete"
    elif not configured:
        state = "not-configured"
        reason = "persistent qBittorrent configuration is missing"
    elif not data_ready:
        state = "blocked-storage"
        reason = data_message
    elif not protected:
        state = "blocked-vpn"
        reason = "VPN protection checks are not passing"
    else:
        state = "stopped"
        reason = "qBittorrent is stopped"
    pid = None
    if running:
        try:
            pid = int(QBT_PID.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pass
    try:
        settings = load_settings()
    except (OSError, json.JSONDecodeError):
        settings = {}
    smb_running = process_alive(SMB_PID)
    nfs_is_running = nfs_running()
    print(json.dumps({
        "vpn_protected": protected,
        "qbittorrent_running": running,
        "qbittorrent_configured": configured,
        "qbittorrent_state": state,
        "qbittorrent_reason": reason,
        "qbittorrent_pid": pid,
        "data_ready": data_ready,
        "data_message": data_message,
        "shares": {
            "path": (f"{settings.get('data_path')}/downloads"
                     if settings.get("data_path") else "not configured"),
            "smb": {
                "enabled": share_enabled("smb", settings),
                "running": smb_running,
                "state": "running" if smb_running else "stopped",
            },
            "nfs": {
                "enabled": share_enabled("nfs", settings),
                "running": nfs_is_running,
                "state": "running" if nfs_is_running else "stopped",
            },
        },
    }))


def reboot_system():
    shares_stop()
    qbt_stop()
    run(["/sbin/reboot"])


def main():
    operations = {
        "vpn-start": vpn_start,
        "vpn-stop": vpn_stop,
        "vpn-check": vpn_check,
        "clock-save": clock_save,
        "qbt-start": qbt_start,
        "qbt-stop": qbt_stop,
        "smb-start": smb_start,
        "smb-stop": smb_stop,
        "nfs-start": nfs_start,
        "nfs-stop": nfs_stop,
        "shares-start": shares_start,
        "shares-stop": shares_stop,
        "status": status,
        "reboot": reboot_system,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in operations:
        print(
            "usage: qbtos-control "
            "{vpn-start|vpn-stop|vpn-check|clock-save|qbt-start|qbt-stop|"
            "smb-start|smb-stop|nfs-start|nfs-stop|shares-start|shares-stop|status|reboot}",
            file=sys.stderr)
        return 2
    try:
        result = operations[sys.argv[1]]()
    except (OSError, RuntimeError, json.JSONDecodeError,
            subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0 if result is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
