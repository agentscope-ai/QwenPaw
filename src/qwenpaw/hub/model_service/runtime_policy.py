# -*- coding: utf-8 -*-
"""Guard legacy runtime APIs when organization model ownership is active."""

from fastapi import HTTPException


def require_model_route(path: str, method: str, enabled: bool) -> None:
    """Permit directory reads and model selection, never provider mutation."""
    if not enabled or not path.startswith("models"):
        return
    readable = method == "GET" and path.rstrip("/") in {
        "models",
        "models/active",
    }
    selectable = method == "PUT" and path == "models/active"
    if not readable and not selectable:
        raise HTTPException(403, "Organization models are managed")


def require_model_runtime(store, runtime_id: str) -> None:
    """Prevent old, unprovisioned runtimes from serving managed requests."""
    with store.connect() as db:
        row = db.execute(
            "SELECT 1 FROM hub_model_runtime_tokens WHERE runtime_id = ?",
            (runtime_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(409, "Restart runtime to enable managed models")
