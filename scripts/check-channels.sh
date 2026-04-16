#!/bin/bash
#
# Channel Pre-Commit Check Script
# =================================
#
# Run this script before committing channel changes to catch issues early.
#
# Note: Contract tests are the PRIMARY gate (tests/contract/channels/).
#       Unit tests are optional supplements (tests/unit/channels/).
#
# Usage:
#   ./scripts/check-channels.sh              # Check all channels (contract tests)
#   ./scripts/check-channels.sh dingtalk     # Check specific channel
#   ./scripts/check-channels.sh --changed    # Only check changed channels
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse arguments
TARGET="${1:-all}"
CHECK_CHANGED=0

if [ "$TARGET" == "--changed" ] || [ "$TARGET" == "-c" ]; then
    CHECK_CHANGED=1
    TARGET="changed"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}CoPaw Channel Pre-Commit Check${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if we're in a git repo
if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo -e "${RED}Error: Not a git repository${NC}"
    exit 1
fi

cd "$PROJECT_ROOT"

# Determine which channels to test
if [ "$CHECK_CHANGED" -eq 1 ]; then
    echo -e "${YELLOW}Detecting changed channels...${NC}"

    # Get changed channel files
    CHANGED_FILES=$(git diff --name-only HEAD 2>/dev/null || echo "")
    STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

    ALL_CHANGED="$CHANGED_FILES $STAGED_FILES"

    # Check if base.py changed
    if echo "$ALL_CHANGED" | grep -qE "channels/(base|registry|manager|renderer)\.py"; then
        echo -e "${YELLOW}⚠️  BaseChannel or common code changed - running ALL channel tests${NC}"
        CHANNELS="all"
    else
        # Extract modified channels
        CHANNELS=$(echo "$ALL_CHANGED" | grep -oE 'channels/[^/]+' | sed 's/channels\///' | sort -u | grep -v "^$" || true)

        if [ -z "$CHANNELS" ]; then
            echo -e "${GREEN}✅ No channel changes detected${NC}"
            exit 0
        fi

        echo -e "${BLUE}Changed channels: $CHANNELS${NC}"
    fi
elif [ "$TARGET" == "all" ]; then
    CHANNELS="all"
else
    CHANNELS="$TARGET"
fi

# Setup Python environment
echo ""
echo -e "${BLUE}Setting up Python environment...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found${NC}"
    exit 1
fi

# Check if dependencies are installed
if ! python3 -c "import copaw" 2>/dev/null; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -e ".[dev]" -q
fi

# Run tests
echo ""
echo -e "${BLUE}Running tests...${NC}"

EXIT_CODE=0

if [ "$CHANNELS" == "all" ]; then
    # Run ALL contract tests (PRIMARY gate)
    echo -e "${YELLOW}Running ALL channel CONTRACT tests (PRIMARY)...${NC}"

    if ! pytest tests/contract/channels -v --tb=short; then
        EXIT_CODE=1
    fi

    # Run optional unit tests (informational)
    echo ""
    echo -e "${YELLOW}Running optional UNIT tests (supplemental)...${NC}"

    if ! pytest tests/unit/channels -v --tb=short 2>/dev/null; then
        echo -e "${YELLOW}⚠️  Some unit tests failed (optional, does not block PR)${NC}"
    fi
else
    # Run specific channel contract tests
    for ch in $CHANNELS; do
        echo ""
        echo -e "${BLUE}----------------------------------------${NC}"
        echo -e "${BLUE}Testing channel: $ch${NC}"
        echo -e "${BLUE}----------------------------------------${NC}"

        # PRIMARY: Check if contract test file exists
        CONTRACT_TEST_FILE="tests/contract/channels/test_${ch}_contract.py"

        if [ -f "$CONTRACT_TEST_FILE" ]; then
            echo -e "${GREEN}✅ Contract test found: $CONTRACT_TEST_FILE${NC}"

            if ! pytest "$CONTRACT_TEST_FILE" -v --tb=short; then
                echo -e "${RED}❌ Contract tests FAILED for $ch${NC}"
                EXIT_CODE=1
            else
                echo -e "${GREEN}✅ Contract tests PASSED for $ch${NC}"
            fi
        else
            echo -e "${RED}❌ CONTRACT TEST MISSING for $ch${NC}"
            echo -e "${RED}   Required: $CONTRACT_TEST_FILE${NC}"
            echo -e "${YELLOW}   Template: tests/contract/channels/test_console_contract.py${NC}"
            EXIT_CODE=1
        fi

        # OPTIONAL: Check if unit test file exists
        UNIT_TEST_FILE="tests/unit/channels/test_${ch}.py"
        if [ -f "$UNIT_TEST_FILE" ]; then
            echo ""
            echo -e "${BLUE}Running optional unit tests for $ch...${NC}"
            if ! pytest "$UNIT_TEST_FILE" -v --tb=short 2>/dev/null; then
                echo -e "${YELLOW}⚠️  Unit tests failed (optional)${NC}"
            else
                echo -e "${GREEN}✅ Unit tests passed${NC}"
            fi
        fi
    done

    # Run base channel contract tests if base might be affected
    if echo "$ALL_CHANGED" | grep -qE "channels/base\.py"; then
        echo ""
        echo -e "${BLUE}Running BaseChannel contract tests...${NC}"
        if ! pytest tests/contract/channels/ -v --tb=short; then
            EXIT_CODE=1
        fi
    fi
fi

# Summary
echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo -e "${GREEN}You can safely commit your changes.${NC}"
else
    echo -e "${RED}❌ Some checks failed${NC}"
    echo ""
    echo "Required fixes:"
    echo "  - Create missing contract test: tests/contract/channels/test_<channel>_contract.py"
    echo "  - Ensure contract test implements create_instance() method"
    echo "  - Fix failing contract test assertions"
    echo ""
    echo "Note: Unit tests are OPTIONAL and do not block PR merging."
fi
echo -e "${BLUE}========================================${NC}"

exit $EXIT_CODE
