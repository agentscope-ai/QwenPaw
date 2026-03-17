from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _build_console_dist(tmp_path: Path) -> Path:
    console_dir = tmp_path / "console_dist"
    assets_dir = console_dir / "assets"
    assets_dir.mkdir(parents=True)
    (console_dir / "index.html").write_text(
        "<html><body>ok</body></html>",
        encoding="utf-8",
    )
    (assets_dir / "index-test.js").write_text("console.log('ok')", encoding="utf-8")
    return console_dir


def test_console_assets_support_base_url_prefixed_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    console_dir = _build_console_dist(tmp_path)

    monkeypatch.setenv("COPAW_CONSOLE_STATIC_DIR", str(console_dir))
    monkeypatch.setenv("BASE_URL", "custom/prefix-10001")

    from copaw.app import _app as app_module

    app_module = importlib.reload(app_module)
    client = TestClient(app_module.app)

    base_url_prefixed = client.get("/custom/prefix-10001/assets/index-test.js")
    assert base_url_prefixed.status_code == 200
    assert "console.log('ok')" in base_url_prefixed.text

    missing = client.get("/custom/prefix-10001/assets/not-found.js")
    assert missing.status_code == 404


def test_console_assets_support_console_prefix_without_base_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    console_dir = _build_console_dist(tmp_path)

    monkeypatch.setenv("COPAW_CONSOLE_STATIC_DIR", str(console_dir))
    monkeypatch.delenv("BASE_URL", raising=False)

    from copaw.app import _app as app_module

    app_module = importlib.reload(app_module)
    client = TestClient(app_module.app)

    console_prefixed = client.get("/console/assets/index-test.js")
    assert console_prefixed.status_code == 200
    assert "console.log('ok')" in console_prefixed.text
