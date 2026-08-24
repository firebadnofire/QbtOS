#!/usr/bin/env bash

set -Eeuo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
default_image="${repo_root}/output/images/sdcard.img"
large_device_bytes=$((100 * 1024 * 1024 * 1024))
alignment_bytes=$((1024 * 1024))

usage() {
	cat <<'EOF'
Usage: build-scripts/imager.sh [--image PATH]

Interactively select a whole block device, write the qbtOS SD image, and
optionally create a separate ext4 or NTFS QBTOS_DATA partition after the OS.

Options:
  --image PATH  Raw or Zstandard-compressed qbtOS SD image
                (default: output/images/sdcard.img)
  -h, --help    Show this help
EOF
}

select_image() {
	local selection custom_path

	selection=$(whiptail --title "qbtOS Image" --menu \
		"Choose the qbtOS image to write." 14 78 2 \
		default "Default: ${default_image}" \
		custom "Enter a custom .img or .img.zst path" \
		3>&1 1>&2 2>&3) || return 1
	if [[ "$selection" == "default" ]]; then
		printf '%s\n' "$default_image"
		return 0
	fi
	while true; do
		custom_path=$(whiptail --title "Custom qbtOS Image" --inputbox \
			"Enter the path to a qbtOS .img or .img.zst file." 10 78 "" \
			3>&1 1>&2 2>&3) || return 1
		if [[ -f "$custom_path" && -s "$custom_path" ]]; then
			printf '%s\n' "$custom_path"
			return 0
		fi
		whiptail --title "Invalid image" --msgbox \
			"The image is missing or empty:\n${custom_path}" 9 72
	done
}

cleanup_staged_image() {
	if [[ -n "${staged_image_path:-}" ]]; then
		rm -f -- "$staged_image_path"
		staged_image_path=
	fi
}

prepare_image() {
	local source=$1

	image_source_path=$(realpath "$source")
	[[ -f "$image_source_path" && -s "$image_source_path" ]] || die \
		"image is missing or empty: ${image_source_path}"
	case "${image_source_path,,}" in
		*.zst)
			require_command zstd
			staged_image_path=$(mktemp --suffix=.img qbtos-imager.XXXXXXXXXX)
			printf 'Decompressing %s...\n' "$image_source_path"
			zstd -q -d --stdout -- "$image_source_path" > "$staged_image_path" || \
				die "could not decompress image: ${image_source_path}"
			[[ -s "$staged_image_path" ]] || die \
				"decompressed image is empty: ${image_source_path}"
			image_path=$staged_image_path
			;;
		*)
			image_path=$image_source_path
			;;
	esac
}

die() {
	printf 'Error: %s\n' "$1" >&2
	exit 1
}

require_command() {
	command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

validate_image_layout() {
	local image=$1
	local table

	table=$(sfdisk -d "$image") || die "cannot read the image partition table"
	grep -q '^label-id: 0x5142544f$' <<<"$table" || die \
		"image does not have the qbtOS MBR signature"
	grep -Eq '^.+2 : .+type=83' <<<"$table" || die "image has no system slot A"
	grep -Eq '^.+3 : .+type=83' <<<"$table" || die "image has no system slot B"
	grep -Eq '^.+4 : .+type=f' <<<"$table" || die \
		"image does not reserve extended partition 4"
	grep -Eq '^.+5 : .+type=83' <<<"$table" || die \
		"image has no logical QBTOS_STATE partition"
}

human_size() {
	numfmt --to=iec-i --suffix=B "$1"
}

device_tags() {
	local size_bytes=$1
	local removable=$2
	local transport=$3
	local hotplug=${4:-0}
	local tags=""

	case "$transport:$hotplug" in
		*:1)
			tags="${tags} (external)"
			;;
		usb:*|mmc:*|sdio:*|firewire:*)
			tags="${tags} (external)"
			;;
		*)
			if [[ "$removable" == "1" ]]; then
				tags="${tags} (external)"
			fi
			;;
	esac
	if ((size_bytes > large_device_bytes)); then
		tags="${tags} (large device)"
	fi
	printf '%s' "$tags"
}

partition_path() {
	local device=$1
	local number=$2
	if [[ "$device" =~ [0-9]$ ]]; then
		printf '%sp%s\n' "$device" "$number"
	else
		printf '%s%s\n' "$device" "$number"
	fi
}

