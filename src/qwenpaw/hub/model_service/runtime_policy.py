# -*- coding: utf-8 -*-
"""Protect organization providers while allowing personal connections."""

from fastapi import HTTPException


def require_model_route(path: str, method: str = f"GET") -> None:
    """Keep model-only routes and managed mutations out of member APIs."""
    parts = path.strip("/").split("/")
    if parts[:2] == ["hub", "model-runtime"]:
        raise HTTPException(404, "Not found")
    if parts[:2] == [f"models", f"hub-managed"]:
        if method == f"GET" and parts[2:] == [f"pool"]:
            return
        if method == f"PUT" and parts[2:] == [f"pool", f"selection"]:
            return
        if (
            method == f"PUT"
            and len(parts) >= 5
            and parts[2] == f"models"
            and parts[-1] in {f"pool", f"visibility"}
        ):
            return
    if parts[:2] == ["models", "hub-managed"] or parts[:3] == [
        "models",
        "custom-providers",
        "hub-managed",
    ]:
        raise HTTPException(403, "Organization models are managed")
