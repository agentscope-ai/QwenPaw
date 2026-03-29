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
ENV COPAW_WORKING_DIR=/app/working
ENV COPAW_SECRET_DIR=/app/working.secret

# Channel filtering: use COPAW_DISABLED_CHANNELS (exclusion, recommended)
# or COPAW_ENABLED_CHANNELS (whitelist). Override at runtime with -e.
ARG COPAW_DISABLED_CHANNELS="imessage"
ENV COPAW_DISABLED_CHANNELS=${COPAW_DISABLED_CHANNELS}
ARG COPAW_ENABLED_CHANNELS=""
ENV COPAW_ENABLED_CHANNELS=${COPAW_ENABLED_CHANNELS}

ARG DEBIAN_FRONTEND=noninteractive

# Use Aliyun Debian mirror for faster downloads in China
RUN echo 'deb http://mirrors.aliyun.com/debian bookworm main' > /etc/apt/sources.list && \
    echo 'deb http://mirrors.aliyun.com/debian bookworm-updates main' >> /etc/apt/sources.list && \
    echo 'deb http://mirrors.aliyun.com/debian-security bookworm-security main' >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    libssl-dev \
    git \
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
    libu2f-udev \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get clean

RUN sed -i 's/^CHROMIUM_FLAGS=""/CHROMIUM_FLAGS="--no-sandbox"/' /usr/bin/chromium

# Playwright: use system Chromium (already installed above).
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
# Avoid Playwright downloading its own browser when executable_path is used.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
# Indicate running in container (used e.g. for Chromium --no-sandbox).
ENV COPAW_RUNNING_IN_CONTAINER=1

WORKDIR ${WORKSPACE_DIR}

RUN python3 -m venv venv
ENV PATH="/app/venv/bin:$PATH"

COPY pyproject.toml setup.py README.md ./
COPY src ./src
# Inject console dist from build stage (repo does not commit dist).
COPY --from=console-builder /app/console/dist/ ./src/copaw/console/

# Use Aliyun PyPI mirror for pip
RUN pip3 config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip3 config set global.trusted-host mirrors.aliyun.com && \
    pip install --no-cache-dir .[ollama]

# Init working dir with default config.json and HEARTBEAT.md (build time).
RUN copaw init --defaults --accept-security

# CoPaw app port (default 8088). Override at runtime with -e COPAW_PORT=3000.
ENV COPAW_PORT=8088

COPY --chmod=755 deploy/entrypoint.sh /entrypoint.sh

EXPOSE 8088

CMD ["/entrypoint.sh"]
