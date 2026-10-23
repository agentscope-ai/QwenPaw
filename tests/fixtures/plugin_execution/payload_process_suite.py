"""Prepared only: run after the logical-payload Source freeze is authorized."""

import asyncio
import base64
import hashlib
import json
import os

import pytest

from payload_support import ledger_rows
from process_suite import eventually

pytest_plugins = ["process_suite", "payload_support"]


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def attachment(size, value):
    return "data:application/octet-stream;base64," + base64.b64encode(
        bytes([value]) * size
    ).decode("ascii")


@pytest.mark.parametrize("shape", ["imessage_800000", "multiple_attachments"])
@pytest.mark.asyncio
async def test_actual_child_large_request_and_response_are_exact(
    payload_launch, payload_processes, shape
):
    spec, marker = payload_launch()
    process = payload_processes()
    await process.start(spec)
    parts = [attachment(800000, 71)]
    if shape == "multiple_attachments":
        parts.append(attachment(900000, 83))
    value = {"attachments": parts, "text": "  原文\n⟦ unchanged ⟧  ", "ordered": [1, 2]}
    assert len(encoded(value)) > 1024 * 1024
    assert await process.call("fixture.payload_echo", value) == value
    rows = ledger_rows(marker)
    assert len(rows) == 1 and rows[0]["phase"] == "echo"
    assert rows[0]["bytes"] == len(encoded(value))
    assert rows[0]["sha256"] == hashlib.sha256(encoded(value)).hexdigest()
    assert rows[0]["pid"] == process.health_snapshot()["pid"] != os.getpid()


@pytest.mark.asyncio
async def test_actual_child_generated_reply_and_reverse_rpc_preserve_large_utf8(
    payload_launch, payload_processes
):
    spec, marker = payload_launch()
    process = payload_processes()
    seen = []

    def host(params, _request):
        seen.append(params)
        return params

    process.register_method("fixture.payload_host", host)
    await process.start(spec)
    value = {"text": "原文" * 210000}
    assert await process.call("fixture.payload_reply", {"repetitions": 210000}) == value
    assert await process.call("fixture.payload_reverse", value) == value
    assert seen == [value]
    assert [row["phase"] for row in ledger_rows(marker)] == ["reply", "reverse"]


@pytest.mark.asyncio
async def test_actual_response_publication_commits_once_after_large_write(
    payload_launch, payload_processes
):
    spec, marker = payload_launch()
    process = payload_processes()
    await process.start(spec)
    value = {"data": attachment(800000, 5)}
    assert await process.call("fixture.payload_publication", value) == value
    await eventually(lambda: len(ledger_rows(marker)) == 2)
    rows = ledger_rows(marker)
    assert [row["phase"] for row in rows] == ["prepare", "published"]
    assert len({row["request_id"] for row in rows}) == 1
    assert all(row["sha256"] == hashlib.sha256(encoded(value)).hexdigest() for row in rows)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_visible_large_effect_timeout_or_cancel_never_auto_replays(
    api, payload_launch, payload_processes, cancel
):
    spec, marker = payload_launch()
    process = payload_processes()
    await process.start(spec)
    value = {"data": attachment(800000, 31)}
    pending = asyncio.create_task(
        process.call("fixture.payload_commit", value, timeout=1)
    )
    await eventually(lambda: bool(ledger_rows(marker)))
    if cancel:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        with pytest.raises(api.CallUnknown):
            await pending
    assert len(ledger_rows(marker)) == 1
    unknown = process.health_snapshot()["unknown_outcomes"]
    assert len(unknown) == 1
    assert unknown[0]["request_id"] == ledger_rows(marker)[0]["request_id"]
    assert unknown[0]["method"] == "fixture.payload_commit"
    assert unknown[0]["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
    # A subsequent ordinary roundtrip provides a deterministic observation,
    # without retrying the original business request or sleeping arbitrarily.
    probe = await process.call("fixture.probe")
    assert probe["pid"] == process.health_snapshot()["pid"]
    assert len(ledger_rows(marker)) == 1
    result = await process.stop()
    assert result.exited and not result.residual
    assert len(ledger_rows(marker)) == 1
