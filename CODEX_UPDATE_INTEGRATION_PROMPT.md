# Codex prompt: integrate signed A/B updates into qbtOS

You are working in the qbtOS repository. Read `README.md`, `VISION.md`, `AGENTS.md`, the existing Buildroot external tree, board configuration, image-generation files, manager service, tests, and build scripts before changing anything.

qbtOS is a Buildroot-based Raspberry Pi 4 appliance. Keep upstream Buildroot changes inside the `buildroot/` submodule to an absolute minimum. Put qbtOS-specific work in `br2-external/`, `build-scripts/`, `docs/`, and the existing top-level Makefile.

Implement a production-oriented, signed, image-based update system using RAUC with A/B system slots and U-Boot boot selection. Do not invent a custom updater that writes active partitions directly. Do not mutate the read-only SquashFS root package by package.

## Required version scheme

The release version is derived from two independent values:

- Build date: current date in `America/New_York`, formatted `YYYY-MM-DD`.
- Revision: the highest positive integer from a reachable Git tag named exactly `revision-N`.

The final version is:

```text
YYYY-MM-DD-revN
```

Examples:

```text
revision-1  + 2026-08-02 -> 2026-08-02-rev1
revision-1  + 2026-08-09 -> 2026-08-09-rev1
revision-2  + 2026-08-09 -> 2026-08-09-rev2
```

The date changes whenever a build occurs on a different local calendar date. The revision must not change merely because commits were added or a scheduled build ran. It changes only after I create and push a new `revision-N` tag.

Reject missing tags, malformed tags, `revision-0`, leading-zero revisions such as `revision-01`, and the misspelling `revsion-N`. Select the numerically highest valid `revision-N` tag reachable from `HEAD`, not the most recently created tag by timestamp.

All distributable files must use the exact basename `YYYY-MM-DD-revN`:

```text
YYYY-MM-DD-revN.img.zst
YYYY-MM-DD-revN.raucb
YYYY-MM-DD-revN.manifest.json
YYYY-MM-DD-revN.sha256
```

Do not add architecture, board, channel, commit, or project text to those filenames. Put that information inside the manifest.

## Architecture

Implement this persistent storage model:

1. FAT boot partition.
2. Read-only SquashFS system slot A.
3. Read-only SquashFS system slot B.
4. Writable ext4 state partition.
5. Torrent data remains on user-selected external storage and must never be included in an update artifact.

Use labels and PARTUUIDs rather than unstable `/dev/mmcblk*` names.

Integrate U-Boot as the slot-selection layer and RAUC as the userspace update engine. The bootloader environment must be redundant or otherwise power-loss tolerant. An update must always be written to the inactive slot. The active slot must never be overwritten.

The boot flow must provide:

- active and inactive slot discovery;
- a pending slot with a limited boot-attempt count;
- automatic fallback after failed boot attempts;
- userspace confirmation after health checks pass;
- preservation of the previous known-good slot;
- a documented manual recovery path.

Do not treat Internet access, VPN-provider availability, or an established VPN tunnel as an operating-system boot-success requirement. A provider outage must not cause slot rollback. qBittorrent must remain disabled or fail-closed when VPN protection is unavailable.

## RAUC signing

Use RAUC bundle signing and verification. Production images contain only the trusted public certificate or certificate chain. Build-time signing material is supplied through paths in these environment variables:

```text
RAUC_CERT_FILE
RAUC_KEY_FILE
```

Never commit private keys, generated signing keys, VPN secrets, credentials, or CI secret material. Fail the release build when either signing variable is absent or unreadable.

Add documented development-key generation, but make it impossible to accidentally ship an image that trusts a development certificate when a production build is requested.

## Build metadata

Generate `/etc/qbtos-release` in the target image with at least:

```text
QBTOS_VERSION=YYYY-MM-DD-revN
QBTOS_BUILD_DATE=YYYY-MM-DD
QBTOS_REVISION=N
QBTOS_SOURCE_TAG=revision-N
QBTOS_COMMIT=<full commit SHA>
QBTOS_COMPATIBLE=qbtos-rpi4
QBTOS_CHANNEL=stable
```

Expose the same data through the qbtOS manager status API and web interface.

## Required build scripts and Make targets

Add a POSIX shell script:

```text
build-scripts/release-version.sh
```

It must print shell-safe assignments for:

```text
BUILD_DATE
REVISION
VERSION
SOURCE_TAG
COMMIT
```

Add or update Make targets so CI can run:

```sh
make check
make release \
  VERSION="$VERSION" \
  BUILD_DATE="$BUILD_DATE" \
  REVISION="$REVISION" \
  SOURCE_TAG="$SOURCE_TAG" \
  COMMIT="$COMMIT" \
  RAUC_CERT_FILE="$RAUC_CERT_FILE" \
  RAUC_KEY_FILE="$RAUC_KEY_FILE"
```

