# qbtOS

qbtOS is a development-stage, Buildroot-based appliance for running
qBittorrent behind WireGuard or OpenVPN. The primary target is a 64-bit
Raspberry Pi 4 Model B with wired Ethernet; amd64 and arm64 QEMU targets are
provided for development. See [VISION.md](VISION.md) for the longer-term goals.

qbtOS uses a read-only SquashFS system with A/B slots, a writable state
partition, and separate torrent-data storage. A small HTTPS management service
handles first-time setup and reports VPN, firewall, qBittorrent, storage, and
update status. Saved VPN settings are restored on boot before qBittorrent is
started. qBittorrent remains stopped unless setup is complete and the VPN
traffic-lock checks pass. After setup, the manager provides explicit Start,
Stop, and Restart controls plus the service state, PID, storage readiness, and
the reason a fail-closed start was refused.

> **Development warning:** qbtOS has not been certified for privacy or
> anonymity. The fail-closed design has been exercised in QEMU, but disconnect,
> DNS, update/rollback, and leak testing on Raspberry Pi hardware remain release
> requirements.

## Clone and build

Use a current 64-bit Linux host with a case-sensitive filesystem, network
access, and approximately 20–30 GiB of available disk space. Distribution
package examples and the authoritative tool list are in
[docs/BUILDING.md](docs/BUILDING.md).

```bash
git clone --recurse-submodules \
  https://pubcode.archuser.org/firebadnofire/qbtOS.git
cd qbtOS
make configure
make build
```

For an existing checkout, initialize the pinned Buildroot submodule first:

```bash
git submodule update --init --recursive
```

The build produces the SD-card-ready raw image:

```text
output/images/sdcard.img
```

All qbtOS targets include the `curl` command-line client and CA certificate
bundle for HTTPS diagnostics and integration testing.

Routine builds use the checked-in defconfig and do not require `menuconfig`.
Use `make rebuild` for a clean target rebuild or `make distclean` followed by
the two build commands for a completely fresh output tree.

## Write the SD card

The recommended writer is the repository's interactive terminal imager:

```bash
sudo make imager
```

From an elevated Windows PowerShell terminal, use the native equivalent. It
offers NTFS or ext4 for the optional end partition and defaults to NTFS:

```powershell
.\build-scripts\imager.ps1
```

Both imagers offer default-image and custom-path choices in the terminal UI,
accept raw `.img` and Zstandard-compressed `.img.zst` images, and support an
explicit path such as `--image C:\path\to\qbtos.img.zst`. The Windows imager
requires `zstd.exe` on `PATH` for compressed images and `mke2fs.exe` or
`mkfs.ext4.exe` on `PATH` when ext4 is selected.

Select the **whole SD-card device**, not a partition. The imager identifies
external devices and devices larger than 100 GiB, asks for destructive
confirmation, writes and verifies the image, and optionally allocates an ext4
or Windows-compatible NTFS `QBTOS_DATA` partition in the card's remaining
space. Enter `0` at the storage prompt if torrent data will live on a separately
supplied USB or other writable filesystem.

Device selection can destroy all data on the selected disk. Read
[docs/FLASHING.md](docs/FLASHING.md) before proceeding; it also documents a
manual `lsblk`/`dd`/`sync` workflow and generic imaging applications.

## Boot and complete setup

1. Connect the Raspberry Pi 4 to a trusted LAN using Ethernet.
2. Attach writable data storage unless the imager created `QBTOS_DATA` on the
   SD card.
3. Insert the card and power on the Pi.
4. Find the `qbtos` DHCP lease in the router's client list.
5. Open `https://LAN-IP:8080` and accept the expected development certificate
   warning after verifying the device address. The `https://` scheme is
   required; plaintext HTTP is not exposed on this port.
6. Set the qBittorrent administrator credentials, provide a WireGuard or
   OpenVPN configuration, select the data path, and test the VPN.
7. Complete installation only when the manager reports active VPN protection.

