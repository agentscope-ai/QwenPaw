#!/bin/sh
# QwenPaw Creator entrypoint.
# 1. Auto-install bundled Creator plugin if not already present.
# 2. Substitute port in supervisord template.
# 3. Start supervisord (which manages app + xvfb + xfce4).
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
SECURITY NOTICE: QwenPaw Creator is running in Docker without authentication.

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

# Auto-install bundled Creator plugin if not already present.
# Set CREATOR_FORCE_PLUGIN_UPDATE=true to force overwrite existing plugins.
if [ -d "/app/bundled-plugins/qwenpaw-creator" ]; then
  case "${QWENPAW_WORKING_DIR}" in
    ""|"/") echo "ERROR: QWENPAW_WORKING_DIR is unset or /" >&2; exit 1 ;;
  esac
  if [ "${CREATOR_FORCE_PLUGIN_UPDATE:-}" = "true" ] || [ ! -d "${QWENPAW_WORKING_DIR}/plugins/qwenpaw-creator" ]; then
    echo "📦 Installing bundled Creator plugin..."
    mkdir -p "${QWENPAW_WORKING_DIR}/plugins"
    rm -rf "${QWENPAW_WORKING_DIR}/plugins/qwenpaw-creator"
    cp -r /app/bundled-plugins/qwenpaw-creator "${QWENPAW_WORKING_DIR}/plugins/"
    CREATOR_VERSION=$(python3 -c "import json;print(json.load(open('/app/bundled-plugins/qwenpaw-creator/plugin.json'))['version'])" 2>/dev/null || echo "unknown")
    echo "✅ Creator plugin v${CREATOR_VERSION} installed."
  else
    echo "✓ Creator plugin already installed (set CREATOR_FORCE_PLUGIN_UPDATE=true to overwrite)."
  fi
else
  echo "✓ Creator plugin not bundled."
fi

export QWENPAW_PORT="${QWENPAW_PORT:-8088}"
warn_if_auth_off_container_bind

envsubst '${QWENPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
