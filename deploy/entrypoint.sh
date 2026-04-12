#!/bin/sh
# Start copaw app directly (GUI components removed in optimization).
# Default port 8088; override at runtime with -e COPAW_PORT=3000.
set -e
exec copaw app --host 0.0.0.0 --port "${COPAW_PORT:-8088}"
