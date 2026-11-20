#!/usr/bin/env bash
# Check built-in console contracts and official channel plugin unit tests.
# Usage: ./scripts/check-channels.sh [all|<channel>|--changed|-c]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TARGET="${1:-all}"
cd "$PROJECT_ROOT"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Error: $PYTHON_BIN not found" >&2
    exit 1
fi

# Only built-ins use the BaseChannel contract. Official plugins declare
# their channel keys in manifests and exercise the driver API in unit tests.
REGISTRY_SPECS="$("$PYTHON_BIN" scripts/check_channel_contracts.py --list-specs)"
PLUGIN_SPECS="$("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

for manifest in sorted(Path("plugins/channel").glob("*/channel.json")):
    key = json.loads(manifest.read_text(encoding="utf-8"))["channel_key"]
    print(f"{key}\t{manifest.parent.as_posix()}\ttests/unit/channels/test_{key}.py")
PY
)"
SPECS="$(
    while IFS=$'\t' read -r key source_dir contract; do
        [ -n "$key" ] && printf '%s\tsrc/qwenpaw/app/channels/%s\t%s\n' "$key" "$source_dir" "$contract"
    done <<<"$REGISTRY_SPECS"
    printf '%s\n' "$PLUGIN_SPECS"
)"
TEST_FILES=""

if [ "$TARGET" = "--changed" ] || [ "$TARGET" = "-c" ]; then
    CHANGED_FILES="$(git diff --name-only HEAD)"
    UNTRACKED_FILES="$(git ls-files --others --exclude-standard)"
    CHANGED_FILES+=$'\n'"$UNTRACKED_FILES"
    # Validate paths before shared changes can select the full suite.
    while IFS= read -r changed; do
        case "$changed" in
            plugins/channel/*/channel.json|tests/unit/channels/test_*.py|tests/unit/plugins/test_plugin_process.py|tests/contract/channels/test_*.py)
                if [ ! -f "$changed" ]; then
                    echo "Error: Missing channel check path: $changed" >&2
                    exit 1
                fi
                ;;
        esac
        case "$changed" in
            tests/contract/channels/test_*.py)
                if ! printf '%s\n' "$REGISTRY_SPECS" |
                    awk -F '\t' -v path="$changed" '
                        $3 == path { found = 1 }
                        END { exit !found }
                    '; then
                    echo "Error: Non-canonical channel contract path: $changed" >&2
                    exit 1
                fi
                ;;
        esac
    done <<<"$CHANGED_FILES"
    # Shared protocol, execution, host and test helpers affect every driver.
    if grep -qE '^(src/qwenpaw/(channel_protocol/|plugins/(execution/|(channel_[^/]+|_?channels|official_channels|official_channel_catalog|official_execution_context|execution_backend)\.py$)|config/channel_config_compat\.py$|app/channels/[^/]+\.py$)|tests/(channel_support/|conftest\.py$|unit/channels/(conftest|__init__)\.py$|contract(/channels)?/__init__\.py$)|scripts/(check-channels\.sh|check_channel_contracts\.py)$)' <<<"$CHANGED_FILES"; then
        TARGET="all"
    else
        while IFS= read -r changed; do
            while IFS=$'\t' read -r key source_dir test_file; do
                case "$changed" in
                    "$source_dir"/*|"$test_file")
                        TEST_FILES+="$test_file"$'\n'
                        ;;
                esac
            done <<<"$SPECS"
            case "$changed" in
                tests/unit/channels/test_*.py|tests/unit/plugins/test_plugin_process.py)
                    TEST_FILES+="$changed"$'\n'
                    ;;
            esac
        done <<<"$CHANGED_FILES"
        if [ -z "$TEST_FILES" ]; then
            echo "No channel changes detected."
            exit 0
        fi
    fi
elif [ "$TARGET" != "all" ]; then
    TEST_FILES="$(printf '%s\n' "$SPECS" | awk -F '\t' -v key="$TARGET" '$1 == key { print $3 }')"
    if [ -z "$TEST_FILES" ]; then
        echo "Error: Unknown channel: $TARGET" >&2
        exit 1
    fi
fi

if [ "$TARGET" = "all" ]; then
    TEST_FILES=$'tests/contract/channels\ntests/unit/channels\ntests/unit/plugins/test_plugin_process.py'
fi

if ! PROJECT_ROOT="$PROJECT_ROOT" "$PYTHON_BIN" -c '
import os
from pathlib import Path

import pytest
import qwenpaw

source_root = (Path(os.environ["PROJECT_ROOT"]) / "src").resolve()
module_path = Path(qwenpaw.__file__).resolve()
raise SystemExit(0 if module_path.is_relative_to(source_root) else 1)
'; then
    echo "Installing dependencies..."
    "$PYTHON_BIN" -m pip install -e ".[dev,test,full]" -q
fi

EXIT_CODE=0
if ! "$PYTHON_BIN" scripts/check_channel_contracts.py; then
    EXIT_CODE=1
fi

# Keep paths as array entries and propagate every pytest failure with logs.
TEST_ARGS=()
while IFS= read -r test_file; do
    [ -z "$test_file" ] || TEST_ARGS+=("$test_file")
done < <(printf '%s\n' "$TEST_FILES" | sort -u)
if ! "$PYTHON_BIN" -m pytest "${TEST_ARGS[@]}" -v --tb=short; then
    EXIT_CODE=1
fi

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "All channel checks passed."
else
    echo "Channel checks failed." >&2
fi
exit "$EXIT_CODE"
