#!/bin/sh
# Install plugins shipped inside the image into the working directory.
#
# PluginLoader discovers plugins from <working_dir>/plugins, which is a bind
# mount or volume, so a plugin baked into the image is invisible until it is
# copied in.  This runs on every container start:
#   - same version installed  -> left untouched (the admin may have edited it)
#   - different version       -> replaced, previous copy backed up
#
# Backups go OUTSIDE <working_dir>/plugins on purpose: the loader treats every
# directory under it as a plugin, so a backup left there would be discovered
# and loaded as a second, stale copy.
set -e

BUNDLED_PLUGINS_DIR="${BUNDLED_PLUGINS_DIR:-/app/bundled-plugins}"
PLUGIN_BACKUP_DIR="${PLUGIN_BACKUP_DIR:-/app/plugin-backups}"

if [ -z "${QWENPAW_WORKING_DIR}" ]; then
  echo "QWENPAW_WORKING_DIR is not set; skipping bundled plugin sync." >&2
  exit 0
fi

[ -d "${BUNDLED_PLUGINS_DIR}" ] || exit 0

plugin_version() {
  python3 -c \
    "import json,sys;print(json.load(open(sys.argv[1])).get('version') or 'unknown')" \
    "$1" 2>/dev/null || echo "unknown"
}

dest_root="${QWENPAW_WORKING_DIR}/plugins"
mkdir -p "${dest_root}"

for src in "${BUNDLED_PLUGINS_DIR}"/*; do
  # Skips the unexpanded glob when the bundle dir is empty.
  [ -f "${src}/plugin.json" ] || continue

  name="$(basename "${src}")"
  dest="${dest_root}/${name}"
  src_version="$(plugin_version "${src}/plugin.json")"

  if [ -d "${dest}" ]; then
    dest_version="$(plugin_version "${dest}/plugin.json")"
    if [ "${src_version}" = "${dest_version}" ]; then
      echo "✓ Bundled plugin ${name} (${src_version}) already installed."
      continue
    fi
    backup="${PLUGIN_BACKUP_DIR}/${name}-${dest_version}-$(date +%Y%m%d%H%M%S)"
    mkdir -p "${PLUGIN_BACKUP_DIR}"
    mv "${dest}" "${backup}"
    echo "↺ Backed up ${name} ${dest_version} to ${backup}"
  fi

  cp -a "${src}" "${dest}"
  echo "✅ Installed bundled plugin ${name} (${src_version})."
done
