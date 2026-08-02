#!/bin/sh
set -eu

board_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
config_image="${BINARIES_DIR}/config.ext4"
config_root="${BUILD_DIR}/qbtos-config-root"
genimage_tmp="${BUILD_DIR}/genimage.tmp"

install -D -m 0644 "${board_dir}/cmdline.txt" \
	"${BINARIES_DIR}/rpi-firmware/cmdline.txt"
install -D -m 0644 "${board_dir}/config.txt" \
	"${BINARIES_DIR}/rpi-firmware/config.txt"

rm -rf "${config_root}" "${genimage_tmp}"
install -d -m 0700 "${config_root}/qbtos"
printf '%s\n' 'qbtOS persistent configuration partition' > "${config_root}/README"

rm -f "${config_image}"
truncate -s 128M "${config_image}"
"${HOST_DIR}/sbin/mkfs.ext4" -F -L QBTOS_CONFIG -d "${config_root}" \
	"${config_image}"
for image_path in / /README /qbtos; do
	"${HOST_DIR}/sbin/debugfs" -w -R "set_inode_field ${image_path} uid 0" \
		"${config_image}" >/dev/null 2>&1
	"${HOST_DIR}/sbin/debugfs" -w -R "set_inode_field ${image_path} gid 0" \
		"${config_image}" >/dev/null 2>&1
done

"${HOST_DIR}/bin/genimage" \
	--rootpath "${config_root}" \
	--tmppath "${genimage_tmp}" \
	--inputpath "${BINARIES_DIR}" \
	--outputpath "${BINARIES_DIR}" \
	--config "${board_dir}/genimage.cfg"

printf '%s\n' "qbtOS image created: ${BINARIES_DIR}/sdcard.img"
