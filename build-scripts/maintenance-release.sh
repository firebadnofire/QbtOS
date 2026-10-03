#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH='' cd -- "$script_dir/.." && pwd)
cd "$repo"

publish=0
case "${1:-}" in
    '') ;;
    --publish) publish=1 ;;
    *) printf 'Usage: %s [--publish]\n' "$0" >&2; exit 2 ;;
esac
test "$#" -le 1 || { echo 'Unexpected maintenance arguments' >&2; exit 2; }

stage=preflight
changed=0
committed=0
tagged=0
published=0
patch_removed=0
tag=
start=
buildroot_report=current
qb_report=current
unreleased=no
validation='not required'
publication='not attempted'
maintenance_commit=none
archive=

summary() {
    printf '\nqbtOS maintenance summary\n'
    printf 'Buildroot: %s\nqBittorrent: %s\n' "$buildroot_report" "$qb_report"
    printf 'Existing unreleased qbtOS commits: %s\n' "$unreleased"
    printf 'Validation: %s\nMaintenance commit: %s\n' "$validation" "$maintenance_commit"
    test -z "$tag" || printf 'Revision: %s\n' "$tag"
    printf 'Publication: %s\n' "$publication"
}
fail_exit() {
    status=$?
    if test -n "$archive" && test -e "$archive"; then
        rm -f -- "$archive" || printf 'maintenance: could not remove temporary archive %s\n' "$archive" >&2
    fi
    if test "$status" -ne 0; then
        printf 'maintenance: failed at %s (exit %s)\n' "$stage" "$status" >&2
        validation="failed at $stage"
        publication=none
        if test "$published" -eq 0 && test -n "$start"; then
            if test "$tagged" -eq 1; then
                git tag -d "$tag" >/dev/null || printf 'maintenance: could not delete local tag %s\n' "$tag" >&2
            fi
            if test "$committed" -eq 1; then
                git reset --soft "$start" >/dev/null || \
                    printf 'maintenance: local commit needs manual cleanup\n' >&2
            fi
            if test "$changed" -eq 1; then
                git restore --staged -- buildroot \
                    br2-external/package/qbittorrent/qbittorrent.mk \
                    br2-external/package/qbittorrent/qbittorrent.hash \
                    br2-external/configs/qbtos_rpi4_defconfig \
                    br2-external/configs/qbtos_qemu_amd64_defconfig \
                    br2-external/configs/qbtos_qemu_arm64_defconfig || \
                    printf 'maintenance: candidate index needs manual cleanup\n' >&2
                git restore -- buildroot br2-external/package/qbittorrent/qbittorrent.mk \
                    br2-external/package/qbittorrent/qbittorrent.hash \
                    br2-external/configs/qbtos_rpi4_defconfig \
                    br2-external/configs/qbtos_qemu_amd64_defconfig \
                    br2-external/configs/qbtos_qemu_arm64_defconfig || \
                    printf 'maintenance: candidate source needs manual cleanup\n' >&2
                if test "$patch_removed" -eq 1; then
                    git restore --staged -- "$qb_patch" || \
                        printf 'maintenance: qBittorrent patch index needs manual cleanup\n' >&2
                    git restore -- "$qb_patch" || \
                        printf 'maintenance: qBittorrent patch needs manual cleanup\n' >&2
                fi
                git submodule update --init buildroot || \
                    printf 'maintenance: Buildroot checkout needs manual cleanup\n' >&2
            fi
        fi
    fi
    summary
}
trap fail_exit EXIT

for tool in git python3 curl make sha256sum find grep sed mktemp sfdisk; do
    command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 1; }
done
test -z "$(git status --porcelain --untracked-files=all)" || {
    echo 'Working tree must be clean before maintenance' >&2; exit 1;
}
test "$(git symbolic-ref --short HEAD)" = main || {
    echo 'Maintenance requires a checked-out main branch' >&2; exit 1;
}
start=$(git rev-parse HEAD)
git fetch --no-recurse-submodules origin 'refs/heads/main:refs/remotes/origin/main' --tags
test "$start" = "$(git rev-parse refs/remotes/origin/main)" || {
    echo 'Local main differs from origin/main; update the checkout first' >&2; exit 1;
}
git submodule update --init --recursive
test -z "$(git status --porcelain --untracked-files=all)" || {
    echo 'Submodule initialization left a dirty checkout' >&2; exit 1;
}

