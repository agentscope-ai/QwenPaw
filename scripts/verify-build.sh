#!/bin/bash
# Build Verification Script for CI/CD
# Validates that frontend builds have correct base paths and resource references

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo -e "${GREEN}=== CoPaw Build Verification ===${NC}"
echo ""

# ── 1. Verify console build ──────────────────────────────────────────────────
echo "Checking console build..."

CONSOLE_DIST="$PROJECT_DIR/console/dist"
CONSOLE_INDEX="$CONSOLE_DIST/index.html"

if [ ! -f "$CONSOLE_INDEX" ]; then
    echo -e "${RED}✗ Console dist/index.html not found${NC}"
    echo "  Run: cd console && npm run build"
    exit 1
fi

# Check base path in vite.config.ts
EXPECTED_BASE="/console/"
VITE_CONFIG="$PROJECT_DIR/console/vite.config.ts"
if ! grep -q "base: '$EXPECTED_BASE'" "$VITE_CONFIG" && ! grep -q "base: \"$EXPECTED_BASE\"" "$VITE_CONFIG"; then
    echo -e "${YELLOW}⚠ Warning: vite.config.ts base path may not be set to '$EXPECTED_BASE'${NC}"
fi

# Verify resource paths in index.html
echo "  Verifying resource paths..."
INVALID_PATHS=$(grep -oE '(src|href)="(/[^/][^"]*)"' "$CONSOLE_INDEX" | grep -v "/console/" || true)
if [ -n "$INVALID_PATHS" ]; then
    echo -e "${RED}✗ Found resources without /console/ prefix:${NC}"
    echo "$INVALID_PATHS"
    echo ""
    echo "  This means the build was created with incorrect base path."
    echo "  Fix: Ensure vite.config.ts has base: '/console/' and rebuild"
    exit 1
fi

# Verify assets directory exists
if [ ! -d "$CONSOLE_DIST/assets" ]; then
    echo -e "${RED}✗ Console dist/assets directory not found${NC}"
    exit 1
fi

# Count JS and CSS files
JS_COUNT=$(find "$CONSOLE_DIST/assets" -name "*.js" | wc -l)
CSS_COUNT=$(find "$CONSOLE_DIST/assets" -name "*.css" | wc -l)

echo -e "${GREEN}✓ Console build verified${NC}"
echo "  - Base path: $EXPECTED_BASE"
echo "  - JS files: $JS_COUNT"
echo "  - CSS files: $CSS_COUNT"
echo ""

# ── 2. Verify website build (if exists) ──────────────────────────────────────
WEBSITE_DIST="$PROJECT_DIR/website/dist"
WEBSITE_INDEX="$WEBSITE_DIST/index.html"

if [ -f "$WEBSITE_INDEX" ]; then
    echo "Checking website build..."

    if [ ! -d "$WEBSITE_DIST/assets" ]; then
        echo -e "${RED}✗ Website dist/assets directory not found${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ Website build verified${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠ Website dist not found (skipping)${NC}"
    echo ""
fi

# ── 3. Verify nginx configuration ────────────────────────────────────────────
echo "Checking nginx configuration..."

NGINX_CONF="$PROJECT_DIR/nginx/nginx.conf"
if [ ! -f "$NGINX_CONF" ]; then
    echo -e "${RED}✗ nginx/nginx.conf not found${NC}"
    exit 1
fi

# Check for console location block
if ! grep -q "location /console/" "$NGINX_CONF"; then
    echo -e "${RED}✗ nginx.conf missing 'location /console/' block${NC}"
    exit 1
fi

# Check for assets location
if ! grep -q "location /console/assets/" "$NGINX_CONF"; then
    echo -e "${YELLOW}⚠ Warning: nginx.conf missing specific 'location /console/assets/' block${NC}"
fi

echo -e "${GREEN}✓ Nginx configuration verified${NC}"
echo ""

# ── 4. Verify docker-compose configuration ───────────────────────────────────
echo "Checking docker-compose configuration..."

DOCKER_COMPOSE="$PROJECT_DIR/docker-compose.yml"
if [ ! -f "$DOCKER_COMPOSE" ]; then
    echo -e "${RED}✗ docker-compose.yml not found${NC}"
    exit 1
fi

# Check for COPAW_AUTH_ENABLED
if ! grep -q "COPAW_AUTH_ENABLED" "$DOCKER_COMPOSE"; then
    echo -e "${YELLOW}⚠ Warning: docker-compose.yml missing COPAW_AUTH_ENABLED environment variable${NC}"
fi

# Check for volume mounts
if ! grep -q "./console/dist:/var/www/console" "$DOCKER_COMPOSE"; then
    echo -e "${YELLOW}⚠ Warning: docker-compose.yml may not mount console dist correctly${NC}"
fi

echo -e "${GREEN}✓ Docker Compose configuration verified${NC}"
echo ""

# ── 5. Summary ───────────────────────────────────────────────────────────────
echo -e "${GREEN}=== Build Verification Complete ===${NC}"
echo ""
echo "All checks passed! The build is ready for deployment."
echo ""
echo "Next steps:"
echo "  1. Test locally: docker compose up -d"
echo "  2. Verify authentication: curl http://localhost/api/auth/status"
echo "  3. Access console: http://localhost/console/"
