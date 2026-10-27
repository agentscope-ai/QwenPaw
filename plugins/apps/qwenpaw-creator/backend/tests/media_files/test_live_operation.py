# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,redefined-outer-name

"""Unit coverage for live operation: facts, recording bounds and publication."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.media_files.live_operation import (
    ActionFact,
    BoundingBox,
    TakeManifest,
    Viewport,
    build_image_records,
    build_take_records,
    facts_within,
    normalized_location,
    project_location_to_canvas,
)
from services.media_files.live_operation.bridge import (
    AgentRecorder,
    LiveOperationError,
    _ActivePage,
    _BoundBrowser,
    _BoundPage,
    _compile,
    run_browser_code,
)
from services.media_files.live_operation.recorder import (
    RecorderError,
    TakeRecorder,
    _viewport_from_metadata,
)
from services.media_files.live_operation.recording_link import (
    RecordingControlLink,
    _operation_name,
)

from services.media_files.live_operation.session import (
    LiveBrowserSession,
    LiveSessionError,
)

pytestmark = pytest.mark.unit


# ─── coordinate projection ──────────────────────────────────────────────


def test_bound_browser_allows_only_run_safe_sdk_delegations() -> None:
    class BrowserFacade:
        public_value = "visible"
        _engine = object()

        async def pages(self):
            return ["page-1"]

        async def close(self):
            raise AssertionError("bridge must own session cleanup")

    class Session:
        browser = BrowserFacade()

    browser = _BoundBrowser(Session(), _ActivePage())
    assert asyncio.run(browser.pages()) == ["page-1"]
    with pytest.raises(LiveOperationError, match="unavailable"):
        getattr(browser, "public_value")
    with pytest.raises(LiveOperationError, match="unavailable"):
        getattr(browser, "_engine")
    with pytest.raises(LiveOperationError, match="unavailable"):
        getattr(browser, "close")


def test_bound_browser_and_page_reject_non_http_navigation() -> None:
    class RawPage:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def goto(self, url: str):
            self.urls.append(url)
            return {"url": url}

        async def snapshot(self):
            return "snapshot"

    class BrowserFacade:
        def __init__(self) -> None:
            self.page = RawPage()
            self.urls: list[str | None] = []

        async def open(self, url: str | None = None):
            self.urls.append(url)
            return self.page

        async def present(self, url: str | None = None):
            self.urls.append(url)
            return self.page

    class Session:
        browser = BrowserFacade()

    async def exercise() -> None:
        active_page = _ActivePage()
        browser = _BoundBrowser(Session(), active_page)
        page = await browser.open("https://example.com/path")
        assert isinstance(page, _BoundPage)
        assert active_page.page is browser._session.browser.page
        assert await page.snapshot() == "snapshot"
        assert await page.goto("http://example.org/next") == {
            "url": "http://example.org/next",
        }
        for unsafe in (
            "file:///etc/passwd",
            "data:text/html,unsafe",
            "javascript:alert(1)",
            "vbscript:msgbox(1)",
            "example.net/no-scheme",
            "https://example.com/line\nfeed",
        ):
            with pytest.raises(LiveOperationError, match="URL"):
                await browser.present(unsafe)
            with pytest.raises(LiveOperationError, match="URL"):
                await page.goto(unsafe)

    asyncio.run(exercise())


def test_bounding_box_rejects_degenerate_rectangles():
    assert (
        BoundingBox.from_raw({"x": 1, "y": 2, "width": 0, "height": 5}) is None
    )
    assert BoundingBox.from_raw({"x": 1, "y": 2, "width": 5}) is None
    assert BoundingBox.from_raw(None) is None
    assert (
        BoundingBox.from_raw(
            {"x": float("nan"), "y": 2, "width": 5, "height": 5},
        )
        is None
    )
    box = BoundingBox.from_raw({"x": 1.5, "y": 2.5, "width": 4, "height": 6})
    assert (box.x, box.y, box.width, box.height) == (1.5, 2.5, 4.0, 6.0)


def test_coordinate_helpers_clip_and_validate_viewports():
    viewport = Viewport(100.0, 100.0)
    assert normalized_location(
        BoundingBox(x=-20.0, y=80.0, width=40.0, height=40.0),
        viewport,
    ) == {"x": 0.1, "y": 0.9, "width": 0.2, "height": 0.2}
    assert (
        normalized_location(
            BoundingBox(x=150.0, y=150.0, width=10.0, height=10.0),
            viewport,
        )
        is None
    )
    assert (
        normalized_location(
            BoundingBox(x=0.0, y=0.0, width=10.0, height=10.0),
            Viewport(0.0, 0.0),
        )
        is None
    )
    assert _viewport_from_metadata(
        {"deviceWidth": 1280, "deviceHeight": 720, "pageScaleFactor": 1},
    ) == Viewport(1280.0, 720.0)
    assert (
        _viewport_from_metadata({"deviceWidth": 0, "deviceHeight": 0}) is None
    )


def test_action_location_projects_and_fails_closed():
    assert project_location_to_canvas(
        {"x": 0.75, "y": 0.25, "width": 0.1, "height": 0.08},
        {
            "x": 0.35,
            "y": 0.65,
            "width": 1.5,
            "height": 1.5,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
        },
    ) == {"x": 0.725, "y": 0.275, "width": 0.15, "height": 0.12}
    assert project_location_to_canvas(
        {"x": 0.95, "y": 0.5, "width": 0.2, "height": 0.2},
        {
            "x": 0.5,
            "y": 0.5,
            "width": 0.8,
            "height": 0.8,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
        },
    ) == {"x": 0.86, "y": 0.5, "width": 0.16, "height": 0.16}
    assert (
        project_location_to_canvas(
            {"x": 0.98, "y": 0.5, "width": 0.08, "height": 0.2},
            {
                "x": -0.6,
                "y": 0.5,
                "width": 1.0,
                "height": 1.0,
            },
        )
        is None
    )
    source = {"x": 0.5, "y": 0.5, "width": 0.2, "height": 0.2}
    assert project_location_to_canvas(source, None) == source
    assert project_location_to_canvas(source, {"rotation_degrees": 15}) is None
    assert project_location_to_canvas({"x": "bad"}, None) is None


# ─── manifest shape ─────────────────────────────────────────────────────


def _manifest_with_facts() -> TakeManifest:
    manifest = TakeManifest(take_id="take-001", label="搜索仓库")
    manifest.viewport = Viewport(1280.0, 720.0)
    manifest.video_width = 1280
    manifest.video_height = 720
    manifest.fps = 25
    manifest.duration_ms = 4200
    manifest.frame_count = 30
    manifest.record(
        ActionFact(
            op="click",
            t_start_ms=1000,
            t_end_ms=1200,
            target='get_by_role("button", name="Search")',
            bbox=BoundingBox(640.0, 360.0, 128.0, 72.0),
        ),
    )
    manifest.record(
        ActionFact(
            op="navigate",
            t_start_ms=2000,
            t_end_ms=2600,
            target="https://example.com",
        ),
    )
    return manifest


def test_manifest_serializes_facts_with_projected_locations():
    payload = json.loads(_manifest_with_facts().as_json_bytes())
    assert payload["schema"] == "creator.live_operation.take_manifest"
    assert payload["take_id"] == "take-001"
    assert payload["label"] == "搜索仓库"
    click, navigate = payload["facts"]
    assert click["op"] == "click"
    assert click["bbox"] == {
        "x": 640.0,
        "y": 360.0,
        "width": 128.0,
        "height": 72.0,
    }
    assert click["location"] == {
        "x": 0.55,
        "y": 0.55,
        "width": 0.1,
        "height": 0.1,
    }
    # A navigation has no rectangle, and must not invent one.
    assert "location" not in navigate


def test_facts_within_selects_rebases_and_retimes_clip_actions():
    manifest = json.loads(_manifest_with_facts().as_json_bytes())
    selected = facts_within(manifest, start_ms=1500, end_ms=3000)
    assert [fact["op"] for fact in selected] == ["navigate"]
    assert selected[0]["clip_offset_ms"] == 500
    assert not facts_within(manifest, start_ms=9000, end_ms=9500)
    assert not facts_within({"facts": "broken"}, start_ms=0, end_ms=1)
    selected = facts_within(manifest, start_ms=1100, end_ms=1150)
    assert [fact["op"] for fact in selected] == ["click"]
    assert selected[0]["clip_offset_ms"] == 0
    selected = facts_within(
        manifest,
        start_ms=500,
        end_ms=3000,
        playback_rate=2.0,
    )
    assert [fact["clip_offset_ms"] for fact in selected] == [250, 750]
    assert not facts_within(
        manifest,
        start_ms=0,
        end_ms=3000,
        playback_rate=float("nan"),
    )


# ─── recorded operation vocabulary ──────────────────────────────────────


def test_only_screen_changing_verbs_become_facts():
    assert _operation_name("locator_action", {"action": "click"}) == "click"
    assert _operation_name("navigate", {}) == "navigate"
    assert (
        _operation_name("input", {"kind": "mouse", "action": "click"})
        == "mouse_click"
    )
    # Perception must stay free: reading a page is not an action.
    assert _operation_name("capture_tree", {}) is None
    assert _operation_name("locator_read", {"prop": "inner_text"}) is None
    assert _operation_name("screenshot", {}) is None


# ─── recording link behaviour ───────────────────────────────────────────


class _FakeLink:
    """A control link that answers the two verbs recording depends on."""

    variant = "playwright"

    def __init__(
        self,
        *,
        bbox: dict | None = None,
        fail_action: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._bbox = bbox
        self._fail_action = fail_action

    def is_available(self) -> bool:
        return True

    def on_event(self, sink):  # noqa: ARG002 - protocol shape only
        del sink
        return lambda: None

    async def request(
        self,
        method,
        params,
        *,
        timeout=None,
    ):
        del timeout  # accepted for protocol parity; unused by the fake
        self.calls.append((method, dict(params)))
        if method == "locator_bounding_box":
            return {"value": self._bbox}
        if method == "locator_action" and self._fail_action:
            raise RuntimeError("click failed")
        if method == "screenshot":
            return {"path": "/tmp/shot-1.png"}
        return {"evidence": "ok"}


def _link_with(
    manifest: TakeManifest | None,
    **kwargs,
) -> tuple[RecordingControlLink, _FakeLink]:
    inner = _FakeLink(**kwargs)
    link = RecordingControlLink(
        inner,
        manifest_source=lambda: manifest,
        elapsed_ms=lambda: 1234,
    )
    return link, inner


def test_actions_are_recorded_with_a_pre_action_rectangle():
    manifest = TakeManifest(take_id="take-001")
    link, inner = _link_with(
        manifest,
        bbox={"x": 10, "y": 20, "width": 30, "height": 40},
    )
    params = {
        "workspace_id": "w",
        "session_id": "s",
        "page_id": "p",
        "spec": [
            {
                "method": "get_by_role",
                "args": ["button"],
                "kwargs": [["name", "Save"]],
            },
            {"method": "first", "args": [], "kwargs": []},
        ],
        "action": "click",
    }
    asyncio.run(link.request("locator_action", params))
    # The rectangle is read before the action, because a click that navigates
    # leaves nothing to measure afterwards.
    assert [method for method, _ in inner.calls] == [
        "locator_bounding_box",
        "locator_action",
    ]
    fact = manifest.facts[0]
    assert fact.op == "click"
    assert fact.target == 'get_by_role("button", name="Save").first()'
    assert fact.bbox == BoundingBox(10.0, 20.0, 30.0, 40.0)
    assert fact.failed is False


def test_a_failed_action_is_still_recorded_and_reraised():
    manifest = TakeManifest(take_id="take-001")
    link, _ = _link_with(manifest, fail_action=True)
    with pytest.raises(RuntimeError):
        asyncio.run(
            link.request(
                "locator_action",
                {
                    "workspace_id": "w",
                    "session_id": "s",
                    "spec": [],
                    "action": "click",
                },
            ),
        )
    assert manifest.facts[0].failed is True


def test_action_finishing_at_duration_watchdog_is_clipped_to_video():
    manifest = TakeManifest(take_id="take-001")
    active = manifest

    class SlowLink(_FakeLink):
        async def request(self, method, params, *, timeout=None):
            nonlocal active
            if method == "locator_action":
                manifest.duration_ms = 1300
                active = None
            return await super().request(method, params, timeout=timeout)

    link = RecordingControlLink(
        SlowLink(),
        manifest_source=lambda: active,
        elapsed_ms=lambda: 1200 if active is not None else 0,
    )
    asyncio.run(
        link.request(
            "locator_action",
            {
                "workspace_id": "w",
                "session_id": "s",
                "page_id": "p",
                "spec": [],
                "action": "click",
            },
        ),
    )
    assert manifest.facts[0].t_start_ms == 1200
    assert manifest.facts[0].t_end_ms == 1300


def test_off_camera_actions_skip_bbox_and_screenshots_are_deduplicated():
    link, inner = _link_with(None)
    asyncio.run(
        link.request(
            "locator_action",
            {
                "workspace_id": "w",
                "session_id": "s",
                "spec": [],
                "action": "click",
            },
        ),
    )
    for _ in range(2):
        asyncio.run(
            link.request(
                "screenshot",
                {"workspace_id": "w", "session_id": "s"},
            ),
        )
    # Without a running take there is no bbox probe either: perceiving and
    # acting off-camera must cost nothing.
    assert [method for method, _ in inner.calls] == [
        "locator_action",
        "screenshot",
        "screenshot",
    ]
    assert link.screenshots == ["/tmp/shot-1.png"]


def test_scroll_records_timing_without_a_misleading_document_box():
    manifest = TakeManifest(take_id="take-001")
    link, inner = _link_with(
        manifest,
        bbox={"x": 0, "y": 0, "width": 1280, "height": 18000},
    )
    asyncio.run(
        link.request(
            "locator_action",
            {
                "workspace_id": "w",
                "session_id": "s",
                "page_id": "p",
                "spec": [
                    {"method": "locator", "args": ["body"], "kwargs": []},
                ],
                "action": "scroll",
            },
        ),
    )

    assert [method for method, _ in inner.calls] == ["locator_action"]
    assert manifest.facts[0].op == "scroll"
    assert manifest.facts[0].bbox is None


# ─── recorder lifecycle ─────────────────────────────────────────────────


class _FakeCdp:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self._handlers: dict = {}

    def on(self, event, handler):
        self._handlers[event] = handler

    def remove_listener(self, event, handler):
        if self._handlers.get(event) is handler:
            self._handlers.pop(event)

    async def send(self, method, params=None):
        del params  # the fake records only which methods were sent
        self.sent.append(method)
        return {}


class _FailingStartCdp(_FakeCdp):
    async def send(self, method, params=None):
        await super().send(method, params)
        if method == "Page.startScreencast":
            raise RuntimeError("start failed")
        return {}


def test_recorder_rejects_overlapping_and_empty_takes(tmp_path: Path):
    recorder = TakeRecorder(workspace=tmp_path)
    cdp = _FakeCdp()
    asyncio.run(recorder.start(cdp, label="first"))
    assert recorder.recording is True
    with pytest.raises(RecorderError):
        asyncio.run(recorder.start(cdp, label="second"))
    with pytest.raises(RecorderError, match="no frames"):
        asyncio.run(recorder.stop())
    assert recorder.recording is False


def test_failed_start_removes_listener_and_allows_a_clean_retry(
    tmp_path: Path,
):
    recorder = TakeRecorder(workspace=tmp_path)
    cdp = _FailingStartCdp()

    async def scenario():
        with pytest.raises(RuntimeError, match="start failed"):
            await recorder.start(cdp)
        assert recorder.recording is False
        assert not cdp._handlers
        healthy = _FakeCdp()
        await recorder.start(healthy)
        assert recorder.recording is True

    asyncio.run(scenario())


class _EventCdp:
    def __init__(self) -> None:
        self.handlers: list = []
        self.sent: list[str] = []

    def on(self, event, handler):
        assert event == "Page.screencastFrame"
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        assert event == "Page.screencastFrame"
        self.handlers.remove(handler)

    async def send(self, method, params=None):
        del params
        self.sent.append(method)
        return {}

    def emit_frame(self):
        payload = {
            "data": base64.b64encode(b"jpeg-frame").decode("ascii"),
            "sessionId": 1,
            "metadata": {"deviceWidth": 800, "deviceHeight": 600},
        }
        for handler in list(self.handlers):
            handler(payload)


def _fake_assembler(tmp_path: Path):
    def assemble(take_id, frames, stopped_at):
        del frames, stopped_at
        output = tmp_path / f"{take_id}.mp4"
        output.write_bytes(b"fake-mp4")
        return output

    return assemble


def test_each_take_removes_its_cdp_listener(tmp_path: Path, monkeypatch):
    recorder = TakeRecorder(workspace=tmp_path)
    monkeypatch.setattr(recorder, "_assemble", _fake_assembler(tmp_path))
    monkeypatch.setattr(
        "services.media_files.live_operation.recorder._probe_output",
        lambda _path: (1280, 720, 7120),
    )
    cdp = _EventCdp()

    async def scenario():
        for label in ("first", "second"):
            await recorder.start(cdp, label=label)
            assert len(cdp.handlers) == 1
            cdp.emit_frame()
            await asyncio.sleep(0)
            await recorder.stop()
            assert not cdp.handlers

    asyncio.run(scenario())
    assert [take.label for take in recorder.takes] == ["first", "second"]
    assert [take.manifest.duration_ms for take in recorder.takes] == [
        7120,
        7120,
    ]
    assert [take.manifest.frame_count for take in recorder.takes] == [178, 178]


def test_take_duration_ceiling_auto_stops_and_remains_collectable(
    tmp_path: Path,
    monkeypatch,
):
    recorder = TakeRecorder(workspace=tmp_path)
    recorder._max_duration = 0.01
    monkeypatch.setattr(recorder, "_assemble", _fake_assembler(tmp_path))
    monkeypatch.setattr(
        "services.media_files.live_operation.recorder._probe_output",
        lambda _path: (800, 600, 500),
    )
    cdp = _EventCdp()

    async def scenario():
        await recorder.start(cdp, label="bounded")
        cdp.emit_frame()
        await asyncio.sleep(0.5)
        assert recorder.recording is False
        # Agent code that calls stop just after the ceiling receives the take
        # that was safely auto-stopped instead of failing and losing it.
        return await recorder.stop()

    take = asyncio.run(scenario())
    assert take.label == "bounded"
    assert len(recorder.takes) == 1


def test_creator_browser_sessions_are_explicit_and_host_safe(monkeypatch):
    from qwenpaw.browser.runtime import links as runtime_links
    from qwenpaw.browser.sdk.contracts import Owner
    from qwenpaw.browser.sdk.execution_context import (
        ExecutionContext,
        get_execution_context,
        reset_execution_context,
        set_execution_context,
    )

    class Link:
        variant = "playwright"
        supported_contexts = frozenset({"incognito", "profile"})

        def __init__(self, name):
            self.name = name
            self.calls = []

        def is_available(self):
            return True

        async def request(self, method, params, *, timeout=None):
            del timeout
            self.calls.append((method, dict(params)))
            if method == "open_session":
                return {"headless": True}
            if method == "new_page":
                return {"page_id": f"page-{self.name}", "url": ""}
            return {}

    global_link = Link("qwenpaw-host")
    one = Link("one")
    two = Link("two")
    runtime_links.register_local(global_link)
    before = runtime_links.registered_links()

    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda: SimpleNamespace(
            browser=SimpleNamespace(identity="auto", backend="auto"),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.browser.runtime.launch_resolve.resolve_launch_env",
        lambda _config: {},
    )

    async def use_explicit(link):
        session = await LiveBrowserSession.connect(
            links=(link,),
            identity="guest",
        )
        assert session.control_link is link
        page = await session.browser.open()
        await asyncio.sleep(0.02)
        await session.close()
        return page.id

    async def scenario():
        host_context = ExecutionContext(
            owner=Owner(workspace_id="host", session_id="host-session"),
        )
        host_browser = object()
        host_context.browser = host_browser
        token = set_execution_context(host_context)
        try:
            pages = await asyncio.gather(
                use_explicit(one),
                use_explicit(two),
            )
            # Creator teardown must not clear an enclosing QwenPaw browser.
            assert get_execution_context().browser is host_browser
            return pages
        finally:
            reset_execution_context(token)

    try:
        assert asyncio.run(scenario()) == ["page-one", "page-two"]
        assert runtime_links.registered_links() == before
        assert runtime_links.link_for("playwright") is global_link
        assert not global_link.calls
        assert [method for method, _ in one.calls] == [
            "open_session",
            "new_page",
            "close_session",
        ]
        assert [method for method, _ in two.calls] == [
            "open_session",
            "new_page",
            "close_session",
        ]
    finally:
        runtime_links.unregister_local(global_link)


# ─── publication records ────────────────────────────────────────────────


def test_take_records_carry_the_manifest_pointer():
    manifest = _manifest_with_facts()
    video_file, manifest_file, version, logical_asset_id = build_take_records(
        project_id="proj-1",
        take_id="take-001",
        label="搜索仓库",
        video=b"same-video",
        manifest_payload=manifest.as_json_bytes(),
        duration_seconds=4.2,
        request_id="req-1",
    )
    assert video_file.media_type == "video/mp4"
    assert video_file.relative_uri.startswith("assets/sources/")
    assert manifest_file.schema_name == "creator.live_operation.take_manifest"
    assert version.media_kind == "video"
    assert version.duration_seconds == 4.2
    assert version.file_id == video_file.file_id
    # The sidecar pointer is what lets motion design find the recorded facts.
    assert version.metadata["manifestFileId"] == manifest_file.file_id
    assert version.metadata["sourceKind"] == "live_operation_take"
    assert logical_asset_id.startswith("asset-")
    second = build_take_records(
        project_id="proj-1",
        take_id="take-002",
        label="b",
        video=b"same-video",
        manifest_payload=manifest.as_json_bytes(),
        duration_seconds=4.2,
        request_id="req-2",
    )
    # Re-publishing the same footage must not duplicate the asset.
    assert video_file.file_id == second[0].file_id
    assert version.version_id == second[2].version_id


def test_screenshot_records_preserve_source_kind_and_media_type():
    indexed, version, logical_asset_id = build_image_records(
        project_id="proj-1",
        name="WebP screenshot",
        content=b"webp-bytes",
        media_type="image/webp",
        request_id="req-1",
    )
    assert indexed.relative_uri.endswith(".webp")
    assert indexed.media_type == "image/webp"
    assert version.media_type == "image/webp"
    assert version.media_kind == "image"
    assert version.metadata["sourceKind"] == "live_operation_screenshot"
    assert logical_asset_id.startswith("asset-")


# ─── code execution surface ─────────────────────────────────────────────


def test_compile_accepts_top_level_await_and_reports_syntax_errors():
    compiled = _compile("x = 1\nawait Browser.connect()")
    assert compiled is not None
    with pytest.raises(LiveOperationError, match="syntax error"):
        _compile("await (")


@pytest.mark.parametrize(
    "code",
    (
        "import os",
        "from os import environ",
        "print(Browser.__dict__)",
        "print(Browser.__class__.__base__.__subclasses__())",
        "print(__builtins__)",
        "globals()",
        'getattr(Browser, "__class__")',
        "type(Browser)",
        "object()",
        "dir(Browser)",
    ),
)
def test_model_code_cannot_escape_into_the_creator_backend(code: str):
    with pytest.raises(LiveOperationError, match="unavailable"):
        _compile(code)


@pytest.mark.parametrize(
    ("code", "message"),
    (
        ("while True:\n    pass", "while loops are unavailable"),
        (
            "def recurse():\n    return recurse()\nrecurse()",
            "definitions are unavailable",
        ),
        (
            "async def recurse():\n    return await recurse()\nawait recurse()",
            "definitions are unavailable",
        ),
        (
            "recurse = lambda: recurse()\nrecurse()",
            "definitions are unavailable",
        ),
        ("class Recurse:\n    pass", "definitions are unavailable"),
    ),
)
def test_model_code_rejects_unbounded_control_surfaces(
    code: str,
    message: str,
):
    with pytest.raises(LiveOperationError, match=message):
        _compile(code)


def test_model_code_bounds_range_before_it_can_block_the_event_loop():
    from services.media_files.live_operation.bridge import _execute

    with pytest.raises(LiveOperationError, match="limited to 1000 items"):
        asyncio.run(_execute(_compile("list(range(1001))"), {}))

    assert (
        asyncio.run(_execute(_compile("result = list(range(1000))"), {}))
        is None
    )


@pytest.mark.parametrize(
    ("code", "message"),
    (
        ("x = 2 ** 30", "power and left-shift"),
        ("payload = [0] * 1000", "sequence repetition"),
        ('x = "a"\nx *= 1000', "augmented multiplication"),
        ("n = 1_000_000_000", "numeric constants are limited"),
        (
            "for i in range(10):\n"
            "    for j in range(10):\n"
            "        for k in range(10):\n"
            "            v = i\n",
            "nest deeper",
        ),
        (
            "try:\n    v = 1\nexcept:\n    pass\n",
            "bare except",
        ),
    ),
)
def test_model_code_rejects_memory_and_cpu_amplifiers(
    code: str,
    message: str,
):
    """Single statements must not allocate unbounded memory or nest loops
    beyond what the execution deadline can bound."""
    with pytest.raises(LiveOperationError, match=message):
        _compile(code)


def test_oversized_literals_and_huge_programs_are_rejected():
    elements = ", ".join("0" for _ in range(501))
    with pytest.raises(LiveOperationError, match="container literals"):
        _compile(f"payload = [{elements}]")
    with pytest.raises(LiveOperationError, match="string constants"):
        _compile(f's = "{"a" * 10_001}"')
    huge_program = "\n".join(f"v{i} = {i % 9}" for i in range(1_001))
    with pytest.raises(LiveOperationError, match="syntax nodes"):
        _compile(huge_program)


def test_synchronous_loops_are_preempted_at_the_deadline():
    """asyncio.wait_for cannot interrupt synchronous Python; the line-level
    deadline must pre-empt model code that never yields, and the model's own
    exception handlers must not be able to swallow the pre-emption."""
    import time as _time

    from services.media_files.live_operation.bridge import _execute

    code = (
        "for i in range(1000):\n"
        "    try:\n"
        "        for j in range(1000):\n"
        "            values = sorted(range(1000))\n"
        "    except Exception:\n"
        "        pass\n"
    )
    started = _time.monotonic()
    with pytest.raises(LiveOperationError, match="pre-empted"):
        asyncio.run(_execute(_compile(code), {}, deadline_seconds=0.2))
    assert _time.monotonic() - started < 5.0

    # Well-behaved code runs to completion under the same machinery.
    namespace: dict = {}
    asyncio.run(
        _execute(
            _compile("result = sum(range(100))"),
            namespace,
            deadline_seconds=30.0,
        ),
    )
    assert namespace["result"] == sum(range(100))


def test_model_print_is_captured_without_process_global_stdout():
    import io

    from services.media_files.live_operation.bridge import _execute

    output = io.StringIO()
    asyncio.run(
        _execute(
            _compile('print("isolated", 7, sep=":")'),
            {},
            output=output,
        ),
    )
    assert output.getvalue() == "isolated:7\n"


def test_empty_code_is_rejected_before_a_browser_is_launched(tmp_path: Path):
    with pytest.raises(LiveOperationError, match="empty"):
        asyncio.run(run_browser_code("   ", run_root=tmp_path, run_id="run-1"))


def test_recording_defaults_to_the_page_just_opened():
    """start() must work right after open(), before any other operation.

    Regression guard: defaulting to the last page the control link happened
    to see made the first take depend on an incidental perceive/act call in
    between, which broke a second run in the same process.
    """

    class _StubRecorder:
        def __init__(self) -> None:
            self.started_with = None

        async def start(self, cdp, *, label=""):
            self.started_with = (cdp, label)
            return "take-001"

    class _StubSession:
        def __init__(self) -> None:
            self.requested = None

        async def cdp_session_for(self, page):
            self.requested = page
            return f"cdp-for-{page}"

    active = _ActivePage()
    recorder = _StubRecorder()
    agent_recorder = AgentRecorder(_StubSession(), recorder, active)

    # No page opened yet: starting must ask for a page, not film nothing.
    with pytest.raises(LiveSessionError, match="no page has been opened"):
        asyncio.run(agent_recorder.start())

    active.page = "page-object"
    take_id = asyncio.run(agent_recorder.start(label="first step"))
    assert take_id == "take-001"
    assert recorder.started_with == ("cdp-for-page-object", "first step")

    explicit_page = _BoundPage("explicit-page-object")
    take_id = asyncio.run(
        agent_recorder.start(explicit_page, label="explicit page"),
    )
    assert take_id == "take-001"
    assert recorder.started_with == (
        "cdp-for-explicit-page-object",
        "explicit page",
    )
