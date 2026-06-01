# -*- coding: utf-8 -*-
"""Per-request context propagation for tool guard."""
from __future__ import annotations

import contextvars
from typing import Dict

_REQUEST_CONTEXT_VAR: contextvars.ContextVar[
    Dict[str, str]
] = contextvars.ContextVar("_qp_request_context", default={})


def _current_request_context() -> Dict[str, str]:
    """Return the active per-request context (or empty dict)."""
    return _REQUEST_CONTEXT_VAR.get() or {}
