#!/usr/bin/env bash
# Generate macOS app icons from the canonical QwenPaw SVG with platform-safe
# visual padding. The generated icon files are build artifacts and should not
# be committed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="${1:-${REPO_ROOT}/dist/generated-icons/macos}"
SOURCE_ICON="${2:-${REPO_ROOT}/scripts/pack/assets/icon.svg}"
PADDING="${MACOS_ICON_SAFE_AREA_PADDING:-96}"
CANVAS_SIZE=1024

if [[ ! -f "${SOURCE_ICON}" ]]; then
  echo "ERROR: source icon not found: ${SOURCE_ICON}" >&2
  exit 1
fi

if ! [[ "${PADDING}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: MACOS_ICON_SAFE_AREA_PADDING must be an integer, got: ${PADDING}" >&2
  exit 1
fi

if (( PADDING < 0 || PADDING >= CANVAS_SIZE / 2 )); then
  echo "ERROR: MACOS_ICON_SAFE_AREA_PADDING must be between 0 and $((CANVAS_SIZE / 2 - 1))" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required to prepare the macOS safe-area SVG" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is required to run the Tauri icon generator" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

SAFE_ICON="${TMP_DIR}/qwenpaw-macos-safe-area.svg"

python3 - "${SOURCE_ICON}" "${SAFE_ICON}" "${PADDING}" "${CANVAS_SIZE}" <<'PY'
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

source_icon, safe_icon, padding_text, canvas_text = sys.argv[1:]
padding = int(padding_text)
canvas = int(canvas_text)
inner_size = canvas - padding * 2

svg_ns = "http://www.w3.org/2000/svg"
xlink_ns = "http://www.w3.org/1999/xlink"
ET.register_namespace("", svg_ns)
ET.register_namespace("xlink", xlink_ns)

source_tree = ET.parse(source_icon)
source_root = source_tree.getroot()
source_view_box = source_root.attrib.get("viewBox")
if source_view_box != f"0 0 {canvas} {canvas}":
    raise SystemExit(
        f"expected source SVG viewBox '0 0 {canvas} {canvas}', got {source_view_box!r}",
    )

safe_root = ET.Element(
    f"{{{svg_ns}}}svg",
    {
        "width": str(canvas),
        "height": str(canvas),
        "viewBox": f"0 0 {canvas} {canvas}",
        "fill": "none",
    },
)
inner_svg = ET.SubElement(
    safe_root,
    f"{{{svg_ns}}}svg",
    {
        "x": str(padding),
        "y": str(padding),
        "width": str(inner_size),
        "height": str(inner_size),
        "viewBox": source_view_box,
    },
)
for child in list(source_root):
    source_root.remove(child)
    inner_svg.append(child)

ET.ElementTree(safe_root).write(safe_icon, encoding="utf-8", xml_declaration=True)
PY

mkdir -p "${OUTPUT_DIR}"

if [[ ! -x "${REPO_ROOT}/console/node_modules/.bin/tauri" ]]; then
  echo "== Installing frontend tooling for Tauri icon generation =="
  (cd "${REPO_ROOT}/console" && npm ci)
fi

echo "== Generating macOS safe-area icons =="
echo "Source: ${SOURCE_ICON}"
echo "Output: ${OUTPUT_DIR}"
echo "Padding: ${PADDING}px"
(cd "${REPO_ROOT}/console" && npm exec -- tauri icon --output "${OUTPUT_DIR}" "${SAFE_ICON}")

if [[ ! -f "${OUTPUT_DIR}/icon.icns" ]]; then
  echo "ERROR: Tauri icon generator did not create ${OUTPUT_DIR}/icon.icns" >&2
  exit 1
fi
