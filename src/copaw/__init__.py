# -*- coding: utf-8 -*-
import logging
import os
import time

from .utils.logging import setup_logger

# Key used when CLI sets log level (we set both BOOSTCLAW_LOG_LEVEL and COPAW_LOG_LEVEL).
LOG_LEVEL_ENV = "COPAW_LOG_LEVEL"

_bootstrap_err: Exception | None = None
try:
    from .envs import load_envs_into_environ

    load_envs_into_environ()
except Exception as exc:
    _bootstrap_err = exc

_t0 = time.perf_counter()
from ._env_compat import get_app_env

setup_logger(get_app_env("LOG_LEVEL", "info"))
if _bootstrap_err is not None:
    logging.getLogger(__name__).warning(
        "copaw: failed to load persisted envs on init: %s",
        _bootstrap_err,
    )
logging.getLogger(__name__).debug(
    "%.3fs package init",
    time.perf_counter() - _t0,
)
