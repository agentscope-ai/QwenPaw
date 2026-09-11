# -*- coding: utf-8 -*-
"""QwenPaw 2.0 built-in conversation checkpoints.

A workspace-scoped shadow Git store under ``checkpoints/`` supports optional
automatic snapshots and exposes timeline / snapshot / restore / gc / reset
through the ``/checkpoint`` slash command.

This package is 2.0-only and does not read legacy session formats.
"""

from __future__ import annotations

from .service import CheckpointService
from .models import (
    CheckpointEntry,
    CheckpointError,
    GcResult,
    RestorePlan,
    RestoreResult,
)
from .policy import CheckpointPolicy
from .repository import CheckpointRepository
from .restore import RestoreService
from .runtime import RUNTIME

__all__ = [
    "RUNTIME",
    "CheckpointService",
    "CheckpointPolicy",
    "CheckpointRepository",
    "RestoreService",
    "CheckpointEntry",
    "CheckpointError",
    "GcResult",
    "RestorePlan",
    "RestoreResult",
]
