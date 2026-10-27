# Use the pinned official Node image by default. Override NODE_IMAGE to use
# an ACR mirror where Docker Hub is unavailable.
ARG NODE_IMAGE=node:22.23.4-slim
ARG UV_IMAGE=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/uv:0.13.4

# -----------------------------------------------------------------------------
# Stage 1: build console frontend (dist not committed in repo).
# -----------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS console-builder
WORKDIR /app
COPY console /app/console
COPY src/qwenpaw/plugins/frontend /app/src/qwenpaw/plugins/frontend
RUN cd /app/console && npm ci --include=dev && npm run build

# Alias for uv binary so COPY --from can reference a build-arg image.
FROM ${UV_IMAGE} AS uv-src

# -----------------------------------------------------------------------------
# Stage 2: runtime image with Python, Chromium, and app.
# -----------------------------------------------------------------------------
FROM ${NODE_IMAGE}

ARG QWENPAW_MANAGED_RUNTIME_BOUNDARY_VERSION
LABEL io.qwenpaw.managed-runtime-boundary.version=\
${QWENPAW_MANAGED_RUNTIME_BOUNDARY_VERSION}

# Fail the build when NODE_IMAGE does not match the repository runtime pin.
COPY .nvmrc /tmp/qwenpaw-node-version
RUN expected_version="v$(tr -d '[:space:]' < /tmp/qwenpaw-node-version)" \
  && actual_version="$(node --version)" \
  && if [ "${actual_version}" != "${expected_version}" ]; then \
       echo "Node version mismatch: expected ${expected_version}, got ${actual_version}" >&2; \
       exit 1; \
     fi \
  && rm /tmp/qwenpaw-node-version

# ENV variables
ENV NODE_ENV=production
ENV WORKSPACE_DIR=/app
ENV QWENPAW_WORKING_DIR=/app/working
ENV QWENPAW_SECRET_DIR=/app/working.secret
ENV QWENPAW_BACKUP_DIR=/app/working.backups

# Channel filtering: use QWENPAW_DISABLED_CHANNELS (exclusion, recommended)
# or QWENPAW_ENABLED_CHANNELS (whitelist). Override at runtime with -e.
ARG QWENPAW_DISABLED_CHANNELS="imessage"
ENV QWENPAW_DISABLED_CHANNELS=${QWENPAW_DISABLED_CHANNELS}
ARG QWENPAW_ENABLED_CHANNELS=""
ENV QWENPAW_ENABLED_CHANNELS=${QWENPAW_ENABLED_CHANNELS}

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --fix-missing \
    ca-certificates \
    curl  \
    python3  \
    python3-venv \
    build-essential  \
    libssl-dev  \
    git  \
    supervisor  \
    vim  \
    gettext-base \
    xfce4 \
    xfce4-terminal \
    xvfb \
    dbus-x11 \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
  && update-ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get clean


RUN apt-get update && apt-get install -y --fix-missing \
    chromium \
    chromium-sandbox \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxtst6 \
    libnss3 \
    libglib2.0-0 \
    libdrm2 \
    libgbm1 \
    libasound2 \
    fonts-liberation \
    libu2f-udev \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get clean


RUN sed -i 's/^CHROMIUM_FLAGS=""/CHROMIUM_FLAGS="--no-sandbox"/' /usr/bin/chromium

# Playwright: use system Chromium (already installed above).
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
# Avoid Playwright downloading its own browser when executable_path is used.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
# Indicate running in container (used e.g. for Chromium --no-sandbox).
ENV QWENPAW_RUNNING_IN_CONTAINER=1

WORKDIR ${WORKSPACE_DIR}

# Keep Debian's Python for system services; use the desktop runtime for QwenPaw.
COPY scripts/pack-tauri/stage_python_runtime.py /tmp/stage_python_runtime.py
RUN python3 /tmp/stage_python_runtime.py \
    --dest /opt/qwenpaw-python --python-version 3.11 \
  && /opt/qwenpaw-python/python/bin/python3 -m pip install --upgrade "pip>=26.2.2" \
  && /opt/qwenpaw-python/python/bin/python3 -m pip install --upgrade "certifi>=2026.10.19" \
  && /opt/qwenpaw-python/python/bin/python3 -m venv /app/venv \
  && /app/venv/bin/python -m pip install --upgrade "pip>=26.2.2" \
  && /app/venv/bin/python -m pip install --upgrade "certifi>=2026.10.19" \
  && rm /tmp/stage_python_runtime.py
ENV PATH="/app/venv/bin:$PATH"

COPY pyproject.toml setup.py README.md ./
COPY src ./src
COPY plugins/hub ./plugins/hub
COPY packages/qwenpawmail-mcp/src/qwenpawmail_mcp ./packages/qwenpawmail-mcp/src/qwenpawmail_mcp
COPY website/public/docs/ ./src/qwenpaw/docs/
# Inject console dist from build stage (repo does not commit dist).
COPY --from=console-builder /app/console/dist/ ./src/qwenpaw/console/
# Speed up Python package installation with uv.
COPY --from=uv-src /uv /bin/uv
# Validate the binary, including when UV_IMAGE points at an internal mirror.
RUN python -c 'import re, subprocess, sys; \
    output = subprocess.check_output(["/bin/uv", "--version"], text=True); \
    match = re.match(r"uv (\d+)\.(\d+)\.(\d+)(?:\s|$)", output); \
    sys.exit(0 if match and tuple(map(int, match.groups())) >= (0, 13, 4) \
    else "uv >= 0.13.4 is required")'
# Pin setuptools <82: lark-oapi still calls pkg_resources.declare_namespace
# at import time. A *fresh* install of setuptools >= 82 removes pkg_resources
# wholesale, so lark-oapi's except-ImportError fallback (pkgutil.extend_path)
# kicks in and the import works. The proven failure mode is an *in-place*
# upgrade of a legacy setuptools (seen on the macOS CI runners, and possible
# in any environment upgrading an existing install): it can leave a
# half-removed pkg_resources (module present, declare_namespace gone), which
# raises an AttributeError the fallback does not catch — crashing the Feishu
# channel. The pin keeps every environment in the known-good state.
RUN uv pip install --python /app/venv/bin/python \
    --no-cache-dir . "setuptools<82" \
  && rm -rf ./build


# QwenPaw app port (default 8088). Override at runtime with -e QWENPAW_PORT=3000.
ENV QWENPAW_PORT=8088

COPY deploy/config/supervisord.conf.template /etc/supervisor/conf.d/supervisord.conf.template
COPY --chmod=755 deploy/entrypoint.sh /entrypoint.sh

EXPOSE 8088

CMD ["/entrypoint.sh"]
