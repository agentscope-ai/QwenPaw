#!/bin/sh
# Substitute QWENPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e QWENPAW_PORT=3000.
set -e

is_auth_enabled() {
  if [ "${QWENPAW_AUTH_ENABLED+x}" ]; then
    flag="${QWENPAW_AUTH_ENABLED}"
  else
    flag="${COPAW_AUTH_ENABLED:-}"
  fi
  flag="$(printf '%s' "$flag" | tr '[:upper:]' '[:lower:]')"
  [ "$flag" = "true" ] || [ "$flag" = "1" ] || [ "$flag" = "yes" ]
}

warn_if_auth_off_container_bind() {
  if is_auth_enabled; then
    return
  fi

  cat >&2 <<EOF
============================================================
SECURITY NOTICE: QwenPaw is running in Docker without authentication.

QwenPaw cannot verify whether access to the service is limited to a trusted
network. Anyone who can reach the service may access QwenPaw APIs without login.

Recommended:
  - Restrict access to a trusted network or protected environment.
  - Enable authentication with QWENPAW_AUTH_ENABLED=true if untrusted users or
    processes may reach the service.
============================================================
EOF
}

# Auto-initialize if config.json is missing (bind mount with empty directory).
if [ ! -f "${QWENPAW_WORKING_DIR}/config.json" ]; then
  echo "⚠️  No config.json found in ${QWENPAW_WORKING_DIR}"
  echo "📦 Running initialization..."
  qwenpaw init --defaults --accept-security
  echo "✅ Initialization complete!"
else
  echo "✓ Config found in ${QWENPAW_WORKING_DIR}, skipping initialization."
fi

export QWENPAW_PORT="${QWENPAW_PORT:-8088}"
warn_if_auth_off_container_bind
envsubst '${QWENPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
