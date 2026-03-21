#!/bin/bash
# Quick development mode: Start Python backend and Electron frontend
# No packaging required, uses system Python and existing console build

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=================================="
echo "  RyPaw Desktop - Dev Mode"
echo "=================================="
echo "[dev] Repo: $REPO_ROOT"
echo ""

# Check prerequisites
echo "[1/5] Checking prerequisites..."

if ! command -v node &> /dev/null; then
  echo "❌ Node.js not found. Please install Node.js 18+"
  exit 1
fi
echo "✓ Node.js: $(node --version)"

if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
  echo "❌ Python not found. Please install Python 3.10+"
  exit 1
fi
PYTHON_CMD=$(command -v python3 || command -v python)
echo "✓ Python: $($PYTHON_CMD --version)"

# Set PYTHONPATH to use local rypaw module
export PYTHONPATH="$REPO_ROOT/src:$PYTHONPATH"
echo "✓ PYTHONPATH: $PYTHONPATH"

# Verify rypaw can be imported
if ! $PYTHON_CMD -c "import rypaw" 2>/dev/null; then
  echo ""
  echo "❌ rypaw module not found in PYTHONPATH"
  echo "   Installing rypaw in editable mode with dependencies..."
  $PYTHON_CMD -m pip install -e "$REPO_ROOT[full]" --quiet
  if [ $? -ne 0 ]; then
    echo "❌ Failed to install rypaw"
    exit 1
  fi
  echo "✓ rypaw installed in editable mode"
fi

# Verify critical dependencies
echo ""
echo "Checking dependencies..."
MISSING_DEPS=0
for dep in agentscope transformers; do
  if ! $PYTHON_CMD -c "import $dep" 2>/dev/null; then
    echo "  ❌ $dep not found"
    MISSING_DEPS=1
  fi
done

if [ $MISSING_DEPS -eq 1 ]; then
  echo ""
  echo "❌ Missing critical dependencies. Installing now..."
  $PYTHON_CMD -m pip install -e "$REPO_ROOT[full]"
  if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies"
    exit 1
  fi
  echo "✓ Dependencies installed"
else
  echo "✓ All critical dependencies present"
fi

# Check console build
if [ ! -d "$REPO_ROOT/console/dist" ]; then
  echo ""
  echo "❌ Console not built. Building now..."
  cd "$REPO_ROOT/console"
  npm install
  npm run build
  cd "$REPO_ROOT"
  echo "✓ Console built"
else
  echo "✓ Console build exists"
fi

# Install Electron dependencies
echo ""
echo "[2/5] Installing Electron dependencies..."
cd "$REPO_ROOT/electron"
if [ ! -d "node_modules" ]; then
  npm install
  echo "✓ Electron dependencies installed"
else
  echo "✓ Electron dependencies already installed"
fi
cd "$REPO_ROOT"

# Set environment
export NODE_ENV=development
export RYPAW_LOG_LEVEL=${RYPAW_LOG_LEVEL:-info}

echo ""
echo "[3/5] Configuration:"
echo "  - Node env: $NODE_ENV"
echo "  - Log level: $RYPAW_LOG_LEVEL"
echo "  - Backend: Electron will start Python backend on port 18765"
echo "  - Frontend: http://localhost:18765"

# Note: Electron will start the Python backend via main.js
# We don't start it here to avoid conflicts
PYTHON_PID=""
cleanup() {
  if [ -n "$PYTHON_PID" ]; then
    echo ""
    echo "[dev] Stopping Python backend (PID: $PYTHON_PID)..."
    kill $PYTHON_PID 2>/dev/null || true
  fi
  # Kill any other rypaw processes on port 18765
  pkill -f "rypaw.*18765" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "[4/5] Starting Electron (will also start Python backend)..."
echo "=================================="
cd "$REPO_ROOT/electron"
npm run dev
