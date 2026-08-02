# qbtOS Initial Image Implementation Plan

## Milestone boundary

This milestone targets only Raspberry Pi 4 Model B (64-bit), wired DHCP, a
read-only SquashFS system, persistent configuration, VPN setup, qBittorrent,
and a small HTTPS management interface. The broader roadmap remains in
`VISION.md`.

## Delivery sequence

1. Pin Buildroot 2026.05.1 and derive `qbtos_rpi4_defconfig` from its supported
   Raspberry Pi 4 64-bit configuration.
2. Produce a raw MBR SD image containing FAT boot, SquashFS system, and labeled
   ext4 configuration partitions. Keep runtime writes in tmpfs or `/config`.
3. Package qBittorrent 4.6.7 from source and install Python standard-library
   management code through the external tree.
4. Mount persistent state, apply the nftables traffic lock, start the HTTPS
   manager, and leave qBittorrent stopped until setup and VPN route checks pass.
5. Validate Buildroot metadata and manager tests, build from a clean output
   directory, and inspect the image and target filesystem.

## Safety boundary

The qBittorrent process runs as a dedicated unprivileged user. nftables rejects
that user's non-Web-UI traffic unless it leaves through `wg0` or `tun0`.
Starting qBittorrent additionally requires installation state, an active VPN
interface, a VPN route for an external address, and the qbtOS firewall table.
If any check fails, qBittorrent remains stopped. This development milestone
does not claim production-grade leak testing until verified on Raspberry Pi
hardware and against disconnect, route-change, DNS, and reboot scenarios.

## Current status

The image path, manager tests, Buildroot metadata checks, filesystem contents,
and raw partition payloads have been validated on a Linux build host. Physical
Raspberry Pi boot and network leak testing remain open; see `VALIDATION.md`.

## Deferred work

- Automated USB/FAT configuration import and general removable-media mounting
- Wi-Fi, Raspberry Pi 5, A/B updates, signed releases, and rollback
- Production PKI, hardened privilege separation, and browser-trusted TLS
- Provider-specific VPN behavior and exhaustive network-namespace leak tests
