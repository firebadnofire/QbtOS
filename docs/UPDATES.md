# Signed A/B Updates

## Trust and partition layout

Raspberry Pi releases use an MBR image with a 64 MiB `QBTOS_BOOT` FAT
partition, 96 MiB read-only SquashFS slots A and B, and an extended partition
containing the 512 MiB writable `QBTOS_STATE` ext4 logical partition. The
interactive imager may append `QBTOS_DATA` as a second logical partition;
otherwise torrent payloads remain on a separate user-selected filesystem. The
fixed image disk signature gives the system slots stable PARTUUIDs ending in
`-02` and `-03`; RAUC never targets the active slot.

The state partition is 512 MiB; its ext4 filesystem occupies the first 511 MiB.
U-Boot stores two redundant, CRC-protected 16 KiB environment records in the
reserved tail at partition-relative offsets `0x1ff00000` and `0x1ff04000`.
Linux reaches the same records through state PARTUUID `5142544f-05`, while
U-Boot uses the corresponding fixed whole-disk offsets. This avoids U-Boot's
non-redundant ext4 environment backend and keeps the records outside filesystem
allocation. `BOOT_ORDER`, `BOOT_A_LEFT`, and `BOOT_B_LEFT` implement
three-attempt boot selection. A successful local health check runs
`rauc status mark-good`. Failed pending boots consume their attempts and fall
back to the previous slot. Boot success depends only on local init,
writable/valid state, the manager, firewall, and qBittorrent being protected or
stopped; Internet and VPN-provider availability are deliberately excluded.

The FAT kernel and bootloader are shared and are not changed by the initial
rootfs-only RAUC bundle. Kernel/bootloader transactional updates remain a later
milestone.

## Versions and release builds

Create and push exact annotated or lightweight tags named `revision-N`, where
`N` is a positive integer without leading zeroes. The numerically greatest tag
reachable from `HEAD` supplies the revision; the New York build date supplies
the date:

```sh
git tag revision-2
git push origin revision-2
eval "$(./build-scripts/release-version.sh)"
```

Malformed or misspelled reachable revision tags make the release fail. Every
`revision-N` push starts `.forgejo/workflows/release.yml`; the job independently
validates the exact tag before building.

RAUC uses CMS/X.509 signatures. The public hierarchy in `ca/` is built into the
image: `root-ca.pem` is the immutable RAUC trust anchor,
`intermediate-ca.pem` is included with signed bundles, and `release.crt`
identifies the permitted pre-production signer. `RAUC_CERT_FILE` must contain
that release certificate and `RAUC_KEY_FILE` its matching private signing key.
The additional OpenPGP layer uses a public keyring supplied as
`QBTOS_GPG_KEYRING_FILE`; CI
derives it from `CI_KEY`, clear-signs the required `.sha256` artifact using
`CI_KEY_PASSPHRASE`, and verifies the signature and hashes before upload.
Neither private key enters the image. This dedicated CA is not installed in
the system TLS store; normal HTTPS continues to use only Buildroot's Mozilla
CA bundle. RAUC verifies the leaf with `check-purpose=codesign`.

```sh
eval "$(./build-scripts/release-version.sh)"
make release VERSION="$VERSION" BUILD_DATE="$BUILD_DATE" \
  REVISION="$REVISION" SOURCE_TAG="$SOURCE_TAG" COMMIT="$COMMIT" \
  RAUC_CERT_FILE=/secure/release.crt RAUC_KEY_FILE=/secure/release.key \
  QBTOS_GPG_KEYRING_FILE=/secure/release-public.gpg
```

The command creates exactly `dist/$VERSION.img.zst`, `.raucb`,
`.manifest.json`, and `.sha256`. A direct local build leaves `.sha256` as plain
text; Forgejo replaces it with an ASCII clear-signed document while retaining
the required filename.

For development only, create an isolated, short-lived code-signing certificate
and use `make development-release`:

