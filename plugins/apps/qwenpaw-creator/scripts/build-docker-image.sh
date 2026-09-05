#!/bin/bash
# Build QwenPaw Creator Docker image.
#
# This script builds a Creator-specific image on top of the official QwenPaw
# image, dramatically reducing build time by reusing:
#   - Python toolchain and system dependencies
#   - Chromium and Playwright runtime
#   - QwenPaw host application and console frontend
#
# The Dockerfile handles Creator UI build internally:
#   Stage 1: creator-ui-builder — builds Creator UI SPA (~3-5 min)
#   Final stage: runtime — adds Creator plugin on official QwenPaw image (~1-2 min)
#
# Total build time: ~5-10 minutes (vs ~15-25 min for full build from scratch)
#
# Usage:
#   ./scripts/build-docker-image.sh [image_name]
#   NO_CACHE=true ./scripts/build-docker-image.sh   # force full rebuild
#
# Examples:
#   ./scripts/build-docker-image.sh                          # qwenpaw-creator:latest
#   ./scripts/build-docker-image.sh my-registry/creator:v1   # custom name/tag
#
# Build args (optional, via environment):
#   QWENPAW_BASE_IMAGE                      - Base QwenPaw image (default: ACR latest)
#   QWENPAW_DISABLED_CHANNELS               - Channels to disable (default: "imessage")
#   QWENPAW_ENABLED_CHANNELS                - Channels whitelist (default: empty)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREATOR_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${CREATOR_DIR}/../../.." && pwd)"

IMAGE_NAME="${1:-qwenpaw-creator:latest}"

# Optional build args.
QWENPAW_BASE_IMAGE="${QWENPAW_BASE_IMAGE:-agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw:latest}"
NODE_IMAGE="${NODE_IMAGE:-agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim}"

# Read version from source for the runtime boundary label.
QWENPAW_VERSION=""
if [ -f "${REPO_ROOT}/src/qwenpaw/__version__.py" ]; then
  QWENPAW_VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
    "${REPO_ROOT}/src/qwenpaw/__version__.py")
fi

echo "=== Building QwenPaw Creator Docker image ==="
echo "Image: ${IMAGE_NAME}"
echo "Base image: ${QWENPAW_BASE_IMAGE}"
echo "Repo root: ${REPO_ROOT}"
if [ -n "${QWENPAW_VERSION}" ]; then
  echo "Version: ${QWENPAW_VERSION}"
fi
echo ""

# Build Docker image.
echo "🐳 Building Docker image: ${IMAGE_NAME}"

# Collect optional build args.
BUILD_ARGS=(
  "--build-arg" "QWENPAW_BASE_IMAGE=${QWENPAW_BASE_IMAGE}"
  "--build-arg" "NODE_IMAGE=${NODE_IMAGE}"
)

if [ -n "${QWENPAW_VERSION}" ]; then
  BUILD_ARGS+=("--build-arg" "QWENPAW_MANAGED_RUNTIME_BOUNDARY_VERSION=${QWENPAW_VERSION}")
fi

if [ -n "${QWENPAW_DISABLED_CHANNELS:-}" ]; then
  BUILD_ARGS+=("--build-arg" "QWENPAW_DISABLED_CHANNELS=${QWENPAW_DISABLED_CHANNELS}")
fi

if [ -n "${QWENPAW_ENABLED_CHANNELS:-}" ]; then
  BUILD_ARGS+=("--build-arg" "QWENPAW_ENABLED_CHANNELS=${QWENPAW_ENABLED_CHANNELS}")
fi

if [ "${NO_CACHE:-}" = "true" ]; then
  BUILD_ARGS+=("--no-cache")
  echo "  (forcing full rebuild with --no-cache)"
fi

docker build \
  "${BUILD_ARGS[@]}" \
  -f "${CREATOR_DIR}/Dockerfile" \
  -t "${IMAGE_NAME}" \
  "${REPO_ROOT}"

echo ""
echo "✅ Docker image built: ${IMAGE_NAME}"
echo ""
echo "Run with:"
echo "  docker run -p 127.0.0.1:8088:8088 ${IMAGE_NAME}"
echo ""
echo "Or with custom port:"
echo "  docker run -p 127.0.0.1:3000:3000 -e QWENPAW_PORT=3000 ${IMAGE_NAME}"
