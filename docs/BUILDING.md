# Building qbtOS

## Supported host

Use a current 64-bit Linux system with a case-sensitive filesystem, working
network access, and enough free memory and storage for a full C++ cross-build.
Plan for roughly 20-30 GiB of free disk space for one output tree plus downloads;
actual use varies with Buildroot and package revisions.

Buildroot requires standard GNU build tools: Bash, GNU Make 4.x, GCC/G++,
binutils, patch, tar, gzip, bzip2, cpio, unzip, rsync, file, `bc`, Perl, Python 3,
Git, OpenSSL, GnuPG, Zstandard, `jq`, and a download client. ncurses development
headers support configuration tools. `python-magic`, Flake8, and ShellCheck are
needed by `make check` and Buildroot's `check-package` utility.

Package names vary by distribution and release. Typical starting points are:

```bash
# Debian/Ubuntu
sudo apt install build-essential git rsync cpio unzip bc file wget patch perl \
  python3 python3-magic flake8 shellcheck libncurses-dev openssl gnupg zstd jq

# Fedora
sudo dnf install gcc gcc-c++ make binutils git rsync cpio unzip bc file wget \
  patch perl python3 python3-magic python3-flake8 ShellCheck ncurses-devel \
  openssl gnupg2 zstd jq

# Gentoo
sudo emerge --ask sys-devel/gcc sys-devel/make dev-vcs/git net-misc/rsync \
  app-arch/cpio app-arch/unzip sys-devel/bc sys-apps/file net-misc/wget \
  dev-lang/python dev-python/python-magic dev-python/flake8 dev-util/shellcheck \
  sys-libs/ncurses dev-libs/openssl app-crypt/gnupg app-arch/zstd app-misc/jq
```

Consult the Buildroot manual's authoritative host requirements if a host check
reports another missing tool.

The optional interactive SD-card writer additionally needs `whiptail`,
`lsblk`, `sfdisk`, `mkfs.ext4`, `dd`, and `sha256sum`. Selecting NTFS also
requires `mkfs.ntfs`. These are commonly provided by packages named `whiptail`
or `newt`, `util-linux`, `e2fsprogs`, `coreutils`, and `ntfs-3g`, but names
differ across distributions and releases. Debian/Ubuntu and Fedora commonly
call the NTFS package `ntfs-3g`; Gentoo commonly provides it as
`sys-fs/ntfs3g`.

## Normal build

Buildroot is pinned as a Git submodule at release `2026.05.1`.

```bash
git submodule update --init --recursive
make configure
make build
```

The default `flat` format loads `br2-external/configs/qbtos_rpi4_defconfig`;
routine builds do not use `menuconfig`. It downloads source archives, builds
the cross-toolchain dependencies and image, checks the expected image
components, then prints the image path and SHA-256 digest:

```text
output/images/sdcard.img
output/images/sdcard.img.sha256
```

The checksum sidecar is refreshed after every successful flat-image build. The
interactive imager uses it to verify the written image without reading the
large source image a second time; stale or malformed sidecars are ignored in
favor of a byte comparison.

The one-command equivalent is `./build-scripts/build.sh`. Capture a searchable
build log with:

```bash
./build-scripts/build.sh 2>&1 | tee .build-log-qbtos
```

Set `JOBS` to limit parallelism, for example
`JOBS=4 ./build-scripts/build.sh`. The equivalent two-step interface is
`make configure && make build`. Use `make rebuild` to clean target build
products and rebuild. Use `make distclean && ./build-scripts/build.sh` for a
completely new output tree. Downloads are cached under the ignored
`buildroot/dl/` directory by Buildroot; neither downloads nor output belong in
Git.

## QEMU builds

QEMU targets use separate output trees so they cannot contaminate the Raspberry
Pi configuration:

```bash
./build-scripts/build.sh --format qcow --arch amd64
./build-scripts/build.sh --format qcow --arch arm64 --size 32
```

