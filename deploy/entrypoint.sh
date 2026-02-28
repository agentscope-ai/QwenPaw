#!/bin/sh
# CoPaw Docker entrypoint.
# 1. Initialize working dir if config.json does not exist (first run or
#    empty volume mount). This runs at container START, not build time,
#    so user-mounted volumes are respected and existing config is preserved.
# 2. Substitute COPAW_PORT in supervisord template and start supervisord.
set -e

WORKING_DIR="${COPAW_WORKING_DIR:-/app/working}"

if [ ! -f "${WORKING_DIR}/config.json" ]; then
    echo "copaw: first run detected, initializing ${WORKING_DIR}..."
    copaw init --defaults --accept-security
fi

export COPAW_PORT="${COPAW_PORT:-8088}"
envsubst '${COPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
