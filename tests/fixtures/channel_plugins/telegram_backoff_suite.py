"""Real native 409 cycles expose retry progression, cap and poll reset."""

import asyncio
import json
from urllib.parse import quote

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_support import (
    TOKEN,
    fault_runtime,
    rows,
    runtime,
    telegram,
    telegram_sdk,
)


@pytest.mark.asyncio
async def test_conflict_cycles_cap_at_effective_timeout_plus_one_ok_resets(
    runtime, telegram_sdk
):
    directory = telegram_sdk.work / quote(TOKEN, safe="")
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "poll-script.json"
    script.write_text(json.dumps([{"code": 409}] * 5))
    await telegram(runtime, telegram_sdk)

    def polls():
        return [
            v
            for v in rows(telegram_sdk.work, "getUpdates")
            if v["arguments"].get("timeout") == 10
        ]

    async with asyncio.timeout(100):
        while len(polls()) < 6:
            await asyncio.sleep(0.02)
    first = polls()[:6]
    calls = rows(telegram_sdk.work)
    starts = [v for v in calls if v["kind"] == "getMe"][:6]
    # Native Updater.stop completes its one-second error retry before close.
    # Observe the reconnect sleep after that actual cleanup, not both delays.
    delays = []
    for left, right in zip(starts, starts[1:]):
        closed = [
            v
            for v in calls
            if v["kind"] == "http-close-exit"
            and left["at"] < v["at"] < right["at"]
        ]
        assert len(closed) == 2
        delays.append(right["at"] - closed[-1]["at"])
    for actual, minimum in zip(delays, (5, 9, 16.2, 29.16, 31)):
        assert minimum <= actual < minimum + 1
    assert first[0]["read_timeout"] == 30
    assert delays[-1] >= first[0]["read_timeout"] + 1
    async with asyncio.timeout(8):
        while not any(
            v["arguments"].get("timeout") == 10
            for v in rows(telegram_sdk.work, "getUpdates-success")
        ):
            await asyncio.sleep(0.01)
    before = len(polls())
    script.write_text(json.dumps([{"code": 409}]))
    async with asyncio.timeout(8):
        while len(polls()) < before + 2:
            await asyncio.sleep(0.01)
    resumed = polls()[before : before + 2]
    current = rows(telegram_sdk.work)
    closed = [
        v
        for v in current
        if v["kind"] == "http-close-exit"
        and resumed[0]["at"] < v["at"] < resumed[1]["at"]
    ]
    assert len(closed) == 2
    assert 5 <= resumed[1]["at"] - closed[-1]["at"] < 6
    calls = rows(telegram_sdk.work)
    starts = [i for i, value in enumerate(calls) if value["kind"] == "getMe"]
    assert all(
        any(
            value["kind"] == "http-close-exit"
            for value in calls[left + 1 : right]
        )
        for left, right in zip(starts, starts[1:])
    )
