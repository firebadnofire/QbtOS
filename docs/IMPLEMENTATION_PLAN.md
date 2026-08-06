# qbtOS Initial Image Implementation Plan

## Milestone boundary

This milestone targets Raspberry Pi 4 Model B (64-bit) plus amd64 and arm64
QEMU development guests, wired DHCP, a read-only SquashFS system, persistent
configuration, VPN setup, qBittorrent, and a small HTTPS management interface.
The broader roadmap remains in `VISION.md`.

## Delivery sequence

1. Pin Buildroot 2026.05.1 and derive `qbtos_rpi4_defconfig` from its supported
   Raspberry Pi 4 64-bit configuration.
2. Produce a raw MBR SD image containing FAT boot, A/B SquashFS system slots,
   and a labeled ext4 state partition. Keep runtime writes in tmpfs or `/config`.
3. Package qBittorrent 4.6.7 from source and install Python standard-library
   management code through the external tree.
4. Mount persistent state, apply the nftables traffic lock, start the HTTPS
   manager, and leave qBittorrent stopped until setup and VPN route checks pass.
5. Validate Buildroot metadata and manager tests, build from a clean output
   directory, and inspect the image and target filesystem.
6. Reuse the appliance userspace for QEMU, generate separate system and data
   QCOW2 disks, and provide a direct-kernel launcher with loopback-only port
   forwarding.
7. Add U-Boot boot selection, RAUC inactive-slot installation, local boot
   confirmation, atomic state generations, signed release metadata, and a
   Forgejo revision-tag pipeline.

## Safety boundary

The qBittorrent process runs as a dedicated unprivileged user. nftables rejects
that user's non-Web-UI traffic unless it leaves through `wg0` or `tun0`.
Starting qBittorrent additionally requires installation state, an active VPN
interface, a VPN route for an external address, and the qbtOS firewall table.
If any check fails, qBittorrent remains stopped. This development milestone
does not claim production-grade leak testing until verified on Raspberry Pi
hardware and against disconnect, route-change, DNS, and reboot scenarios.

## Current status

The image path, manager tests, Buildroot metadata, filesystem contents, raw
partition payloads, A/B environment, and optional imager-created data partition
were validated on a Linux build host. A Raspberry Pi 4 has booted slot A through
U-Boot to serial login, DHCP, and the HTTPS manager. The latest extended-layout
image still needs a physical reflash, and signed inactive-slot installation,
fallback, state survival, and exhaustive VPN leak testing remain open. amd64
and arm64 QEMU guests boot to the HTTPS setup interface; see `VALIDATION.md`.

## Deferred work

- Automated USB/FAT configuration import and general removable-media mounting
- Wi-Fi, Raspberry Pi 5, and transactional FAT/kernel updates
- Successful production-signed Forgejo publication and feed deployment
- Production PKI, hardened privilege separation, and browser-trusted TLS
- Provider-specific VPN behavior and exhaustive network-namespace leak tests
