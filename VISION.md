# qbtOS Vision

## Summary

qbtOS is a specialized Raspberry Pi operating system for running qBittorrent safely through a VPN.

It is designed for self-hosting enthusiasts who want a simple, reliable torrent appliance without configuring a full general-purpose Linux distribution. A user should be able to write qbtOS to an SD card, provide a VPN configuration, connect storage, boot the Raspberry Pi, and manage torrents through a web interface.

The core promise is:

> A simple VPN-enabled torrent server that is ready to use with minimal configuration.

## Product Goals

qbtOS should:

1. Run qBittorrent as a dedicated network appliance.
2. Route torrent traffic through a supported VPN connection.
3. Prevent torrent traffic from leaking outside the VPN tunnel.
4. Provide a web-based setup and management interface.
5. Support unattended first-boot configuration from removable or attached storage.
6. Keep the base operating system small, dependable, and mostly immutable.
7. Store downloads and persistent configuration separately from the operating system.
8. Be reproducible from source and suitable for automated image builds.
9. Recover cleanly from interrupted boots, power loss, and failed updates.
10. Require little or no routine Linux administration after initial setup.

## Primary Audience

qbtOS is intended primarily for self-hosting enthusiasts.

The expected user is comfortable with concepts such as:

* Writing an image to an SD card
* Connecting a USB drive
* Using a web interface on a local network
* Obtaining a VPN configuration from a VPN provider
* Assigning storage for downloads

The user should not need to manually install packages, configure system services, edit firewall rules, or administer a conventional Linux server.

## Core Experience

The normal qbtOS setup flow should be:

1. Download and write the qbtOS image to an SD card.
2. Place a VPN configuration on a USB drive, configuration partition, or other supported filesystem.
3. Connect a storage device for torrent data.
4. Insert the SD card and boot the Raspberry Pi.
5. Open the qbtOS web interface from another device.
6. Confirm or complete setup.
7. Add torrents through the qBittorrent Web UI.

Once configured, the appliance should boot directly into a working VPN-protected qBittorrent service.

## Configuration Methods

qbtOS should support two configuration paths.

### Web Setup

On first boot, qbtOS exposes a setup web interface on the local network.

The setup interface should allow the user to:

* Import a VPN configuration
* Configure VPN credentials when required
* Select or initialize download storage
* Set the qBittorrent administrator password
* Configure the hostname
* Configure basic network options
* Test VPN connectivity
* Confirm that torrent traffic cannot leave through the normal network interface
* Finish setup and start qBittorrent

The setup interface should clearly report whether the VPN is connected and whether the traffic lock is active.

### Automatic Configuration

A user may prepare an ext4 or FAT32 filesystem containing a supported VPN configuration and optional qbtOS settings.

At boot, qbtOS should inspect supported removable devices and configuration partitions for a recognized configuration layout.

A minimal automatic configuration should require only:

* A supported VPN configuration
* Writable storage for qBittorrent data

Optional settings may include:

* VPN credentials
* qBittorrent Web UI credentials
* Hostname
* Static network configuration
* Download directory
* Incomplete download directory
* Port settings
* DNS settings
* Locale and timezone

When valid configuration is found, qbtOS should import it, apply safe defaults, and start without requiring interaction through the setup interface.

Automatic configuration must be deterministic and documented. It should not silently guess when multiple conflicting configurations are present.

## Storage Model

qbtOS should distinguish between three classes of storage.

### System Storage

The operating system should use a read-only SquashFS root filesystem.

The base system should contain:

* The Linux kernel and required modules
* The init system
* Networking tools
* VPN support
* Firewall support
* qBittorrent
* The qbtOS management service
* The setup web interface
* Recovery and update tools

The base root filesystem should not contain user torrent data.

### Persistent Configuration

Persistent configuration should live outside the SquashFS root.

This includes:

* qbtOS settings
* VPN configuration
* VPN credentials or references to protected credentials
* qBittorrent configuration
* SSH host keys, when SSH is enabled
* Device identity
* Update state
* Boot success state

Persistent configuration may live on a dedicated writable partition or approved external storage.

### Torrent Data

Torrent data should live on a user-selected ext4 filesystem whenever possible.

This includes:

* Completed downloads
* Incomplete downloads
* Torrent metadata
* Resume data
* Watch directories
* Optional logs and statistics

FAT32 may be supported for importing configuration, but it is a poor primary download filesystem because of its file size and filesystem limitations. qbtOS should recommend ext4 for torrent storage.

## Networking and VPN Safety

VPN protection is a defining feature of qbtOS, not an optional convenience.

qbtOS must:

* Establish the VPN before starting torrent transfers
* Bind qBittorrent to the VPN interface where supported
* Apply firewall rules that prevent torrent traffic from leaving through other interfaces
* Keep the local management interface reachable from the trusted LAN
* Prevent DNS traffic from bypassing the VPN unless explicitly configured
* Stop or pause torrent traffic when the VPN disconnects
* Restore service automatically when the VPN reconnects
* Clearly expose VPN and traffic-lock status in the web interface

A broken VPN connection must fail closed.

The system should never report itself as protected merely because a VPN process is running. Protection should be based on actual interface, route, DNS, and firewall state.

## Supported VPN Technologies

The initial release should prioritize:

1. WireGuard
2. OpenVPN

WireGuard should be preferred where available because it has a smaller configuration surface and is well suited to an appliance.

