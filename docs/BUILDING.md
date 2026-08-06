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
`lsblk`, `sfdisk`, `mkfs.ext4`, `dd`, and `sha256sum`. These are commonly
provided by packages named `whiptail` or `newt`, `util-linux`, `e2fsprogs`, and
`coreutils`, but names differ across distributions and releases.

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
