#!/bin/sh
set -eu

board_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
arch="${QBTOS_ARCH:-}"
data_size_gb="${QBTOS_DATA_SIZE_GB:-16}"
work_dir="${BUILD_DIR}/qbtos-qemu-image"
config_root="${work_dir}/config-root"
data_root="${work_dir}/data-root"
genimage_tmp="${work_dir}/genimage.tmp"
genimage_output="${work_dir}/output"
config_image="${BINARIES_DIR}/config.ext4"
data_image="${work_dir}/data.ext4"
raw_system_image="${genimage_output}/qbtos-qemu.raw"
system_qcow="${BINARIES_DIR}/qbtos-${arch}.qcow2"
data_qcow="${BINARIES_DIR}/qbtos-data-${arch}.qcow2"
qemu_img="${HOST_DIR}/bin/qemu-img"

case "$arch" in
	amd64|arm64)
		;;
	*)
		printf 'QBTOS_ARCH must be amd64 or arm64, got: %s\n' "$arch" >&2
		exit 1
		;;
esac
case "$data_size_gb" in
	''|*[!0-9]*|0)
		printf 'QBTOS_DATA_SIZE_GB must be a positive integer\n' >&2
		exit 1
		;;
esac
test -x "$qemu_img" || {
	printf 'Buildroot host qemu-img is missing: %s\n' "$qemu_img" >&2
	exit 1
}

rm -rf "$work_dir"
install -d -m 0700 "$config_root/qbtos" "$data_root" \
	"$genimage_tmp" "$genimage_output"
printf '%s\n' 'qbtOS persistent configuration partition' > "$config_root/README"
printf '%s\n' 'qbtOS QEMU data disk' > "$data_root/README"

rm -f "$config_image"
truncate -s 128M "$config_image"
"${HOST_DIR}/sbin/mkfs.ext4" -F -L QBTOS_CONFIG -d "$config_root" \
	"$config_image"
for image_path in / /README /qbtos; do
	"${HOST_DIR}/sbin/debugfs" -w -R "set_inode_field ${image_path} uid 0" \
		"$config_image" >/dev/null 2>&1
	"${HOST_DIR}/sbin/debugfs" -w -R "set_inode_field ${image_path} gid 0" \
		"$config_image" >/dev/null 2>&1
done

truncate -s "${data_size_gb}G" "$data_image"
"${HOST_DIR}/sbin/mkfs.ext4" -F -L QBTOS_DATA -d "$data_root" "$data_image"

"${HOST_DIR}/bin/genimage" \
	--rootpath "$config_root" \
	--tmppath "$genimage_tmp" \
	--inputpath "$BINARIES_DIR" \
	--outputpath "$genimage_output" \
	--config "${board_dir}/genimage.cfg"

rm -f "$system_qcow" "$data_qcow"
"$qemu_img" convert -f raw -O qcow2 -o compat=1.1 \
	"$raw_system_image" "$system_qcow"
"$qemu_img" convert -f raw -O qcow2 -o compat=1.1 \
	"$data_image" "$data_qcow"

printf '%s\n' "qbtOS QEMU system image: ${system_qcow}"
printf '%s\n' "qbtOS QEMU data image (${data_size_gb} GiB): ${data_qcow}"