Successful installation redirects to qBittorrent's standard HTTPS Web UI at
`https://LAN-IP:8081`. It reuses the device certificate from port 8080, so the
same development certificate warning is expected. Verify protection status
before adding torrents. Detailed setup, diagnostics, and always-on 115200-baud
GPIO UART instructions are in [docs/FIRST_BOOT.md](docs/FIRST_BOOT.md).

The public X.509 hierarchy under `ca/` is included in every base image solely
for update authentication. `root-ca.pem` is installed as RAUC's immutable
`/etc/rauc/keyring.pem`; the intermediate chain and code-signing leaf are
retained under `/usr/share/qbtos/ca` for inspection. RAUC enforces the
`codeSigning` certificate purpose. The qbtOS CA is never added to the system
TLS CA bundle, and no private signing key is included.

After installation, the management UI can install qBittorrent alternative Web
UI themes from public, credential-free HTTPS Git URLs, update them atomically,
and switch between installed themes and qBittorrent's built-in UI. Theme files
are persistent at `/themes`, backed by the selected data filesystem. A theme is
accepted only when it contains `public/index.html` and no symbolic links.

The management UI also provides independently controlled SMB and NFSv4 shares
for the persistent `downloads` directory. Both services are disabled by
default. When enabled, clients on the trusted IPv4 LAN ranges can read and
write without credentials; clients arriving over the VPN or from any other
source are denied. This is source-network trust, not user authentication, so
enable sharing only on a LAN you control. SMB is available as
`\\qbtos\downloads` on TCP port 445. NFSv4 exports the directory as the
pseudofilesystem root and can be mounted with, for example:

```bash
sudo mount -t nfs4 qbtos:/ /mnt/qbtos-downloads
```

## QEMU development

Build a QCOW2 appliance and a separate sparse data disk with:

```bash
./build-scripts/build.sh --format qcow --arch amd64 --size 16
./build-scripts/run-qemu.sh --arch amd64
```

Use `--arch arm64` for the arm64 guest. The default forwarded management URL is
`https://127.0.0.1:8080`. See [docs/QEMU.md](docs/QEMU.md) for dependencies,
artifacts, networking, persistent overlays, and cross-architecture emulation.

## Development and release references

- [Building](docs/BUILDING.md): host packages, clean builds, logs, QEMU, and
  signed release commands.
- [Architecture](docs/ARCHITECTURE.md): boot chain, partitions, persistence,
  services, and security boundaries.
- [Signed updates](docs/UPDATES.md): revision tags, RAUC/U-Boot A/B operation,
  signing, rollback, and recovery.
- [Validation status](docs/VALIDATION.md): what has been tested and what still
  requires Raspberry Pi hardware.
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md): milestone scope and
  remaining work.
- [Contributor guide](AGENTS.md): repository layout, conventions, and checks.

Run `make check` before submitting changes. Buildroot license materials can be
generated after a successful build with `make legal-info`. Original qbtOS code
is licensed under GPL-3.0-or-later; bundled components retain their own
licenses. qBittorrent may upload data to peers, and users are responsible for
the content they download, possess, and share.

## Credits

Argon ONE case hardware and its original scripts are developed and distributed
by [Argon 40](https://www.argon40.com/). The Rust service integrated here is
the [Argon40case-Rust project](https://pubcode.archuser.org/firebadnofire/Argon40case-Rust),
which derives its hardware behavior from the
[Argon40-ArgonOne-Script project](https://github.com/okunze/Argon40-ArgonOne-Script).
qbtOS embeds the Rust project as a Git submodule, pins commit
`cbde9ecd2f03d74767f93e78107b2bd788d4bdab`, enables the Pi 4 I²C/GPIO
interfaces, and runs the fan and power-button daemon with its checked-in
defaults. The source repository currently contains no explicit license grant,
so qbtOS records it as third-party proprietary material in Buildroot legal
information rather than assigning it a qbtOS license. The software and Argon
branding remain the property of their respective owners; qbtOS is independent
and is not affiliated with or endorsed by Argon 40.
