#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
	cat <<'EOF'
Usage: build-scripts/run-qemu.sh [OPTIONS]

Run a built qbtOS QCOW appliance with persistent runtime copies.

Options:
  --arch amd64|arm64       Guest architecture (default: host architecture)
  --https-port PORT        Host HTTPS management port (default: 8080)
  --qbittorrent-port PORT  Host qBittorrent Web UI port (default: 8081)
  --bind-address IPV4      Host forward address (default: 127.0.0.1)
  --memory MB              Guest memory in MiB (default: 2048)
  --cpus COUNT             Guest CPU count (default: 2)
  -h, --help               Show this help

Environment:
  QBTOS_OUTPUT_DIR         Override the architecture's Buildroot output tree
  QBTOS_RUNTIME_DIR        Override the persistent QEMU runtime directory
EOF
}

die() {
	printf 'Error: %s\n' "$1" >&2
	exit 2
}

require_value() {
	[[ -n "${2:-}" ]] || die "$1 requires a value"
}

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
arch=""
https_port="8080"
qbittorrent_port="8081"
bind_address="127.0.0.1"
memory_mb="2048"
cpus="2"

while (($#)); do
	case "$1" in
		--arch)
			require_value "$1" "${2:-}"
			arch="$2"
			shift 2
			;;
		--https-port)
			require_value "$1" "${2:-}"
			https_port="$2"
			shift 2
			;;
		--qbittorrent-port)
			require_value "$1" "${2:-}"
			qbittorrent_port="$2"
			shift 2
			;;
		--bind-address)
			require_value "$1" "${2:-}"
			bind_address="$2"
			shift 2
			;;
		--memory)
			require_value "$1" "${2:-}"
			memory_mb="$2"
			shift 2
			;;
		--cpus)
			require_value "$1" "${2:-}"
			cpus="$2"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			die "unknown option: $1"
			;;
	esac
done

if [[ -z "$arch" ]]; then
	case "$(uname -m)" in
		x86_64)
			arch="amd64"
			;;
		aarch64|arm64)
			arch="arm64"
			;;
		*)
			die "cannot infer guest architecture on $(uname -m); use --arch"
			;;
	esac
fi
case "$arch" in
	amd64|arm64)
		;;
	*)
		die "--arch must be amd64 or arm64"
		;;
esac
for value_name in https_port qbittorrent_port; do
	value="${!value_name}"
	if [[ ! "$value" =~ ^[1-9][0-9]*$ ]] || ((value > 65535)); then
		die "${value_name//_/-} must be between 1 and 65535"
	fi
done
[[ "$https_port" != "$qbittorrent_port" ]] || die "forwarded ports must differ"
IFS=. read -r address_a address_b address_c address_d remainder <<< "$bind_address"
[[ -z "${remainder:-}" ]] || die "bind-address must be an IPv4 address"
for octet in "$address_a" "$address_b" "$address_c" "$address_d"; do
	if [[ ! "$octet" =~ ^[0-9]{1,3}$ ]] || ((10#$octet > 255)); then
		die "bind-address must be an IPv4 address"
	fi
done
[[ "$memory_mb" =~ ^[1-9][0-9]*$ ]] || die "--memory must be a positive integer"
[[ "$cpus" =~ ^[1-9][0-9]*$ ]] || die "--cpus must be a positive integer"

output_dir="${QBTOS_OUTPUT_DIR:-${repo_root}/output/qemu-${arch}}"
runtime_dir="${QBTOS_RUNTIME_DIR:-${repo_root}/runtime/qemu/${arch}}"
if [[ "$output_dir" != /* ]]; then
	output_dir="${repo_root}/${output_dir}"
fi
if [[ "$runtime_dir" != /* ]]; then
	runtime_dir="${repo_root}/${runtime_dir}"
fi

images_dir="${output_dir}/images"
base_system="${images_dir}/qbtos-${arch}.qcow2"
base_data="${images_dir}/qbtos-data-${arch}.qcow2"
instance_system="${runtime_dir}/qbtos-system.qcow2"
instance_data="${runtime_dir}/qbtos-data.qcow2"
qemu_img="${output_dir}/host/bin/qemu-img"

if [[ "$arch" == "amd64" ]]; then
	kernel="${images_dir}/bzImage"
	qemu="${output_dir}/host/bin/qemu-system-x86_64"
else
	kernel="${images_dir}/Image"
	qemu="${output_dir}/host/bin/qemu-system-aarch64"
fi
for artifact in "$base_system" "$base_data" "$kernel" "$qemu_img" "$qemu"; do
	[[ -s "$artifact" ]] || die "required QEMU artifact is missing: $artifact"
done

install -d -m 0700 "$runtime_dir"
if [[ ! -f "$instance_system" ]]; then
	printf 'Creating persistent system instance: %s\n' "$instance_system"
	"$qemu_img" convert -f qcow2 -O qcow2 "$base_system" "$instance_system"
fi
if [[ ! -f "$instance_data" ]]; then
	printf 'Creating persistent data instance: %s\n' "$instance_data"
	"$qemu_img" convert -f qcow2 -O qcow2 "$base_data" "$instance_data"
fi

acceleration=()
case "$(uname -m):${arch}" in
	x86_64:amd64|aarch64:arm64|arm64:arm64)
		if [[ -r /dev/kvm && -w /dev/kvm ]]; then
			acceleration=(-enable-kvm -cpu host)
		fi
		;;
esac
if ((${#acceleration[@]} == 0)); then
	if [[ "$arch" == "arm64" ]]; then
		acceleration=(-cpu cortex-a53)
	else
		acceleration=(-cpu max)
	fi
fi

network=(
	-netdev "user,id=net0,hostfwd=tcp:${bind_address}:${https_port}-:8080,hostfwd=tcp:${bind_address}:${qbittorrent_port}-:8081"
)
common=(
	-m "$memory_mb"
	-smp "$cpus"
	-nographic
	-rtc "base=utc,clock=host"
	-object "rng-random,filename=/dev/urandom,id=rng0"
)

printf 'qbtOS management UI: https://%s:%s\n' "$bind_address" "$https_port"
printf 'The self-signed certificate warning is expected.\n'
printf 'Persistent runtime state: %s\n' "$runtime_dir"

if [[ "$arch" == "amd64" ]]; then
	exec "$qemu" \
		-machine pc \
		"${acceleration[@]}" \
		"${common[@]}" \
		-kernel "$kernel" \
		-append 'root=PARTUUID=00000000-01 rootfstype=squashfs ro rootwait console=ttyS0,115200n8' \
		-drive "file=${instance_system},if=virtio,format=qcow2" \
		-drive "file=${instance_data},if=virtio,format=qcow2" \
		"${network[@]}" \
		-device virtio-net-pci,netdev=net0 \
		-device virtio-rng-pci,rng=rng0
else
	exec "$qemu" \
		-machine virt \
		"${acceleration[@]}" \
		"${common[@]}" \
		-kernel "$kernel" \
		-append 'root=PARTUUID=00000000-01 rootfstype=squashfs ro rootwait console=ttyAMA0,115200n8' \
		-drive "file=${instance_system},if=none,format=qcow2,id=system" \
		-device virtio-blk-device,drive=system \
		-drive "file=${instance_data},if=none,format=qcow2,id=data" \
		-device virtio-blk-device,drive=data \
		"${network[@]}" \
		-device virtio-net-device,netdev=net0 \
		-device virtio-rng-device,rng=rng0
fi
