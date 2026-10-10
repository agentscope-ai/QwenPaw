# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,redefined-outer-name

"""Unit coverage for the desktop (computer_use) live-operation path.

Actual desktop capture needs the Tauri host runtime, which is absent in CI, so
these tests cover everything host-independent: capability probing, graceful
degradation, the ffmpeg capture command, the recorder lifecycle, and the
approval coordinator that single-sources grants to the host access store.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import pytest

from services.media_files.live_operation import (
    RecordedTake,
    TakeManifest,
    computer_use_status,
    run_computer_use_code,
)
from services.media_files.live_operation import desktop as desktop_module
from services.media_files.live_operation.desktop import (
    DesktopController,
)
from services.media_files.live_operation.screen_recorder import (
    _capture_command,
    _crop_filter,
    _viewport_from_bounds,
)

pytestmark = pytest.mark.unit


# ─── capability probing & degradation ───────────────────────────────────


def test_status_reports_each_precondition_separately():
    status = computer_use_status()
    for key in (
        "available",
        "screen_capture_supported",
        "native_helper_platform",
        "host_reachable",
        "host_feature_state_available",
        "host_feature_enabled",
        "ffmpeg",
    ):
        assert key in status
    # Desktop control remains useful without recording; recording reports its
    # own stricter conjunction instead of disabling the whole tool.
    assert status["available"] == (
        status["native_helper_platform"]
        and status["host_reachable"]
        and status["host_feature_state_available"]
        and status["host_feature_enabled"]
    )
    assert status["recording_available"] == (
        status["available"]
        and status["screen_capture_supported"]
        and status["ffmpeg"]
    )


def test_desktop_run_rejects_empty_code_and_host_kill_switch(
    tmp_path: Path,
    monkeypatch,
):
    from services.media_files.live_operation import LiveOperationError

    with pytest.raises(LiveOperationError, match="empty"):
        asyncio.run(
            run_computer_use_code(
                "   ",
                run_root=tmp_path,
                run_id="empty",
                session_id="creator-session",
            ),
        )

    monkeypatch.setattr(
        desktop_module,
        "computer_use_status",
        lambda: {
            "available": False,
            "host_feature_state_available": True,
            "host_feature_enabled": False,
            "native_helper_platform": True,
            "screen_capture_supported": True,
            "host_reachable": True,
        },
    )
    loaded = False

    def should_not_load(_session_id):
        nonlocal loaded
        loaded = True
        raise AssertionError("native client must not load while host is off")

    monkeypatch.setattr(desktop_module, "_load_native_client", should_not_load)
    outcome = asyncio.run(
        run_computer_use_code(
            "await desktop.observe_window()",
            run_root=tmp_path,
            run_id="host-off",
            session_id="creator-session",
        ),
    )

    assert loaded is False
    assert outcome.takes == []
    assert "turned off in the host" in outcome.output


# ─── ffmpeg capture command ─────────────────────────────────────────────


def test_capture_contract_uses_window_bounds_and_platform_backend():
    assert (
        _crop_filter({"x": 40, "y": 60, "width": 800, "height": 600})
        == "crop=800:600:40:60"
    )
    assert _crop_filter({"width": 0, "height": 600}) is None
    viewport = _viewport_from_bounds({"width": 1280, "height": 720})
    assert (viewport.width, viewport.height) == (1280.0, 720.0)
    assert _viewport_from_bounds({"width": 0, "height": 0}) is None
    command = _capture_command(
        ffmpeg="ffmpeg",
        fps=25,
        screen="0",
        crop="crop=800:600:0:0",
        max_duration_seconds=12,
        output=Path("/tmp/take.mp4"),
    )
    if sys.platform == "darwin":
        assert "avfoundation" in command
        assert "0:none" in command
    elif sys.platform == "win32":
        assert "gdigrab" in command
        assert "desktop" in command
    else:
        # Linux has no supported desktop capture backend.
        assert command is None
        return
    joined = " ".join(command)
    assert "crop=800:600:0:0" in joined
    assert "libx264" in command
    assert command[command.index("-t") + 1] == "12"
    assert command[-1] == "/tmp/take.mp4"


# ─── real bridge contracts with injected native/capture planes ──────────


class _FakeNativeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def execute(self, method, params):
        from qwenpaw.app import agent_context

        assert agent_context.get_current_session_id() == "creator-session"
        self.calls.append((method, dict(params)))
        return {"ok": True}

    async def close(self):
        self.closed = True


class _FakeScreenRecorder:
    def __init__(self, *, workspace, fps, max_duration_seconds):
        del fps, max_duration_seconds
        self.workspace = workspace
        self._manifest = None
        self._takes = []

    @property
    def recording(self):
        return self._manifest is not None

    @property
    def manifest(self):
        return self._manifest

    @property
    def takes(self):
        return list(self._takes)

    def elapsed_ms(self):
        return 10 if self.recording else 0

    def start(self, *, label="", window_bounds=None, screen="0"):
        del window_bounds
        assert screen == "0"
        self._manifest = TakeManifest(
            take_id="desktop-take-001",
            label=label,
        )
        return self._manifest.take_id

    def stop(self):
        manifest = self._manifest
        assert manifest is not None
        self._manifest = None
        manifest.duration_ms = 1000
        manifest.frame_count = 25
        output = self.workspace / "desktop-take-001.mp4"
        output.write_bytes(b"fake-mp4")
        self._takes.append(
            RecordedTake(
                take_id=manifest.take_id,
                label=manifest.label,
                video_path=output,
                manifest=manifest,
            ),
        )
        return output, manifest

    def stop_if_recording(self):
        return self.stop() if self.recording else None


def test_explicit_desktop_stop_survives_the_run_and_uses_creator_session(
    tmp_path: Path,
    monkeypatch,
):
    client = _FakeNativeClient()
    monkeypatch.setattr(
        desktop_module,
        "computer_use_status",
        lambda: {"available": True},
    )
    monkeypatch.setattr(
        desktop_module,
        "_load_native_client",
        lambda _sid: client,
    )
    monkeypatch.setattr(desktop_module, "ScreenRecorder", _FakeScreenRecorder)

    outcome = asyncio.run(
        run_computer_use_code(
            'await desktop.launch_app("app:calculator")\n'
            'await recorder.start(label="addition")\n'
            "await recorder.stop()",
            run_root=tmp_path,
            run_id="run-1",
            session_id="creator-session",
        ),
    )

    assert len(outcome.takes) == 1
    assert outcome.takes[0].video_path.read_bytes() == b"fake-mp4"
    assert client.calls == [("launch_app", {"app": "app:calculator"})]
    assert client.closed is True


def test_observation_screenshot_and_element_coordinates_are_preserved(
    tmp_path: Path,
):
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode("ascii")

    class Client:
        def __init__(self):
            self.calls = []

        async def execute(self, method, params):
            self.calls.append((method, dict(params)))
            if method == "observe_window":
                return {
                    "window": {
                        "bounds": {
                            "x": 100,
                            "y": 50,
                            "width": 800,
                            "height": 600,
                        },
                    },
                    "accessibility": {
                        "elements": [
                            {
                                "id": "button-1",
                                "bounds": {
                                    "x": 120,
                                    "y": 70,
                                    "width": 40,
                                    "height": 20,
                                },
                            },
                        ],
                    },
                    "screenshots": [
                        {
                            "id": "shot-1",
                            "origin": {"x": 100, "y": 50},
                            "url": f"data:image/png;base64,{encoded}",
                        },
                    ],
                }
            return {"ok": True}

    class Recorder:
        manifest = TakeManifest(take_id="desktop-take-001")

        @staticmethod
        def elapsed_ms():
            return 100

    client = Client()
    controller = DesktopController(client, Recorder(), tmp_path)
    asyncio.run(controller.observe_window(window_id="window-1"))
    asyncio.run(controller.click(element_id="button-1"))
    asyncio.run(controller.double_click(element_id="button-1"))
    asyncio.run(controller.right_click(element_id="button-1"))

    assert len(controller.screenshots) == 1
    assert Path(controller.screenshots[0]).read_bytes().endswith(b"image")
    assert [fact.op for fact in Recorder.manifest.facts] == [
        "click",
        "double_click",
        "right_click",
    ]
    assert client.calls[-2:] == [
        ("click", {"element_id": "button-1", "count": 2}),
        ("click", {"element_id": "button-1", "button": "right"}),
    ]
    fact = Recorder.manifest.facts[0]
    assert (fact.bbox.x, fact.bbox.y, fact.bbox.width, fact.bbox.height) == (
        20.0,
        20.0,
        40.0,
        20.0,
    )
