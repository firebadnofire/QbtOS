#!/bin/sh

set -eu

die() {
	printf 'release: %s\n' "$1" >&2
	exit 1
}

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
release_output="${repo_root}/output/release"
dist_dir="${repo_root}/dist"
rauc_keyring="${repo_root}/ca/root-ca.pem"
rauc_intermediate="${repo_root}/ca/intermediate-ca.pem"
rauc_release_cert="${repo_root}/ca/release.crt"

: "${VERSION:?VERSION is required}"
: "${BUILD_DATE:?BUILD_DATE is required}"
: "${REVISION:?REVISION is required}"
: "${SOURCE_TAG:?SOURCE_TAG is required}"
: "${COMMIT:?COMMIT is required}"
: "${RAUC_CERT_FILE:?RAUC_CERT_FILE is required}"
: "${RAUC_KEY_FILE:?RAUC_KEY_FILE is required}"
: "${QBTOS_GPG_KEYRING_FILE:?QBTOS_GPG_KEYRING_FILE is required}"

provided_version=$VERSION
provided_build_date=$BUILD_DATE
provided_revision=$REVISION
provided_source_tag=$SOURCE_TAG
provided_commit=$COMMIT

case "$BUILD_DATE" in
	????-??-??) ;;
	*) die 'BUILD_DATE must use YYYY-MM-DD' ;;
esac
case "$REVISION" in
	[1-9]|[1-9][0-9]*) ;;
	*) die 'REVISION must be a positive integer without leading zeroes' ;;
esac
test "$SOURCE_TAG" = "revision-${REVISION}" || die 'SOURCE_TAG does not match REVISION'
test "$VERSION" = "${BUILD_DATE}-rev${REVISION}" || die 'VERSION does not match metadata'
case "$COMMIT" in
	[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*);;
	*) die 'COMMIT is not a full hexadecimal Git object ID' ;;
esac
test "${#COMMIT}" -eq 40 || die 'COMMIT must be the full 40-character SHA'

expected=$("${script_dir}/release-version.sh") || exit 1
eval "$expected"
test "$provided_version" = "$VERSION" || die 'VERSION does not match the derived version'
test "$provided_build_date" = "$BUILD_DATE" || die 'BUILD_DATE does not match the derived date'
test "$provided_revision" = "$REVISION" || die 'REVISION does not match reachable tags'
test "$provided_source_tag" = "$SOURCE_TAG" || die 'SOURCE_TAG does not match reachable tags'
test "$provided_commit" = "$COMMIT" || die 'COMMIT does not match HEAD'
git -C "$repo_root" merge-base --is-ancestor "$SOURCE_TAG" HEAD || \
	die "$SOURCE_TAG is not reachable from HEAD"

test -r "$RAUC_CERT_FILE" || die 'RAUC_CERT_FILE is missing or unreadable'
test -r "$RAUC_KEY_FILE" || die 'RAUC_KEY_FILE is missing or unreadable'
test -r "$QBTOS_GPG_KEYRING_FILE" || \
	die 'QBTOS_GPG_KEYRING_FILE is missing or unreadable'
