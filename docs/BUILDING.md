# Building qbtOS

## Supported host

Use a current 64-bit Linux system with a case-sensitive filesystem, working
network access, and enough free memory and storage for a full C++ cross-build.
Plan for roughly 20-30 GiB of free disk space for one output tree plus downloads;
actual use varies with Buildroot and package revisions.

Buildroot requires standard GNU build tools: Bash, GNU Make 4.x, GCC/G++,
binutils, patch, tar, gzip, bzip2, cpio, unzip, rsync, file, `bc`, Perl, Python 3,
Git, and a download client. ncurses development headers support configuration
tools. `python-magic`, Flake8, and ShellCheck are needed by `make check` and
Buildroot's `check-package` utility.

Package names vary by distribution and release. Typical starting points are:

```bash
# Debian/Ubuntu
sudo apt install build-essential git rsync cpio unzip bc file wget patch perl \
  python3 python3-magic flake8 shellcheck libncurses-dev

# Fedora
sudo dnf install gcc gcc-c++ make binutils git rsync cpio unzip bc file wget \
  patch perl python3 python3-magic python3-flake8 ShellCheck ncurses-devel

# Gentoo
sudo emerge --ask sys-devel/gcc sys-devel/make dev-vcs/git net-misc/rsync \
  app-arch/cpio app-arch/unzip sys-devel/bc sys-apps/file net-misc/wget \
  dev-lang/python dev-python/python-magic dev-python/flake8 dev-util/shellcheck \
  sys-libs/ncurses
```

Consult the Buildroot manual's authoritative host requirements if a host check
reports another missing tool.

## Normal build

Buildroot is pinned as a Git submodule at release `2026.05.1`.

```bash
git submodule update --init --recursive
make configure
make build
```

`make configure` loads `br2-external/configs/qbtos_rpi4_defconfig`; routine
builds do not use `menuconfig`. `make build` downloads source archives, builds
the cross-toolchain dependencies and image, then prints the image path:

```text
output/images/sdcard.img
```

Capture a searchable build log with:

```bash
make build 2>&1 | tee qbtos-build.log
```

Use `make rebuild` to clean target build products and rebuild. Use
`make distclean && make configure && make build` for a completely new output
tree. Downloads are cached under the ignored `buildroot/dl/` directory by
Buildroot; neither downloads nor output belong in Git.

Run `make legal-info` after a successful build to collect the corresponding
source archives, license texts, and manifest under `output/legal-info/` for
distribution review.

## Updating configuration

For an intentional configuration change only:

```bash
make configure
make menuconfig
make savedefconfig
git diff -- br2-external/configs/qbtos_rpi4_defconfig
```

Review the reduced defconfig; it is the source of truth. Kernel changes belong
in `br2-external/board/qbtos/rpi4/kernel.fragment`.

## Common failures

- Missing `buildroot/Makefile`: initialize the submodule.
- Hash/download error: do not bypass hash checking; confirm network/proxy state
  and the pinned source before changing a hash.
- Host prerequisite failure: install the named tool or development headers.
- Interrupted or inconsistent output: run `make rebuild`; use `make distclean`
  when changing toolchains or Buildroot releases.
- Out of space: remove only generated `output/` after preserving useful logs.
