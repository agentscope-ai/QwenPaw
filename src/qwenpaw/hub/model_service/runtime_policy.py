# -*- coding: utf-8 -*-
"""Protect organization providers while allowing personal connections."""

from fastapi import HTTPException


def require_model_route(path: str) -> None:
    """Keep model-only routes and managed mutations out of member APIs."""
    parts = path.strip("/").split("/")
    if parts[:2] == ["hub", "model-runtime"]:
        raise HTTPException(404, "Not found")
    if parts[:2] == ["models", "hub-managed"] or parts[:3] == [
        "models",
        "custom-providers",
        "hub-managed",
    ]:
        raise HTTPException(403, "Organization models are managed")
