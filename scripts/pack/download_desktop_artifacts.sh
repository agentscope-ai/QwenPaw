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

artifact_records=""
selected=()
selected_ids=()
archive=$(mktemp)
trap 'rm -f -- "$archive"' EXIT

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
  selected_ids=()

  # Select the newest unexpired artifact per name across all API pages.
  # Break timestamp ties by ID so selection does not depend on API ordering.
  if artifact_records=$(gh api --paginate --method GET \
    "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/artifacts" \
    -f per_page=100 \
    | jq --slurp --raw-output '
        [.[] | .artifacts[] | select(.expired == false)]
        | group_by(.name)[]
        | max_by([.created_at, .id])
        | [.name, .id, .created_at] | @tsv
      '); then
    while IFS=$'\t' read -r name artifact_id created_at; do
      if [[ "$name" =~ ^QwenPaw-Desktop-Tauri-(Windows|macOS)-[a-zA-Z0-9._+-]+$ ]]; then
        selected+=("$name")
        selected_ids+=("$artifact_id")
      elif $include_updater_metadata && \
        [[ "$name" =~ ^tauri-updater-meta-(windows|macos)$ ]]; then
        selected+=("$name")
        selected_ids+=("$artifact_id")
      else
        continue
      fi
      echo "Selected artifact: $name (ID: $artifact_id, created: $created_at)"
    done <<< "$artifact_records"
  else
    echo "::warning::Could not list artifacts for attempt ${attempt}"
  fi

  cleanup_downloads

  download_ok=true
  if [ ${#selected[@]} -eq 0 ]; then
    echo "::warning::No matching desktop artifacts found"
    download_ok=false
  else
    for index in "${!selected[@]}"; do
      name=${selected[$index]}
      artifact_id=${selected_ids[$index]}
      echo "Downloading artifact: $name (ID: $artifact_id)"
      if ! gh api --method GET \
        "repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}/zip" \
        > "$archive"; then
        echo "::warning::Download failed for artifact: $name"
        download_ok=false
        break
      fi
      if ! unzip -q "$archive" -d "$name"; then
        echo "::warning::Extraction failed for artifact: $name"
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
