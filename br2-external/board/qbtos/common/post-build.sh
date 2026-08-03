#!/bin/sh
set -eu

install -d -m 0755 "${TARGET_DIR}/boot" "${TARGET_DIR}/config" "${TARGET_DIR}/data" \
	"${TARGET_DIR}/usr/share/qbtos"
chmod 0600 "${TARGET_DIR}/etc/nftables-qbtos.conf"

release_file="${TARGET_DIR}/etc/qbtos-release"
if test "${QBTOS_RELEASE_BUILD:-0}" = 1; then
	: "${QBTOS_VERSION:?missing QBTOS_VERSION}"
	: "${QBTOS_BUILD_DATE:?missing QBTOS_BUILD_DATE}"
	: "${QBTOS_REVISION:?missing QBTOS_REVISION}"
	: "${QBTOS_SOURCE_TAG:?missing QBTOS_SOURCE_TAG}"
	: "${QBTOS_COMMIT:?missing QBTOS_COMMIT}"
	: "${QBTOS_RAUC_CERT_FILE:?missing QBTOS_RAUC_CERT_FILE}"
	: "${QBTOS_GPG_KEYRING_FILE:?missing QBTOS_GPG_KEYRING_FILE}"
	test -r "${QBTOS_RAUC_CERT_FILE}" || {
		printf '%s\n' 'RAUC release certificate is unreadable' >&2
		exit 1
	}
	if grep -q 'PRIVATE KEY' "${QBTOS_RAUC_CERT_FILE}"; then
		printf '%s\n' 'RAUC certificate file contains private key material' >&2
		exit 1
	fi
	install -D -m 0644 "${QBTOS_RAUC_CERT_FILE}" \
		"${TARGET_DIR}/etc/rauc/keyring.pem"
	test -s "${QBTOS_GPG_KEYRING_FILE}" || {
		printf '%s\n' 'OpenPGP update keyring is unreadable or empty' >&2
		exit 1
	}
	install -D -m 0644 "${QBTOS_GPG_KEYRING_FILE}" \
		"${TARGET_DIR}/etc/qbtos/update-signing.gpg"
else
	QBTOS_VERSION=development
	QBTOS_BUILD_DATE=unknown
	QBTOS_REVISION=0
	QBTOS_SOURCE_TAG=unreleased
	QBTOS_COMMIT=unknown
	rm -f "${TARGET_DIR}/etc/rauc/keyring.pem"
	rm -f "${TARGET_DIR}/etc/qbtos/update-signing.gpg"
fi

{
	printf 'QBTOS_VERSION=%s\n' "${QBTOS_VERSION}"
	printf 'QBTOS_BUILD_DATE=%s\n' "${QBTOS_BUILD_DATE}"
	printf 'QBTOS_REVISION=%s\n' "${QBTOS_REVISION}"
	printf 'QBTOS_SOURCE_TAG=%s\n' "${QBTOS_SOURCE_TAG}"
	printf 'QBTOS_COMMIT=%s\n' "${QBTOS_COMMIT}"
	printf '%s\n' 'QBTOS_COMPATIBLE=qbtos-rpi4' 'QBTOS_CHANNEL=stable'
} > "${release_file}"
printf '%s\n' '1' > "${TARGET_DIR}/usr/share/qbtos/state-schema"

# Provide a safe lower bound for platforms without a working real-time clock.
build_epoch="${SOURCE_DATE_EPOCH:-$(date +%s)}"
printf '%s\n' "$build_epoch" > "${TARGET_DIR}/usr/share/qbtos/build-epoch"
