#!/bin/sh
# Substitute BOOSTCLAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e BOOSTCLAW_PORT=3000.
set -e
export BOOSTCLAW_PORT="${BOOSTCLAW_PORT:-8088}"
envsubst '${BOOSTCLAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
