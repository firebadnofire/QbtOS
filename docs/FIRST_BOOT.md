# First Boot

1. Connect the Raspberry Pi 4 to the trusted LAN with Ethernet.
2. If the interactive imager did not create an on-card `QBTOS_DATA` partition,
   connect a writable ext4 or NTFS data device with that label. qbtOS mounts the
   labeled filesystem at `/data`.
3. Insert the flashed SD card and power on the Pi.
4. Find the `qbtos` DHCP lease in the router, or inspect the router's client
   list. `qbtos.local` may work on some networks but is not assumed.
5. Open `https://LAN-IP:8080`—the `https://` scheme is required.
6. Accept the expected self-signed-certificate warning only after confirming
   that the address is the new qbtOS device.
7. Set qBittorrent credentials, load a full-tunnel WireGuard or OpenVPN
   configuration, select the mounted data path, and choose **Test VPN**.
8. Complete installation only after the interface reports active VPN
   protection. Verify status again before adding any torrent.

The management page shows the LAN address, selected path, protection result,
qBittorrent state, and basic diagnostics. Successful installation redirects to
the standard qBittorrent Web UI on `https://LAN-IP:8081`; the same link remains
available from management status. Port 8081 reuses the locally generated
certificate from port 8080, so the same certificate warning is expected. Sign
in with the qBittorrent credentials entered during setup. qBittorrent remains
stopped when protection checks fail.

After installation, the **qBittorrent service** panel provides **Start**,
**Stop**, and **Restart** controls. It reports the process state and PID,
persistent-state mount health, data-filesystem readiness, and a specific reason
when startup is blocked. Start and restart never bypass VPN or storage checks.

## Reboots and themes

The installation marker, VPN profile, qBittorrent profile, TLS identity, and
manager credentials live on `QBTOS_STATE` and survive reboot. The saved VPN is
started before qBittorrent. If its interface, route, firewall, or WireGuard
handshake check fails, qBittorrent deliberately remains stopped. Use **Retry
VPN and start qBittorrent** in the manager after correcting a transient LAN or
provider problem; repeating setup is unnecessary. The boot process waits for
the labeled state and data devices before declaring them missing, and refuses
to fall back to ephemeral root storage.

After setup, use **qBittorrent themes** in the manager to install a trusted
alternative Web UI from a public HTTPS Git repository. The checkout must have
`public/index.html`. Select **Built-in qBittorrent UI** to disable a theme.
Updates are explicit and replace a validated checkout atomically. All theme
files live in persistent `/themes` (backed by `/data/themes`).

Argon ONE cases use the upstream default fan curve. A double press requests a
reboot; a supported long press requests orderly shutdown and case power-off.
If the service reports that `/dev/i2c-1` is unavailable, verify the image is a
current Raspberry Pi build and inspect `dtparam=i2c_arm=on` in `config.txt`.

The status page also reports the qbtOS version, active and inactive system
slots, pending update state, and boot-attempt environment. Do not install an
update until its OpenPGP checksum and RAUC signature checks both succeed. See
[UPDATES.md](UPDATES.md) before exercising rollback or serial recovery.

The Pi has no battery-backed clock. qbtOS seeds it with the image build time and
persists a monotonic lower bound after VPN success and clean shutdown so a
reboot cannot replay an older WireGuard handshake timestamp. Accurate network
time synchronization remains future work.

## HTTPS behavior

qbtOS uses `sslh` to distinguish plaintext HTTP from TLS on ports 8080 and
8081. TLS is forwarded to loopback-only manager and qBittorrent HTTPS backends;
plaintext requests receive a permanent redirect to the corresponding HTTPS URL
with the path and query preserved. The redirect service does not process setup
credentials or proxy request bodies to an application over plaintext.

## Serial diagnostics

Development images keep the GPIO UART enabled and open at 115200 baud, 8 data
bits, no parity, one stop bit. `config.txt` contains `enable_uart=1` and
`uart_2ndstage=1`, so Raspberry Pi firmware and U-Boot diagnostics are emitted
before Linux starts. `dtoverlay=disable-bt` dedicates the stable PL011 UART to
GPIO 14/15 instead of onboard Bluetooth. U-Boot appends
`console=ttyAMA0,115200n8` to the kernel command line and neither stage uses
quiet boot. BusyBox init opens its login getty
directly on `ttyAMA0` and respawns it whenever it exits, so the port remains
available after boot as well as during kernel startup.

U-Boot routes its input, output, and error streams to this serial port. If the
selected kernel cannot start, qbtOS stops at the U-Boot recovery prompt instead
of repeatedly resetting. Run `reset` at the prompt only after recording the
failure and correcting the boot environment or SD-card contents.

Use a **3.3-volt TTL** USB serial adapter, never an RS-232-level adapter. Connect
Pi GPIO pin 8 (TX) to adapter RX, pin 10 (RX) to adapter TX, and a Pi ground
(for example pin 6) to adapter ground. A common ground is required. Do not
connect the adapter power pin unless a specific, understood setup requires it.
At 115200 baud, use a terminal such as `picocom /dev/ttyUSB0 -b 115200`.

If DHCP fails, the serial log can show link state, DHCP attempts, configuration
partition mount errors, firewall loading, and manager startup. Hardware boot and
network behavior remain mandatory validation before a production release.
