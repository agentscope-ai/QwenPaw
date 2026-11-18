# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for the Docker application Python runtime."""

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_docker_uses_standalone_python_for_app_venv() -> None:
    """Keep system Python separate from the application environment."""
    dockerfile = (REPO_ROOT / "deploy/Dockerfile").read_text(
        encoding="utf-8",
    )
    stage = "python3 /tmp/stage_python_runtime.py"
    venv = "/opt/qwenpaw-python/python/bin/python3 -m venv /app/venv"
    install = "uv pip install --python /app/venv/bin/python"

    assert (
        "COPY scripts/pack-tauri/stage_python_runtime.py "
        "/tmp/stage_python_runtime.py"
    ) in dockerfile
    assert "--dest /opt/qwenpaw-python --python-version 3.11" in dockerfile
    assert dockerfile.index(stage) < dockerfile.index(venv)
    assert dockerfile.index(venv) < dockerfile.index(install)
    assert 'ENV PATH="/app/venv/bin:$PATH"' in dockerfile
    assert "RUN python3 -m venv" not in dockerfile
    assert "    python3  \\" in dockerfile
    assert "    supervisor  \\" in dockerfile


@pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
def test_staging_supports_linux_image_architectures(
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
) -> None:
    """The shared desktop stager must select matching Linux install assets."""
    spec = importlib.util.spec_from_file_location(
        "stage_python_runtime",
        REPO_ROOT / "scripts/pack-tauri/stage_python_runtime.py",
    )
    assert spec is not None and spec.loader is not None
    stager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stager)
    monkeypatch.setattr(stager.platform, "system", lambda: "Linux")
    monkeypatch.setattr(stager.platform, "machine", lambda: machine)

    triple = stager._host_triple()
    assert triple == f"{machine}-unknown-linux-gnu"
    name = (
        f"cpython-3.11.15+{stager.DEFAULT_RELEASE}-{triple}"
        "-install_only.tar.gz"
    )
    asset = {
        "name": name,
        "browser_download_url": "https://example.com/python",
    }
    assert (
        stager._asset_url_from_release(
            {"assets": [asset]},
            "3.11",
            triple,
        )
        == asset["browser_download_url"]
    )
