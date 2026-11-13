#!/usr/bin/env bash

# Verify GitHub Release asset sizes after upload. If the first check fails,
# overwrite the asset once before checking again. Together with the initial
# workflow upload, this caps uploads at two without downloading large assets.

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <tag> <asset> [asset ...]" >&2
  exit 2
fi

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

tag="$1"
shift
attempts=2

get_release_asset_size() {
  local release_tag="$1"
  local name="$2"
  local size

  size=$(gh release view "$release_tag" \
    --repo "$GITHUB_REPOSITORY" \
    --json assets \
    --jq ".assets[] | select(.name == \"${name}\") | .size") || return 1
  [[ "$size" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$size"
}

for asset in "$@"; do
  asset_name=$(basename "$asset")
  expected_size=$(wc -c < "$asset")
  expected_size=${expected_size//[[:space:]]/}
  verified=false

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if [ "$attempt" -gt 1 ]; then
      echo "Retrying GitHub Release upload: $asset_name"
      if ! gh release upload "$tag" "$asset" \
        --repo "$GITHUB_REPOSITORY" \
        --clobber; then
        echo "::warning::GitHub Release retry upload failed: $asset_name"
        continue
      fi
    fi

    echo "GitHub Release size verification attempt ${attempt}/${attempts}: $asset_name"
    remote_size=$(get_release_asset_size "$tag" "$asset_name") || remote_size=""
    if [ "$remote_size" = "$expected_size" ]; then
      echo "Verified GitHub Release asset size: $asset_name (${remote_size} bytes)"
      verified=true
      break
    fi

    echo "::warning::GitHub Release asset size mismatch: $asset_name "\
      "(expected ${expected_size} bytes, got ${remote_size:-unavailable})"
    if [ "$attempt" -lt "$attempts" ]; then
      sleep 10
    fi
  done

  if ! $verified; then
    echo "::error::GitHub Release asset failed size verification: $asset_name"
    exit 1
  fi
done