Additional VPN technologies may be added later, but they should not complicate the first release.

## Web Interfaces

qbtOS may expose two related interfaces.

### qbtOS Management Interface

This interface manages the appliance itself.

It should provide:

* First-boot setup
* VPN status
* VPN configuration import
* Storage selection and health
* Network information
* Service status
* System update controls
* Reboot and shutdown controls
* Diagnostic information
* Backup and restore of configuration

### qBittorrent Web UI

The standard qBittorrent Web UI should remain available for torrent management.

qbtOS should avoid unnecessarily reimplementing qBittorrent features. The qbtOS interface should manage the appliance, while the qBittorrent interface should manage torrents.

The two interfaces may be linked or presented behind a common landing page.

## Operating System Design

qbtOS should behave like firmware rather than a conventional desktop or server distribution.

The intended architecture is:

* Raspberry Pi boot firmware and boot files on a FAT partition
* Linux kernel and initramfs
* Read-only SquashFS system root
* Temporary writable OverlayFS layer in RAM
* Separate persistent configuration storage
* Separate torrent data storage
* Optional A/B system images for safe updates and rollback

Routine writes should not modify the base operating system.

The system should remain operational after unexpected power loss whenever the underlying hardware remains healthy.

## Updates

Updates should replace the system image rather than mutate the installed root filesystem package by package.

The long-term update model should support:

* Signed update manifests
* Cryptographic image verification
* A/B system slots
* Automatic rollback after a failed boot
* Preservation of configuration and torrent state
* Clear reporting of the active and inactive system versions

The first prototype may use a simpler update mechanism, but its filesystem layout should not block the future A/B design.

## Security Principles

qbtOS should follow these principles:

* No default remote administrative password
* First-boot credential creation
* Local-network-only setup by default
* Firewall enabled by default
* VPN traffic lock enabled by default
* Minimal installed software
* No unnecessary listening services
* Read-only base operating system
* Signed production updates
* Secrets excluded from logs
* Sensitive configuration stored with restrictive permissions
* SSH disabled by default in production images, or limited to explicit opt-in
* Clear warnings when the user selects unsafe settings

qbtOS should not claim to make torrenting lawful, anonymous, or risk-free. It should accurately describe the protections it implements without making guarantees outside its control.

## Licensing

Original qbtOS software is licensed under the GNU General Public License version 3 or later.

qbtOS is a software distribution containing independently licensed components. Each included component remains subject to its own license.

qBittorrent is an independent project. qbtOS is not affiliated with or endorsed by the qBittorrent project unless such a relationship is established later.

## Responsibility Notice

qBittorrent is a file-sharing program. When a torrent is active, data may be uploaded to other peers.

Users are responsible for the content they download, possess, and share, and for complying with laws, contracts, network policies, and VPN provider terms that apply to them.

qbtOS should present this notice during setup without repeatedly interrupting normal operation.

## Initial Hardware Target

The first supported hardware target should be the Raspberry Pi 4 Model B, using its 64-bit ARM architecture.

Initial development should prioritize:

* Raspberry Pi 4 Model B
* Wired Ethernet
* USB-attached ext4 storage
* Headless operation
* Serial-console diagnostics
* WireGuard and OpenVPN
* qBittorrent Web UI

Support for Raspberry Pi 5, Wi-Fi-only operation, and other ARM boards may follow after the Raspberry Pi 4 image is dependable.

## Minimum Viable Product

The first usable qbtOS release should provide:

* A bootable Raspberry Pi 4 image
* A read-only SquashFS root filesystem
* Persistent configuration outside the system root
* USB or partition-based configuration import
* WireGuard support
* OpenVPN support
* A firewall-based VPN traffic lock
* qBittorrent-nox
* The qBittorrent Web UI
* A basic qbtOS setup and status web interface
* External ext4 download storage
* Safe behavior when the VPN disconnects
* Reboot-safe qBittorrent configuration and resume state
* Basic logs and diagnostics
* Reproducible image builds

## Non-Goals for the Initial Release

The initial qbtOS release is not intended to be:

* A desktop operating system
* A general-purpose Raspberry Pi server distribution
* A media center
* A seedbox hosting platform for multiple unrelated users
* A container orchestration system
* A NAS replacement
* A full VPN router for the rest of the network
* A torrent search engine
* A tool for bypassing copyright law or network policy
* A system that supports every VPN provider-specific application
* A package-managed rolling Linux installation

Features outside the core appliance purpose should be rejected unless they directly improve VPN-protected qBittorrent operation.

## Design Priorities

When design choices conflict, qbtOS should prioritize them in this order:

1. Preventing traffic leaks
2. Preserving torrent and configuration state
3. Reliable unattended boot
4. Simple setup
5. Recoverable updates
6. Clear diagnostics
7. Small image size
8. Additional features

A smaller or more elegant implementation is not better when it weakens leak prevention or recovery.

## Success Criteria

qbtOS succeeds when a user can:

1. Write the image to an SD card.
2. Copy a VPN configuration to a supported filesystem.
3. Connect an ext4 storage device.
4. Boot the Raspberry Pi.
5. Open a web interface.
6. Add a torrent.
7. Confirm that torrent traffic uses only the VPN.
8. Reboot or lose power without losing configuration or torrent state.
9. Update the operating system without rebuilding the appliance manually.

The product should feel like a dedicated device, not a Linux installation the user must continually maintain.