# This checked-in file contains only two optional exact-version holds.
# shellcheck disable=SC1091 # Source path is resolved from the script directory.
. "$script_dir/maintenance.conf"
python3 - "${BUILDROOT_HOLD:-}" "${QBITTORRENT_HOLD:-}" <<'PY'
import re
import sys

for name, value, pattern in (
        ('BUILDROOT_HOLD', sys.argv[1], r'20[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?'),
        ('QBITTORRENT_HOLD', sys.argv[2], r'[1-9][0-9]*\.[0-9]+\.[0-9]+(?:\.[0-9]+)?')):
    if value and not re.fullmatch(pattern, value):
        raise SystemExit(f'Invalid {name}: expected a stable final release version')
PY

stage='discover Buildroot'
buildroot_url='https://gitlab.com/buildroot.org/buildroot.git'
test "$(git -C buildroot remote get-url origin)" = "$buildroot_url" || {
    echo 'Buildroot submodule origin is not the official repository' >&2; exit 1;
}
current_buildroot_tags=$(git -C buildroot tag --points-at HEAD)
current_buildroot=$(printf '%s\n' "$current_buildroot_tags" | \
    python3 "$script_dir/maintenance-select.py" buildroot 2>/dev/null) || {
    echo 'Pinned Buildroot commit has no stable final release tag' >&2; exit 1;
}
buildroot_tags=$(git ls-remote --tags --refs "$buildroot_url")
upstream_buildroot=$(printf '%s\n' "$buildroot_tags" | \
    python3 "$script_dir/maintenance-select.py" buildroot)
target_buildroot=${BUILDROOT_HOLD:-$upstream_buildroot}
if test -n "${BUILDROOT_HOLD:-}"; then buildroot_report="held at $target_buildroot"; fi

stage='discover qBittorrent'
qb_mk=br2-external/package/qbittorrent/qbittorrent.mk
qb_hash=br2-external/package/qbittorrent/qbittorrent.hash
qb_patch=br2-external/package/qbittorrent/0001-http-include-container-headers-for-Qt-6.8.patch
current_qb=$(sed -n 's/^QBITTORRENT_VERSION = //p' "$qb_mk")
test -n "$current_qb" || { echo 'qBittorrent version missing' >&2; exit 1; }
qb_url='https://github.com/qbittorrent/qBittorrent.git'
qb_tags=$(git ls-remote --tags --refs "$qb_url")
upstream_qb_tag=$(printf '%s\n' "$qb_tags" | \
    python3 "$script_dir/maintenance-select.py" qbittorrent)