If `--arch` is omitted, x86-64 hosts select `amd64` and arm64 hosts select
`arm64`. The positive integer `--size` value is the virtual GiB capacity of the
separate sparse `QBTOS_DATA` QCOW2 image and defaults to 16. Outputs appear
under `output/qemu-ARCH/images/`. See [QEMU.md](QEMU.md) for launching and port
forwarding.

Run `make legal-info` after a successful build to collect the corresponding
source archives, license texts, and manifest under `output/legal-info/` for
distribution review.

## Signed releases

Releases require a reachable exact `revision-N` Git tag plus separate RAUC
X.509 signing material and an OpenPGP public verification keyring. Derive the
metadata instead of typing it:

```bash
eval "$(./build-scripts/release-version.sh)"
make check
make release VERSION="$VERSION" BUILD_DATE="$BUILD_DATE" \
  REVISION="$REVISION" SOURCE_TAG="$SOURCE_TAG" COMMIT="$COMMIT" \
  RAUC_CERT_FILE=/secure/release.crt RAUC_KEY_FILE=/secure/release.key \
  QBTOS_GPG_KEYRING_FILE=/secure/release-public.gpg
```

The release uses a fresh `output/release/` tree and writes exactly four public
files under `dist/`. The normal Forgejo path additionally clear-signs and
verifies `.sha256` with `CI_KEY`. See [UPDATES.md](UPDATES.md) for key handling,
feed publication, and recovery.

## Updating configuration

For an intentional configuration change only:

```bash
make configure
make menuconfig
make savedefconfig
git diff -- br2-external/configs/qbtos_rpi4_defconfig
```

Review the reduced defconfig; it is the source of truth. Shared kernel changes
belong in `br2-external/board/qbtos/common/kernel.fragment`.

## Common failures

- Missing `buildroot/Makefile`: initialize the submodule.
- Hash/download error: do not bypass hash checking; confirm network/proxy state
  and the pinned source before changing a hash.
- Host prerequisite failure: install the named tool or development headers.
- Interrupted or inconsistent output: run `make rebuild`; use `make distclean`
  when changing toolchains or Buildroot releases.
- Out of space: remove only generated `output/` after preserving useful logs.

## Forgejo release runner troubleshooting

The Forgejo release is a Raspberry Pi 4 `arm64` cross-build. The captured
`revision-12` job nevertheless ran its Debian build container as
`linux/amd64`, installed amd64 host packages, and then cross-compiled the
`qbtos_rpi4_defconfig` target for ARM64. Container architecture is selected by
the Forgejo Runner label mapping, not by this workflow. No runner, Colima, or
LaunchDaemon configuration is stored in this repository, so the repository
does not prove whether the Mac mini is Apple Silicon. On an Apple Silicon host,
that mapping makes all Buildroot host tools run through the amd64 translation
path even though the final appliance target remains ARM64. Separate development
QEMU configurations support both amd64 and ARM64 guests, but the tagged release
workflow builds only the Raspberry Pi 4 ARM64 image.

CI defaults to four Buildroot jobs through `QBTOS_BUILD_JOBS`. Treat 8 GiB of
Colima memory with two jobs as a practical minimum; prefer 12 GiB of memory,
4 GiB of swap, at least 6 virtual CPUs, four build jobs, and a 60 GiB VM disk
with at least 35 GiB free before a clean release. Leave enough physical memory
for macOS. Change `QBTOS_BUILD_JOBS` only after checking peak memory pressure;
raising the VM CPU count does not make a higher build job count safe by itself.

The build wrapper records start/end times, host and container architecture,
available CPUs, selected `/proc/meminfo` values, cgroup memory/CPU/PID limits
and events, filesystem usage, periodic five-minute heartbeats, and the real
command exit status. It does not dump the environment, process command lines,
or signing material. An ordinary build failure should therefore show a shell
or `make` error, a final `failure` snapshot, a numeric command status, the
post-failure artifact upload, and the signing cleanup step. If output stops in
the middle of a line and none of those run, the container execution channel or
runner disappeared; repository code cannot run cleanup or upload evidence
after that point. Signing files remain in per-job runner temporary storage and
the short-lived job container, with mode `0600`; the runner host must also
delete abandoned job workspaces and containers after a crash.

