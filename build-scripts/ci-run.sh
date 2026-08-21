#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
	cat <<'EOF'
Usage: build-scripts/ci-run.sh LOG_FILE COMMAND [ARGUMENT...]

Run a CI command with periodic, secret-safe resource diagnostics while copying
all output to LOG_FILE. QBTOS_CI_HEARTBEAT_SECONDS controls the interval and
defaults to 300 seconds.
EOF
}

die_usage() {
	printf 'ci-run: %s\n\n' "$1" >&2
	usage >&2
	exit 2
}

print_file_if_readable() {
	label="$1"
	path="$2"
	if [[ -r "$path" ]]; then
		printf '%s: ' "$label"
		tr '\n' ' ' < "$path"
		printf '\n'
	fi
}

snapshot() {
	phase="$1"
	printf '\n[qbtOS CI diagnostics: %s]\n' "$phase"
	printf 'utc_time: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
	printf 'elapsed_seconds: %s\n' "$(( $(date +%s) - start_epoch ))"
	printf 'uid_gid: %s\n' "$(id -u):$(id -g)"
	printf 'uname: '
	uname -a
	printf 'machine: '
	uname -m
	if command -v nproc >/dev/null 2>&1; then
		printf 'available_cpus: %s\n' "$(nproc)"
	else
		printf 'available_cpus: %s\n' \
			"$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf unknown)"
	fi
	if [[ -r /proc/meminfo ]]; then
		awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree):/ {
			printf "memory_%s_kib: %s\n", tolower(substr($1, 1, length($1) - 1)), $2
		}' /proc/meminfo
	fi
	print_file_if_readable cgroup_memory_max /sys/fs/cgroup/memory.max
	print_file_if_readable cgroup_memory_current /sys/fs/cgroup/memory.current
	print_file_if_readable cgroup_memory_events /sys/fs/cgroup/memory.events
	print_file_if_readable cgroup_cpu_max /sys/fs/cgroup/cpu.max
	print_file_if_readable cgroup_pids_max /sys/fs/cgroup/pids.max
	print_file_if_readable cgroup_v1_memory_limit \
		/sys/fs/cgroup/memory/memory.limit_in_bytes
	print_file_if_readable cgroup_v1_memory_usage \
		/sys/fs/cgroup/memory/memory.usage_in_bytes
	printf 'filesystem_usage:\n'
	df -hP "$PWD" /tmp 2>&1 | awk '!seen[$0]++'
}

[[ "$#" -ge 2 ]] || die_usage 'a log file and command are required'

log_file="$1"
shift
heartbeat_seconds="${QBTOS_CI_HEARTBEAT_SECONDS:-300}"
[[ "$heartbeat_seconds" =~ ^[1-9][0-9]*$ ]] || die_usage \
	'QBTOS_CI_HEARTBEAT_SECONDS must be a positive integer'
[[ ! -L "$log_file" ]] || die_usage 'refusing to write through a log-file symlink'

install -d -m 0755 "$(dirname -- "$log_file")"
: > "$log_file"
exec > >(tee "$log_file") 2>&1

start_epoch=$(date +%s)
snapshot start
printf 'heartbeat_seconds: %s\n' "$heartbeat_seconds"
printf 'command_started (arguments withheld from diagnostics)\n'

"$@" &
command_pid=$!

heartbeat() {
	while sleep "$heartbeat_seconds"; do
		kill -0 "$command_pid" 2>/dev/null || return 0
		snapshot heartbeat
	done
}

heartbeat &
heartbeat_pid=$!

set +e
wait "$command_pid"
command_status=$?
set -e

kill "$heartbeat_pid" 2>/dev/null || true
wait "$heartbeat_pid" 2>/dev/null || true

if [[ "$command_status" -eq 0 ]]; then
	snapshot success
else
	snapshot failure
fi
printf 'command_exit_status: %s\n' "$command_status"
exit "$command_status"
