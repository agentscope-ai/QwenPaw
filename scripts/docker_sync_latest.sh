#!/usr/bin/env bash
set -euo pipefail

BUILDX_VERSION="v0.31.1"
PLUGINS_DIR="${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"
BUILDX_PLUGIN="$PLUGINS_DIR/docker-buildx"

die() { echo "[docker_tag_pre_to_latest] ERROR: $*" >&2; exit 1; }
log() { echo "[docker_tag_pre_to_latest] $*"; }

install_buildx() {
  local os arch suffix url
  case "$(uname -s)" in
    Darwin) os="darwin" ;;
    Linux)  os="linux" ;;
    *) die "Unsupported OS: $(uname -s)" ;;
  esac
  case "$(uname -m)" in
    x86_64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) die "Unsupported arch: $(uname -m)" ;;
  esac

  suffix="${os}-${arch}"
  url="https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.${suffix}"
  log "Installing buildx ${BUILDX_VERSION} from ${url}"
  mkdir -p "$PLUGINS_DIR"

  if command -v curl &>/dev/null; then
    curl -fsSL "$url" -o "$BUILDX_PLUGIN"
  elif command -v wget &>/dev/null; then
    wget -q "$url" -O "$BUILDX_PLUGIN"
  else
    die "Need curl or wget to install buildx"
  fi

  chmod +x "$BUILDX_PLUGIN"
  log "buildx installed at $BUILDX_PLUGIN"
}

require_buildx_imagetools() {
  command -v docker &>/dev/null || die "docker not found in PATH"

  # Check whether docker recognizes the buildx subcommand
  if ! docker buildx version &>/dev/null; then
    log "docker has no 'buildx' command. Will try to install buildx plugin..."
    install_buildx

    # Re-check after installation
    if ! docker buildx version &>/dev/null; then
      die $'docker still has no buildx after plugin install.\nPossible causes:\n- You are not using official Docker CLI (e.g. podman-docker / other wrapper)\n- Docker version is too old to load CLI plugins\nFix:\n- Use Docker Desktop / official docker-ce\n- Ensure docker is the official CLI, then re-run.'
    fi
  fi

  # Check whether imagetools is available (and supports -t)
  docker buildx imagetools create --help &>/dev/null \
    || die "buildx exists but 'imagetools create' is not available. Please upgrade Docker/buildx."
}

require_buildx_imagetools

ACR_REGISTRY="agentscope-registry.ap-southeast-1.cr.aliyuncs.com"
IMAGE="agentscope/qwenpaw"

ACR_PRE="${ACR_REGISTRY}/${IMAGE}:pre"
ACR_LATEST="${ACR_REGISTRY}/${IMAGE}:latest"
DH_PRE="docker.io/${IMAGE}:pre"
DH_LATEST="docker.io/${IMAGE}:latest"

log "ACR: ${ACR_PRE} -> ${ACR_LATEST}"
docker buildx imagetools create -t "$ACR_LATEST" "$ACR_PRE"

log "Docker Hub: ${DH_PRE} -> ${DH_LATEST}"
docker buildx imagetools create -t "$DH_LATEST" "$DH_PRE"

log "Done."
