# -*- coding: utf-8 -*-
"""Expose the Console shipped with this Runtime to its Platform host."""

import hashlib
import re
import stat
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ...__version__ import __version__


def create_console_frontend_router(directory: str) -> APIRouter:
    """Keep every resource inside one versioned Console build directory."""
    router = APIRouter(prefix="/api/console/frontend")
    root = Path(directory).resolve()
    assets = StaticFiles(directory=root, check_dir=False)

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
        try:
            path, file_stat = assets.lookup_path(resource)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "Console resource not found") from exc
        if file_stat is None or not stat.S_ISREG(file_stat.st_mode):
            raise HTTPException(404, "Console resource not found")
        return FileResponse(
            path,
            stat_result=file_stat,
            headers={"Cache-Control": "no-store"},
        )

    return router
