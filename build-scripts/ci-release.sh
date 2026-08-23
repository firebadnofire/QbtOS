#!/usr/bin/env bash

set -Eeuo pipefail

die() {
	printf 'ci-release: %s\n' "$1" >&2
	exit 1
}

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)

[[ "$(id -u)" -ne 0 ]] || die 'the Buildroot release must not run as root'
[[ "${QBTOS_WORKSPACE:-}" == "$repo_root" ]] || \
	die 'QBTOS_WORKSPACE does not match the checked-out repository'
[[ "${QBTOS_BUILD_JOBS:-}" =~ ^[1-9][0-9]*$ ]] || \
	die 'QBTOS_BUILD_JOBS must be a positive integer'

for required_name in VERSION BUILD_DATE REVISION SOURCE_TAG COMMIT RUNNER_TEMP \
	BR2_DL_DIR BR2_CCACHE_DIR RAUC_CERT_FILE RAUC_KEY_FILE \
	QBTOS_GPG_KEYRING_FILE; do
	[[ -n "${!required_name:-}" ]] || die "${required_name} is required"
done

[[ "$BR2_DL_DIR" == "${repo_root}/.ci-cache/buildroot-dl" ]] || \
	die 'BR2_DL_DIR must use the workspace-local CI download cache'
[[ "$BR2_CCACHE_DIR" == "${repo_root}/.ci-cache/buildroot-ccache" ]] || \
	die 'BR2_CCACHE_DIR must use the workspace-local CI compiler cache'
for cache_dir in "$BR2_DL_DIR" "$BR2_CCACHE_DIR"; do
	[[ -d "$cache_dir" && -w "$cache_dir" ]] || \
		die 'a required Buildroot cache directory is missing or unwritable'
done

for signing_file in \
	"$RAUC_CERT_FILE" "$RAUC_KEY_FILE" "$QBTOS_GPG_KEYRING_FILE"; do
	[[ -r "$signing_file" ]] || die 'a required signing input is unreadable'
done

cd "$repo_root"
mkdir -p output/ci

# Expand release metadata and signing paths only inside the unprivileged shell.
# shellcheck disable=SC2016
exec "${script_dir}/ci-run.sh" output/ci/release-build.log bash -c '
	set -Eeuo pipefail
	printf "CI phase: source and unit checks\n"
	make --silent --no-print-directory check
	printf "CI phase: signed ARM64 release with %s job(s)\n" \
		"$QBTOS_BUILD_JOBS"
	make --silent --no-print-directory release \
		VERSION="$VERSION" BUILD_DATE="$BUILD_DATE" \
		REVISION="$REVISION" SOURCE_TAG="$SOURCE_TAG" COMMIT="$COMMIT" \
		RAUC_CERT_FILE="$RAUC_CERT_FILE" RAUC_KEY_FILE="$RAUC_KEY_FILE" \
		QBTOS_GPG_KEYRING_FILE="$QBTOS_GPG_KEYRING_FILE" \
		JOBS="$QBTOS_BUILD_JOBS"
	printf "CI phase: Buildroot ccache statistics\n"
	if ! make --silent --no-print-directory \
		-C "$QBTOS_WORKSPACE/buildroot" \
		BR2_EXTERNAL="$QBTOS_WORKSPACE/br2-external" \
		O="$QBTOS_WORKSPACE/output/release" ccache-stats; then
		printf "Warning: Buildroot ccache statistics are unavailable.\n" >&2
	fi
'
