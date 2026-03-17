# -*- coding: utf-8 -*-
from pathlib import Path

from copaw.app.channels.mattermost.channel import _DEFAULT_MEDIA_DIR
from copaw.config.config import MattermostConfig


def test_mattermost_config_default_media_dir_uses_boostclaw_path() -> None:
    assert MattermostConfig().media_dir == "~/.boostclaw/media/mattermost"


def test_mattermost_channel_default_media_dir_resolves_boostclaw_path() -> None:
    expected = Path("~/.boostclaw/media/mattermost").expanduser()
    assert _DEFAULT_MEDIA_DIR == expected

