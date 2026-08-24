#!/bin/sh

set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
check_package=${QBTOS_CHECK_PACKAGE:-${repo_root}/buildroot/utils/check-package}

test -x "$check_package" || {
	printf 'check-package: checker is missing or not executable: %s\n' \
		"$check_package" >&2
	exit 1
}

exec "$check_package" --verbose --br2-external "$@"
