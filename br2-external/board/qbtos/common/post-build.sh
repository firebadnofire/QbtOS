#!/bin/sh
set -eu

install -d -m 0755 "${TARGET_DIR}/boot" "${TARGET_DIR}/config" "${TARGET_DIR}/data" \
	"${TARGET_DIR}/themes" \
	"${TARGET_DIR}/usr/share/qbtos"
chmod 0600 "${TARGET_DIR}/etc/nftables-qbtos.conf"

# qbtOS starts file sharing only after persistent settings are mounted and only
# when explicitly enabled. Remove upstream packages' unconditional init hooks.
rm -f "${TARGET_DIR}/etc/init.d/S30rpcbind" \
	"${TARGET_DIR}/etc/init.d/S60nfs" "${TARGET_DIR}/etc/init.d/S91smb"

release_file="${TARGET_DIR}/etc/qbtos-release"
rauc_keyring="${TARGET_DIR}/etc/rauc/keyring.pem"
rauc_intermediate="${TARGET_DIR}/usr/share/qbtos/ca/intermediate-ca.pem"
rauc_release_cert="${TARGET_DIR}/usr/share/qbtos/ca/release.crt"
test -s "$rauc_keyring" || {
	printf '%s\n' 'Embedded RAUC root CA is missing or empty' >&2
	exit 1
}
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
	openssl x509 -in "${QBTOS_RAUC_CERT_FILE}" \
		-noout -ext basicConstraints | grep -q 'CA:FALSE' || {
		printf '%s\n' 'RAUC certificate must be a non-CA leaf' >&2
		exit 1
	}
	openssl x509 -in "${QBTOS_RAUC_CERT_FILE}" \
		-noout -ext extendedKeyUsage | \
		grep -Eq 'Code Signing|1\.3\.6\.1\.5\.5\.7\.3\.3' || {
		printf '%s\n' 'RAUC certificate lacks codeSigning EKU' >&2
		exit 1
	}
	openssl x509 -in "${QBTOS_RAUC_CERT_FILE}" \
		-noout -ext keyUsage | grep -q 'Digital Signature' || {
		printf '%s\n' 'RAUC certificate lacks digitalSignature key usage' >&2
		exit 1
	}
	if test "${QBTOS_ALLOW_DEVELOPMENT_CERT:-0}" = 1; then
		# A development image trusts only its isolated development signer.
		openssl x509 -in "${QBTOS_RAUC_CERT_FILE}" -noout -subject | \
			grep -qi 'development' || {
			printf '%s\n' 'Development image requires a development certificate' >&2
			exit 1
		}
		openssl verify -purpose any -CAfile "${QBTOS_RAUC_CERT_FILE}" \
			"${QBTOS_RAUC_CERT_FILE}" >/dev/null || {
			printf '%s\n' 'Development RAUC certificate must be self-signed' >&2
			exit 1
		}
		install -D -m 0644 "${QBTOS_RAUC_CERT_FILE}" "$rauc_keyring"
	else
		openssl verify -purpose any -CAfile "$rauc_keyring" \
			-untrusted "$rauc_intermediate" "${QBTOS_RAUC_CERT_FILE}" \
			>/dev/null || {
			printf '%s\n' 'RAUC release certificate is not trusted by embedded CA' >&2
			exit 1
		}
		expected_fingerprint=$(openssl x509 -in "$rauc_release_cert" \
			-noout -fingerprint -sha256)
		provided_fingerprint=$(openssl x509 -in "${QBTOS_RAUC_CERT_FILE}" \
			-noout -fingerprint -sha256)
		test "$expected_fingerprint" = "$provided_fingerprint" || {
			printf '%s\n' 'RAUC release certificate does not match embedded signer' >&2
			exit 1
		}
	fi
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
