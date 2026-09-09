# QwenPaw Creator Docker image — built on top of the official QwenPaw image.
#
# This dramatically reduces build time by reusing the official image which
# already contains:
#   - Python toolchain (python3, pip, venv, build-essential)
#   - System tools (curl, git, supervisor, vim, gettext-base)
#   - Desktop environment (xfce4, xvfb, dbus-x11)
#   - CJK fonts (fonts-wqy-zenhei, fonts-wqy-microhei)
#   - Chromium and all Playwright runtime dependencies
#   - QwenPaw host application and console frontend
#
# Build stages:
#   Stage 1: creator-ui-builder — builds Creator UI SPA
#   Final stage: runtime — adds Creator plugin on top of official QwenPaw image

# Global ARGs: must be declared before first FROM to be available in all stages.
# Use ACR registry for users in China; override with --build-arg for Docker Hub.
ARG QWENPAW_BASE_IMAGE=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw:latest
ARG NODE_IMAGE=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim

# PyPI mirror for faster package downloads in China.
# Override with --build-arg PYPI_INDEX_URL=https://pypi.org/simple/ for global mirror.
ARG PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# -----------------------------------------------------------------------------
# Stage 1: build Creator UI frontend.
# -----------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS creator-ui-builder
WORKDIR /app
COPY plugins/apps/qwenpaw-creator/ui /app/creator-ui
RUN cd /app/creator-ui && npm ci --include=dev && npm run build

# -----------------------------------------------------------------------------
# Final stage: runtime image with Creator plugin on top of official QwenPaw.
# -----------------------------------------------------------------------------
FROM ${QWENPAW_BASE_IMAGE}

# Install geopandas system dependency (not included in official QwenPaw image).
# Replace default Debian mirror with Aliyun mirror for faster downloads in China.
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && apt-get install -y --fix-missing libgeos-dev \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get clean

# -----------------------------------------------------------------------------
# Bundle Creator plugin into the image.
# -----------------------------------------------------------------------------
COPY plugins/apps/qwenpaw-creator /app/bundled-plugins/qwenpaw-creator

# Copy Creator UI build artifacts from Stage 1.
# Vite outputs to dist/app/ (SPA files) and package-plugin.mjs generates
# dist/index.js (plugin entry wrapper). Copy the full dist/ so both are included.
COPY --from=creator-ui-builder /app/creator-ui/dist/ /app/bundled-plugins/qwenpaw-creator/ui/dist/

# Install Creator Python dependencies into the existing venv.
# Extract hostname from PYPI_INDEX_URL for --trusted-host (strip protocol and path).
RUN PYPI_HOST=$(echo "${PYPI_INDEX_URL}" | sed -E 's|https?://([^/]+).*|\1|') && \
    uv pip install --no-cache-dir \
    --index-url "${PYPI_INDEX_URL}" \
    --trusted-host "${PYPI_HOST}" \
    -r /app/bundled-plugins/qwenpaw-creator/requirements.txt

# Override entrypoint to auto-install Creator plugin on startup.
COPY --chmod=755 plugins/apps/qwenpaw-creator/entrypoint.sh /entrypoint-creator.sh

# Health check: verify the app is responding on the configured port.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:${QWENPAW_PORT:-8088}/ || exit 1

CMD ["/entrypoint-creator.sh"]
