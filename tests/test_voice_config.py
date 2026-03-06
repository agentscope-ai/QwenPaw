# -*- coding: utf-8 -*-
"""Tests for VoiceChannelConfig."""
from copaw.config.config import VoiceChannelConfig, ChannelConfig


class TestVoiceChannelConfig:
    def test_defaults(self):
        config = VoiceChannelConfig()
        assert config.enabled is False
        assert config.twilio_account_sid == ""
        assert config.twilio_auth_token == ""
        assert config.phone_number == ""
        assert config.phone_number_sid == ""
        assert config.tts_provider == "google"
        assert config.tts_voice == "en-US-Journey-D"
        assert config.stt_provider == "deepgram"
        assert config.language == "en-US"

    def test_custom_values(self):
        config = VoiceChannelConfig(
            enabled=True,
            twilio_account_sid="AC123",
            twilio_auth_token="token123",
            phone_number="+15551234567",
            phone_number_sid="PN123",
            tts_provider="amazon",
            tts_voice="Joanna",
        )
        assert config.enabled is True
        assert config.twilio_account_sid == "AC123"
        assert config.tts_provider == "amazon"

    def test_channel_config_includes_voice(self):
        ch = ChannelConfig()
        assert hasattr(ch, "voice")
        assert isinstance(ch.voice, VoiceChannelConfig)
        assert ch.voice.enabled is False

    def test_channel_config_from_dict(self):
        data = {
            "voice": {
                "enabled": True,
                "twilio_account_sid": "AC456",
                "twilio_auth_token": "secret",
                "phone_number": "+15559999999",
                "phone_number_sid": "PN456",
            },
        }
        ch = ChannelConfig(**data)
        assert ch.voice.enabled is True
        assert ch.voice.twilio_account_sid == "AC456"
        assert ch.voice.phone_number == "+15559999999"
