#!/usr/bin/env bash
#
# Channel Pre-Commit Check Script
# =================================
#
# Run this script before committing channel changes to catch issues early.
#
# Contract tests are the primary gate (tests/contract/channels/).
# Unit tests are optional supplements (tests/unit/channels/).
#
# Usage:
#   ./scripts/check-channels.sh              # Check all channels
#   ./scripts/check-channels.sh dingtalk     # Check one channel
#   ./scripts/check-channels.sh --changed    # Check changed channels

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="${PYTHON_BIN:-python3}"

TARGET="${1:-all}"
CHECK_CHANGED=0
ALL_CHANGED=""
CHANGED_UNIT_TESTS=""

if [ "$TARGET" = "--changed" ] || [ "$TARGET" = "-c" ]; then
    CHECK_CHANGED=1
    TARGET="changed"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}QwenPaw Channel Pre-Commit Check${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if ! git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo -e "${RED}Error: Not a git repository${NC}"
    exit 1
fi

cd "$PROJECT_ROOT"

if ! command -v "$PYTHON_BIN" &>/dev/null; then
    echo -e "${RED}Error: $PYTHON_BIN not found${NC}"
    exit 1
fi

if ! REGISTRY_SPECS="$(
    "$PYTHON_BIN" scripts/check_channel_contracts.py --list-specs
)"; then
    echo -e "${RED}Error: Could not read the built-in channel registry${NC}"
    exit 1
fi

if [ -z "$REGISTRY_SPECS" ]; then
    echo -e "${RED}Error: The built-in channel registry is empty${NC}"
    exit 1
fi

REGISTRY_KEYS="$(printf '%s\n' "$REGISTRY_SPECS" | cut -f1)"

registry_has_key() {
    local candidate="$1"
    printf '%s\n' "$REGISTRY_KEYS" | grep -Fxq "$candidate"
}

registry_key_for_source_dir() {
    local source_dir="$1"
    printf '%s\n' "$REGISTRY_SPECS" |
        awk -F '\t' -v source_dir="$source_dir" \
            '$2 == source_dir { print $1; exit }'
}

registry_key_for_contract_path() {
    local contract_path="$1"
    printf '%s\n' "$REGISTRY_SPECS" |
        awk -F '\t' -v contract_path="$contract_path" \
            '$3 == contract_path { print $1; exit }'
}

registry_contract_path() {
    local channel_key="$1"
    printf '%s\n' "$REGISTRY_SPECS" |
        awk -F '\t' -v channel_key="$channel_key" \
            '$1 == channel_key { print $3; exit }'
}

if [ "$CHECK_CHANGED" -eq 1 ]; then
    echo -e "${YELLOW}Detecting changed channels...${NC}"

    CHANGED_FILES="$(git diff --name-only HEAD)"
    UNTRACKED_FILES="$(git ls-files --others --exclude-standard)"
    ALL_CHANGED="$(
        printf '%s\n%s\n' "$CHANGED_FILES" "$UNTRACKED_FILES" |
            sort -u
    )"
    CHANGED_UNIT_TESTS="$(
        printf '%s\n' "$ALL_CHANGED" |
            sed -nE '\#^tests/unit/channels/test_.*\.py$#p'
    )"

    if grep -qE '^(src/qwenpaw/app/channels/[^/]+\.py|tests/contract(/channels)?/__init__\.py|tests/(conftest\.py|unit/channels/(conftest|__init__)\.py)|scripts/(check-channels\.sh|check_channel_contracts\.py))$' <<<"$ALL_CHANGED"; then
        echo -e "${YELLOW}BaseChannel or common code changed; testing all channels.${NC}"
        CHANNELS="all"
    else
        SOURCE_DIRS="$(
            printf '%s\n' "$ALL_CHANGED" |
                sed -nE 's#^src/qwenpaw/app/channels/([^/]+)/.*#\1#p' |
                sort -u
        )"
        SOURCE_CHANNELS=""
        for source_dir in $SOURCE_DIRS; do
            source_key="$(registry_key_for_source_dir "$source_dir")"
            if [ -n "$source_key" ]; then
                SOURCE_CHANNELS="$(
                    printf '%s\n%s\n' "$SOURCE_CHANNELS" "$source_key" |
                        sed '/^$/d' |
                        sort -u
                )"
            fi
        done

        CONTRACT_CANDIDATES="$(
            printf '%s\n' "$ALL_CHANGED" |
                sed -nE '\#^tests/contract/channels/test_[^/]+_contract\.py$#p'
        )"
        CONTRACT_CHANNELS=""
        for contract_path in $CONTRACT_CANDIDATES; do
            contract_key="$(registry_key_for_contract_path "$contract_path")"
            if [ -z "$contract_key" ]; then
                echo -e "${RED}Error: Non-canonical channel contract path: $contract_path${NC}"
                exit 1
            fi
            CONTRACT_CHANNELS="$(
                printf '%s\n%s\n' "$CONTRACT_CHANNELS" "$contract_key" |
                    sed '/^$/d' |
                    sort -u
            )"
        done

        UNIT_CHANNELS=""
        for unit_test in $CHANGED_UNIT_TESTS; do
            unit_name="${unit_test##*/}"
            for registry_key in $REGISTRY_KEYS; do
                unit_prefix="test_${registry_key}"
                case "$unit_name" in
                    "$unit_prefix.py"|"$unit_prefix"_*.py)
                        UNIT_CHANNELS="$(
                            printf '%s\n%s\n' "$UNIT_CHANNELS" "$registry_key" |
                                sed '/^$/d' |
                                sort -u
                        )"
                        ;;
                esac
            done
        done

        CHANNELS="$(
            printf '%s\n%s\n%s\n' "$SOURCE_CHANNELS" "$CONTRACT_CHANNELS" "$UNIT_CHANNELS" |
                sed '/^$/d' |
                sort -u
        )"

        if [ -z "$CHANNELS" ] && [ -z "$CHANGED_UNIT_TESTS" ]; then
            echo -e "${GREEN}No channel changes detected.${NC}"
            exit 0
        fi

        if [ -n "$CHANNELS" ]; then
            echo -e "${BLUE}Changed channels: $CHANNELS${NC}"
        fi
        if [ -n "$CHANGED_UNIT_TESTS" ]; then
            echo -e "${BLUE}Changed channel unit tests: $CHANGED_UNIT_TESTS${NC}"
        fi
    fi
