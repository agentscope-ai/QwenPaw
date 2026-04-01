#!/bin/bash
# CoPaw Backend Local Dev Stop Script
# Stops local backend and restores Docker backend container.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo -e "${GREEN}=== Restoring Docker Backend ===${NC}"
echo ""

# ── 1. Restore original nginx config ─────────────────────────────────────────
docker cp "$PROJECT_DIR/nginx/nginx.conf" copaw-nginx:/etc/nginx/nginx.conf
docker exec copaw-nginx nginx -s reload
echo -e "${GREEN}Nginx restored to Docker backend routing.${NC}"

# ── 2. Start Docker backend container ────────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q '^copaw$'; then
    echo -e "${YELLOW}Starting Docker backend container...${NC}"
    docker start copaw
    echo -e "${GREEN}Docker backend started.${NC}"
else
    echo "Docker backend already running."
fi

echo ""
echo -e "${GREEN}Done! Backend is running in Docker again.${NC}"
