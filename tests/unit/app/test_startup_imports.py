# -*- coding: utf-8 -*-
"""Keep provider-specific SDKs off the HTTP application import path."""

import os
import subprocess
import sys
import textwrap


def test_app_import_does_not_load_inactive_model_sdks(tmp_path):
    env = {
        **os.environ,
        "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_DEPENDENCY_STATE_DIR": str(tmp_path / "dependencies"),
        "QWENPAW_RUNNING_IN_CONTAINER": "true",
        "QWENPAW_TELEMETRY_DISABLED": "true",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                from qwenpaw.app._app import app
                from qwenpaw.providers.model_error_policy import (
                    classify_model_error,
                )

                assert app is not None
                assert classify_model_error(RuntimeError()).kind == "unknown"
                sdks = {"anthropic", "google.genai"} & sys.modules.keys()
                assert not sdks, f"Unexpected SDK imports: {sorted(sdks)}"
                """,
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
