# -*- coding: utf-8 -*-
import logging
import os
import time

try:
    # Load persisted env vars before importing modules that read env-backed
    # constants at import time (e.g., WORKING_DIR).
    from .envs import load_envs_into_environ

    load_envs_into_environ()
except Exception:
    # Best effort: package import should not fail if env bootstrap fails.
    pass

from .utils.logging import setup_logger

_t0 = time.perf_counter()
setup_logger(os.environ.get("COPAW_LOG_LEVEL", "info"))
logging.getLogger(__name__).debug(
    "%.3fs package init",
    time.perf_counter() - _t0,
)
