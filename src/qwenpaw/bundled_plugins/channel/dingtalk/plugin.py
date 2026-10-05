# -*- coding: utf-8 -*-
"""DingTalk registration is SDK-free; each workspace owns its connection."""


def _load_channel():
    from .channel import DingTalkChannel

    return DingTalkChannel


class DingTalkPlugin:
    def register(self, api):
        api.register_channel(
            channel_key="dingtalk",
            channel_loader=_load_channel,
            label="DingTalk",
            description="DingTalk Stream and AI Cards",
            config_fields=[
                {"name": "client_id", "label": "Client ID", "type": "text"},
                {
                    "name": "client_secret",
                    "label": "Client Secret",
                    "type": "password",
                },
            ],
        )


plugin = DingTalkPlugin()
