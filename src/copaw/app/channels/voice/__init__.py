# -*- coding: utf-8 -*-
"""Voice channel: Twilio ConversationRelay + Cloudflare Tunnel."""

try:
    import twilio  # type: ignore[import-not-found]  # noqa: F401
except ImportError:
    VOICE_AVAILABLE = False
    VoiceChannel = None  # type: ignore[assignment,misc]
else:
    VOICE_AVAILABLE = True
    from .channel import VoiceChannel  # noqa: F401

__all__ = ["VoiceChannel", "VOICE_AVAILABLE"]