select_device() {
	local -a menu_items=()
	local path size_bytes removable hotplug type model transport tags description

	while read -r path size_bytes removable hotplug type; do
		[[ "$type" == "disk" ]] || continue
		model=$(lsblk -dn -o MODEL "$path" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
		transport=$(lsblk -dn -o TRAN "$path" | tr -d '[:space:]')
		tags=$(device_tags "$size_bytes" "$removable" "$transport" "$hotplug")
		[[ -n "$model" ]] || model="unknown model"
		description="$(human_size "$size_bytes") ${model}${tags}"
		menu_items+=("$path" "$description")
	done < <(lsblk -bdn -o PATH,SIZE,RM,HOTPLUG,TYPE)

	((${#menu_items[@]} > 0)) || die "no whole block devices were found"
	whiptail --title "qbtOS Imager" \
		--menu "Select the whole block device to overwrite." 22 78 14 \
		"${menu_items[@]}" 3>&1 1>&2 2>&3
}

select_data_size() {
	local maximum_gib=$1
	local default_gib=$maximum_gib
	local answer

	((default_gib > 0)) || default_gib=0
	while true; do
		answer=$(whiptail --title "qbtOS Data Storage" --inputbox \
			"How much free space following the OS do you want?\n\n"\
"Enter an integer size in GiB (maximum ${maximum_gib}). This creates a "\
"separate QBTOS_DATA partition for bootstrap and storage. Enter 0 to use "\
"your own USB or other external data drive." \
			16 78 "$default_gib" 3>&1 1>&2 2>&3) || return 1
		if [[ "$answer" =~ ^[0-9]+$ ]] && ((answer <= maximum_gib)); then
			printf '%s\n' "$answer"
			return 0
		fi
		whiptail --title "Invalid size" --msgbox \
			"Enter a whole number from 0 through ${maximum_gib}." 8 60
	done
}

select_data_filesystem() {
	whiptail --title "qbtOS Data Filesystem" \
		--menu "Choose the filesystem for QBTOS_DATA." 14 74 2 \
		ext4 "Linux native (recommended)" \
		ntfs "Windows compatible (future Windows installer support)" \
		3>&1 1>&2 2>&3
}

mounted_children() {
	local device=$1
	lsblk -nrpo NAME,MOUNTPOINT "$device" | while read -r node mountpoint; do
		[[ -n "${mountpoint:-}" ]] && printf '%s\t%s\n' "$node" "$mountpoint"
	done
}

unmount_children() {
	local device=$1
	local node mountpoint
	while IFS=$'\t' read -r node mountpoint; do
		[[ -n "${node:-}" ]] || continue
		umount "$node" || die "could not unmount ${node} from ${mountpoint}"
	done < <(mounted_children "$device")

	if command -v swapon >/dev/null 2>&1; then
		while read -r node; do
			[[ -n "$node" ]] || continue
			case "$node" in
				"$device"|"$device"[0-9]*|"$device"p[0-9]*)
					swapoff "$node" || die "could not disable swap on ${node}"
					;;
			esac
		done < <(swapon --show=NAME --noheadings 2>/dev/null || true)
	fi
}

confirm_write() {
	local device=$1
	local image=$2
	local data_gib=$3
	local data_filesystem=$4
	local device_summary mounts data_summary

	device_summary=$(lsblk -dn -o PATH,SIZE,MODEL,TRAN,RM "$device")
	mounts=$(mounted_children "$device" || true)
	[[ -n "$mounts" ]] || mounts="none"
	if ((data_gib == 0)); then
		data_summary="No on-device QBTOS_DATA partition will be created."
	else
		data_summary="A ${data_gib} GiB QBTOS_DATA ${data_filesystem} partition will be created."
	fi

	whiptail --title "DESTROY ALL DATA?" --yesno \
		"The selected device and every filesystem on it will be overwritten.\n\n"\
"Device: ${device_summary}\nImage: ${image}\nMounted children:\n${mounts}\n\n"\
"${data_summary}\n\nContinue?" \
		20 78
}

extend_partition_table() {
	local device=$1
	local image_sectors=$2
	local data_sectors=$3
	local sector_size=${4:-512}
	local partition_type=${5:-83}
	local data_start extended_start extended_size

	data_start=$((image_sectors + alignment_bytes / sector_size))
	extended_start=$(sfdisk -d "$device" | \
		awk -F'[,= ]+' '$1 ~ /4$/ { for (i=1; i<=NF; i++) if ($i == "start") { print $(i+1); exit } }')
	[[ "$extended_start" =~ ^[0-9]+$ ]] || die \
		"the flashed image does not contain the expected extended partition"
	extended_size=$((data_start + data_sectors - extended_start))

	printf ',%s,f\n' "$extended_size" | \
		sfdisk --no-reread --no-tell-kernel -N 4 "$device"
	printf ',%s,%s\n' "$data_sectors" "$partition_type" | \
		sfdisk --no-reread --no-tell-kernel --append "$device"
}

refresh_partition_table() {
	local device=$1
	local attempt

	# A desktop automounter can reopen QBTOS_BOOT or QBTOS_STATE as soon as a
	# partition-change event is emitted. Clear those mounts before each retry.
	for attempt in {1..5}; do
		unmount_children "$device"
		if blockdev --rereadpt "$device"; then
			command -v udevadm >/dev/null 2>&1 && udevadm settle || true
			return 0
		fi
		printf 'Partition-table refresh attempt %s failed; retrying...\n' \
			"$attempt" >&2
		sleep 0.5
	done

	# BLKRRPART rejects a busy disk wholesale. BLKPG, used by partx, can update
	# individual partition mappings and is a safe fallback after all filesystems
	# have been unmounted.
	if command -v partx >/dev/null 2>&1; then
		unmount_children "$device"
		if partx --update "$device"; then
			command -v udevadm >/dev/null 2>&1 && udevadm settle || true
			return 0
		fi
	fi

	die "kernel could not refresh ${device}; disconnect and reconnect it, "\
"inspect partition 6 with lsblk, then create QBTOS_DATA manually"
}

cached_image_sha256() {
	local image=$1
	local checksum_file="${image}.sha256"
	local digest remainder
	local -a checksum_lines

	[[ -r "$checksum_file" ]] || return 1
	if [[ "$image" -nt "$checksum_file" ]]; then
		printf 'Ignoring stale checksum cache: %s\n' "$checksum_file" >&2
		return 1
	fi
	mapfile -t checksum_lines < "$checksum_file"
	if ((${#checksum_lines[@]} != 1)); then
		printf 'Ignoring invalid checksum cache: %s\n' "$checksum_file" >&2
		return 1
	fi
	IFS=' ' read -r digest remainder <<< "${checksum_lines[0]}"
	[[ "$digest" =~ ^[[:xdigit:]]{64}$ ]] || {
		printf 'Ignoring invalid checksum cache: %s\n' "$checksum_file" >&2
		return 1
	}
	printf '%s\n' "${digest,,}"
}

verify_written_image() {
	local device=$1
	local image=$2
	local image_bytes=$3
	local expected actual

	if expected=$(cached_image_sha256 "$image"); then
		printf 'Using cached SHA-256 from %s.sha256...\n' "$image"
		actual=$(dd if="$device" bs=4M iflag=count_bytes \
			count="$image_bytes" status=none | sha256sum | awk '{print $1}')
		[[ "$actual" == "$expected" ]] || die \
			"written image checksum mismatch: expected ${expected}, got ${actual}"
	else
		printf '%s\n' "No current checksum cache; using byte comparison..."
		cmp --bytes="$image_bytes" "$image" "$device"
	fi
}

extend_for_data_partition() {
	local device=$1
	local data_gib=$2
	local data_filesystem=$3
	local sector_size image_sectors data_sectors data_device
	local partition_type

	sector_size=$(blockdev --getss "$device")
	[[ "$sector_size" == "512" ]] || die \
		"${device} uses ${sector_size}-byte logical sectors; qbtOS requires 512"
	image_sectors=$(( $(stat -c %s "$image_path") / sector_size ))
	data_sectors=$((data_gib * 1024 * 1024 * 1024 / sector_size))
	case "$data_filesystem" in
		ext4)
			partition_type=83
			;;
		ntfs)
			partition_type=7
			;;
		*)
			die "unsupported data filesystem: ${data_filesystem}"
			;;
	esac
	extend_partition_table "$device" "$image_sectors" "$data_sectors" \
		"$sector_size" "$partition_type"

	refresh_partition_table "$device"
	data_device=$(partition_path "$device" 6)
	for _ in {1..50}; do
		[[ -b "$data_device" ]] && break
		sleep 0.1
	done
	[[ -b "$data_device" ]] || die "partition device did not appear: ${data_device}"
	case "$data_filesystem" in
		ext4)
		mkfs.ext4 -F -m 0 -L QBTOS_DATA "$data_device"
		;;
		ntfs)
		mkfs.ntfs -F -f -L QBTOS_DATA "$data_device"
		;;
	esac
}

main() {
	local selected_device data_gib data_filesystem data_summary
	local device_bytes image_bytes maximum_gib
	local requested_image=
	image_path=
	image_source_path=
	staged_image_path=

	while (($#)); do
		case "$1" in
		--image)
			(($# >= 2)) || die "--image requires a path"
			requested_image=$2
				shift 2
				;;
			-h|--help)
				usage
				return 0
				;;
			*)
				die "unknown option: $1"
				;;
		esac
	done

	for command_name in whiptail lsblk numfmt realpath blockdev dd cmp sha256sum sfdisk \
		awk grep sed stat tr sleep umount sync mktemp rm; do
		require_command "$command_name"
	done
	[[ -t 0 && -t 1 ]] || die "the imager requires an interactive terminal"
	if ((EUID != 0)); then
		require_command sudo
		if [[ -n "$requested_image" ]]; then
			exec sudo -- "${script_dir}/imager.sh" --image "$requested_image"
		else
			exec sudo -- "${script_dir}/imager.sh"
		fi
	fi
	if [[ -z "$requested_image" ]]; then
		requested_image=$(select_image) || {
			printf '%s\n' "Imaging cancelled."
			return 0
		}
	fi
	trap cleanup_staged_image EXIT
	prepare_image "$requested_image"
	validate_image_layout "$image_path"

	selected_device=$(select_device) || {
		printf '%s\n' "Imaging cancelled."
		return 0
	}
	[[ -b "$selected_device" ]] || die "not a block device: ${selected_device}"
	[[ "$(lsblk -dn -o TYPE "$selected_device" | tr -d '[:space:]')" == "disk" ]] || \
		die "select a whole disk, not a partition: ${selected_device}"

	device_bytes=$(blockdev --getsize64 "$selected_device")
	[[ "$(blockdev --getss "$selected_device")" == "512" ]] || die \
		"selected device must use 512-byte logical sectors"
	image_bytes=$(stat -c %s "$image_path")
	((device_bytes >= image_bytes)) || die "selected device is smaller than the image"
	maximum_gib=$(((device_bytes - image_bytes - alignment_bytes) / 1024 / 1024 / 1024))
	((maximum_gib >= 0)) || maximum_gib=0
	data_gib=$(select_data_size "$maximum_gib") || {
		printf '%s\n' "Imaging cancelled."
		return 0
	}
	data_filesystem=none
	if ((data_gib > 0)); then
		data_filesystem=$(select_data_filesystem) || {
			printf '%s\n' "Imaging cancelled."
			return 0
		}
		case "$data_filesystem" in
			ext4)
				require_command mkfs.ext4
				;;
			ntfs)
				require_command mkfs.ntfs
				;;
		esac
	fi
	confirm_write "$selected_device" "$image_source_path" "$data_gib" \
		"$data_filesystem" || {
		printf '%s\n' "Imaging cancelled."
		return 0
	}

	unmount_children "$selected_device"
	printf 'Writing %s to %s...\n' "$image_path" "$selected_device"
	dd if="$image_path" of="$selected_device" bs=4M status=progress conv=fsync
	printf '%s\n' "Verifying the written OS image..."
	verify_written_image "$selected_device" "$image_path" "$image_bytes"
	if ((data_gib > 0)); then
		printf 'Creating %s GiB %s QBTOS_DATA filesystem...\n' \
			"$data_gib" "$data_filesystem"
		extend_for_data_partition "$selected_device" "$data_gib" \
			"$data_filesystem"
	else
		refresh_partition_table "$selected_device"
	fi
	sync

	if ((data_gib > 0)); then
		data_summary="${data_gib} GiB of on-device QBTOS_DATA storage "\
"(${data_filesystem}) was created."
	else
		data_summary="No on-device QBTOS_DATA storage was created."
	fi
	whiptail --title "qbtOS Imager" --msgbox \
		"qbtOS was written successfully to ${selected_device}.\n\n"\
"${data_summary} You may now remove the device safely." \
		12 72
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	main "$@"
fi