For the `revision-12` incident, the last recorded line was `GCC extensions:`
while configuring `host-xz` at approximately `2026-08-12 19:22 EDT`. The log
contains no Buildroot, compiler, shell, timeout, or killed-process error. It
shows 16 parallel jobs in `linux/amd64`, then no output for roughly 12 minutes
before Forgejo closed the 19m30s step, and the `if: always()` cleanup did not
run. That evidence makes runner, Colima/Docker, resource exhaustion, or
runner-to-Forgejo communication loss more likely than an xz source failure,
but it does not identify which infrastructure category occurred.

Run these checks on the Mac mini before retrying. `launchctl print` and the
plist reveal the runner executable plus its configured `stdout path` and
`stderr path`. If `StandardOutPath` or `StandardErrorPath` is absent, use the
macOS unified log. Preserve the output before pruning Docker state.

```sh
sudo launchctl print system/org.forgejo.runner
sudo plutil -p /Library/LaunchDaemons/org.forgejo.runner.plist

colima status
colima list
colima ssh -- uname -a
colima ssh -- free -h
colima ssh -- df -h
colima ssh -- sudo dmesg -T | \
  grep -Ei 'out of memory|oom|killed process|qemu|rosetta|binfmt|I/O error'

docker info
docker ps -a --no-trunc
docker system df -v
docker events --since '2026-08-12T19:10:00-04:00' \
  --until '2026-08-12T19:40:00-04:00'

sudo log show --style compact \
  --start '2026-08-12 19:10:00' --end '2026-08-12 19:40:00' \
  --predicate 'process == "forgejo-runner" OR process == "colima" OR process == "Docker" OR eventMessage CONTAINS[c] "org.forgejo.runner" OR eventMessage CONTAINS[c] "memory pressure"'
vm_stat
memory_pressure
```

Inspect the LaunchDaemon's actual stdout/stderr files over the same interval.
Also inspect Forgejo server logs for task 1293 and runner ID
`c3d6a19b-ccd0-43ce-94c4-98086e60a879`, looking for a runner restart/crash,
Docker `exec` EOF or daemon disconnect, Colima restart, container exit/OOM,
guest or host memory pressure, VM disk exhaustion, emulation failure, lost
websocket/API connectivity, or zombie-task expiration. Do not increase the
zombie-task timeout unless those logs show the runner and build remained alive
and heartbeats were lost or misclassified.

Confirm the architecture path explicitly:

```sh
uname -m
colima ssh -- uname -m
docker info --format '{{.Architecture}}'
docker run --rm --platform linux/amd64 node:22-bookworm uname -m
docker run --rm --platform linux/arm64 node:22-bookworm uname -m
```

A native ARM64 Debian container can in principle build native ARM64 Buildroot
host utilities and cross-build the same Raspberry Pi ARM64 target. It may avoid
whole-container amd64 translation on Apple Silicon, but it changes the host
tool execution architecture and must complete a clean signed release and
artifact validation before the runner label is changed. Keep amd64 if the
runner or any required host tool fails that test; in that case retain the
four-job limit and budget for emulation overhead.

To reproduce the repository-controlled portion manually on a current Linux
checkout, use protected files outside the repository and do not enable shell
tracing:

```sh
git submodule update --init --recursive
eval "$(./build-scripts/release-version.sh)"
QBTOS_BUILD_QUIET=0 JOBS=4 make check
QBTOS_BUILD_QUIET=0 JOBS=4 make release \
  VERSION="$VERSION" BUILD_DATE="$BUILD_DATE" REVISION="$REVISION" \
  SOURCE_TAG="$SOURCE_TAG" COMMIT="$COMMIT" \
  RAUC_CERT_FILE=/secure/release.crt \
  RAUC_KEY_FILE=/secure/release.key \
  QBTOS_GPG_KEYRING_FILE=/secure/release-public.gpg \
  2>&1 | tee qbtos-release-build.log
```
