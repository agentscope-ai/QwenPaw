# -*- coding: utf-8 -*-
"""App-local environment isolation for the stable managed-service API."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import APP_DATA_DIR

_PROCESS_ENV = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
)


def managed_service(
    app,
    name,
    *,
    command,
    env=None,
    inherit_env=(),
    env_factory=None,
    on_before_start=None,
    **kwargs,
):
    env_dir = APP_DATA_DIR / "service-env"
    env_path = env_dir / f"{name}.json"

    async def prepare():
        if on_before_start is not None:
            await on_before_start()
        environment = {
            key: os.environ[key]
            for key in (*_PROCESS_ENV, *inherit_env)
            if key in os.environ
        }
        environment.update(env or {})
        if env_factory is not None:
            environment.update(env_factory())
        env_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=env_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(environment, stream)
            os.replace(temporary, env_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    launcher = Path(__file__).with_name("service_entry.py")
    return app.managed_service(
        name,
        command=(command[0], str(launcher), str(env_path), *command[1:]),
        on_before_start=prepare,
        **kwargs,
    )
