# -*- coding: utf-8 -*-
"""Protect organization providers while allowing personal connections."""

from fastapi import HTTPException


def require_model_route(path: str) -> None:
    """Keep organization provider mutations out of member APIs."""
    parts = path.strip("/").split("/")
    if parts[:2] == ["models", "hub-managed"] or parts[:3] == [
        "models",
        "custom-providers",
        "hub-managed",
    ]:
        raise HTTPException(403, "Organization models are managed")


def require_model_runtime(store, runtime_id: str) -> None:
    """Prevent old, unprovisioned runtimes from serving managed requests."""
    with store.connect() as db:
        row = db.execute(
            "SELECT 1 FROM hub_model_runtime_tokens WHERE runtime_id = ?",
            (runtime_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(409, "Runtime is missing its Hub model capability")
