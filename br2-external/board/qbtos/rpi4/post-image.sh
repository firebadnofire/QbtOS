#!/bin/sh
set -eu

board_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
state_image="${BINARIES_DIR}/state.ext4"
state_root="${BUILD_DIR}/qbtos-state-root"
genimage_tmp="${BUILD_DIR}/genimage.tmp"

install -D -m 0644 "${board_dir}/cmdline.txt" \
	"${BINARIES_DIR}/rpi-firmware/cmdline.txt"
install -D -m 0644 "${board_dir}/config.txt" \
	"${BINARIES_DIR}/rpi-firmware/config.txt"
install -D -m 0644 "${BINARIES_DIR}/u-boot.bin" \
	"${BINARIES_DIR}/rpi-firmware/u-boot.bin"

rm -rf "${state_root}" "${genimage_tmp}"
install -d -m 0700 "${state_root}/qbtos" "${state_root}/qbtos-backups"
printf '%s\n' 'qbtOS persistent state partition' > "${state_root}/README"

rm -f "${state_image}"
truncate -s 511M "${state_image}"
"${HOST_DIR}/sbin/mkfs.ext4" -F -L QBTOS_STATE -d "${state_root}" \
	"${state_image}"
for image_path in / /README /qbtos /qbtos-backups; do
	"${HOST_DIR}/sbin/debugfs" -w -R "set_inode_field ${image_path} uid 0" \
		"${state_image}" >/dev/null 2>&1
	"${HOST_DIR}/sbin/debugfs" -w -R "set_inode_field ${image_path} gid 0" \
		"${state_image}" >/dev/null 2>&1
done

"${HOST_DIR}/bin/genimage" \
	--rootpath "${state_root}" \
	--tmppath "${genimage_tmp}" \
	--inputpath "${BINARIES_DIR}" \
	--outputpath "${BINARIES_DIR}" \
	--config "${board_dir}/genimage.cfg"

# The 511 MiB ext4 image leaves a 1 MiB tail in logical partition 5. U-Boot
# uses two raw, CRC-protected environment records there so a power loss during
# saveenv cannot destroy the last valid slot-selection state.
test "$(wc -c < "${BINARIES_DIR}/uboot-env.bin")" -eq $((0x4000))
dd if="${BINARIES_DIR}/uboot-env.bin" of="${BINARIES_DIR}/sdcard.img" \
	bs=512 seek=$((0x180800)) conv=notrunc status=none
dd if="${BINARIES_DIR}/uboot-env.bin" of="${BINARIES_DIR}/sdcard.img" \
	bs=512 seek=$((0x180820)) conv=notrunc status=none
# genimage records the full 512 MiB partition size in the MBR but normally
# stops the sparse file at its last input byte. Extend it through the declared
# end of the state partition after placing both environment records.
truncate -s $((0x30200000)) "${BINARIES_DIR}/sdcard.img"

printf '%s\n' "qbtOS image created: ${BINARIES_DIR}/sdcard.img"
