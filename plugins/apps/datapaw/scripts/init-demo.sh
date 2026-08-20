#!/usr/bin/env bash
# Seed the DataPaw demo against a running docker-compose context service.
#
# Use this script when you start only the infrastructure services:
#   docker compose up -d neo4j postgres context seed
# and run QwenPaw locally with DATAPAW_CONTEXT_MODE=external.
#
# If you run `docker compose up -d` (including the qwenpaw service), the seed
# container is executed automatically and this script is not needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(dirname "$SCRIPT_DIR")"

cd "$COMPOSE_DIR"

if [ ! -f .env ]; then
    echo "Copying .env.example to .env"
    cp .env.example .env
fi

# Pull environment variables into the current shell for substitution.
set -a
# shellcheck source=/dev/null
source .env
set +a

CONTEXT_URL="${CONTEXT_URL:-http://127.0.0.1:${CONTEXT_PORT:-8765}}"
POSTGRES_DSN="${POSTGRES_DSN:-postgresql://${POSTGRES_USER:-datapaw}:${POSTGRES_PASSWORD:-datapaw-demo}@127.0.0.1:${POSTGRES_PORT:-55432}/${POSTGRES_DB:-datapaw_demo}}"
CONTEXT_TOKEN="${DATAPAW_CONTEXT_TOKEN:-datapaw-demo-token}"

docker compose run --rm \
    -e CONTEXT_URL="$CONTEXT_URL" \
    -e POSTGRES_DSN="$POSTGRES_DSN" \
    -e CONTEXT_TOKEN="$CONTEXT_TOKEN" \
    seed
