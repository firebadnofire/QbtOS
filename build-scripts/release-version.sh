#!/bin/sh

set -eu

die() {
	printf 'release-version: %s\n' "$1" >&2
	exit 1
}

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die 'not in a Git repository'

tags=$(git tag --merged HEAD)
invalid=$(printf '%s\n' "$tags" | awk '
	/^revsion-/ { print; next }
	/^revision-/ && $0 !~ /^revision-[1-9][0-9]*$/ { print }
')
test -z "$invalid" || die "invalid reachable revision tag: $(printf '%s\n' "$invalid" | head -n 1)"

revision=$(printf '%s\n' "$tags" | awk '
	/^revision-[1-9][0-9]*$/ {
		value = substr($0, 10) + 0
		if (value > highest) highest = value
	}
	END { if (highest > 0) print highest }
')
test -n "$revision" || die 'no reachable revision-N tag found'

build_date=$(TZ=America/New_York date '+%Y-%m-%d')
source_tag="revision-${revision}"
commit=$(git rev-parse HEAD)
version="${build_date}-rev${revision}"

printf "BUILD_DATE='%s'\n" "$build_date"
printf "REVISION='%s'\n" "$revision"
printf "VERSION='%s'\n" "$version"
printf "SOURCE_TAG='%s'\n" "$source_tag"
printf "COMMIT='%s'\n" "$commit"
