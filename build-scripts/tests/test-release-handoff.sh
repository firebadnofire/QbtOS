#!/usr/bin/env bash

set -Eeuo pipefail

die() {
	printf 'test-release-handoff: %s\n' "$1" >&2
	exit 1
}

[[ "$(id -u)" -eq 0 ]] || die 'this Linux privilege test must run as root'
[[ "$#" -eq 1 ]] || die 'usage: test-release-handoff.sh BUILD_USER'
build_user="$1"
build_uid="$(id -u "$build_user")" || die 'build user does not exist'
build_gid="$(id -g "$build_user")"
[[ "$build_uid" -ne 0 ]] || die 'build user must not be root'

test_root="$(mktemp -d /tmp/qbtos-release-handoff-test.XXXXXX)"
chmod 0755 "$test_root"
cleanup() {
	case "$test_root" in
	/tmp/qbtos-release-handoff-test.*) rm -rf -- "$test_root" ;;
	*) printf 'test-release-handoff: unsafe cleanup path: %s\n' "$test_root" >&2 ;;
	esac
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

workspace="$test_root/workspace"
runner_temp="$test_root/runner-temp"
install -d -m 0755 "$workspace/build-scripts" "$runner_temp"
install -d -m 0755 \
	"$workspace/.ci-cache/buildroot-dl" \
	"$workspace/.ci-cache/buildroot-ccache"
printf '%s\n' source-owned-by-root > "$workspace/source-sentinel"
for input in rauc-release.crt rauc-release.key qbtos-update-signing.gpg; do
	printf '%s\n' non-secret-test-input > "$runner_temp/$input"
	chmod 0600 "$runner_temp/$input"
done

cat > "$workspace/build-scripts/ci-release.sh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$(id -u)" -ne 0 ]]
[[ -r "$RAUC_CERT_FILE" && -r "$RAUC_KEY_FILE" && \
	-r "$QBTOS_GPG_KEYRING_FILE" ]]
for input in "$RAUC_CERT_FILE" "$RAUC_KEY_FILE" "$QBTOS_GPG_KEYRING_FILE"; do
	[[ "$(stat -c '%u:%g:%a' "$input")" == "$(id -u):$(id -g):600" ]]
done
touch "$QBTOS_WORKSPACE/output/unprivileged-write-ok"
touch "$BR2_DL_DIR/download-cache-write-ok"
printf '%s\n' "$RAUC_KEY_FILE" > "$QBTOS_WORKSPACE/output/private-copy-path"
EOF
chmod 0755 "$workspace/build-scripts/ci-release.sh"

source_uid="$(stat -c '%u' "$workspace/source-sentinel")"
QBTOS_WORKSPACE="$workspace" RUNNER_TEMP="$runner_temp" \
	BR2_DL_DIR="$workspace/.ci-cache/buildroot-dl" \
	BR2_CCACHE_DIR="$workspace/.ci-cache/buildroot-ccache" \
	RAUC_CERT_FILE="$runner_temp/rauc-release.crt" \
	RAUC_KEY_FILE="$runner_temp/rauc-release.key" \
	QBTOS_GPG_KEYRING_FILE="$runner_temp/qbtos-update-signing.gpg" \
	bash "$PWD/build-scripts/prepare-release-build.sh" "$build_user" -- \
	"$workspace/build-scripts/ci-release.sh"

[[ "$(stat -c '%u' "$workspace/source-sentinel")" == "$source_uid" ]] || \
	die 'source-tree ownership changed'
[[ "$(stat -c '%u:%g' "$workspace/output/unprivileged-write-ok")" == \
	"$build_uid:$build_gid" ]] || die 'release command did not run as the build user'
[[ -f "$workspace/.ci-cache/buildroot-dl/download-cache-write-ok" ]] || \
	die 'build user could not write the download cache'
private_copy_path="$(cat "$workspace/output/private-copy-path")"
[[ ! -e "$private_copy_path" ]] || die 'private signing copy survived cleanup'
[[ "$(stat -c '%u:%g:%a' "$runner_temp/rauc-release.key")" == "0:0:600" ]] || \
	die 'runner-owned private key permissions changed'

printf '%s\n' 'test-release-handoff: PASS'
