#!/bin/bash
# Start RyPaw Desktop in development mode
# This starts both the Python backend and Electron frontend with hot reload

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Starting RyPaw Desktop (Development Mode) =="
echo "[dev] REPO_ROOT=$REPO_ROOT"

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
  echo "[dev] ERROR: Node.js not found. Please install Node.js first."
  exit 1
fi

# Install Electron dependencies if not already installed
if [ ! -d "$REPO_ROOT/electron/node_modules" ]; then
  echo "[dev] Installing Electron dependencies..."
  cd "$REPO_ROOT/electron"
  npm install
  cd "$REPO_ROOT"
fi

# Set development environment
export NODE_ENV=development
export RYPAW_LOG_LEVEL=${RYPAW_LOG_LEVEL:-debug}

echo "[dev] Starting Electron in development mode..."
echo "[dev] - Python backend: system Python"
echo "[dev] - Frontend: http://localhost:18765"
echo "[dev] - Press Ctrl+C to stop"

cd "$REPO_ROOT/electron"
npm run dev
