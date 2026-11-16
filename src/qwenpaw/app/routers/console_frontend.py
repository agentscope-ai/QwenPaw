# -*- coding: utf-8 -*-
"""Expose the Console shipped with this Runtime to its Platform host."""

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...__version__ import __version__


def create_console_frontend_router(directory: str) -> APIRouter:
    """Keep every resource inside one versioned Console build directory."""
    router = APIRouter(prefix="/api/console/frontend")
    root = Path(directory).resolve()

    def manifest_data() -> dict:
        try:
            content = (root / "index.html").read_bytes()
        except OSError as exc:
            raise HTTPException(503, "Console is not installed") from exc
        protocol = re.search(
            rb'name="qwenpaw-console-protocol" content="(\d+)"',
            content,
        )
        return {
            "protocol": int(protocol[1]) if protocol else 0,
            "build": hashlib.sha256(content).hexdigest()[:24],
            "runtime_version": __version__,
        }

    @router.get("")
    def manifest():
        return manifest_data()

    @router.get("/assets/{build}/{resource:path}")
    def resource(build: str, resource: str):
        if build != manifest_data()["build"]:
            raise HTTPException(409, "Console was updated; reload the page")
        path = (root / resource).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Console resource not found")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    return router
