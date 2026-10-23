"""Native Slack retry waits consume the same worker operation deadline."""

import time

import pytest

from slack_suite import forbid_host_sdk
from slack_support import rows, slack

pytest_plugins = ["slack_support"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "budget,stage_delay,retry_after,want,attempts",
    [
        (1, 0.05, 0.05, "acknowledged", 2),
        (0.35, 0.2, 0.1, "unknown", 2),
        (0.35, 0, 3, "failed", 1),
    ],
)
async def test_rate_retry_fits_or_exhausts_one_total_budget(
    runtime,
    slack_sdk,
    budget,
    stage_delay,
    retry_after,
    want,
    attempts,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    boundary = slack_sdk.site / "qwenpaw_slack_test_boundary.py"
    with boundary.open("a") as stream:
        stream.write(f"""
_budget_original_effect = effect
_budget_attempts = 0
async def effect(kind, token=None):
    global _budget_attempts
    if kind == "chat.postMessage":
        _budget_attempts += 1
        record("budget-attempt", token, attempt=_budget_attempts)
        try:
            await asyncio.sleep({stage_delay!r})
        except asyncio.CancelledError:
            record("budget-cancelled", token)
            raise
        if _budget_attempts == 1:
            response = NS(
                status_code=429, headers={{"Retry-After": {str(retry_after)!r}}},
                get=lambda key, default=None: (
                    "ratelimited" if key == "error" else default
                ),
            )
            raise SlackApiError("controlled rate rejection", response)
    return await _budget_original_effect(kind, token)
""")
    rt = await slack(
        runtime,
        slack_sdk,
        runtime_settings={"send_timeouts": {"slack": budget}},
    )
    meta = {}
    started = time.monotonic()
    if want == "acknowledged":
        await rt.channel.send("C123", "budget retry", meta)
        assert not meta.get("_reply_unknown")
        assert len(rows(slack_sdk.work, "post-result")) == 1
    else:
        with pytest.raises(ChannelDeliveryError) as caught:
            await rt.channel.send("C123", "budget retry", meta)
        assert caught.value.state == want
        assert rows(slack_sdk.work, "post-result") == []
        if want == "unknown":
            assert meta["_reply_unknown"] is True
            assert len(rows(slack_sdk.work, "budget-cancelled")) == 1
            with pytest.raises(ChannelDeliveryError) as replay:
                await rt.channel.send("C123", "budget retry", meta)
            assert replay.value.state == "unknown"
    elapsed = time.monotonic() - started
    assert elapsed < (0.25 if retry_after == 3 else 0.8)
    assert len(rows(slack_sdk.work, "budget-attempt")) == attempts
