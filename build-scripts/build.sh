#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
	cat <<'EOF'
Usage: build-scripts/build.sh [OPTIONS]

Build a qbtOS Raspberry Pi SD image or QEMU QCOW2 appliance.

Options:
  --format flat|qcow       Image format (default: flat)
  --arch amd64|arm64       QCOW guest architecture (default: build host)
  --size GB                QBTOS_DATA QCOW virtual size in GiB (default: 16)
  --configure-only         Apply the selected checked-in defconfig and stop
  --skip-configure         Build an already configured matching output tree
  -h, --help               Show this help

Environment:
  JOBS                     Parallel build jobs (default: detected CPU count)
  QBTOS_OUTPUT_DIR         Override the selected Buildroot output directory;
                           relative paths resolve from the repository root

Examples:
  build-scripts/build.sh --format flat
  build-scripts/build.sh --format qcow --arch amd64 --size 32
  build-scripts/build.sh --format qcow --arch arm64
EOF
}

die_usage() {
	printf 'Error: %s\n\n' "$1" >&2
	usage >&2
	exit 2
}

require_value() {
	option="$1"
	value="${2:-}"
	[[ -n "$value" ]] || die_usage "${option} requires a value"
}

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
buildroot_dir="${repo_root}/buildroot"
external_dir="${repo_root}/br2-external"
format="flat"
arch=""
data_size_gb="16"
arch_was_set=0
size_was_set=0
configure=1
build=1

while (($#)); do
	case "$1" in
		--format)
			require_value "$1" "${2:-}"
			format="$2"
			shift 2
			;;
		--arch)
			require_value "$1" "${2:-}"
			arch="$2"
			arch_was_set=1
			shift 2
			;;
		--size)
			require_value "$1" "${2:-}"
			data_size_gb="$2"
			size_was_set=1
			shift 2
			;;
		--configure-only)
			build=0
			shift
			;;
		--skip-configure)
			configure=0
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			die_usage "unknown option: $1"
			;;
	esac
done

((configure || build)) || die_usage \
	"--configure-only and --skip-configure cannot be used together"

case "$format" in
	flat)
		((arch_was_set == 0)) || die_usage "--arch is only valid with --format qcow"
		((size_was_set == 0)) || die_usage "--size is only valid with --format qcow"
		arch="arm64"
		defconfig="qbtos_rpi4_defconfig"
		target_name="flat:arm64"
		default_output="${repo_root}/output"
		;;
	qcow)
		if [[ -z "$arch" ]]; then
			case "$(uname -m)" in
				x86_64)
					arch="amd64"
					;;
				aarch64|arm64)
					arch="arm64"
					;;
				*)
					die_usage "cannot infer QCOW architecture on $(uname -m); use --arch"
					;;
			esac
		fi
		case "$arch" in
			amd64|arm64)
				;;
			*)
				die_usage "--arch must be amd64 or arm64"
				;;
		esac
		[[ "$data_size_gb" =~ ^[1-9][0-9]*$ ]] || \
			die_usage "--size must be a positive integer number of GiB"
		defconfig="qbtos_qemu_${arch}_defconfig"
		target_name="qcow:${arch}"
		default_output="${repo_root}/output/qemu-${arch}"
		;;
	*)
		die_usage "--format must be flat or qcow"
		;;
esac

output_dir="${QBTOS_OUTPUT_DIR:-${default_output}}"
if [[ "$output_dir" != /* ]]; then
	output_dir="${repo_root}/${output_dir}"
fi
marker_path="${output_dir}/.qbtos-target"

if [[ ! -f "${buildroot_dir}/Makefile" ]]; then
	printf '%s\n' \
		"Buildroot is missing. Run: git submodule update --init --recursive" >&2
	exit 1
fi
if [[ ! -f "${external_dir}/configs/${defconfig}" ]]; then
	printf 'Missing qbtOS defconfig: %s\n' \
		"${external_dir}/configs/${defconfig}" >&2
	exit 1
fi

if [[ -z "${JOBS:-}" ]]; then
	if command -v nproc >/dev/null 2>&1; then
		JOBS=$(nproc)
	else
		JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1')
	fi
fi
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die_usage \
	"JOBS must be a positive integer, got: ${JOBS}"

# Host paths can contaminate Buildroot configure tests or be rejected outright.
unset LD_LIBRARY_PATH PKG_CONFIG_PATH
export QBTOS_ARCH="$arch"
export QBTOS_DATA_SIZE_GB="$data_size_gb"

buildroot_make=(
	make -C "$buildroot_dir"
	"BR2_EXTERNAL=${external_dir}"
	"O=${output_dir}"
)

if ((configure)); then
	printf 'Configuring qbtOS target %s in %s\n' "$target_name" "$output_dir"
	"${buildroot_make[@]}" "$defconfig"
	printf '%s\n' "$target_name" > "$marker_path"
fi

if ((!build)); then
	printf 'qbtOS configuration written to %s/.config\n' "$output_dir"
	exit 0
fi

if [[ ! -f "${output_dir}/.config" ]]; then
	printf '%s\n' "Build configuration is missing; omit --skip-configure first." >&2
	exit 1
fi
if [[ ! -f "$marker_path" ]] || [[ "$(cat "$marker_path")" != "$target_name" ]]; then
	printf 'Output tree does not match target %s; configure it first.\n' \
		"$target_name" >&2
	exit 1
fi

printf 'Building qbtOS %s with %s parallel job(s)\n' "$target_name" "$JOBS"
"${buildroot_make[@]}" -j"$JOBS"

if [[ "$format" == "flat" ]]; then
	required_images=(
		boot.scr boot.vfat rootfs.squashfs state.ext4 uboot-env.bin sdcard.img
	)
	for artifact in "${required_images[@]}"; do
		[[ -s "${output_dir}/images/${artifact}" ]] || {
			printf 'Expected image artifact is missing or empty: %s\n' \
				"${output_dir}/images/${artifact}" >&2
			exit 1
		}
	done
	[[ "$(stat -c %s "${output_dir}/images/sdcard.img")" -eq $((0x30200000)) ]] || {
		printf 'SD image does not reach its declared partition-table end: %s\n' \
			"${output_dir}/images/sdcard.img" >&2
		exit 1
	}
	artifacts=("${output_dir}/images/sdcard.img")
else
	if [[ "$arch" == "amd64" ]]; then
		kernel_name="bzImage"
	else
		kernel_name="Image"
	fi
	required_images=(
		rootfs.squashfs
		config.ext4
		"$kernel_name"
		"qbtos-${arch}.qcow2"
		"qbtos-data-${arch}.qcow2"
	)
	for artifact in "${required_images[@]}"; do
		[[ -s "${output_dir}/images/${artifact}" ]] || {
			printf 'Expected image artifact is missing or empty: %s\n' \
				"${output_dir}/images/${artifact}" >&2
			exit 1
		}
	done
	qemu_img="${output_dir}/host/bin/qemu-img"
	"$qemu_img" check -q "${output_dir}/images/qbtos-${arch}.qcow2"
	"$qemu_img" check -q "${output_dir}/images/qbtos-data-${arch}.qcow2"
	artifacts=(
		"${output_dir}/images/qbtos-${arch}.qcow2"
		"${output_dir}/images/qbtos-data-${arch}.qcow2"
		"${output_dir}/images/${kernel_name}"
	)
fi

printf '\nqbtOS artifacts:\n'
for artifact in "${artifacts[@]}"; do
	printf '  %s\n' "$artifact"
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$artifact"
	fi
done
