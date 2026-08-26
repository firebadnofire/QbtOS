#!/bin/sh

set -eu

die() {
	printf 'publish-github: %s\n' "$1" >&2
	exit 1
}

: "${GH_KEY:?GH_KEY is required}"
: "${VERSION:?VERSION is required}"
: "${SOURCE_TAG:?SOURCE_TAG is required}"
: "${COMMIT:?COMMIT is required}"

command -v curl >/dev/null 2>&1 || die 'curl is required'
command -v jq >/dev/null 2>&1 || die 'jq is required'
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
dist_dir="${repo_root}/dist"
release_notes="${script_dir}/release-notes.md"
repository="${GITHUB_REPOSITORY:-firebadnofire/qbtos}"
api="https://api.github.com/repos/${repository}"
authorization="Authorization: Bearer ${GH_KEY}"
accept='Accept: application/vnd.github+json'
api_version='X-GitHub-Api-Version: 2022-11-28'
temporary=$(mktemp -d)
trap 'find "$temporary" -type f -delete; rmdir "$temporary"' EXIT HUP INT TERM
response="${temporary}/response.json"
managed_suffixes='img.zst img.zst.asc raucb raucb.asc manifest.json manifest.json.asc sha256 sha256.asc imager-windows-x64.exe imager-windows-x64.exe.asc'

phase() {
	printf 'GitHub mirror: %s...\n' "$1"
}

show_api_error() {
	operation="$1"
	printf 'publish-github: %s failed' "$operation" >&2
	if test -s "$response"; then
		message=$(jq -r '.message // .error // empty' "$response" 2>/dev/null || true)
		if test -n "$message"; then
			printf ': %s' "$message" >&2
		fi
	fi
	printf '\n' >&2
}

github_write() {
	operation="$1"
	shift
	: > "$response"
	if ! curl --silent --show-error --fail-with-body --output "$response" \
		-H "$authorization" -H "$accept" -H "$api_version" "$@"; then
		show_api_error "$operation"
		return 1
	fi
}

test -s "$release_notes" || die 'release notes are missing or empty'
test "$(find "$dist_dir" -maxdepth 1 -type f | wc -l)" -eq 10 || \
	die 'dist must contain exactly ten files'
for suffix in $managed_suffixes; do
	test -s "${dist_dir}/${VERSION}.${suffix}" || \
		die "missing ${VERSION}.${suffix}"
done
jq -n --arg tag "$SOURCE_TAG" --arg name "$VERSION" --arg commit "$COMMIT" \
	--rawfile body "$release_notes" \
	'{tag_name:$tag,target_commitish:$commit,name:$name,body:$body,draft:false,prerelease:false}' \
	> "${temporary}/release.json"

phase "looking up release ${SOURCE_TAG}"
status=$(curl --silent --show-error --output "$response" --write-out '%{http_code}' \
	-H "$authorization" -H "$accept" -H "$api_version" \
	"${api}/releases/tags/${SOURCE_TAG}")
case "$status" in
	200)
		release_id=$(jq -er '.id' "$response")
		phase "reusing release ${SOURCE_TAG}"
		;;
	404)
		phase "creating release ${SOURCE_TAG}"
		github_write 'creating GitHub release' \
			-X POST -H 'Content-Type: application/json' \
			--data-binary "@${temporary}/release.json" "${api}/releases"
		release_id=$(jq -er '.id' "$response")
		;;
	*)
		show_api_error 'looking up GitHub release'
		die "GitHub release lookup returned HTTP ${status}"
		;;
esac

phase 'updating release verification instructions'
github_write 'updating GitHub release metadata' \
	-X PATCH -H 'Content-Type: application/json' \
	--data-binary "@${temporary}/release.json" "${api}/releases/${release_id}"

phase 'reconciling ten release assets'
github_write 'listing GitHub release assets' \
	"${api}/releases/${release_id}/assets?per_page=100"
asset_list="${temporary}/github-assets.json"
cp "$response" "$asset_list"
for suffix in $managed_suffixes; do
	filename="${VERSION}.${suffix}"
	for asset_id in $(jq -r --arg name "$filename" \
		'.[] | select(.name == $name) | .id' "$asset_list"); do
		github_write "removing existing GitHub asset ${filename}" \
			-X DELETE "${api}/releases/assets/${asset_id}"
	done
	github_write "uploading GitHub asset ${filename}" \
		-X POST -H 'Content-Type: application/octet-stream' \
		--data-binary "@${dist_dir}/${filename}" \
		"https://uploads.github.com/repos/${repository}/releases/${release_id}/assets?name=${filename}"
done

printf 'Mirrored GitHub release %s with ten assets\n' "$SOURCE_TAG"