target_qb=${QBITTORRENT_HOLD:-${upstream_qb_tag#release-}}
if test -n "${QBITTORRENT_HOLD:-}"; then qb_report="held at $target_qb"; fi

# Refuse downgrades even when a hold is supplied.
python3 - "$current_buildroot" "$target_buildroot" "$current_qb" "$target_qb" <<'PY'
import sys
for current, target in ((sys.argv[1], sys.argv[2]), (sys.argv[3], sys.argv[4])):
    def parts(version):
        return tuple(map(int, version.split('.')))
    if parts(target) < parts(current):
        raise SystemExit(f'maintenance: downgrade refused: {current} -> {target}')
PY

if test "$target_buildroot" != "$current_buildroot"; then
    stage="apply Buildroot $current_buildroot -> $target_buildroot"
    changed=1
    git -C buildroot fetch --no-tags origin "refs/tags/$target_buildroot:refs/tags/$target_buildroot"
    git -C buildroot checkout --detach "$target_buildroot"
    buildroot_report="$current_buildroot -> $target_buildroot"
fi

if test "$target_qb" != "$current_qb"; then
    stage="apply qBittorrent $current_qb -> $target_qb"
    changed=1
    archive=$(mktemp "${TMPDIR:-/tmp}/qbtos-qbittorrent.XXXXXX")
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
        --retry 2 --max-time 600 --output "$archive" \
        "https://codeload.github.com/qbittorrent/qBittorrent/tar.gz/refs/tags/release-$target_qb"
    if test -f "$qb_patch"; then patch_present=1; else patch_present=0; fi
    patch_removed=$(python3 - "$current_qb" "$target_qb" "$archive" "$qb_mk" "$qb_hash" "$qb_patch" "$patch_present" <<'PY'
import hashlib
import io
import pathlib
import re
import sys
import tarfile

old, new, archive, mk_file, hash_file, patch_file, patch_present = sys.argv[1:]
source = pathlib.Path(archive).read_bytes()
with tarfile.open(fileobj=io.BytesIO(source), mode='r:gz') as tar:
    copying = [m for m in tar.getmembers() if m.name.count('/') == 1 and m.name.endswith('/COPYING') and m.isfile()]
    if len(copying) != 1:
        raise SystemExit('Expected exactly one top-level COPYING file in qBittorrent archive')
    license_hash = hashlib.sha256(tar.extractfile(copying[0]).read()).hexdigest()
    headers = [m for m in tar.getmembers() if m.name.endswith('/src/base/http/types.h') and m.isfile()]
    if patch_present == '1' and len(headers) != 1:
        raise SystemExit('Cannot inspect the qBittorrent HTTP header before patch migration')
    upstream_header = tar.extractfile(headers[0]).read() if headers else b''
mk = pathlib.Path(mk_file)
content = mk.read_text()
expected = f'QBITTORRENT_VERSION = {old}'
if content.count(expected) != 1:
    raise SystemExit('Unexpected qBittorrent version definition')
mk.write_text(content.replace(expected, f'QBITTORRENT_VERSION = {new}'))
pathlib.Path(hash_file).write_text(
    '# Locally calculated from the official GitHub release tag archive.\n'
    f'sha256  {hashlib.sha256(source).hexdigest()}  qbittorrent-{new}.tar.gz\n'
    f'sha256  {license_hash}  COPYING\n'
)
if patch_present == '1' and b'#include <QHash>' in upstream_header and b'#include <QMap>' in upstream_header:
    pathlib.Path(patch_file).unlink()
    print('1')
else:
    print('0')
PY
    )
    rm -f -- "$archive"
    qb_report="$current_qb -> $target_qb"
fi

stage='detect unreleased source'
revision_tags=$(git tag --list)
printf '%s\n' "$revision_tags" | python3 "$script_dir/maintenance-select.py" revision >/dev/null
revision_tags=$(git tag --merged HEAD)
latest=$(printf '%s\n' "$revision_tags" | python3 "$script_dir/maintenance-select.py" revision)
previous="revision-$((${latest#revision-} - 1))"
if test "$previous" = revision-0; then
    unreleased=yes
elif ! git merge-base --is-ancestor "$previous" HEAD; then
    echo "Latest revision $previous is not an ancestor of main" >&2; exit 1
elif test "$(git rev-parse "$previous^{commit}")" != "$start"; then
    unreleased=yes
fi

if test "$changed" -eq 0 && test "$unreleased" = no; then
    publication=no-op
    exit 0
fi

stage='make check'
make check
stage='clean Raspberry Pi configure'
mkdir -p output
validation_output=$(mktemp -d "$repo/output/maintenance.XXXXXX")
OUTPUT="$validation_output" QBTOS_OUTPUT_DIR="$validation_output" make configure
stage='review Buildroot configuration migration'
python3 - "$repo/br2-external/configs/qbtos_rpi4_defconfig" "$validation_output/.config" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
requested = [line for line in source.read_text().splitlines()
             if (line.startswith('BR2_') and '=' in line) or
             (line.startswith('# BR2_') and line.endswith(' is not set'))]
configured = set(pathlib.Path(sys.argv[2]).read_text().splitlines())
missing = [line for line in requested if line not in configured]
legacy = 'BR2_TOOLCHAIN_EXTERNAL_CXX=y'
if missing == [legacy] and 'BR2_INSTALL_LIBSTDCPP=y' in configured:
    configs = sorted(source.parent.glob('qbtos_*_defconfig'))
    if len(configs) != 3:
        raise SystemExit('Expected exactly three qbtOS defconfigs for C++ migration')
    for config in configs:
        lines = config.read_text().splitlines(keepends=True)
        if sum(line.strip() == legacy for line in lines) != 1:
            raise SystemExit(f'Unexpected C++ toolchain setting in {config}')
        config.write_text(''.join(line for line in lines if line.strip() != legacy))
    print('Migrated obsolete external C++ selection; new Buildroot selects libstdc++')
    missing = []
if missing:
    raise SystemExit('Buildroot changed or dropped checked-in configuration:\n' +
                     '\n'.join(missing))
PY
stage='clean Raspberry Pi image build'
OUTPUT="$validation_output" QBTOS_OUTPUT_DIR="$validation_output" make build
stage='image content checks'
test -s "$validation_output/images/rootfs.squashfs"
test -s "$validation_output/images/sdcard.img"
python3 - "$validation_output/images/sdcard.img" "$validation_output/images/rootfs.squashfs" <<'PY'
import json
import pathlib
import subprocess
import sys

image, rootfs = map(pathlib.Path, sys.argv[1:])
table = json.loads(subprocess.check_output(['sfdisk', '--json', str(image)], text=True))['partitiontable']
parts = table['partitions']
expected_types = [0x0c, 0x83, 0x83, 0x0f, 0x83]
types = [int(part['type'].lower().replace('0x', ''), 16) for part in parts]
if table.get('label') != 'dos' or table.get('id', '').lower() != '0x5142544f':
    raise SystemExit('Raspberry Pi image has an unexpected MBR or disk signature')
if types != expected_types or not parts[0].get('bootable'):
    raise SystemExit(f'Raspberry Pi image has an unexpected A/B/state partition layout: {types}')
boot, system_a, system_b, extended, state = parts
if (boot['size'] != 64 * 1024 * 1024 // 512 or
        system_a['size'] != 96 * 1024 * 1024 // 512 or
        system_b['size'] != system_a['size'] or
        state['size'] != 512 * 1024 * 1024 // 512 or
        state['start'] < extended['start'] or
        state['start'] + state['size'] > extended['start'] + extended['size'] or
        rootfs.stat().st_size > system_a['size'] * 512):
    raise SystemExit('Raspberry Pi image partition sizes or A/B payload capacity changed')
print('Verified Raspberry Pi MBR, boot, equal A/B slots, and state partition')
PY
test -x "$validation_output/target/usr/bin/qbittorrent-nox" || \
    test -x "$validation_output/target/usr/local/bin/qbittorrent-nox"
test -x "$validation_output/target/usr/bin/rauc" || \
    test -x "$validation_output/target/usr/sbin/rauc"
test -f "$validation_output/target/etc/rauc/keyring.pem"
test ! -e "$validation_output/target/etc/rauc/release.key"
private_key_paths=$(find "$validation_output/target" -type f \
    \( -name '*.key' -o -name '*private*.pem' \) -print)
test -z "$private_key_paths" || {
    printf 'Private-key-shaped files entered the image:\n%s\n' "$private_key_paths" >&2
    exit 1
}
if grep -r -I -l -E -- '-----BEGIN ([A-Z ]+ )?PRIVATE KEY-----' \
    "$validation_output/target" > "$validation_output/private-key-scan.txt"; then
    printf 'PEM private key material entered the image:\n' >&2
    cat "$validation_output/private-key-scan.txt" >&2
    exit 1
else
    scan_status=$?
    test "$scan_status" -eq 1 || {
        printf 'Private-key scan failed (exit %s)\n' "$scan_status" >&2
        exit 1
    }
fi
validation=passed

if test "$publish" -eq 0; then
    publication='preview only; candidate changes left in checkout'
    exit 0
fi

stage='recheck remote main and tags'
git fetch --no-recurse-submodules origin 'refs/heads/main:refs/remotes/origin/main' --tags
test "$start" = "$(git rev-parse refs/remotes/origin/main)" || {
    echo 'origin/main advanced during validation; retry maintenance' >&2; exit 1;
}
revision_tags=$(git tag --list)
tag=$(printf '%s\n' "$revision_tags" | python3 "$script_dir/maintenance-select.py" revision)
if test "$changed" -eq 1; then
    stage='commit validated maintenance sources'
    git add -- buildroot "$qb_mk" "$qb_hash" br2-external/configs/qbtos_rpi4_defconfig \
        br2-external/configs/qbtos_qemu_amd64_defconfig \
        br2-external/configs/qbtos_qemu_arm64_defconfig
    if test "$patch_removed" -eq 1; then git add -u -- "$qb_patch"; fi
    git diff --cached --quiet && { echo 'Candidate produced no staged source change' >&2; exit 1; }
    body=$(
        if test "$current_buildroot" != "$target_buildroot"; then
            printf 'Buildroot: %s -> %s\n' "$current_buildroot" "$target_buildroot"
        fi
        if test "$current_qb" != "$target_qb"; then
            printf 'qBittorrent: %s -> %s\n' "$current_qb" "$target_qb"
        fi
    )
    git -c commit.gpgsign=false commit -m 'Refresh qbtOS upstream dependencies' -m "$body"
    committed=1
    maintenance_commit=$(git rev-parse HEAD)
fi
stage='tag validated commit'
git tag "$tag" HEAD
tagged=1
stage='atomically push validated main and tag'
git push --atomic origin HEAD:refs/heads/main "refs/tags/$tag:refs/tags/$tag"
published=1
publication='tag pushed; signed release workflow owns artifacts and feed'
