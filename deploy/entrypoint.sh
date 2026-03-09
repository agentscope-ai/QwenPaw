#!/bin/sh
# Substitute COPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e COPAW_PORT=3000.
set -e
export COPAW_PORT="${COPAW_PORT:-8088}"

# ---------------------------------------------------------------------------
# Persist secrets inside the mounted working-dir volume.
#
# COPAW_SECRET_DIR (default /app/working.secret) is a *sibling* of
# COPAW_WORKING_DIR (/app/working).  When users only mount a volume at
# /app/working, the secret dir lives on the ephemeral container layer and
# is lost on container recreation.
#
# Fix: if COPAW_SECRET_DIR is NOT a separate mount, redirect it into
# COPAW_WORKING_DIR/.secret via symlink so data lands on the same volume.
# ---------------------------------------------------------------------------
_work="${COPAW_WORKING_DIR:-/app/working}"
_secret="${COPAW_SECRET_DIR:-${_work}.secret}"
_inner="${_work}/.secret"

if [ -d "$_work" ] && ! mountpoint -q "$_secret" 2>/dev/null; then
  mkdir -p "$_inner"
  # Seed from image-layer defaults when inner dir is still empty.
  if [ -d "$_secret" ] && [ ! -L "$_secret" ]; then
    cp -an "$_secret"/. "$_inner"/ 2>/dev/null || true
    rm -rf "$_secret"
  fi
  # (Re-)create the symlink on every start (container layer is fresh).
  ln -sfn "$_inner" "$_secret"
fi

envsubst '${COPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
