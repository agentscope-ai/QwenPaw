# -*- coding: utf-8 -*-
import logging
import os
import time
import warnings

from .utils.logging import setup_logger

LOG_LEVEL_ENV = "COPAW_LOG_LEVEL"

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
    warnings.warn(
        f"copaw: failed to load persisted envs on init: {_bootstrap_err}",
        RuntimeWarning,
    )
logging.getLogger(__name__).debug(
    "%.3fs package init",
    time.perf_counter() - _t0,
)
