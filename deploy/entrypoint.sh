#!/bin/sh
# Substitute QWENPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e QWENPAW_PORT=3000.
set -e

wait_for_csi_mount() {
  mount_dir="$1"
  timeout="${QWENPAW_CSI_WAIT_TIMEOUT:-0}"
  waited=0

  mkdir -p "$mount_dir"
  echo "Waiting for CSI mount at ${mount_dir}..."

  while true; do
    link_target="$(readlink "$mount_dir" 2>/dev/null || true)"

    if [ -n "$link_target" ] && echo "$link_target" | grep -q '^/run/csi/mount-root/'; then
      echo "CSI mount detected: ${mount_dir} -> ${link_target}"
      return 0
    fi

    if command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$mount_dir"; then
      echo "Mount detected at ${mount_dir}"
      return 0
    fi

    if [ "$timeout" != "0" ] && [ "$waited" -ge "$timeout" ]; then
      echo "ERROR: timed out waiting for CSI mount at ${mount_dir}" >&2
      exit 1
    fi

    sleep 2
    waited=$((waited + 2))
  done
}

bootstrap_and_start() {
  mkdir -p "$QWENPAW_WORKING_DIR" "$QWENPAW_SECRET_DIR" "$QWENPAW_BACKUP_DIR"

  # Auto-initialize if config.json is missing.
  if [ ! -f "${QWENPAW_WORKING_DIR}/config.json" ]; then
    echo "⚠️  No config.json found in ${QWENPAW_WORKING_DIR}"
    echo "📦 Running initialization..."
    qwenpaw init --defaults --accept-security
    echo "✅ Initialization complete!"
  else
    echo "✓ Config found in ${QWENPAW_WORKING_DIR}, skipping initialization."
  fi

  export QWENPAW_PORT="${QWENPAW_PORT:-8088}"
  envsubst '${QWENPAW_PORT}' \
    < /etc/supervisor/conf.d/supervisord.conf.template \
    > /etc/supervisor/conf.d/supervisord.conf
  exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
}

export QWENPAW_WORKING_DIR="${QWENPAW_WORKING_DIR:-/app/working}"
export QWENPAW_SECRET_DIR="${QWENPAW_SECRET_DIR:-/app/working.secret}"
export QWENPAW_BACKUP_DIR="${QWENPAW_BACKUP_DIR:-/app/working.backups}"

if [ "${QWENPAW_WAIT_FOR_CSI:-0}" = "1" ]; then
  wait_for_csi_mount "${QWENPAW_CSI_MOUNT_DIR:-$QWENPAW_WORKING_DIR}"
  bootstrap_and_start
else
  bootstrap_and_start
fi
