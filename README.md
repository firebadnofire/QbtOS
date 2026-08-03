# qbtOS

qbtOS is a development-stage, Buildroot-based Raspberry Pi 4 appliance for
running qBittorrent through WireGuard or OpenVPN, with amd64 and arm64 QEMU
targets for development. Its design goals and future scope are described in
[VISION.md](VISION.md).

## Build an image

```bash
git clone --recurse-submodules REPOSITORY_URL
cd qbtOS
./build-scripts/build.sh
```

The raw SD-card image is written to `output/images/sdcard.img`. See
[docs/BUILDING.md](docs/BUILDING.md), [docs/FLASHING.md](docs/FLASHING.md), and
[docs/FIRST_BOOT.md](docs/FIRST_BOOT.md) before using it. Host-side verification
results are recorded in [docs/VALIDATION.md](docs/VALIDATION.md). Signed
Raspberry Pi A/B release and recovery procedures are in
[docs/UPDATES.md](docs/UPDATES.md).

The equivalent two-step Make interface is `make configure && make build`.

Build and run an amd64 or arm64 QEMU appliance with:

```bash
./build-scripts/build.sh --format qcow --arch amd64 --size 16
./build-scripts/run-qemu.sh --arch amd64
```

The management interface is then available at `https://127.0.0.1:8080`. See
[docs/QEMU.md](docs/QEMU.md) for artifacts, persistent runtime storage, port
forwarding, and cross-architecture emulation.

> **Development warning:** this first image has not been certified for privacy
> or anonymity. qBittorrent stays disabled until setup and VPN protection checks
> pass, but physical Raspberry Pi leak testing is still required.

Original qbtOS software is licensed under the GNU General Public License
version 3 or later. Distribution components retain their own licenses; consult
their copyright files and the generated Buildroot legal information.

qBittorrent is a file-sharing program. Active torrents may upload data to other
peers. Users are responsible for the content they download, possess, and share.
