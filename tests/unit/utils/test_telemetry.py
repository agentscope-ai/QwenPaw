# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import qwenpaw.utils.telemetry as telemetry_module
from qwenpaw.utils.telemetry import (
    TELEMETRY_MARKER_FILE,
    _detect_gpu,
    _safe_get,
    collect_and_upload_telemetry,
    has_telemetry_been_collected,
    is_telemetry_opted_out,
    mark_telemetry_collected,
)

# ---------------------------------------------------------------------------
# _safe_get
# ---------------------------------------------------------------------------


def test_safe_get_success() -> None:
    assert _safe_get(lambda: "hello") == "hello"


def test_safe_get_exception_returns_default() -> None:
    def boom():
        raise RuntimeError("fail")

    assert _safe_get(boom) == "unknown"


def test_safe_get_custom_default() -> None:
    assert _safe_get(lambda: (_ for _ in ()).throw(ValueError), "N/A") == "N/A"


# ---------------------------------------------------------------------------
# has_telemetry_been_collected
# ---------------------------------------------------------------------------


def test_has_collected_no_marker(tmp_path: Path) -> None:
    assert has_telemetry_been_collected(tmp_path) is False


def test_has_collected_v13_format_current_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(
        json.dumps(
            {
                "collected_versions": ["1.0.0"],
                "version": "1.3",
            },
        ),
    )
    assert has_telemetry_been_collected(tmp_path) is True


def test_has_collected_v13_format_different_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "2.0.0",
    )
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(
        json.dumps(
            {
                "collected_versions": ["1.0.0"],
                "version": "1.3",
            },
        ),
    )
    assert has_telemetry_been_collected(tmp_path) is False


def test_has_collected_v11_compat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "0.5.0",
    )
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(json.dumps({"qwenpaw_version": "0.5.0"}))
    assert has_telemetry_been_collected(tmp_path) is True


def test_has_collected_corrupt_marker(tmp_path: Path) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text("not json")
    assert has_telemetry_been_collected(tmp_path) is False


# ---------------------------------------------------------------------------
# is_telemetry_opted_out
# ---------------------------------------------------------------------------


def test_opted_out_no_marker(tmp_path: Path) -> None:
    assert is_telemetry_opted_out(tmp_path) is False


def test_opted_out_true(tmp_path: Path) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(json.dumps({"opted_out": True}))
    assert is_telemetry_opted_out(tmp_path) is True


def test_opted_out_false(tmp_path: Path) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(json.dumps({"opted_out": False}))
    assert is_telemetry_opted_out(tmp_path) is False


def test_opted_out_corrupt(tmp_path: Path) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text("{bad json")
    assert is_telemetry_opted_out(tmp_path) is False


# ---------------------------------------------------------------------------
# mark_telemetry_collected
# ---------------------------------------------------------------------------


def test_mark_collected_creates_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    mark_telemetry_collected(tmp_path)
    marker = tmp_path / TELEMETRY_MARKER_FILE
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert "1.0.0" in data["collected_versions"]
    assert data["version"] == "1.3"
    assert data["opted_out"] is False


def test_mark_collected_appends_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(
        json.dumps(
            {
                "collected_versions": ["0.9.0"],
                "opted_out": False,
                "version": "1.3",
            },
        ),
    )
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    mark_telemetry_collected(tmp_path)
    data = json.loads(marker.read_text())
    assert "0.9.0" in data["collected_versions"]
    assert "1.0.0" in data["collected_versions"]


def test_mark_collected_v11_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(json.dumps({"qwenpaw_version": "0.5.0"}))
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    mark_telemetry_collected(tmp_path)
    data = json.loads(marker.read_text())
    assert "0.5.0" in data["collected_versions"]
    assert "1.0.0" in data["collected_versions"]


def test_mark_collected_preserves_opt_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / TELEMETRY_MARKER_FILE
    marker.write_text(
        json.dumps({"opted_out": True, "collected_versions": []}),
    )
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    mark_telemetry_collected(tmp_path)
    data = json.loads(marker.read_text())
    assert data["opted_out"] is True


def test_mark_collected_opt_out_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    mark_telemetry_collected(tmp_path, opted_out=True)
    data = json.loads((tmp_path / TELEMETRY_MARKER_FILE).read_text())
    assert data["opted_out"] is True


# ---------------------------------------------------------------------------
# _detect_gpu
# ---------------------------------------------------------------------------


def test_detect_gpu_nvidia_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=""),
    )
    assert _detect_gpu() is True


def test_detect_gpu_apple_silicon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(side_effect=FileNotFoundError),
    )
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert _detect_gpu() is True


def test_detect_gpu_no_gpu_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(side_effect=FileNotFoundError),
    )
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert _detect_gpu() is False


# ---------------------------------------------------------------------------
# collect_and_upload_telemetry
# ---------------------------------------------------------------------------


def test_collect_and_upload_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    monkeypatch.setattr(
        telemetry_module,
        "_upload_telemetry_sync",
        lambda _d: True,
    )
    monkeypatch.setattr(
        telemetry_module,
        "get_system_info",
        lambda: {"install_id": "test"},
    )

    result = collect_and_upload_telemetry(tmp_path)
    assert result is True
    assert (tmp_path / TELEMETRY_MARKER_FILE).exists()


def test_collect_and_upload_failure_still_marks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telemetry_module,
        "_get_current_version",
        lambda: "1.0.0",
    )
    monkeypatch.setattr(
        telemetry_module,
        "_upload_telemetry_sync",
        lambda _d: False,
    )
    monkeypatch.setattr(
        telemetry_module,
        "get_system_info",
        lambda: {"install_id": "test"},
    )

    result = collect_and_upload_telemetry(tmp_path)
    assert result is False
    assert (tmp_path / TELEMETRY_MARKER_FILE).exists()
