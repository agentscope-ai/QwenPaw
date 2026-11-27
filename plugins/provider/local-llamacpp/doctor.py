# -*- coding: utf-8 -*-
"""Read-only local installation and runtime-owner diagnostics."""

import os

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.doctor import DoctorResult

from .io_helpers import run_io
from .runtime_release import server_executable


async def check_local_files(provider, call):
    if not call.deep:
        return [
            DoctorResult(
                "SKIP",
                "Local model details require qwenpaw doctor --deep",
            ),
        ]

    directory = await provider.data_directory()
    selected = bool(
        call.selected_providers & {"qwenpaw-local", "copaw-local"},
    )

    def inspect_files():
        binary = server_executable(directory / "bin", windows=os.name == "nt")
        status = "OK"
        message = f"Local llama.cpp binary: {binary}"
        if not binary.is_file():
            status = "FAIL" if selected else "SKIP"
            if not selected:
                message += " (not selected)"
        results = [
            DoctorResult(status, message),
        ]
        model_files = sum(1 for _ in (directory / "models").rglob("*.gguf"))
        results.append(
            f"Local downloaded model files: {model_files} ({directory / 'models'})",
        )
        return results

    return await run_io(inspect_files)


async def check_local_server(call):
    if not call.deep:
        return []
    try:
        status = await call.get_runtime("local-models/diagnostics")
    except SDKError as exc:
        return [
            DoctorResult(
                "SKIP",
                f"Local server status unavailable from the selected App: {exc}",
            ),
        ]
    if status.get("running"):
        return [
            DoctorResult(
                "OK",
                "Local server process is running: "
                f"model={status.get('model_name')}, port={status.get('port')}, "
                f"pid={status.get('pid')}",
            ),
        ]
    return [
        DoctorResult(
            "SKIP",
            "Local server is stopped; inference was not checked",
        ),
    ]
