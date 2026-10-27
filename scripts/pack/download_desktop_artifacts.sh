#!/usr/bin/env bash

# Download desktop artifacts from the current workflow run. Each failed or
# corrupt attempt is removed before retrying so a partial file cannot leak into
# a later publish step.

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
attempts=2
include_updater_metadata=false

while [ $# -gt 0 ]; do
  case "$1" in
    --attempts)
      if [ $# -lt 2 ]; then
        echo "--attempts requires a value (1 or 2)" >&2
        exit 2
      fi
      attempts="$2"
      shift 2
      ;;
    --include-updater-metadata)
      include_updater_metadata=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if ! [[ "$attempts" =~ ^[12]$ ]]; then
  echo "--attempts must be 1 or 2" >&2
  exit 2
fi

: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"

artifact_names=""
selected=()

cleanup_downloads() {
  local name
  if [ ${#selected[@]} -eq 0 ]; then
    return 0
  fi
  for name in "${selected[@]}"; do
    # Names are accepted only after matching one of the fixed prefixes below.
    rm -rf -- "$name"
  done
}

for ((attempt = 1; attempt <= attempts; attempt++)); do
  echo "Desktop artifact download attempt ${attempt}/${attempts}"
  selected=()

  if artifact_names=$(gh api --paginate --method GET \
    "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/artifacts" \
    -f per_page=100 \
    --jq '.artifacts[] | select(.expired == false) | .name'); then
    while IFS= read -r name; do
      if [[ "$name" =~ ^QwenPaw-Desktop-Tauri-(Windows|macOS)- ]]; then
        selected+=("$name")
      elif $include_updater_metadata && \
        [[ "$name" =~ ^tauri-updater-meta-(windows|macos)$ ]]; then
        selected+=("$name")
      fi
    done <<< "$artifact_names"
  else
    echo "::warning::Could not list artifacts for attempt ${attempt}"
  fi

  cleanup_downloads

  download_ok=true
  if [ ${#selected[@]} -eq 0 ]; then
    echo "::warning::No matching desktop artifacts found"
    download_ok=false
  else
    for name in "${selected[@]}"; do
      echo "Downloading artifact: $name"
      if ! gh run download "$GITHUB_RUN_ID" \
        --repo "$GITHUB_REPOSITORY" \
        --name "$name" \
        --dir "$name"; then
        echo "::warning::Download failed for artifact: $name"
        download_ok=false
        break
      fi
    done
  fi

  if $download_ok && python3 "$script_dir/verify_desktop_artifacts.py" \
    --require windows \
    --require macos; then
    echo "Desktop artifacts downloaded and verified"
    exit 0
  fi

  cleanup_downloads
  if [ "$attempt" -lt "$attempts" ]; then
    delay=$((attempt * 10))
    echo "::warning::Desktop artifact verification failed; retrying in ${delay}s"
    sleep "$delay"
  fi
done

echo "::error::Desktop artifacts remained unavailable or corrupt after ${attempts} attempts"
exit 1