elif [ "$TARGET" = "all" ]; then
    CHANNELS="all"
else
    if ! registry_has_key "$TARGET"; then
        echo -e "${RED}Error: Unknown built-in channel: $TARGET${NC}"
        exit 1
    fi
    CHANNELS="$TARGET"
fi

echo ""
echo -e "${BLUE}Setting up Python environment...${NC}"

if ! PROJECT_ROOT="$PROJECT_ROOT" "$PYTHON_BIN" -c '
import os
from pathlib import Path

import pytest  # noqa: F401
import qwenpaw

source_root = (Path(os.environ["PROJECT_ROOT"]) / "src").resolve()
module_path = Path(qwenpaw.__file__).resolve()
raise SystemExit(0 if module_path.is_relative_to(source_root) else 1)
' 2>/dev/null; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    "$PYTHON_BIN" -m pip install -e ".[dev,test,full]" -q
fi

echo ""
echo -e "${BLUE}Running checks...${NC}"

EXIT_CODE=0

if ! "$PYTHON_BIN" scripts/check_channel_contracts.py; then
    EXIT_CODE=1
fi

if [ "$CHANNELS" = "all" ]; then
    echo -e "${YELLOW}Running all channel contract tests (primary)...${NC}"
    if ! "$PYTHON_BIN" -m pytest tests/contract/channels -v --tb=short; then
        EXIT_CODE=1
    fi

    echo ""
    echo -e "${YELLOW}Running optional unit tests (supplemental)...${NC}"
    if ! "$PYTHON_BIN" -m pytest tests/unit/channels -v --tb=short 2>/dev/null; then
        echo -e "${YELLOW}Some optional unit tests failed.${NC}"
    fi
else
    for ch in $CHANNELS; do
        echo ""
        echo -e "${BLUE}----------------------------------------${NC}"
        echo -e "${BLUE}Testing channel: $ch${NC}"
        echo -e "${BLUE}----------------------------------------${NC}"

        CONTRACT_TEST_FILE="$(registry_contract_path "$ch")"
        if [ -f "$CONTRACT_TEST_FILE" ]; then
            echo -e "${GREEN}Contract test found: $CONTRACT_TEST_FILE${NC}"
            if ! "$PYTHON_BIN" -m pytest "$CONTRACT_TEST_FILE" -v --tb=short; then
                echo -e "${RED}Contract tests failed for $ch.${NC}"
                EXIT_CODE=1
            else
                echo -e "${GREEN}Contract tests passed for $ch.${NC}"
            fi
        else
            echo -e "${RED}Contract test missing for $ch.${NC}"
            echo -e "${RED}Required: $CONTRACT_TEST_FILE${NC}"
            echo -e "${YELLOW}Template: tests/contract/channels/test_console_contract.py${NC}"
            EXIT_CODE=1
        fi

    done

    if [ "$CHECK_CHANGED" -eq 1 ] && [ -n "$CHANGED_UNIT_TESTS" ]; then
        echo ""
        echo -e "${BLUE}Running changed optional channel unit tests...${NC}"
        if ! "$PYTHON_BIN" -m pytest $CHANGED_UNIT_TESTS -v --tb=short 2>/dev/null; then
            echo -e "${YELLOW}Some changed optional unit tests failed.${NC}"
        else
            echo -e "${GREEN}Changed optional unit tests passed.${NC}"
        fi
    elif [ "$CHECK_CHANGED" -eq 0 ]; then
        UNIT_TEST_FILES=""
        for ch in $CHANNELS; do
            for unit_test in \
                "tests/unit/channels/test_${ch}.py" \
                tests/unit/channels/test_"${ch}"_*.py; do
                if [ -f "$unit_test" ]; then
                    UNIT_TEST_FILES="$(
                        printf '%s\n%s\n' "$UNIT_TEST_FILES" "$unit_test" |
                            sed '/^$/d' |
                            sort -u
                    )"
                fi
            done
        done
        if [ -n "$UNIT_TEST_FILES" ]; then
            echo ""
            echo -e "${BLUE}Running optional unit tests for $CHANNELS...${NC}"
            if ! "$PYTHON_BIN" -m pytest $UNIT_TEST_FILES -v --tb=short 2>/dev/null; then
                echo -e "${YELLOW}Some optional unit tests failed.${NC}"
            else
                echo -e "${GREEN}Optional unit tests passed.${NC}"
            fi
        fi
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
if [ "$EXIT_CODE" -eq 0 ]; then
    echo -e "${GREEN}All checks passed.${NC}"
    echo -e "${GREEN}You can safely commit your changes.${NC}"
else
    echo -e "${RED}Some checks failed.${NC}"
    echo ""
    echo "Required fixes:"
    echo "  - Create missing contract test: tests/contract/channels/test_<channel>_contract.py"
    echo "  - Ensure the contract test implements create_instance()"
    echo "  - Fix failing contract assertions"
    echo ""
    echo "Unit tests are optional and do not block this script."
fi
echo -e "${BLUE}========================================${NC}"

exit "$EXIT_CODE"
