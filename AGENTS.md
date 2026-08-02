# Repository Guidelines

## Project Structure & Module Organization

qbtOS is a Buildroot-based Raspberry Pi appliance. The upstream Buildroot source is the `buildroot/` Git submodule; avoid mixing qbtOS-specific changes into it unless an upstream patch is required. Product-specific configuration belongs in `br2-external/`: board files under `board/qbtos/`, Buildroot defconfigs under `configs/`, custom packages under `package/`, and target filesystem additions under the board's `rootfs-overlay/`. `output/` is the generated Buildroot working tree and image destination; rebuild generated files rather than editing them by hand. Product intent and security guarantees are documented in `VISION.md`.

## Build, Test, and Development Commands

- `git submodule update --init --recursive` fetches the pinned Buildroot source.
- `make configure` loads the checked-in Raspberry Pi 4 defconfig.
- `make build` builds the system; the raw image appears at `output/images/sdcard.img`.
- `make rebuild` cleans target products and rebuilds them; `make distclean` removes the entire output tree.
- `make check` runs Buildroot package checks and the manager unit tests.
- `make legal-info` creates the Buildroot license manifest and source bundle.

Builds download toolchains and sources, so expect the first run to take time and require network access.

## Coding Style & Naming Conventions

Follow Buildroot conventions: tabs in Make recipes, uppercase `QBTOS_*` variables in package makefiles, lowercase package directories, and `Config.in` entries prefixed with `BR2_PACKAGE_`. Name board configurations descriptively, for example `qbtos_rpi4_defconfig`. Keep shell scripts POSIX-compatible unless their shebang explicitly selects another shell. Run `check-package` on every changed external-tree file it supports.

## Testing Guidelines

Manager tests use Python's `unittest` framework under `br2-external/package/qbtos-manager/tests/`; name test methods `test_<behavior>`. Run `make check`, complete a clean image build, and verify the artifacts in `output/images/`. For boot, VPN, firewall, or storage changes, test on Raspberry Pi 4 hardware and document the configuration and fail-closed behavior in the pull request.

## Commit & Pull Request Guidelines

Recent history uses short, imperative subjects such as `Initialize qbtOS repository`. Keep commits focused and separate generated output from source changes. Pull requests should explain the user-visible effect, list validation performed, link relevant issues, and call out changes to licensing or `VISION.md` guarantees. Include screenshots for web-interface changes and boot/service logs for system behavior changes, with credentials and VPN secrets removed.
