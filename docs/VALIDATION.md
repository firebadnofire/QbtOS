# Development Image Validation

## Current development image (2026-08-06)

The latest locally built Raspberry Pi artifact is
`output/images/sdcard.img` (807,403,520 bytes) with SHA-256:

```text
d2f53fda22ba6ea0971d8cfdeaf2ececb208edea480ab40eaba5b1013efe3e9a
```

The digest identifies this build, not a reproducible-build guarantee: ext4
UUIDs and timestamps can make separate builds byte-different. `fdisk` and
`partx` report disk signature `0x5142544f`, a 64 MiB FAT boot partition, 96 MiB
slots A and B, and a 513 MiB extended partition containing the 512 MiB logical
state partition as partition 5. Byte comparisons matched the boot image, both
SquashFS slots, and state filesystem. The redundant U-Boot environment records
remain in the reserved state-partition tail; `fw_printenv` reads `BOOT_ORDER=A
B` and three attempts for each slot. The state filesystem passes read-only
`e2fsck`.

The current SquashFS is XZ-compressed and contains RAUC, GPGV, qBittorrent-nox,
WireGuard/OpenVPN tools, the manager/update/migration/confirmation services,
BusyBox `stat`, and the traffic lock. The FAT image contains U-Boot and a boot
script that selects the root by PARTUUID. It retains `enable_uart=1`,
`dtoverlay=disable-bt`, `console=ttyAMA0,115200n8`, and the respawning serial
getty. Production RAUC and OpenPGP public keys are intentionally absent from a
normal development image.

### Live amd64 QEMU and cloud-init test

`build-scripts/build.sh --format qcow --arch amd64 --size 16` completed from a
clean QEMU output directory. Both QCOW2 files pass `qemu-img check`; the data
image has an exact 16 GiB virtual capacity. A fresh KVM guest was exposed only
for the test on the host's libvirt bridge. A disposable VM created with
`~/git/cloud-init-automation` independently reached the manager over HTTPS;
plaintext HTTP on the management port was rejected.

The supplied `ca-mtr-wg-001.conf` established a recent WireGuard handshake.
The manager reported a protected default route and loaded firewall, while
remaining reachable from the LAN. qBittorrent started bound to `wg0`, its Web
API authenticated, and `debian-13.6.0-amd64-DVD-1.iso.torrent` was accepted.
After an eight-second observation window it was paused with zero payload bytes
downloaded. It was then resumed and the VPN was stopped: qBittorrent stopped
automatically, protection status became false, and the cloud-init controller
still received HTTP 200 from the manager. The VM-only random password was
deleted, the guest was stopped, and the controller VM/run disk/cloud-init ISO
were removed. The VPN profile and torrent fixture remain ignored and were not
copied into tracked source or cloud-init data.

This found and fixed missing immutable-root mount directories, BusyBox `stat`,
dual-stack profile handling on the IPv4-only milestone, policy-routing/nftables
kernel options, LAN return routing, active-generation traversal, and an
unsupported qBittorrent command-line option. The read-only entropy-seed warning
remains; QEMU supplies runtime entropy through virtio RNG.

`make check` processed 2,671 external-tree lines with zero warnings, ran 20
manager/update tests and seven release/Forgejo tests, and passed. ShellCheck,
Python byte compilation, workflow YAML parsing, Git whitespace checks, ignored
fixture checks, private-key marker scanning, and Buildroot submodule cleanliness
also passed. `make legal-info` completed under `output/legal-info` with the
documented Buildroot/toolchain source warnings.

### Remaining acceptance boundary

A preceding A/B image booted slot A through U-Boot on a Raspberry Pi 4, mounted
the SquashFS root read-only and state ext4 read/write, obtained DHCP, and served
the manager over HTTPS. The current image changes the partition container so
the imager can append logical `QBTOS_DATA`; it has been inspected on the host
but has **not** yet been reflashed and booted on hardware.

No end-to-end production `make release` has completed with the production RAUC
inputs. Artifact naming, deterministic manifest creation, four-file
enforcement, OpenPGP checksum verification, downgrade rejection, inactive-slot
selection, state migration, and fallback logic are covered by host tests.
Hardware still must demonstrate signed installation to inactive B,
three-failure fallback, healthy-B confirmation, and state/configuration survival
across update and rollback.