test -r "$rauc_keyring" || die 'embedded RAUC root CA is missing'
test -r "$rauc_intermediate" || die 'embedded RAUC intermediate CA is missing'
test -r "$rauc_release_cert" || die 'embedded RAUC release certificate is missing'
openssl x509 -in "$RAUC_CERT_FILE" -noout >/dev/null 2>&1 || die 'invalid RAUC certificate'
openssl pkey -in "$RAUC_KEY_FILE" -noout >/dev/null 2>&1 || die 'invalid RAUC private key'
cert_public=$(openssl x509 -in "$RAUC_CERT_FILE" -pubkey -noout | \
	openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')
key_public=$(openssl pkey -in "$RAUC_KEY_FILE" -pubout -outform DER 2>/dev/null | \
	sha256sum | awk '{print $1}')
test "$cert_public" = "$key_public" || die 'RAUC certificate and key do not match'

certificate_subject=$(openssl x509 -in "$RAUC_CERT_FILE" -noout -subject -issuer)
openssl x509 -in "$RAUC_CERT_FILE" -noout -purpose | \
	grep -q '^Code signing : Yes$' || die 'RAUC certificate lacks codeSigning purpose'
openssl x509 -in "$RAUC_CERT_FILE" -noout -text | \
	grep -q 'Digital Signature' || die 'RAUC certificate lacks digitalSignature key usage'

if test "${QBTOS_ALLOW_DEVELOPMENT_CERT:-0}" = 1; then
	printf '%s\n' "$certificate_subject" | grep -qi 'development' || \
		die 'development release requires a distinct development certificate'
	openssl verify -purpose any -CAfile "$RAUC_CERT_FILE" \
		"$RAUC_CERT_FILE" >/dev/null || \
		die 'development RAUC certificate must be self-signed'
	rauc_signing_keyring=$RAUC_CERT_FILE
	rauc_intermediate_option=
else
	if printf '%s\n' "$certificate_subject" | grep -qi 'development'; then
		die 'development trust root refused by production release target'
	fi
	openssl verify -purpose any -CAfile "$rauc_keyring" \
		-untrusted "$rauc_intermediate" "$RAUC_CERT_FILE" >/dev/null || \
		die 'RAUC certificate is not trusted by the embedded qbtOS CA'
	expected_fingerprint=$(openssl x509 -in "$rauc_release_cert" \
		-noout -fingerprint -sha256)
	provided_fingerprint=$(openssl x509 -in "$RAUC_CERT_FILE" \
		-noout -fingerprint -sha256)
	test "$expected_fingerprint" = "$provided_fingerprint" || \
		die 'RAUC certificate does not match ca/release.crt'
	rauc_signing_keyring=$rauc_keyring
	rauc_intermediate_option="--intermediate=$rauc_intermediate"
fi

if test -f "${release_output}/Makefile"; then
	make -s -C "${repo_root}/buildroot" O="$release_output" distclean
fi

export QBTOS_RELEASE_BUILD=1 QBTOS_VERSION="$VERSION"
export QBTOS_BUILD_DATE="$BUILD_DATE" QBTOS_REVISION="$REVISION"
export QBTOS_SOURCE_TAG="$SOURCE_TAG" QBTOS_COMMIT="$COMMIT"
export QBTOS_RAUC_CERT_FILE="$RAUC_CERT_FILE"
export QBTOS_GPG_KEYRING_FILE
export QBTOS_ALLOW_DEVELOPMENT_CERT="${QBTOS_ALLOW_DEVELOPMENT_CERT:-0}"
QBTOS_OUTPUT_DIR="$release_output" "${script_dir}/build.sh" --format flat

image="${dist_dir}/${VERSION}.img.zst"
bundle="${dist_dir}/${VERSION}.raucb"
manifest="${dist_dir}/${VERSION}.manifest.json"
bundle_root="${release_output}/qbtos-rauc-bundle"

install -d -m 0755 "$dist_dir" "$bundle_root"
find "$dist_dir" -mindepth 1 -maxdepth 1 -delete
find "$bundle_root" -mindepth 1 -maxdepth 1 -delete
install -m 0644 "${release_output}/images/rootfs.squashfs" \
	"${bundle_root}/rootfs.squashfs"
sed \
	-e "s/@VERSION@/${VERSION}/g" \
	-e "s/@BUILD_DATE@/${BUILD_DATE}/g" \
	-e "s/@REVISION@/${REVISION}/g" \
	-e "s/@SOURCE_TAG@/${SOURCE_TAG}/g" \
	-e "s/@COMMIT@/${COMMIT}/g" \
	"${repo_root}/br2-external/board/qbtos/rpi4/rauc-manifest.in" \
	> "${bundle_root}/manifest.raucm"

command -v zstd >/dev/null 2>&1 || die 'host zstd is required'
zstd -q -f -19 "${release_output}/images/sdcard.img" -o "$image"
zstd -q -t "$image"

host_rauc="${release_output}/host/bin/rauc"
test -x "$host_rauc" || die 'Buildroot host RAUC tool was not built'
if test -n "$rauc_intermediate_option"; then
	"$host_rauc" bundle --cert="$RAUC_CERT_FILE" --key="$RAUC_KEY_FILE" \
		"$rauc_intermediate_option" --signing-keyring="$rauc_signing_keyring" \
		"$bundle_root" "$bundle"
else
	"$host_rauc" bundle --cert="$RAUC_CERT_FILE" --key="$RAUC_KEY_FILE" \
		--signing-keyring="$rauc_signing_keyring" "$bundle_root" "$bundle"
fi
"$host_rauc" info --keyring="$rauc_signing_keyring" "$bundle" >/dev/null

"${script_dir}/release-manifest.py" \
	--version "$VERSION" --build-date "$BUILD_DATE" --revision "$REVISION" \
	--source-tag "$SOURCE_TAG" --commit "$COMMIT" \
	--bundle "$bundle" --image "$image" --output "$manifest"
(
	cd "$dist_dir"
	sha256sum "${VERSION}.img.zst" "${VERSION}.raucb" \
		"${VERSION}.manifest.json" > "${VERSION}.sha256"
)

test "$(find "$dist_dir" -mindepth 1 -maxdepth 1 -type f | wc -l)" -eq 4 || \
	die 'dist must contain exactly four files'
for suffix in img.zst raucb manifest.json sha256; do
	test -s "${dist_dir}/${VERSION}.${suffix}" || die "missing ${VERSION}.${suffix}"
done

printf 'qbtOS signed release artifacts:\n'
find "$dist_dir" -mindepth 1 -maxdepth 1 -type f -printf '  %f\n' | sort
