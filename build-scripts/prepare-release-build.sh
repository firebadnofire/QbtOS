#!/usr/bin/env bash

set -Eeuo pipefail

die() {
	printf 'release-handoff: %s\n' "$1" >&2
	exit 1
}

describe_path() {
	label="$1"
	path="$2"
	stat -Lc "release-handoff: ${label} uid=%u gid=%g mode=%a type=%F path=%n" \
		"$path" || die "cannot inspect ${label}"
}

[[ "$(id -u)" -eq 0 ]] || die 'preparation must run as root'
[[ "$#" -ge 3 && "$2" == -- ]] || \
	die 'usage: prepare-release-build.sh BUILD_USER -- COMMAND [ARGUMENT...]'

build_user="$1"
shift 2
getent passwd "$build_user" >/dev/null || die "build user does not exist: $build_user"
build_uid="$(id -u "$build_user")"
build_gid="$(id -g "$build_user")"
[[ "$build_uid" -ne 0 ]] || die 'the build user must not be root'

for required_name in QBTOS_WORKSPACE RUNNER_TEMP BR2_DL_DIR BR2_CCACHE_DIR \
	RAUC_CERT_FILE RAUC_KEY_FILE QBTOS_GPG_KEYRING_FILE; do
	[[ -n "${!required_name:-}" ]] || die "${required_name} is required"
done

workspace="$(CDPATH='' cd -- "$QBTOS_WORKSPACE" 2>/dev/null && pwd -P)" || \
	die 'QBTOS_WORKSPACE is missing or inaccessible'
[[ "$workspace" == "$QBTOS_WORKSPACE" ]] || \
	die 'QBTOS_WORKSPACE must be an absolute canonical path'
[[ "$BR2_DL_DIR" == "$workspace/.ci-cache/buildroot-dl" ]] || \
	die 'BR2_DL_DIR must use the workspace-local CI download cache'
[[ "$BR2_CCACHE_DIR" == "$workspace/.ci-cache/buildroot-ccache" ]] || \
	die 'BR2_CCACHE_DIR must use the workspace-local CI compiler cache'
[[ -d "$RUNNER_TEMP" ]] || die 'RUNNER_TEMP is missing'

describe_path workspace "$workspace"
describe_path runner_temp "$RUNNER_TEMP"
printf 'release-handoff: build_user=%s uid=%s gid=%s\n' \
	"$build_user" "$build_uid" "$build_gid"

signing_index=0
for signing_file in \
	"$RAUC_CERT_FILE" "$RAUC_KEY_FILE" "$QBTOS_GPG_KEYRING_FILE"; do
	signing_index=$((signing_index + 1))
	[[ -f "$signing_file" && ! -L "$signing_file" && -r "$signing_file" ]] || \
		die "signing input ${signing_index} must be a readable regular file"
	[[ -s "$signing_file" ]] || die "signing input ${signing_index} is empty"
	stat -Lc "release-handoff: signing_input_${signing_index} uid=%u gid=%g mode=%a size=%s" \
		"$signing_file" || die "cannot inspect signing input ${signing_index}"
done

for generated_dir in \
	"$workspace/.ci-cache" "$BR2_DL_DIR" "$BR2_CCACHE_DIR" \
	"$workspace/output" "$workspace/dist"; do
	[[ ! -L "$generated_dir" ]] || die "refusing generated-directory symlink: $generated_dir"
	mkdir -p -- "$generated_dir" || die "cannot create generated directory: $generated_dir"
done
chown -R "$build_uid:$build_gid" \
	"$workspace/.ci-cache" "$workspace/output" "$workspace/dist" || \
	die 'cannot delegate generated directories to the build user'

handoff_dir=''
cleanup() {
	case "$handoff_dir" in
	/tmp/qbtos-release-handoff.*)
		rm -rf -- "$handoff_dir"
		;;
	'') ;;
	*)
		printf 'release-handoff: refusing unsafe cleanup path: %s\n' \
			"$handoff_dir" >&2
		;;
	esac
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

umask 077
handoff_dir="$(mktemp -d /tmp/qbtos-release-handoff.XXXXXX)" || \
	die 'cannot create private handoff directory'
install -d -o "$build_uid" -g "$build_gid" -m 0700 \
	"$handoff_dir" "$handoff_dir/home" "$handoff_dir/tmp" \
	"$handoff_dir/signing" || die 'cannot prepare private build directories'
install -o "$build_uid" -g "$build_gid" -m 0600 \
	"$RAUC_CERT_FILE" "$handoff_dir/signing/rauc-release.crt" || \
	die 'cannot copy the RAUC certificate'
install -o "$build_uid" -g "$build_gid" -m 0600 \
	"$RAUC_KEY_FILE" "$handoff_dir/signing/rauc-release.key" || \
	die 'cannot copy the RAUC private key'
install -o "$build_uid" -g "$build_gid" -m 0600 \
	"$QBTOS_GPG_KEYRING_FILE" "$handoff_dir/signing/qbtos-update-signing.gpg" || \
	die 'cannot copy the OpenPGP public keyring'

for generated_dir in "$BR2_DL_DIR" "$BR2_CCACHE_DIR" \
	"$workspace/output" "$workspace/dist"; do
	runuser --user "$build_user" -- test -w "$generated_dir" || \
		die "build user cannot write generated directory: $generated_dir"
	describe_path generated_dir "$generated_dir"
done
runuser --user "$build_user" -- test -r "$workspace/build-scripts/ci-release.sh" || \
	die 'build user cannot read the checked-out release scripts'
for copied_input in "$handoff_dir"/signing/*; do
	[[ "$(stat -c '%u:%g:%a' "$copied_input")" == \
		"$build_uid:$build_gid:600" ]] || \
		die 'copied signing input ownership or mode is unsafe'
done
describe_path private_handoff "$handoff_dir"
printf '%s\n' 'release-handoff: starting unprivileged release command'

runuser --user "$build_user" -- env \
	HOME="$handoff_dir/home" USER="$build_user" LOGNAME="$build_user" \
	TMPDIR="$handoff_dir/tmp" PATH="$PATH" \
	PYTHONDONTWRITEBYTECODE=1 QBTOS_WORKSPACE="$workspace" \
	VERSION="${VERSION:-}" BUILD_DATE="${BUILD_DATE:-}" \
	REVISION="${REVISION:-}" SOURCE_TAG="${SOURCE_TAG:-}" COMMIT="${COMMIT:-}" \
	RUNNER_TEMP="$handoff_dir/tmp" \
	QBTOS_BUILD_QUIET="${QBTOS_BUILD_QUIET:-0}" \
	QBTOS_BUILD_JOBS="${QBTOS_BUILD_JOBS:-}" \
	QBTOS_CI_HEARTBEAT_SECONDS="${QBTOS_CI_HEARTBEAT_SECONDS:-300}" \
	BR2_DL_DIR="$BR2_DL_DIR" BR2_CCACHE_DIR="$BR2_CCACHE_DIR" \
	RAUC_CERT_FILE="$handoff_dir/signing/rauc-release.crt" \
	RAUC_KEY_FILE="$handoff_dir/signing/rauc-release.key" \
	QBTOS_GPG_KEYRING_FILE="$handoff_dir/signing/qbtos-update-signing.gpg" \
	"$@"
