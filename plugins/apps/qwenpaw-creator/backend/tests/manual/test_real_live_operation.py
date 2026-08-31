# -*- coding: utf-8 -*-
"""Manual (real-key) acceptance for live website operation.

Billed DashScope calls plus a real browser session, so this is skipped unless
CREATOR_LIVE_OPERATION_REAL_TEST is set. The point of the run is that the
model itself decides how to work: it is given a goal, the browser_use tool and
the same guidance a production run gets, and nothing about the order of steps
is prescribed here.

    CREATOR_LIVE_OPERATION_REAL_TEST=1 \
    TEXT_API_KEY=<key> \
    python -m pytest -m manual_real \
        tests/manual/test_real_live_operation.py -s

Assertions guard structural invariants only — that the model reached the tool,
that whatever it recorded became Project source material, and that recorded
action facts survive into the take manifest. Whether the footage is good is
judged by watching the printed mp4 path.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

import pytest

from models import config as model_config
from services.media_files.live_operation import (
    LiveOperationError,
    run_browser_code,
)

_ENABLED = os.environ.get(
    "CREATOR_LIVE_OPERATION_REAL_TEST",
    "",
).strip().lower() in {"1", "true", "yes", "on"}

pytestmark = [
    pytest.mark.manual_real,
    pytest.mark.skipif(
        not _ENABLED,
        reason=(
            "set CREATOR_LIVE_OPERATION_REAL_TEST=1 to run the billed "
            "live-operation acceptance"
        ),
    ),
]


@pytest.fixture(autouse=True)
def _reap_browsers():
    """Give each case a clean browser plane.

    Two real sessions back to back can otherwise contend for the shared
    Playwright control link; each case owns its own run in production, so the
    reset only restores that isolation for the test.
    """
    yield
    from qwenpaw.browser.control_link.playwright import adapter as pw_adapter

    for link in list(getattr(pw_adapter, "_LIVE", [])):
        with contextlib.suppress(Exception):
            asyncio.run(link.close_all())


_GOAL = (
    "我要做一个「如何在 example.com 上查看页面内容」的教程视频，请你真实操作"
    "这个网站，把值得放进教程的操作过程留成素材。最终验收必须至少有一段可播放"
    "录像：请用 recorder.start/stop 录下至少一次页面操作；只观察或打印不算完成。"
)


def _require_text_model() -> None:
    """Fail before spending anything when the text model is not configured."""
    missing = [
        name
        for name, value in (
            ("api_key", model_config.get_text_api_key().strip()),
            ("base_url", model_config.get_text_base_url().strip()),
            ("model", model_config.get_text_model_name().strip()),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"Creator text model is not configured: {missing}")


def _model_client():
    from services.file_agent_runtime.model_client import (
        AgentScopeAgentChatClient,
    )

    return AgentScopeAgentChatClient(timeout_seconds=300.0)


def _assert_real_take(outcome) -> None:
    assert outcome is not None
    assert (
        outcome.takes
    ), "the real model run finished without recorded footage"
    for take in outcome.takes:
        print(
            f"take {take.take_id}: {take.summary} -> {take.video_path}",
        )
        assert take.video_path.is_file()
        assert take.video_path.stat().st_size > 0
        payload = json.loads(take.manifest.as_json_bytes())
        print("manifest:", json.dumps(payload, ensure_ascii=False)[:800])
        assert payload["video"]["frame_count"] > 0
        assert payload["facts"], "a recorded take must carry action facts"


def test_model_chooses_how_to_operate_and_record(tmp_path: Path) -> None:
    """A real multi-turn model run must finish with publishable footage."""
    _require_text_model()
    from services.file_agent_runtime.prompts.live_operation_guidance import (
        live_operation_guidance,
    )

    client = _model_client()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_use",
                "description": (
                    "用异步 Python 操作真实浏览器；`Browser` 与 `recorder` " "已在作用域内。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    messages = [
        {"role": "system", "content": live_operation_guidance()},
        {"role": "user", "content": _GOAL},
    ]

    async def one_turn():
        return await client.complete(
            messages=messages,
            tools=tools,
            on_text_delta=None,
            on_thinking_delta=None,
            on_tool_call_delta=None,
        )

    outcome = None
    final_code = ""
    # Production gives the model the result of each tool call. Its first call
    # may legitimately perceive the real site before deciding what to film,
    # so acceptance follows the same bounded continuation instead of grading
    # an exploratory first turn as the final product.
    for turn_index in range(1, 4):
        turn = asyncio.run(one_turn())
        print(f"\n=== model turn {turn_index} ===")
        print("finish reason:", turn.finish_reason)
        print("tool calls:", [call.name for call in turn.tool_calls])
        if not turn.tool_calls:
            break
        assert len(turn.tool_calls) == 1
        call = turn.tool_calls[0]
        assert call.name == "browser_use"
        code = str(call.arguments.get("code") or "")
        print("--- model authored code ---")
        print(code)
        # The closed SDK is what the model must write against; a Playwright-ism
        # here would mean the reused manual failed to teach the real surface.
        assert "Browser.connect" in code
        assert "page.fill(" not in code

        try:
            outcome = asyncio.run(
                run_browser_code(
                    code,
                    run_root=tmp_path,
                    run_id=f"acceptance-{turn_index}",
                ),
            )
        except LiveOperationError as exc:
            print("--- tool failed honestly ---")
            print(type(exc).__name__, str(exc))
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [call.history_dict()],
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "name": call.name,
                    "content": json.dumps(
                        {"ok": False, "error": str(exc)},
                        ensure_ascii=False,
                    ),
                    "failed": True,
                },
            )
            continue
        print("--- tool output ---")
        print(outcome.output)
        print(
            "takes:",
            len(outcome.takes),
            "screenshots:",
            len(outcome.screenshots),
        )
        actionable = [take for take in outcome.takes if take.manifest.facts]
        factless_failure = bool(outcome.takes and not actionable)
        quality_error = (
            "recorded take has 0 real actions; wait/snapshot/print do not "
            "count. Reconnect/open and re-record with click, scroll, "
            "navigation, or input."
            if factless_failure
            else ""
        )
        messages.append(
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [call.history_dict()],
            },
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.call_id,
                "name": call.name,
                "content": json.dumps(
                    {
                        "ok": not factless_failure,
                        "qualityError": quality_error,
                        "output": outcome.output,
                        "takes": [
                            {
                                "takeId": take.take_id,
                                "summary": take.summary,
                            }
                            for take in outcome.takes
                        ],
                        "screenshotCount": len(outcome.screenshots),
                    },
                    ensure_ascii=False,
                ),
                "failed": factless_failure,
            },
        )
        if actionable:
            outcome.takes = actionable
            final_code = code
            break

    assert "recorder.start" in final_code
    assert "recorder.stop" in final_code
    _assert_real_take(outcome)
