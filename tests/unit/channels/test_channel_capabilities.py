# -*- coding: utf-8 -*-
"""Descriptor declarations the host gates response streaming on."""

import json
from pathlib import Path


CHANNELS = Path(__file__).resolve().parents[3] / "plugins" / "channel"


def test_streaming_config_requires_streaming_capability():
    """A streaming switch without the capability can never stream.

    ``IsolatedChannelProxy._response_policy`` clears ``streaming`` unless the
    descriptor declares the ``streaming`` capability, so a channel that offers
    ``streaming_enabled`` without declaring it degrades to complete-message
    delivery silently: no stream is opened and no error is reported.
    """
    missing = []
    for path in sorted(CHANNELS.glob("*/channel.json")):
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        properties = descriptor.get("config_schema", {}).get("properties", {})
        declared = set(descriptor.get("config_fields") or ())
        if "streaming_enabled" not in set(properties) | declared:
            continue
        if "streaming" not in set(descriptor.get("capabilities") or ()):
            missing.append(descriptor.get("channel_key") or path.parent.name)
    assert missing == []
