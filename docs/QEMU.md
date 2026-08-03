# Running qbtOS in QEMU

qbtOS supports amd64 and arm64 QEMU guests. These development images use the
same immutable SquashFS system and persistent configuration model as the
Raspberry Pi image. QEMU boots an architecture-specific kernel beside the QCOW2
disk; keep the files from one output directory together.

## Build

On an x86-64 host, the architecture defaults to `amd64`; on an arm64 host it
defaults to `arm64`:

```bash
./build-scripts/build.sh --format qcow
```

Select an architecture explicitly and set the sparse data disk's virtual size
in GiB when needed:

```bash
./build-scripts/build.sh --format qcow --arch arm64 --size 32
```

The default data capacity is 16 GiB. `--size` accepts positive integers only
and affects `QBTOS_DATA`, not the system/configuration disk. Equivalent Make
usage is:

```bash
make configure FORMAT=qcow ARCH=amd64 SIZE=32
make build FORMAT=qcow ARCH=amd64 SIZE=32
```

Artifacts are written below `output/qemu-ARCH/images/`:

- `qbtos-ARCH.qcow2`: SquashFS system and writable `QBTOS_CONFIG` partition
- `qbtos-data-ARCH.qcow2`: writable `QBTOS_DATA` filesystem
- `bzImage` on amd64 or `Image` on arm64: direct-boot kernel

## Run

Start the matching guest:

```bash
./build-scripts/run-qemu.sh --arch amd64
```

The launcher uses the QEMU executable built by Buildroot, creates independent
persistent copies under `runtime/qemu/ARCH/`, and uses KVM automatically when
available for a same-architecture guest. Cross-architecture emulation uses TCG
and is substantially slower. Direct boot selects the system partition by
PARTUUID; persistent filesystems are discovered by their `QBTOS_CONFIG` and
`QBTOS_DATA` labels rather than architecture-dependent virtio device names.

Open `https://127.0.0.1:8080`. The self-signed certificate warning is expected.
The qBittorrent Web UI is forwarded to host port 8081, but qBittorrent remains
disabled until setup and VPN protection checks succeed.

Override conflicting host ports without changing guest firewall rules:

```bash
./build-scripts/run-qemu.sh --arch amd64 \
  --https-port 8443 --qbittorrent-port 8082
```

For an explicitly authorized integration VM, bind the forwards to a host bridge
address, for example `--bind-address 192.168.122.1`. This exposes both ports to
that network; the default remains loopback-only.

## Cloud-init controller test

The repository includes a non-secret Debian controller fixture for the sibling
`~/git/cloud-init-automation` harness. That harness builds its NoCloud ISO from
a real directory (not a symlink), so copy the two fixture files and boot a
disposable VM:

```bash
install -d "$HOME/git/cloud-init-automation/qbtos-controller"
cp tests/cloud-init/qbtos-controller/{meta-data,user-data} \
  "$HOME/git/cloud-init-automation/qbtos-controller/"
"$HOME/git/cloud-init-automation/bring-up.sh" --no-console qbtos-controller
sudo virsh domifaddr qbtos-controller
```

Run qbtOS with `--bind-address 192.168.122.1`, resolve the controller address
with `virsh` (do not scan), and use the documented `cgpt` SSH key. From the
controller, `curl -k https://192.168.122.1:8080/api/health` verifies that the
HTTPS manager is reachable across a separate VM boundary. The WireGuard profile
and torrent fixture must remain on the host and must never be placed in the
NoCloud ISO or console logs.

The serial console is attached to the terminal. Use `Ctrl-a x` to stop QEMU.
Subsequent launches reuse runtime configuration and torrent data. To start a
fresh instance, stop QEMU and remove only the matching ignored directory, for
example `runtime/qemu/amd64/`; the built templates remain unchanged.

The default network is unprivileged QEMU user-mode NAT and binds forwarded
ports to host loopback only. Bridged/TAP networking is intentionally not
configured by the launcher.
