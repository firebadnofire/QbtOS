# Development Image Validation

Validation was performed on 2026-08-01. Buildroot release `2026.05.1` at commit
`cb857ba4c87a93e5265a9e4a3f32071abf39e14a` was built from a clean output tree:

```bash
make distclean
make configure
make build
```

The build completed and produced `output/images/sdcard.img` (241 MiB). Its
SHA-256 at validation time was:

```text
f68d4a1666d1bbd57812902167bebc1ad3da000fe6aed0d3cbbc08649c9165a7
```

This hash is informational: filesystem UUIDs and timestamps currently make
separate builds byte-different.

## Host-side results

- `make configure` accepted the checked-in defconfig.
- A full clean build, followed by an incremental metadata rebuild, completed.
- `fdisk` reported an MBR image with a 64 MiB FAT32 boot partition at sector
  2048, a 48 MiB Linux system partition at sector 133120, and a 128 MiB Linux
  configuration partition at sector 231424.
- Each partition's bytes in `sdcard.img` matched `boot.vfat`,
  `rootfs.squashfs`, or `config.ext4` at the declared offset.
- `unsquashfs` identified a valid SquashFS 4.0 filesystem using XZ compression.
  It contains qBittorrent-nox, the manager and fixed control helper, setup HTML,
  nftables policy, and all qbtOS init scripts.
- The qBittorrent executable is a stripped ARM64 ELF. The kernel configuration
  includes SquashFS, ext4, OverlayFS, TUN, WireGuard, nftables, and IPv4 reject
  support; IPv6 is disabled for this milestone.
- The `QBTOS_CONFIG` ext4 filesystem is clean, and its initial private qbtOS
  directory is owned by root with mode `0700`.
- The FAT image contains `overlays/disable-bt.dtbo`; its firmware configuration
  enables the UART and applies that overlay. The kernel has PL011 console
  support, names `ttyAMA0` on its command line, and the SquashFS init table
  continuously respawns a 115200-baud getty on the same device.
- `make check` processed 1,120 external-tree lines with zero warnings using
  Flake8 7.3.0 and ShellCheck 0.10.0. All seven manager unit tests passed.
- Python byte-compilation, POSIX shell syntax checks, Git whitespace checks, and
  a source-tree scan for private keys and VPN credential material passed.
- `make legal-info` produced manifests, sources, and license files under
  `output/legal-info`. Buildroot still emits its expected notices that its own
  source is not copied and that the external Bootlin toolchain does not declare
  a savable license file.

## Hardware validation still required

The image has **not** been booted on a physical Raspberry Pi. DHCP, GPIO serial
output, browser access, TLS generation, both VPN implementations, qBittorrent
operation, external storage, disconnect leak behavior, power-loss recovery, and
provider compatibility therefore remain unverified end to end. Do not treat
this development result as a production anonymity guarantee.
