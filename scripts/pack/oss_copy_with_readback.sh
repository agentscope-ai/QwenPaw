#!/usr/bin/env bash

# Upload or copy one OSS object, then verify its remote Content-Length.

set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 <local-or-oss-source> <oss-destination>" >&2
  exit 2
fi

source_path="$1"
destination="$2"
attempts=2

get_oss_size() {
  local object="$1"
  local output
  local size

  output=$(ossutil stat "$object") || return 1
  size=$(awk -F ':' '
    /^[[:space:]]*Content-Length[[:space:]]*:/ {
      gsub(/[[:space:]]/, "", $2)
      print $2
      exit
    }
  ' <<< "$output")
  [[ "$size" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$size"
}

if [[ "$source_path" == oss://* ]]; then
  expected_size=$(get_oss_size "$source_path") || {
    echo "::error::Could not read source OSS object size: $source_path"
    exit 1
  }
else
  expected_size=$(wc -c < "$source_path")
  expected_size=${expected_size//[[:space:]]/}
fi

for ((attempt = 1; attempt <= attempts; attempt++)); do
  echo "OSS upload/copy and size verification attempt ${attempt}/${attempts}: $destination"

  if ossutil cp "$source_path" "$destination" --acl public-read --force; then
    remote_size=$(get_oss_size "$destination") || remote_size=""
    if [ "$remote_size" = "$expected_size" ]; then
      echo "Verified OSS object size: $destination (${remote_size} bytes)"
      exit 0
    fi
  fi

  echo "::warning::OSS object size mismatch: $destination "\
    "(expected ${expected_size} bytes, got ${remote_size:-unavailable})"
  if [ "$attempt" -lt "$attempts" ]; then
    sleep 10
  fi
done

echo "::error::OSS object failed size verification after ${attempts} attempts: $destination"
exit 1
