# -----------------------------------------------------------------------------
# Stage 1: build console frontend (dist not committed in repo).
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim AS console-builder
WORKDIR /app
COPY console /app/console
RUN cd /app/console && npm ci --include=dev && npm run build

# -----------------------------------------------------------------------------
# Stage 2: runtime image with Python, Chromium, and app.
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim

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
    curl  \
    python3  \
    python3-pip  \
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

RUN python3 -m venv venv
ENV PATH="/app/venv/bin:$PATH"

COPY pyproject.toml setup.py README.md ./
COPY src ./src
# Inject console dist from build stage (repo does not commit dist).
COPY --from=console-builder /app/console/dist/ ./src/qwenpaw/console/
RUN pip install --no-cache-dir .


# QwenPaw app port (default 8088). Override at runtime with -e QWENPAW_PORT=3000.
ENV QWENPAW_PORT=8088

COPY deploy/config/supervisord.conf.template /etc/supervisor/conf.d/supervisord.conf.template
COPY --chmod=755 deploy/entrypoint.sh /entrypoint.sh

EXPOSE 8088

CMD ["/entrypoint.sh"]
