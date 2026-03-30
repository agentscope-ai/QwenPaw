#!/usr/bin/env bash
# Build CoPaw Docker image locally and push to Docker Hub.
#
# Usage:
#   bash scripts/docker_push_hub.sh [VERSION] [--no-latest]
#
# Examples:
#   bash scripts/docker_push_hub.sh v1.2.3
#   bash scripts/docker_push_hub.sh v1.2.3-beta.1 --no-latest
#   bash scripts/docker_push_hub.sh            # defaults to "dev"
#
# Credentials (never hard-code in this file; set in your shell or a .env):
#   export DOCKER_USERNAME=music1913
#   export DOCKER_PASSWORD=<your-password>
#
# Or create a .env file at the repo root (it is git-ignored):
#   echo "DOCKER_USERNAME=music1913"  >> .env
#   echo "DOCKER_PASSWORD=<password>" >> .env
# then run:
#   set -o allexport && source .env && set +o allexport
#   bash scripts/docker_push_hub.sh v1.2.3
#
# Proxy support:
#   The script automatically forwards http_proxy / https_proxy / no_proxy (and
#   their uppercase variants) into the Docker build so that apt-get, pip, npm,
#   etc. inside the image can reach the internet through your proxy.
#   Just make sure the vars are set before calling this script, e.g.:
#     export http_proxy=http://172.22.208.1:7890
#     export https_proxy=http://172.22.208.1:7890
#
#   NOTE: Do NOT run with plain `sudo` — sudo strips env vars including proxy
#   settings. Either run as your normal user (add yourself to the docker group:
#     sudo usermod -aG docker $USER && newgrp docker
#   ) or preserve the environment with:
#     sudo -E bash scripts/docker_push_hub.sh v1.2.3

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Config ──────────────────────────────────────────────────────────────────
DOCKERHUB_REPO="music1913/copaw"
DOCKERFILE="$REPO_ROOT/deploy/Dockerfile"
DISABLED_CHANNELS="${COPAW_DISABLED_CHANNELS:-imessage}"

# ── Args ─────────────────────────────────────────────────────────────────────
VERSION="${1:-dev}"
NO_LATEST=false
for arg in "$@"; do
  [[ "$arg" == "--no-latest" ]] && NO_LATEST=true
done

# Auto-detect pre-release from version string (beta/alpha/rc/dev → no latest tag)
if [[ "$VERSION" =~ (beta|alpha|rc|dev) ]] && [[ "$VERSION" != "dev" ]]; then
  NO_LATEST=true
fi
[[ "$VERSION" == "dev" ]] && NO_LATEST=true

# ── Proxy ────────────────────────────────────────────────────────────────────
# Normalise: prefer lowercase vars; fall back to uppercase if lowercase unset.
_http_proxy="${http_proxy:-${HTTP_PROXY:-}}"
_https_proxy="${https_proxy:-${HTTPS_PROXY:-}}"
_no_proxy="${no_proxy:-${NO_PROXY:-}}"

PROXY_ARGS=""
if [[ -n "$_http_proxy" ]]; then
  PROXY_ARGS="$PROXY_ARGS --build-arg http_proxy=$_http_proxy --build-arg HTTP_PROXY=$_http_proxy"
  echo "[docker_push_hub] http_proxy  → $_http_proxy"
fi
if [[ -n "$_https_proxy" ]]; then
  PROXY_ARGS="$PROXY_ARGS --build-arg https_proxy=$_https_proxy --build-arg HTTPS_PROXY=$_https_proxy"
  echo "[docker_push_hub] https_proxy → $_https_proxy"
fi
if [[ -n "$_no_proxy" ]]; then
  PROXY_ARGS="$PROXY_ARGS --build-arg no_proxy=$_no_proxy --build-arg NO_PROXY=$_no_proxy"
  echo "[docker_push_hub] no_proxy    → $_no_proxy"
fi
if [[ -z "$_http_proxy" && -z "$_https_proxy" ]]; then
  echo "[docker_push_hub] No proxy detected (set http_proxy/https_proxy if needed)."
fi

# ── Credentials ──────────────────────────────────────────────────────────────
DOCKER_USERNAME="${DOCKER_USERNAME:-}"
DOCKER_PASSWORD="${DOCKER_PASSWORD:-}"

if [[ -z "$DOCKER_USERNAME" || -z "$DOCKER_PASSWORD" ]]; then
  echo "[docker_push_hub] ERROR: DOCKER_USERNAME and DOCKER_PASSWORD must be set."
  echo "  export DOCKER_USERNAME=music1913"
  echo "  export DOCKER_PASSWORD=<your-password>"
  echo "  Or source a .env file (see script header for details)."
  exit 1
fi

# ── Login ─────────────────────────────────────────────────────────────────────
echo "[docker_push_hub] Logging in to Docker Hub as $DOCKER_USERNAME ..."
echo "$DOCKER_PASSWORD" | docker login docker.io \
  --username "$DOCKER_USERNAME" --password-stdin

# ── Compute tags ─────────────────────────────────────────────────────────────
TAGS="-t ${DOCKERHUB_REPO}:${VERSION} -t ${DOCKERHUB_REPO}:pre"
if [[ "$NO_LATEST" == "false" ]]; then
  TAGS="${TAGS} -t ${DOCKERHUB_REPO}:latest"
fi

echo "[docker_push_hub] Building image: $DOCKERHUB_REPO  (version=$VERSION, latest=$( [[ "$NO_LATEST" == "false" ]] && echo yes || echo no ))"
echo "[docker_push_hub] Tags: $(echo "$TAGS" | tr ' ' '\n' | grep -o '[^ ]*:[^ ]*')"

# ── Build & push ─────────────────────────────────────────────────────────────
# Uses the current platform only (native local build, no cross-compilation).
# For multi-arch (amd64 + arm64) add: --platform linux/amd64,linux/arm64
# and make sure 'docker buildx' is installed and a builder is active:
#   docker buildx create --use
docker buildx build \
  -f "$DOCKERFILE" \
  --build-arg COPAW_DISABLED_CHANNELS="$DISABLED_CHANNELS" \
  ${COPAW_ENABLED_CHANNELS:+--build-arg COPAW_ENABLED_CHANNELS="$COPAW_ENABLED_CHANNELS"} \
  $PROXY_ARGS \
  $TAGS \
  --push \
  .

echo "[docker_push_hub] Done. Image pushed:"
echo "  docker pull ${DOCKERHUB_REPO}:${VERSION}"
[[ "$NO_LATEST" == "false" ]] && echo "  docker pull ${DOCKERHUB_REPO}:latest"
