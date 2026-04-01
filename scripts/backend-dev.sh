#!/bin/bash
# CoPaw Backend Local Development Start Script
# Stops the Docker backend container and runs copaw locally for faster dev iteration.
# Console, Website, and Nginx remain in Docker.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== CoPaw Backend Local Dev ===${NC}"
echo ""

# ── 1. Activate venv and check copaw ──────────────────────────────────────────
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating venv...${NC}"
    uv venv "$VENV_DIR" --python 3.10
fi
source "$VENV_DIR/bin/activate"

if ! command -v copaw &> /dev/null; then
    echo -e "${YELLOW}copaw CLI not found. Installing from source...${NC}"
    cd "$PROJECT_DIR"
    uv pip install -e ".[supabase]"
    echo -e "${GREEN}copaw installed successfully.${NC}"
fi

# ── 2. Stop Docker backend container ─────────────────────────────────────────
if docker ps --format '{{.Names}}' | grep -q '^copaw$'; then
    echo -e "${YELLOW}Stopping Docker backend container 'copaw'...${NC}"
    docker stop copaw
    echo -e "${GREEN}Docker backend stopped.${NC}"
else
    echo "Docker backend container already stopped."
fi

# ── 3. Get host gateway IP for nginx ─────────────────────────────────────────
# Find the gateway IP of the Docker network so nginx can reach the host
NETWORK_NAME=$(docker network ls --format '{{.Name}}' | grep 'copaw.*network' | head -1)
if [ -z "$NETWORK_NAME" ]; then
    NETWORK_NAME="copaw_copaw-network"
fi
GATEWAY_IP=$(docker network inspect "$NETWORK_NAME" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['IPAM']['Config'][0]['Gateway'])" 2>/dev/null || echo "172.19.0.1")
echo "Host gateway IP: $GATEWAY_IP"

# ── 4. Update nginx to point backend to host ──────────────────────────────────
# Create a modified nginx config with the host gateway IP
sed "s/host-gateway:8088/${GATEWAY_IP}:8088/" "$PROJECT_DIR/nginx/nginx.dev-local.conf" > /tmp/copaw-nginx-dev.conf

# Copy into running nginx container and reload
docker cp /tmp/copaw-nginx-dev.conf copaw-nginx:/etc/nginx/nginx.conf
docker exec copaw-nginx nginx -s reload
echo -e "${GREEN}Nginx updated to route /api/ to host:${GATEWAY_IP}:8088${NC}"

# ── 5. Set up working directory ──────────────────────────────────────────────
# Use the same data as the Docker container (from Docker volumes)
DOCKER_DATA="/var/lib/docker/volumes/copaw-data/_data"
DOCKER_SECRETS="/var/lib/docker/volumes/copaw-secrets/_data"

if [ -d "$DOCKER_DATA" ]; then
    export COPAW_WORKING_DIR="$DOCKER_DATA"
    echo "Using working dir: $COPAW_WORKING_DIR"
fi

if [ -d "$DOCKER_SECRETS" ]; then
    export COPAW_SECRET_DIR="$DOCKER_SECRETS"
    echo "Using secrets dir: $COPAW_SECRET_DIR"
fi

# ── 6. Load environment variables ────────────────────────────────────────────
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
    echo "Loaded .env"
fi

# ── 7. Start copaw locally ──────────────────────────────────────────────────
echo ""
echo -e "${GREEN}Starting copaw backend locally with hot reload...${NC}"
echo -e "  Host: 0.0.0.0:8088"
echo -e "  Reload: enabled"
echo -e "  Log level: info"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

cd "$PROJECT_DIR"
copaw app --host 0.0.0.0 --port 8088 --reload --log-level info
