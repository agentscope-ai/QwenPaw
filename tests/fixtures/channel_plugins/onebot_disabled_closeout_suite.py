"""Original disabled lifecycle at the actual formal Host factory boundary."""

import pytest

from onebot_contract_suite import official_onebot_proxy
from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

__all__ = ["official_onebot_proxy"]


async def test_disabled_formal_start_stop_and_send_have_no_child(
    official_onebot_proxy,
):
    channel = official_onebot_proxy({"enabled": False})
    assert channel.channel_process.health_snapshot()["pid"] is None
    await channel.start()
    assert channel.channel_process.health_snapshot()["pid"] is None
    assert channel.endpoint_service.resolve() is None
    with pytest.raises(ChannelDeliveryError) as failed:
        await channel.send("12345", "disabled")
    assert failed.value.state == "failed"
    assert failed.value.reason_code == "CHANNEL_DISABLED"
    assert channel.channel_process.health_snapshot()["pid"] is None
    await channel.stop()
    assert channel.channel_process.health_snapshot()["pid"] is None
    assert channel.endpoint_service.resolve() is None
