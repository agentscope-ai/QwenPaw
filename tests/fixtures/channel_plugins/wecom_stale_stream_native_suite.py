"""Actual aibot reconnect and worker replacement over verified loopback TLS."""

import asyncio

import pytest

from qwenpaw.channel_protocol.models import (
    IdentityParams,
    ResponseFinishParams,
    ResponseOutcome,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import ingress, prepare, text_frame  # noqa: E402

pytest_plugins = ["wecom_native_support"]


async def eventually(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.01)


async def finish(driver, identity, handle):
    return await driver._finish(
        ResponseFinishParams(
            **identity,
            response_handle=handle,
            outcome=ResponseOutcome.FAILED,
        ),
        None,
    )


async def test_native_abnormal_disconnect_retires_old_stream_and_new_message_works(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    handle = (await ingress(wecom_native, text_frame("before-reconnect")))[
        "response_handle"
    ]
    assert (await prepare(wecom_native, handle))["state"] == "acknowledged"
    platform = driver._platform
    old_epoch = platform._epoch
    old_effects = server.rows("aibot_respond_msg")
    old_connection = server.connection
    await asyncio.to_thread(
        old_connection.close, 1011, "simulated abnormal disconnect"
    )
    await eventually(
        lambda: driver._connected and platform._epoch >= old_epoch + 2
    )
    assert len(server.connections) >= 2
    await finish(driver, identity, handle)
    assert not driver._routes.pending_cleanups()
    assert handle not in platform._frames
    assert handle not in platform._processing
    assert not platform._keepalive_tasks
    assert server.rows("aibot_respond_msg") == old_effects
    new_handle = (await ingress(wecom_native, text_frame("after-reconnect")))[
        "response_handle"
    ]
    assert (await prepare(wecom_native, new_handle))["state"] == "acknowledged"
    await finish(driver, identity, new_handle)
    assert len(server.rows("aibot_respond_msg")) == len(old_effects) + 2


async def test_native_worker_restart_same_epoch_recovers_pending_without_finish_rpc(
    wecom_native, tmp_path
):
    from qwenpaw_channel_wecom.driver import WeComDriver

    driver, peer, identity, server = wecom_native
    handle = (await ingress(wecom_native, text_frame("before-worker-loss")))[
        "response_handle"
    ]
    assert (await prepare(wecom_native, handle))["state"] == "acknowledged"
    old_epoch = driver._platform._epoch
    # Emulate death after the existing finish-intent checkpoint has committed.
    driver._routes.begin_finish(handle, ResponseOutcome.FAILED)
    await driver._checkpoint()
    old_effects = server.rows("aibot_respond_msg")
    capabilities = driver._context.capabilities
    await driver.stop()
    replacement = WeComDriver()
    fresh_identity = IdentityParams(
        "wecom", identity["instance_id"], identity["generation"] + 1
    )
    replacement.bind(DriverContext(peer, fresh_identity, capabilities))
    try:
        await replacement.start(
            {
                "bot_id": "native-bot",
                "secret": "native-secret",
                "ws_url": server.url,
                "workspace_dir": str(tmp_path),
                "streaming_enabled": True,
            }
        )
        assert replacement._platform._epoch == old_epoch
        await eventually(
            lambda: replacement._connected
            and not replacement._routes.pending_cleanups()
        )
        assert replacement._routes.snapshot(handle) is None
        assert replacement._platform._frames == {}
        assert server.rows("aibot_respond_msg") == old_effects
        native = replacement, peer, fresh_identity.to_mapping(), server
        fresh_handle = (
            await ingress(native, text_frame("after-worker-loss"))
        )["response_handle"]
        assert (await prepare(native, fresh_handle))["state"] == "acknowledged"
        await finish(replacement, fresh_identity.to_mapping(), fresh_handle)
    finally:
        await replacement.stop()
