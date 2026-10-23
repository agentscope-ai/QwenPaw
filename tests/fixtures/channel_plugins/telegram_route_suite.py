"""Real PTB callbacks and worker replies observed at the HTTP service."""

import asyncio
import base64
import importlib.abc
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

import pytest

from telegram_support import (
    TOKEN,
    eventually,
    fault_runtime,
    finish,
    identity,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
    telegram,
    telegram_sdk,
)


from telegram_business_suite import forbid_host_sdk


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,meta,want,thread",
    [
        ("12345", {}, 12345, None),
        ("telegram:12345", {}, 12345, None),
        ("456", {"chat_id": "12345", "message_thread_id": 99}, 12345, 99),
        ("telegram:456", {"chat_id": "12345"}, 12345, None),
    ],
)
async def test_legacy_bare_session_and_metadata_target_precedence(
    runtime, telegram_sdk, target, meta, want, thread
):
    rt = await telegram(runtime, telegram_sdk)
    handle = await route(rt, target, meta)
    result = await send(
        rt,
        handle,
        parts=[{"type": "text", "text": "route body"}],
        content_source="direct",
    )
    assert result["state"] == "acknowledged"
    value = rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]
    assert value["chat_id"] == want
    assert value.get("message_thread_id") == thread
    await finish(rt, handle)


@pytest.mark.asyncio
async def test_standard_target_and_cron_retain_historical_chat(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    handle = rt.channel.to_handle_from_target(
        user_id="456", session_id="telegram:12345"
    )
    await rt.channel.send(handle, "cron body", {})
    assert (
        rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["chat_id"]
        == 12345
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry,parts,prefix,want",
    [
        ("direct", [{"type": "text", "text": " x "}], "P", " x "),
        ("parts", [{"type": "text", "text": " x "}], "P", "P   x"),
        ("parts", [{"type": "text", "text": "   "}], "P", "P"),
        ("parts", [{"type": "text", "text": " x "}], "", "x"),
        (
            "parts",
            [
                {"type": "text", "text": "a "},
                {"type": "refusal", "refusal": " b"},
            ],
            "P",
            "P  a \n b",
        ),
        (
            "parts",
            [{"type": "image", "image_url": "https://example.test/p.png"}],
            "P",
            "[Image: https://example.test/p.png]",
        ),
        (
            "parts",
            [
                {"type": "text", "text": " x "},
                {"type": "image", "image_url": "https://example.test/p.png"},
            ],
            "P",
            "P   x \n[Image: https://example.test/p.png]",
        ),
    ],
)
async def test_three_entry_source_preserves_raw_whitespace_prefix_and_notices(
    runtime, telegram_sdk, entry, parts, prefix, want
):
    rt = await telegram(runtime, telegram_sdk, bot_prefix="CONFIG")
    meta = {"bot_prefix": prefix}
    if entry == "direct":
        await rt.channel.send("12345", parts[0]["text"], meta)
    else:
        await rt.channel.send_content_parts("12345", parts, meta)
    assert (
        rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["text"] == want
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,want",
    [
        ("**bold**", "<b>bold</b>"),
        ("*italic*", "<i>italic</i>"),
        ("~~strike~~", "<s>strike</s>"),
        ("||secret||", "<tg-spoiler>secret</tg-spoiler>"),
        ("`a < b`", "<code>a &lt; b</code>"),
        (
            "```python\na < b\n```",
            '<pre><code class="language-python">a &lt; b\n</code></pre>',
        ),
        (
            "[link](https://x.test?a=1&b=2)",
            '<a href="https://x.test?a=1&b=2">link</a>',
        ),
        (
            "# Heading\n> quoted\n- item",
            "<b>Heading</b>\n<blockquote>quoted</blockquote>\n• item",
        ),
    ],
)
async def test_html_keeps_code_entities_links_and_structure(
    runtime, telegram_sdk, text, want
):
    rt = await telegram(runtime, telegram_sdk)
    await rt.channel.send("12345", text, {})
    value = rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]
    assert value["text"] == want
    assert value["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_native_unicode_chunks_respect_utf16_api_limit_without_text_loss(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    text = "😀" * 4000
    await rt.channel.send("12345", text, {})
    calls = rows(telegram_sdk.work, "sendMessage")
    assert len(calls) == 2
    assert "".join(v["arguments"]["text"] for v in calls) == text
    assert all(
        len(v["arguments"]["text"].encode("utf-16-le")) // 2 <= 4096
        for v in calls
    )