```sh
openssl req -x509 -newkey rsa:3072 -nodes -days 30 \
  -subj /CN=qbtOS-development \
  -addext 'basicConstraints=critical,CA:FALSE' \
  -addext 'keyUsage=critical,digitalSignature' \
  -addext 'extendedKeyUsage=critical,codeSigning' \
  -keyout dev-rauc.key -out dev-rauc.crt
gpg --batch --export YOUR_DEVELOPMENT_KEY > dev-release-public.gpg
eval "$(./build-scripts/release-version.sh)"
make development-release VERSION="$VERSION" BUILD_DATE="$BUILD_DATE" \
  REVISION="$REVISION" SOURCE_TAG="$SOURCE_TAG" COMMIT="$COMMIT" \
  RAUC_CERT_FILE=dev-rauc.crt RAUC_KEY_FILE=dev-rauc.key \
  QBTOS_GPG_KEYRING_FILE=dev-release-public.gpg
```

The resulting development image trusts only that development certificate. The
current pre-production image trusts only the checked-in pre-production root; a
future production image must use a separate production root and signer. Never
reuse a development key for pre-production or production, and never put any
private signing key in this repository or an image.

## Feed, installation, and recovery

The configured HTTPS URL points to moving `latest.json`. Schema 1 contains the
release manifest fields plus `bundle_url`, `image_url`, `checksum_url`, and the
three exact filenames. The manager validates board, channel, version/revision,
sizes, HTTPS URLs, and downgrade policy. It then verifies the OpenPGP-signed
checksum set, resumes the bounded bundle download in persistent state, checks
SHA-256, and invokes RAUC with an argument vector. Installation and reboot are
separate explicit actions.
The feed and release attachments must be anonymously readable; qbtOS rejects
URLs containing embedded credentials and does not store a Forgejo API token.

For a locally transferred bundle, inspect and install it with:

```sh
rauc info --keyring=/etc/rauc/keyring.pem /config/qbtos/updates/VERSION.raucb
rauc status
rauc install /config/qbtos/updates/VERSION.raucb
reboot
```

U-Boot prints slot selection on the always-enabled 115200-baud GPIO UART. At its
three-second prompt, inspect `printenv BOOT_ORDER BOOT_A_LEFT BOOT_B_LEFT`; use
`setenv BOOT_ORDER 'A B'; setenv BOOT_A_LEFT 3; saveenv; reset` to prefer A, or
the corresponding B values. Do not write a rootfs partition manually.

State migrations copy the active generation, migrate and validate the copy,
then atomically switch a symlink. A pre-update generation remains until the new
slot is confirmed. Rollback restores a schema the previous slot understands;
torrent payload data is never migrated.

## CI secrets and key rotation

Forgejo requires `RAUC_CERT_PEM`, `RAUC_KEY_PEM`, `CI_KEY`, and
`CI_KEY_PASSPHRASE`. The workflow's short-lived automatic `FORGEJO_TOKEN`
publishes exactly four release attachments and updates the `update-feed` branch.
`CI_KEY` may contain an ASCII-armored OpenPGP private key, but the shared
Forgejo account secret normally contains its base64 encoding; the workflow
decodes that form before importing it. `CI_TRUSTED_PUBLIC_KEYS` remains raw,
importable public OpenPGP data.
The stable feed URL is
`https://FORGEJO/OWNER/REPOSITORY/raw/branch/update-feed/latest.json`.
`CI_TRUSTED_PUBLIC_KEYS` is an optional public-key bundle used during OpenPGP
rotation. Rotate either trust system with an overlap release: first ship both
old and new public trust roots, then change the signer, and remove the old root
only after supported installations have crossed the overlap release. Test
rollback across both steps.

Hardware acceptance still requires booting A on a Pi 4, installing a signed
bundle to B, observing three failed B boots return to A, confirming healthy B,
and checking state across update and rollback. These results must not be
inferred from host or QEMU tests.
