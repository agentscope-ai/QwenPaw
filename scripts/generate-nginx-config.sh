#!/bin/bash
# Nginx Configuration Generator
# Generates nginx.conf from template with environment variable substitution

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default values
BACKEND_HOST="${BACKEND_HOST:-copaw}"
BACKEND_PORT="${BACKEND_PORT:-8088}"
CONSOLE_ROOT="${CONSOLE_ROOT:-/var/www/console}"
WEBSITE_ROOT="${WEBSITE_ROOT:-/var/www/website}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo -e "${GREEN}=== Generating Nginx Configuration ===${NC}"
echo ""
echo "Configuration:"
echo "  Backend: $BACKEND_HOST:$BACKEND_PORT"
echo "  Console root: $CONSOLE_ROOT"
echo "  Website root: $WEBSITE_ROOT"
echo ""

# Generate nginx.conf
cat > "$PROJECT_DIR/nginx/nginx.conf" << 'EOF'
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript
               application/x-javascript application/xml+rss
               application/json application/javascript;

    # Upstream services
    upstream backend {
        server ${BACKEND_HOST}:${BACKEND_PORT};
    }

    server {
        listen 80;
        server_name _;

        # Client max body size
        client_max_body_size 100M;

        # API proxy
        location /api/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_cache_bypass $http_upgrade;
        }

        # Console static assets (exact match, no fallback)
        location /console/assets/ {
            alias ${CONSOLE_ROOT}/assets/;
        }

        # Console static files at root level (logo, icons, etc.)
        location ~ ^/console/(.+\.(?:png|svg|ico|json|js|css|woff2?|ttf))$ {
            alias ${CONSOLE_ROOT}/$1;
        }

        # Console application (SPA fallback)
        location /console/ {
            alias ${CONSOLE_ROOT}/;
            try_files $uri /console/index.html;
        }

        # Redirect root to console
        location = / {
            return 301 /console/;
        }

        location = /login {
            return 301 /console/login;
        }

        # Website application (serve static files)
        location / {
            root ${WEBSITE_ROOT};
            try_files $uri $uri/ /index.html;
        }
    }
}
EOF

# Substitute environment variables
sed -i "s|\${BACKEND_HOST}|$BACKEND_HOST|g" "$PROJECT_DIR/nginx/nginx.conf"
sed -i "s|\${BACKEND_PORT}|$BACKEND_PORT|g" "$PROJECT_DIR/nginx/nginx.conf"
sed -i "s|\${CONSOLE_ROOT}|$CONSOLE_ROOT|g" "$PROJECT_DIR/nginx/nginx.conf"
sed -i "s|\${WEBSITE_ROOT}|$WEBSITE_ROOT|g" "$PROJECT_DIR/nginx/nginx.conf"

echo -e "${GREEN}✓ Generated: nginx/nginx.conf${NC}"
echo ""

# Generate nginx.dev-local.conf for local development
cat > "$PROJECT_DIR/nginx/nginx.dev-local.conf" << 'EOF'
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript
               application/x-javascript application/xml+rss
               application/json application/javascript;

    # Backend runs on host machine (not in Docker)
    upstream backend {
        server host-gateway:8088;
    }

    server {
        listen 80;
        server_name _;

        # Client max body size
        client_max_body_size 100M;

        # API proxy
        location /api/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_cache_bypass $http_upgrade;
        }

        # Console static assets (exact match, no fallback)
        location /console/assets/ {
            alias ${CONSOLE_ROOT}/assets/;
        }

        # Console static files at root level (logo, icons, etc.)
        location ~ ^/console/(.+\.(?:png|svg|ico|json|js|css|woff2?|ttf))$ {
            alias ${CONSOLE_ROOT}/$1;
        }

        # Console application (SPA fallback)
        location /console/ {
            alias ${CONSOLE_ROOT}/;
            try_files $uri /console/index.html;
        }

        # Redirect root to console
        location = / {
            return 301 /console/;
        }

        location = /login {
            return 301 /console/login;
        }

        # Website application (serve static files)
        location / {
            root ${WEBSITE_ROOT};
            try_files $uri $uri/ /index.html;
        }
    }
}
EOF

sed -i "s|\${CONSOLE_ROOT}|$CONSOLE_ROOT|g" "$PROJECT_DIR/nginx/nginx.dev-local.conf"
sed -i "s|\${WEBSITE_ROOT}|$WEBSITE_ROOT|g" "$PROJECT_DIR/nginx/nginx.dev-local.conf"

echo -e "${GREEN}✓ Generated: nginx/nginx.dev-local.conf${NC}"
echo ""
echo "Configuration files generated successfully!"
echo ""
echo "To apply changes:"
echo "  docker compose build --no-cache nginx"
echo "  docker compose up -d"
