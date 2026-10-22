# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Report assistance preserves user control and limits model context."""

import asyncio
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from qwenpaw.app import community_report as reports
from qwenpaw.app.routers import community_report as report_router

pytestmark = [pytest.mark.unit, pytest.mark.p0]


def request(**kwargs):
    return reports.CommunityReportRequest(
        resource_name="Example",
        resource_type="plugin",
        draft="The menu is empty",
        **kwargs,
    )


def test_redaction_removes_credentials_without_removing_error_evidence():
    text = reports.redact_report_text(
        'Authorization: Bearer abc-secret\napi_key="very-secret"\n'
        "password=pwd&access_token=token\n"
        "/Users/alice/work/log.txt\nC:\\Users\\bob\\error.log\n"
        "alice@example.org\nhttps://bob:pw@example.org/log\n"
        "HTTP 503 while loading menu",
    )
    for value in [
        "abc-secret",
        "very-secret",
        "pwd",
        "=token",
        "alice",
        "bob",
        ":pw@",
    ]:
        assert value not in text
    assert "HTTP 503 while loading menu" in text


@pytest.mark.parametrize(
    "image",
    [
        "https://example.org/image.png",
        "file:///tmp/private.png",
        "data:image/svg+xml;base64,PHN2Zz4=",
        "data:image/png;base64,aGVsbG8=",
    ],
)
def test_screenshots_cannot_request_remote_or_local_files(image):
    with pytest.raises(ValidationError):
        reports.ReportScreenshot(data_url=image)


def test_screenshot_uses_native_agentscope_data_block():
    messages = reports._model_messages(
        request(
            screenshots=[
                {
                    "data_url": (
                        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAE"
                        "AAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO"
                        "+aYfQAAAAASUVORK5CYII="
                    ),
                },
            ],
            materials_reviewed=True,
        ),
    )
    block = messages[1].content[1]
    assert block.type == "data"
    assert block.source.type == "base64"
    assert block.source.media_type == "image/png"


@pytest.mark.asyncio
async def test_unreviewed_materials_never_reach_model(monkeypatch):
    async def fail():
        pytest.fail("Model must not load before material review")

    monkeypatch.setattr(reports, "_get_model", fail)
    with pytest.raises(
        reports.ReportGenerationError,
        match="materials_not_reviewed",
    ):
        await reports.generate_community_report(request(logs="selected log"))


@pytest.mark.asyncio
async def test_model_receives_only_reviewed_evidence_and_no_tools(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "agentscope.message",
        SimpleNamespace(
            Msg=SimpleNamespace,
        ),
    )
    captured = []

    async def model(messages):
        captured.extend(messages)
        return SimpleNamespace(
            content=[
                {"type": "thinking", "text": "private reasoning"},
                {"type": "text", "text": "# Menu issue\n"},
                {
                    "type": "text",
                    "text": (
                        "api_key=generated-secret\nNeeds reproduction steps"
                    ),
                },
            ],
        )

    async def load():
        return model

    monkeypatch.setattr(reports, "_get_model", load)
    result = await reports.generate_community_report(
        request(
            logs="access_token=abc123\n503 while loading menu",
            materials_reviewed=True,
        ),
    )
    assert [msg.role for msg in captured] == ["system", "user"]
    assert len(captured[1].content) == 1
    assert "abc123" not in captured[1].content[0]["text"]
    assert "503 while loading menu" in captured[1].content[0]["text"]
    assert "generated-secret" not in result
    assert "private reasoning" not in result
    assert "Needs reproduction steps" in result


@pytest.mark.asyncio
async def test_model_failure_exposes_only_generic_error(monkeypatch):
    async def load():
        raise RuntimeError("Provider configuration contains secret-token")

    monkeypatch.setattr(reports, "_get_model", load)
    with pytest.raises(reports.ReportGenerationError) as error:
        await reports.generate_community_report(request())
    assert str(error.value) == "model_not_available"


@pytest.mark.asyncio
async def test_cumulative_stream_is_closed_on_cancellation(monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()

    async def stream():
        try:
            yield SimpleNamespace(
                content=[{"type": "text", "text": "partial"}],
            )
            started.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def model(_messages):
        return stream()

    async def load():
        return model

    monkeypatch.setattr(reports, "_get_model", load)
    monkeypatch.setattr(reports, "_model_messages", lambda _request: [])
    task = asyncio.create_task(reports.generate_community_report(request()))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_browser_disconnect_cancels_model_task(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def generate(_body):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def disconnect(_request):
        await started.wait()

    monkeypatch.setattr(report_router, "generate_community_report", generate)
    monkeypatch.setattr(report_router, "_wait_for_disconnect", disconnect)
    with pytest.raises(report_router.HTTPException) as error:
        await report_router.generate_report(request(), SimpleNamespace())
    assert error.value.status_code == 499
    assert cancelled.is_set()
