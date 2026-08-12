#!/bin/sh
set -eu

openssl=$1
source_dir=$2

for name in root-ca.pem intermediate-ca.pem ca-chain.pem release.crt; do
	test -s "${source_dir}/${name}" || {
		printf 'qbtOS CA: missing or empty %s\n' "$name" >&2
		exit 1
	}
	if grep -Eq 'BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY' "${source_dir}/${name}"; then
		printf 'qbtOS CA: private key material found in %s\n' "$name" >&2
		exit 1
	fi
done

for name in root-ca.pem intermediate-ca.pem release.crt; do
	"$openssl" x509 -in "${source_dir}/${name}" -noout >/dev/null 2>&1 || {
		printf 'qbtOS CA: invalid X.509 certificate %s\n' "$name" >&2
		exit 1
	}
done

test "$(grep -c 'BEGIN CERTIFICATE' "${source_dir}/ca-chain.pem")" -eq 2 || {
	printf '%s\n' 'qbtOS CA: ca-chain.pem must contain exactly two certificates' >&2
	exit 1
}
"$openssl" verify -CAfile "${source_dir}/root-ca.pem" \
	"${source_dir}/root-ca.pem" >/dev/null
"$openssl" verify -purpose any -CAfile "${source_dir}/root-ca.pem" \
	-untrusted "${source_dir}/intermediate-ca.pem" \
	"${source_dir}/release.crt" >/dev/null
"$openssl" verify -purpose any -CAfile "${source_dir}/ca-chain.pem" \
	"${source_dir}/release.crt" >/dev/null

for name in root-ca.pem intermediate-ca.pem; do
	"$openssl" x509 -in "${source_dir}/${name}" -noout -text | \
		grep -q 'CA:TRUE' || {
		printf 'qbtOS CA: %s is not a CA certificate\n' "$name" >&2
		exit 1
	}
done
"$openssl" x509 -in "${source_dir}/release.crt" -noout -text | \
	grep -q 'CA:FALSE' || {
	printf '%s\n' 'qbtOS CA: release.crt must be a non-CA leaf' >&2
	exit 1
}
"$openssl" x509 -in "${source_dir}/release.crt" -noout -purpose | \
	grep -q '^Code signing : Yes$' || {
	printf '%s\n' 'qbtOS CA: release.crt lacks the codeSigning purpose' >&2
	exit 1
}
"$openssl" x509 -in "${source_dir}/release.crt" -noout -text | \
	grep -q 'Digital Signature' || {
	printf '%s\n' 'qbtOS CA: release.crt lacks digitalSignature key usage' >&2
	exit 1
}
