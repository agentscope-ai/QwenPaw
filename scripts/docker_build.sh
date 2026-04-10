#!/usr/bin/env bash
# Build Docker image (includes console frontend build in multi-stage).
# Run from repo root: bash scripts/docker_build.sh [IMAGE_TAG] [EXTRA_ARGS...]
# Example: bash scripts/docker_build.sh qwenpaw:latest
#          bash scripts/docker_build.sh myreg/qwenpaw:v1 --no-cache
#
# By default the Docker image excludes imessage (macOS-only).
# Override via:
#   QWENPAW_DISABLED_CHANNELS=imessage,voice bash scripts/docker_build.sh
#   QWENPAW_ENABLED_CHANNELS=discord,telegram  bash scripts/docker_build.sh
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DOCKERFILE="${DOCKERFILE:-$REPO_ROOT/deploy/Dockerfile}"
TAG="${1:-qwenpaw:latest}"
shift || true

# Channels to exclude from the image (default: imessage).
DISABLED_CHANNELS="${QWENPAW_DISABLED_CHANNELS:-imessage}"

echo "[docker_build] Building image: $TAG (Dockerfile: $DOCKERFILE)"
docker build -f "$DOCKERFILE" \
    --build-arg QWENPAW_DISABLED_CHANNELS="$DISABLED_CHANNELS" \
    ${QWENPAW_ENABLED_CHANNELS:+--build-arg QWENPAW_ENABLED_CHANNELS="$QWENPAW_ENABLED_CHANNELS"} \
    -t "$TAG" "$@" .
echo "[docker_build] Done."
echo "[docker_build] QwenPaw app port: 8088 (default). Override with -e QWENPAW_PORT=<port>."
echo "[docker_build] Run: docker run -p 127.0.0.1:8088:8088 $TAG"
echo "[docker_build] Or:  docker run -e QWENPAW_PORT=3000 -p 127.0.0.1:3000:3000 $TAG"
