# -*- coding: utf-8 -*-
import logging
import os
import time

DESKTOP_PORT_ENV = "QWENPAW_DESKTOP_PORT"
DESKTOP_APP_ENV = "QWENPAW_DESKTOP_APP"

if os.environ.get(DESKTOP_PORT_ENV):
    os.environ.setdefault(DESKTOP_APP_ENV, "1")
    # Keep the Tauri import lazy so ordinary `import qwenpaw` stays independent
    # from the desktop packaging module.
    from .tauri.env import ensure_desktop_cors_origins

    ensure_desktop_cors_origins()

from .utils.logging import setup_logger  # pylint: disable=wrong-import-position

# Fallback before we can safely read canonical constant definitions.
LOG_LEVEL_ENV = "QWENPAW_LOG_LEVEL"

_bootstrap_err: Exception | None = None
try:
    # Load persisted env vars before importing modules that read env-backed
    # constants at import time (e.g., WORKING_DIR).
    from .envs import load_envs_into_environ

    load_envs_into_environ()
except Exception as exc:
    # Best effort: package import should not fail if env bootstrap fails.
    _bootstrap_err = exc

_t0 = time.perf_counter()
setup_logger(os.environ.get(LOG_LEVEL_ENV, "info"))
if _bootstrap_err is not None:
    logging.getLogger(__name__).warning(
        "qwenpaw: failed to load persisted envs on init: %s",
        _bootstrap_err,
    )
logging.getLogger(__name__).debug(
    "%.3fs package init",
    time.perf_counter() - _t0,
)
