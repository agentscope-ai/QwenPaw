# -*- coding: utf-8 -*-
import logging
import os
import time

# Acquire environment custody before compatibility shims or third-party imports.
# The lazy plugins package and this module are stdlib-only and PYZ compatible.
from .plugins import dependency_maintenance as _environment_custody

_environment_custody.state_root()
_environment_custody.lease_environment(_environment_custody.host_sites())

# These imports must follow environment custody acquisition.
from . import _compat as _compat_bootstrap  # noqa: E402
from .utils.logging import setup_logger  # noqa: E402

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