## Historical initial image validation

Validation began on 2026-08-01 and hardware testing followed on 2026-08-02.
Buildroot release `2026.05.1` at commit
`cb857ba4c87a93e5265a9e4a3f32071abf39e14a` was built from a clean output tree:

```bash
make distclean
make configure
make build
```

The build completed and produced `output/images/sdcard.img` (241 MiB). Its
SHA-256 at validation time was:

```text
9fc5bf9be95429bc3260fb6b38704363c0905ac195955a7f46287e3c8e9d0738
```

This hash is informational: filesystem UUIDs and timestamps currently make
separate builds byte-different.

### Host-side results

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
- `make check` processed 1,376 external-tree lines with zero warnings using
  Flake8 7.3.0 and ShellCheck 0.10.0. All seven manager unit tests passed.
- Python byte-compilation, POSIX shell syntax checks, Git whitespace checks, and
  a source-tree scan for private keys and VPN credential material passed.
- `make legal-info` produced manifests, sources, and license files under
  `output/legal-info`. Buildroot still emits its expected notices that its own
  source is not copied and that the external Bootlin toolchain does not declare
  a savable license file.

### Hardware validation

On 2026-08-05, the first A/B image was reported to reset repeatedly on a
Raspberry Pi 4. Inspection found that U-Boot loaded `boot.scr` at `0x02400000`
and then loaded the 24 MiB kernel at `0x02000000`, overwriting the running
script. The load addresses now use U-Boot's Raspberry Pi layout
(`kernel_addr_r=0x00080000`, `scriptaddr=0x05400000`), and firmware-stage UART
logging is enabled with `uart_2ndstage=1`. The corrected image was rebuilt and
inspected, but it has not yet been reflashed and booted on hardware. The
connected UART produced only NUL bytes from the old image, so it provided no
readable firmware, U-Boot, or kernel trace.

After reflashing that correction, the board still reset. Firmware-stage UART
then proved that EEPROM and `start4.elf` completed, the device tree and
`u-boot.bin` loaded, and execution transferred to ARM before the reset. The
qbtOS default environment had replaced U-Boot's Raspberry Pi environment while
omitting `stdin`, `stdout`, and `stderr`, despite
`CONFIG_SYS_CONSOLE_IS_IN_ENV=y`; this hid all U-Boot diagnostics. The
environment now routes all three streams to `serial`, restores U-Boot's standard
Raspberry Pi memory variables, and leaves a failed kernel boot at the recovery
prompt instead of resetting. A new image containing these changes has been
built and inspected but remains to be reflashed and hardware-tested.

Subsequent UART tracing localized the reset to U-Boot's pre-relocation
`serial_init`. Address resolution against the matching U-Boot ELF showed
`serial_check_stdout()` calling `device_get_uclass_id()` with no device:
`lists_bind_fdt()` may return success while clearing its output pointer when no
driver matches the firmware-modified console node. The qbtOS U-Boot patch now
requires a non-NULL bound device before inspecting it, allowing the existing
fallback serial search to run. Commit `164a1a8b99` did not exhibit this failure
because it configured Raspberry Pi firmware to load `Image` directly and did
not contain the later U-Boot/RAUC A/B boot path. The patched image still
requires a Raspberry Pi reboot test.

That image subsequently booted on the Raspberry Pi 4 through U-Boot slot A and
reached Buildroot init. UART showed the SquashFS root mounted read-only, the
ext4 state partition mounted read/write, Ethernet linked at 1 Gbit/s, and the
manager started. The host received HTTP 200 JSON status from
`https://192.168.86.65:8080`; qBittorrent correctly remained stopped because
setup and VPN protection were incomplete. Boot confirmation exposed a separate
mdev integration issue: BusyBox `blkid` omitted MBR PARTUUID metadata, leaving
the stable device links used by RAUC and `fw_printenv` absent. Early persistence
setup now derives the MBR signature and materializes those links. That follow-up
fix still requires an image reboot test.

