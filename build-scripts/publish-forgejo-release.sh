#!/bin/sh

set -eu

die() {
	printf 'publish-release: %s\n' "$1" >&2
	exit 1
}

: "${FORGEJO_SERVER_URL:?FORGEJO_SERVER_URL is required}"
: "${FORGEJO_REPOSITORY:?FORGEJO_REPOSITORY is required}"
: "${FORGEJO_TOKEN:?FORGEJO_TOKEN is required}"
: "${VERSION:?VERSION is required}"
: "${SOURCE_TAG:?SOURCE_TAG is required}"
: "${COMMIT:?COMMIT is required}"

command -v curl >/dev/null 2>&1 || die 'curl is required'
command -v jq >/dev/null 2>&1 || die 'jq is required'
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH='' cd -- "${script_dir}/.." && pwd)
dist_dir="${repo_root}/dist"
release_notes="${script_dir}/release-notes.md"
api="${FORGEJO_SERVER_URL%/}/api/v1/repos/${FORGEJO_REPOSITORY}"
authorization="Authorization: token ${FORGEJO_TOKEN}"
temporary=$(mktemp -d)
trap 'find "$temporary" -type f -delete; rmdir "$temporary"' EXIT HUP INT TERM
response="${temporary}/response.json"
managed_suffixes='img.zst img.zst.asc raucb raucb.asc manifest.json manifest.json.asc sha256 sha256.asc'

phase() {
	printf 'Forgejo: %s...\n' "$1"
}

show_api_error() {
	operation="$1"
	printf 'publish-release: %s failed' "$operation" >&2
	if test -s "$response"; then
		message=$(jq -r '.message // .error // empty' "$response" 2>/dev/null || true)
		if test -n "$message"; then
			printf ': %s' "$message" >&2
		fi
	fi
	printf '\n' >&2
}

api_write() {
	operation="$1"
	shift
	: > "$response"
	if ! curl --silent --show-error --fail-with-body --output "$response" \
		-H "$authorization" "$@"; then
		show_api_error "$operation"
		return 1
	fi
}

test -s "$release_notes" || die 'release notes are missing or empty'
test "$(find "$dist_dir" -maxdepth 1 -type f | wc -l)" -eq 8 || \
	die 'dist must contain exactly eight files'
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
	-H "$authorization" "${api}/releases/tags/${SOURCE_TAG}")
case "$status" in
	200)
		release_id=$(jq -er '.id' "$response")
		phase "reusing release ${SOURCE_TAG}"
		api_write 'listing existing Forgejo assets' \
			"${api}/releases/${release_id}/assets"
		asset_list="${temporary}/forgejo-assets.json"
		cp "$response" "$asset_list"
		;;
	404)
		phase "creating release ${SOURCE_TAG}"
		api_write 'creating Forgejo release' \
			-X POST -H 'Content-Type: application/json' \
			--data-binary "@${temporary}/release.json" "${api}/releases"
		release_id=$(jq -er '.id' "$response")
		;;
	*)
		show_api_error 'looking up Forgejo release'
		die "Forgejo release lookup returned HTTP ${status}"
		;;
esac

phase 'updating release verification instructions'
api_write 'updating Forgejo release metadata' \
	-X PATCH -H 'Content-Type: application/json' \
	--data-binary "@${temporary}/release.json" "${api}/releases/${release_id}"

if test -n "${asset_list:-}"; then
	phase 'removing existing managed assets'
	for suffix in $managed_suffixes; do
		filename="${VERSION}.${suffix}"
		for asset_id in $(jq -r --arg name "$filename" \
			'.[] | select(.name == $name) | .id' "$asset_list"); do
			api_write "removing existing Forgejo asset ${filename}" \
				-X DELETE "${api}/releases/${release_id}/assets/${asset_id}"
		done
	done
fi

phase 'uploading eight release assets'
for suffix in $managed_suffixes; do
	filename="${VERSION}.${suffix}"
	api_write "uploading Forgejo asset ${filename}" \
		-X POST -F "attachment=@${dist_dir}/${filename}" \
		"${api}/releases/${release_id}/assets?name=${filename}"
done

# Keep a stable feed URL in a dedicated branch. The automatic workflow token
# suppresses recursive workflow triggers for its own repository writes.
phase 'checking update-feed branch'
branch_status=$(curl --silent --show-error --output "$response" \
	--write-out '%{http_code}' -H "$authorization" \
	"${api}/branches/update-feed")
case "$branch_status" in
	200) ;;
	404)
		phase 'creating update-feed branch from main'
		jq -n --arg branch 'update-feed' --arg source 'main' \
			'{new_branch_name:$branch,old_ref_name:$source}' \
			> "${temporary}/branch.json"
		api_write 'creating Forgejo update-feed branch' \
			-X POST -H 'Content-Type: application/json' \
			--data-binary "@${temporary}/branch.json" "${api}/branches"
		;;
	*)
		show_api_error 'looking up Forgejo update-feed branch'
		die "Forgejo feed-branch lookup returned HTTP ${branch_status}"
		;;
esac

phase 'publishing update-feed/latest.json'
content_status=$(curl --silent --show-error --output "$response" \
	--write-out '%{http_code}' -H "$authorization" \
	"${api}/contents/latest.json?ref=update-feed")
encoded=$(base64 -w 0 "${repo_root}/output/latest.json")
case "$content_status" in
	200)
		content_method=PUT
		file_sha=$(jq -er '.sha' "$response")
		jq -n --arg branch update-feed --arg content "$encoded" --arg sha "$file_sha" \
			--arg message "Publish ${VERSION} update feed" \
			'{branch:$branch,content:$content,sha:$sha,message:$message}' \
			> "${temporary}/content.json"
		;;
	404)
		content_method=POST
		jq -n --arg branch update-feed --arg content "$encoded" \
			--arg message "Publish ${VERSION} update feed" \
			'{branch:$branch,content:$content,message:$message}' \
			> "${temporary}/content.json"
		;;
	*)
		show_api_error 'looking up Forgejo latest.json'
		die "Forgejo feed lookup returned HTTP ${content_status}"
		;;
esac
api_write 'publishing Forgejo latest.json' \
	-X "$content_method" -H 'Content-Type: application/json' \
	--data-binary "@${temporary}/content.json" "${api}/contents/latest.json"

printf 'Published Forgejo release and update-feed/latest.json for %s\n' "$VERSION"