`make release` must perform a clean, reproducible Buildroot image build, create the full compressed SD-card image and signed RAUC update bundle, and write only these public artifacts to `dist/`:

```text
$VERSION.img.zst
$VERSION.raucb
$VERSION.manifest.json
$VERSION.sha256
```

The checksum file must cover the `.img.zst`, `.raucb`, and `.manifest.json` files using SHA-256 and stable relative filenames. Validate the bundle with RAUC after creating it. Validate the compressed image with `zstd -t`.

The JSON manifest must be deterministic and contain at least:

```json
{
  "schema": 1,
  "version": "YYYY-MM-DD-revN",
  "build_date": "YYYY-MM-DD",
  "revision": 1,
  "source_tag": "revision-1",
  "commit": "full SHA",
  "compatible": "qbtos-rpi4",
  "channel": "stable",
  "bundle_filename": "YYYY-MM-DD-rev1.raucb",
  "image_filename": "YYYY-MM-DD-rev1.img.zst",
  "bundle_sha256": "...",
  "image_sha256": "...",
  "bundle_size": 123,
  "image_size": 456
}
```

Do not put secret material, local filesystem paths, runner names, or credentials in the manifest.

## Update feed and manager integration

Add a configurable update-feed URL, with a documented default placeholder rather than a fake production domain. The feed is a `latest.json` document published by CI. Its schema matches the versioned manifest and adds fully qualified download URLs.

The manager must:

- check the feed over HTTPS;
- validate schema, compatibility, filenames, revision, and version format;
- refuse a lower revision by default;
- download to persistent state with a temporary filename;
- enforce reasonable size limits;
- verify the expected SHA-256 before invoking RAUC;
- invoke RAUC without shell-string interpolation;
- stream useful progress to the UI;
- preserve logs without exposing secrets;
- offer an explicit install and reboot flow;
- report active slot, inactive slot, current version, available version, and rollback state;
- recover safely from an interrupted download;
- never start qBittorrent outside the VPN traffic lock during update handling.

RAUC signature verification remains authoritative even after the transport checksum passes. Do not claim that a SHA-256 file alone authenticates an update.

## Persistent-state migration

Add an integer state-schema version. Migrations must operate on a temporary copy, validate it, and atomically replace the active configuration only after success. Preserve a pre-update configuration backup until the new slot is confirmed healthy. The immediately previous system version must remain able to read or restore the prior schema after rollback.

Do not modify torrent payload data during an OS update.

## Health confirmation

Create a boot-confirmation service that marks the pending slot good only after all of these pass:

- normal init reached;
- state partition mounted read/write;
- qbtOS configuration parsed;
- required migrations completed;
- qbtOS manager is responsive locally;
- firewall/traffic-lock rules loaded;
- qBittorrent is either safely VPN-protected or deliberately stopped.

Wait long enough to catch immediate service failures before marking the slot good. Do not require an external host, public DNS, VPN provider, or Internet connectivity.

## Tests

Add unit and integration-oriented tests for at least:

- version parsing with no tag;
- `revision-1` and `revision-10` numeric ordering;
- commits after a tag retaining the same revision;
- malformed and misspelled tags being ignored or rejected;
- manifest generation;
- incompatible bundle rejection;
- checksum mismatch rejection;
- attempted downgrade rejection;
- interrupted download cleanup/resume;
- state migration rollback;
- active slot never selected as the installation target;
- boot-success criteria independent of Internet/VPN-provider availability;
- failure to mark good causing bootloader rollback.

Run existing manager tests and Buildroot package checks. Keep shell code POSIX-compatible unless an existing script explicitly uses Bash. Run `check-package` on supported external-tree files.

## Documentation

Update `README.md`, `VISION.md` only where implementation status genuinely changed, and add focused documentation covering:

- partition and slot layout;
- release-tag policy;
- local signed-bundle creation;
- CI secret requirements;
- update-feed format;
- manual update installation;
- rollback behavior;
- recovery procedure;
- signing-certificate rotation;
- security assumptions and limitations.

Do not claim the system is fully power-loss safe or privacy certified without corresponding hardware tests.

## Acceptance criteria

The work is complete only when all of the following are true:

1. A clean Raspberry Pi 4 image boots through U-Boot from slot A.
2. A signed bundle installs only to slot B while A is active.
3. The bootloader attempts B and automatically returns to A after repeated failed boots.
4. A healthy B boot is confirmed and remains selected on subsequent boots.
5. Persistent configuration and torrent state survive update and rollback.
6. `make check` succeeds.
7. `make release` produces exactly the four required `dist/` files with the exact version basename.
8. No private signing key or credential appears in Git history, build output intended for publication, logs, or generated images.
9. The implementation is split into focused commits with clear imperative messages.

When hardware-only validation cannot be performed in your environment, implement the code and automated checks, document the exact Raspberry Pi 4 validation procedure, and clearly list what remains unverified. Do not fake test results.
