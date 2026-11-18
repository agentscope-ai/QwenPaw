# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPOSITORY_ROOT / "plugins" / "apps" / "qwenpaw-data"
VERIFY_FILE = APP_DIR / "scripts" / "verify-data-console.py"
SNAPSHOT_DIR = APP_DIR / "ui" / "public" / "data-console"
BRIDGE_FILE = APP_DIR / "scripts" / "data-console" / "paw-bridge.js"
PATCH_FILE = (
    APP_DIR / "scripts" / "data-console" / "patches" / "console-embed.patch"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_console_verifier_under_test",
        VERIFY_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(tmp_path: Path):
    verifier = _load_verifier()
    root = tmp_path / "data-console"
    assets = root / "assets"
    assets.mkdir(parents=True)
    bridge = 'var API_PREFIX = "/api/qwenpaw-data/";\n'
    (root / "paw-bridge.js").write_text(bridge, encoding="utf-8")
    (assets / "index.js").write_text("export {};\n", encoding="utf-8")
    (assets / "style.css").write_text("body {}\n", encoding="utf-8")
    (root / "index.html").write_text(
        "<html><head>"
        '<script src="./paw-bridge.js"></script>'
        '<script type="module" src="./assets/index.js"></script>'
        '<link rel="stylesheet" href="./assets/style.css">'
        "</head></html>",
        encoding="utf-8",
    )
    (root / "BUILD_INFO").write_text(
        "\n".join(
            (
                "format_version=1",
                "source_project=QwenPaw-Data-Cloud",
                f"source_commit={'a' * 40}",
                f"source_lock_sha256={'b' * 64}",
                f"patch_sha256={'c' * 64}",
                f"bridge_sha256={verifier.sha256(root / 'paw-bridge.js')}",
                "gateway_base=/api/qwenpaw-data/engine",
                "context_console_url=/api/frontend_plugin/qwenpaw-data/files/"
                "ui/dist/context-console/index.html#",
            ),
        )
        + "\n",
        encoding="utf-8",
    )
    verifier.write_checksums(root)
    return verifier, root


def test_checked_in_data_console_snapshot_is_valid() -> None:
    verifier = _load_verifier()

    verifier.validate(SNAPSHOT_DIR, BRIDGE_FILE, PATCH_FILE)


@pytest.mark.parametrize(
    ("relative", "content", "message"),
    [
        ("assets/style.css", "body { color: red; }", "checksum mismatch"),
        ("assets/leak.js", "https://gitlab.alibaba/secret", "internal marker"),
        ("assets/source.js.map", "{}", "source map"),
    ],
)
def test_data_console_verifier_rejects_corruption(
    tmp_path: Path,
    relative: str,
    content: str,
    message: str,
) -> None:
    verifier, root = _snapshot(tmp_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if relative != "assets/style.css":
        verifier.write_checksums(root)

    with pytest.raises(verifier.ValidationError, match=message):
        verifier.validate(root, None)


def test_data_console_verifier_rejects_malformed_provenance(
    tmp_path: Path,
) -> None:
    verifier, root = _snapshot(tmp_path)
    info = root / "BUILD_INFO"
    info.write_text(
        info.read_text(encoding="utf-8").replace(f"{'a' * 40}", "short"),
        encoding="utf-8",
    )
    verifier.write_checksums(root)

    with pytest.raises(verifier.ValidationError, match="full Git commit"):
        verifier.validate(root, None)


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("index.html", "<script>media.src = '/loading.png';</script>"),
        ("assets/index.js", "const image = {src:`/loading${index}.png`};"),
        ("assets/style.css", "body { background: url('/loading.png'); }"),
    ],
)
def test_data_console_verifier_rejects_root_absolute_asset(
    tmp_path: Path,
    relative: str,
    content: str,
) -> None:
    verifier, root = _snapshot(tmp_path)
    target = root / relative
    target.write_text(
        target.read_text(encoding="utf-8") + content,
        encoding="utf-8",
    )
    verifier.write_checksums(root)

    with pytest.raises(
        verifier.ValidationError,
        match="root-absolute static asset",
    ):
        verifier.validate(root, None)


def test_data_console_verifier_rejects_bridge_drift(tmp_path: Path) -> None:
    verifier, root = _snapshot(tmp_path)
    canonical = tmp_path / "canonical-bridge.js"
    canonical.write_text("different\n", encoding="utf-8")

    with pytest.raises(verifier.ValidationError, match="canonical bridge"):
        verifier.validate(root, canonical)


def test_data_console_verifier_rejects_patch_drift(tmp_path: Path) -> None:
    verifier, root = _snapshot(tmp_path)
    canonical = tmp_path / "console-embed.patch"
    canonical.write_text("different\n", encoding="utf-8")

    with pytest.raises(verifier.ValidationError, match="canonical patch"):
        verifier.validate(root, None, canonical)


def test_data_console_verifier_rejects_symlinks(tmp_path: Path) -> None:
    verifier, root = _snapshot(tmp_path)
    try:
        (root / "linked.js").symlink_to(root / "assets" / "index.js")
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(verifier.ValidationError, match="symlink"):
        verifier.validate(root, None)