### Interactive imager validation

The SD image now uses a DOS extended partition so the immutable boot and A/B
slots remain primary, `QBTOS_STATE` is logical partition 5, and the imager can
append `QBTOS_DATA` as logical partition 6. Host inspection found all five base
entries, byte-compared the embedded state filesystem with `state.ext4`, and
confirmed the redundant U-Boot environment at its shifted fixed offsets. A
disposable sparse 3 GiB image test extended partition 4, preserved partitions
1 through 5, and added an exact 1 GiB Linux partition 6. Unit tests cover
external/large-device tags, zero-size behavior, destructive confirmation, and
the append operation. This environment does not permit loop-device attachment,
so the final `mkfs.ext4` call was not exercised through a fake block device.
The extended-partition image and imager output have not yet been booted on
Raspberry Pi hardware.

The imager can also create partition 6 with MBR type 7 and an NTFS filesystem;
the target includes NTFS label detection and a writable NTFS3 mount path. Those
paths have unit and configuration coverage but have not yet been exercised on
Raspberry Pi hardware. qBittorrent is configured to reuse the manager TLS
certificate on port 8081; that HTTPS endpoint also awaits rebuilt-image runtime
validation.

A development image booted on a Raspberry Pi 4. The PL011 console and
respawning login were usable through `/dev/ttyUSB0`; the SquashFS root mounted
read-only; Ethernet obtained `192.168.86.65` by DHCP; and the manager returned
HTTP 200 plus live JSON status at `https://192.168.86.65:8080` after its state
partition was mounted. The self-signed certificate and TLS 1.2 service were
also inspected from the build host.

This test exposed two image defects: util-linux could not resolve the config
partition's label in this minimal userspace, and an `inet` nftables table was
incompatible with the intentionally IPv6-disabled kernel. The repository now
scans block metadata for the exact labels and uses an IPv4 `ip` table. The `ip`
ruleset was successfully loaded on the running Pi without losing HTTPS access.
The corrected image above was rebuilt and inspected, but has not yet been
reflashed and reboot-tested.

WireGuard, OpenVPN, qBittorrent transfers, external data storage, disconnect
leak behavior, power-loss recovery, and provider compatibility remain
unverified end to end. Do not treat this development result as a production
anonymity guarantee.

### Earlier QEMU validation

The 2026-08-05 boot-loop investigation also booted a fresh amd64 guest, checked
the read-only root and writable configuration/data mounts, received HTTP 200
from the HTTPS health API, performed an orderly reboot, and received HTTP 200
again. This validates common userspace behavior, not Raspberry Pi firmware or
U-Boot execution.

Both QEMU architectures were configured and built in independent output trees:

```bash
./build-scripts/build.sh --format qcow --arch amd64
./build-scripts/build.sh --format qcow --arch arm64
```

Each system QCOW2 contains an MBR SquashFS system partition and a clean 128 MiB
`QBTOS_CONFIG` ext4 partition. Each separate data QCOW2 contains a clean
`QBTOS_DATA` ext4 filesystem. The default 16 GiB virtual size was confirmed;
an amd64 build with `--size 3` also produced an exact 3 GiB virtual data disk.
The SquashFS payloads contain architecture-correct qBittorrent executables and
the expected manager, VPN, firewall, and persistence components.

Fresh amd64 and arm64 guests booted with the checked-in launcher. In both,
SquashFS remained read-only, configuration and data filesystems mounted
writable, nftables loaded, and DHCP assigned `10.0.2.15`. HTTPS setup and status
requests through the loopback port forward returned HTTP 200; plaintext HTTP
was rejected; and qBittorrent stayed stopped without completed setup and VPN
checks. amd64 used KVM and arm64 used TCG on the validation host. A deliberately
interrupted TLS identity was also detected and safely regenerated on the next
manager start. At that stage, guests had not been tested with real VPN
credentials or torrent traffic; the newer amd64 test is recorded above. Early
boot currently warns that the read-only root cannot store an
entropy seed; virtio RNG supplied runtime entropy, but persistent seed handling
remains a focused hardening TODO.
