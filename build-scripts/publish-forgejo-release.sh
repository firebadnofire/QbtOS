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
api="${FORGEJO_SERVER_URL%/}/api/v1/repos/${FORGEJO_REPOSITORY}"
authorization="Authorization: token ${FORGEJO_TOKEN}"
temporary=$(mktemp -d)
trap 'find "$temporary" -type f -delete; rmdir "$temporary"' EXIT HUP INT TERM

test "$(find "$dist_dir" -maxdepth 1 -type f | wc -l)" -eq 4 || \
	die 'dist must contain exactly four files'
for suffix in img.zst raucb manifest.json sha256; do
	test -s "${dist_dir}/${VERSION}.${suffix}" || \
		die "missing ${VERSION}.${suffix}"
done

response="${temporary}/response.json"
status=$(curl --silent --show-error --output "$response" --write-out '%{http_code}' \
	-H "$authorization" "${api}/releases/tags/${SOURCE_TAG}")
case "$status" in
	200)
		release_id=$(jq -er '.id' "$response")
		curl --silent --show-error --fail --output "$response" \
			-H "$authorization" "${api}/releases/${release_id}/assets"
		for asset_id in $(jq -r '.[].id' "$response"); do
			curl --silent --show-error --fail --output /dev/null \
				-X DELETE -H "$authorization" \
				"${api}/releases/${release_id}/assets/${asset_id}"
		done
		;;
	404)
		jq -n --arg tag "$SOURCE_TAG" --arg name "$VERSION" --arg commit "$COMMIT" \
			'{tag_name:$tag,target_commitish:$commit,name:$name,draft:false,prerelease:false}' \
			> "${temporary}/release.json"
		curl --silent --show-error --fail --output "$response" \
			-X POST -H "$authorization" -H 'Content-Type: application/json' \
			--data-binary "@${temporary}/release.json" "${api}/releases"
		release_id=$(jq -er '.id' "$response")
		;;
	*)
		die "Forgejo release lookup returned HTTP ${status}"
		;;
esac

for suffix in img.zst raucb manifest.json sha256; do
	filename="${VERSION}.${suffix}"
	curl --silent --show-error --fail --output /dev/null \
		-X POST -H "$authorization" -F "attachment=@${dist_dir}/${filename}" \
		"${api}/releases/${release_id}/assets?name=${filename}"
done

# Keep a stable feed URL in a dedicated branch. The automatic workflow token
# suppresses recursive workflow triggers for its own repository writes.
branch_status=$(curl --silent --show-error --output "$response" \
	--write-out '%{http_code}' -H "$authorization" \
	"${api}/branches/update-feed")
case "$branch_status" in
	200) ;;
	404)
		jq -n --arg branch 'update-feed' --arg source "$COMMIT" \
			'{new_branch_name:$branch,old_ref_name:$source}' \
			> "${temporary}/branch.json"
		curl --silent --show-error --fail --output /dev/null \
			-X POST -H "$authorization" -H 'Content-Type: application/json' \
			--data-binary "@${temporary}/branch.json" "${api}/branches"
		;;
	*) die "Forgejo feed-branch lookup returned HTTP ${branch_status}" ;;
esac

content_status=$(curl --silent --show-error --output "$response" \
	--write-out '%{http_code}' -H "$authorization" \
	"${api}/contents/latest.json?ref=update-feed")
encoded=$(base64 -w 0 "${repo_root}/output/latest.json")
case "$content_status" in
	200)
		file_sha=$(jq -er '.sha' "$response")
		jq -n --arg branch update-feed --arg content "$encoded" --arg sha "$file_sha" \
			--arg message "Publish ${VERSION} update feed" \
			'{branch:$branch,content:$content,sha:$sha,message:$message}' \
			> "${temporary}/content.json"
		;;
	404)
		jq -n --arg branch update-feed --arg content "$encoded" \
			--arg message "Publish ${VERSION} update feed" \
			'{branch:$branch,content:$content,message:$message}' \
			> "${temporary}/content.json"
		;;
	*) die "Forgejo feed lookup returned HTTP ${content_status}" ;;
esac
curl --silent --show-error --fail --output /dev/null \
	-X PUT -H "$authorization" -H 'Content-Type: application/json' \
	--data-binary "@${temporary}/content.json" "${api}/contents/latest.json"

printf 'Published Forgejo release and update-feed/latest.json for %s\n' "$VERSION"
