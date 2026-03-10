# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.channel import WeComChannel
from copaw.config.config import WeComConfig


async def _empty_process(_request):
    if False:
        yield _request


def test_wecom_from_config_reads_fields():
    config = WeComConfig(
        enabled=True,
        bot_prefix="[WX] ",
        bot_id="bot-1",
        bot_secret="secret-1",
        ws_url="wss://example.test/ws",
        ping_interval_seconds=15,
        reconnect_min_seconds=3,
        reconnect_max_seconds=20,
        processed_ids_path="processed.json",
        route_store_path="routes.json",
    )

    channel = WeComChannel.from_config(_empty_process, config)

    assert channel.enabled is True
    assert channel.bot_prefix == "[WX] "
    assert channel.bot_id == "bot-1"
    assert channel.bot_secret == "secret-1"
    assert channel.ws_url == "wss://example.test/ws"
    assert channel.ping_interval_seconds == 15
    assert channel.reconnect_min_seconds == 3
    assert channel.reconnect_max_seconds == 20
