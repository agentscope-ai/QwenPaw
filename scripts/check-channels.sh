#!/bin/bash
#
# Channel Pre-Commit Check Script
# =================================
#
# Run this script before committing channel changes to catch issues early.
#
# Usage:
#   ./scripts/check-channels.sh              # Check all channels
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
    # Run all channel tests
    echo -e "${YELLOW}Running ALL channel tests...${NC}"

    if ! pytest tests/unit/channels -v --tb=short; then
        EXIT_CODE=1
    fi

    # Run coverage check
    echo ""
    echo -e "${YELLOW}Running coverage check...${NC}"

    if ! pytest tests/unit/channels -v --cov=src/copaw/app/channels --cov-report=term-missing --cov-fail-under=60 2>/dev/null; then
        echo -e "${RED}❌ Coverage check FAILED (need 60%)${NC}"
        EXIT_CODE=1
    else
        echo -e "${GREEN}✅ Coverage check passed${NC}"
    fi
else
    # Run specific channel tests
    for ch in $CHANNELS; do
        echo ""
        echo -e "${BLUE}----------------------------------------${NC}"
        echo -e "${BLUE}Testing channel: $ch${NC}"
        echo -e "${BLUE}----------------------------------------${NC}"

        # Check if test file exists
        TEST_FILE="tests/unit/channels/test_${ch}_channel.py"

        if [ -f "$TEST_FILE" ]; then
            if ! pytest "$TEST_FILE" -v --tb=short; then
                echo -e "${RED}❌ Tests failed for $ch${NC}"
                EXIT_CODE=1
            else
                echo -e "${GREEN}✅ Tests passed for $ch${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  No test file found for $ch ($TEST_FILE)${NC}"
            echo -e "${YELLOW}   Please create tests using test_console_channel.py as a template${NC}"
            EXIT_CODE=1
        fi

        # Check if channel has required methods
        echo ""
        echo -e "${BLUE}Checking contract compliance for $ch...${NC}"

        python3 << EOF
import sys
import importlib.util
from pathlib import Path

channel = "$ch"
channel_dir = Path("src/copaw/app/channels") / channel
channel_file = channel_dir / "channel.py"

if not channel_file.exists():
    print(f"⚠️  Channel file not found: {channel_file}")
    sys.exit(0)

try:
    spec = importlib.util.spec_from_file_location(f"{channel}.channel", channel_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Find channel class
    channel_class = None
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and name.lower().endswith('channel') and name != 'BaseChannel':
            channel_class = obj
            break

    if channel_class is None:
        print(f"❌ No channel class found in {channel}")
        sys.exit(1)

    # Check required methods
    required = ['from_env', 'from_config', 'send', 'start', 'stop', 'build_agent_request_from_native']
    missing = [m for m in required if not hasattr(channel_class, m)]

    if missing:
        print(f"❌ Missing required methods: {', '.join(missing)}")
        sys.exit(1)
    else:
        print(f"✅ All required methods present")

except Exception as e:
    print(f"❌ Error loading channel: {e}")
    sys.exit(1)
EOF

        if [ $? -ne 0 ]; then
            EXIT_CODE=1
        fi
    done

    # Run base channel tests if base might be affected
    echo ""
    echo -e "${BLUE}Running BaseChannel contract tests...${NC}"
    if ! pytest tests/unit/channels/test_base_channel.py -v --tb=short; then
        EXIT_CODE=1
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
    echo "Please fix the issues above before committing."
    echo ""
    echo "Common fixes:"
    echo "  - Add missing tests for your channel"
    echo "  - Ensure all required methods are implemented"
    echo "  - Fix failing test assertions"
fi
echo -e "${BLUE}========================================${NC}"

exit $EXIT_CODE
