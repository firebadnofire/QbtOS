#!/bin/sh
set -eu

install -d -m 0755 "${TARGET_DIR}/config" "${TARGET_DIR}/data"
chmod 0600 "${TARGET_DIR}/etc/nftables-qbtos.conf"
