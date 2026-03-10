# -*- coding: utf-8 -*-
"""Tests for TwiML generation helpers."""
import xml.etree.ElementTree as ET

from copaw.app.channels.voice.twiml import (
    build_busy_twiml,
    build_conversation_relay_twiml,
    build_error_twiml,
)


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


class TestConversationRelayTwiml:
    def test_basic_generation(self):
        twiml = build_conversation_relay_twiml(
            "wss://example.trycloudflare.com/voice/ws",
        )
        root = _parse(twiml)
        assert root.tag == "Response"

        connect = root.find("Connect")
        assert connect is not None

        relay = connect.find("ConversationRelay")
        assert relay is not None
        assert (
            relay.attrib["url"] == "wss://example.trycloudflare.com/voice/ws"
        )
        assert relay.attrib["interruptible"] == "true"

    def test_custom_params(self):
        twiml = build_conversation_relay_twiml(
            "wss://test.com/ws",
            welcome_greeting="Hello!",
            tts_provider="amazon",
            tts_voice="Joanna",
            stt_provider="google",
            language="es-ES",
            interruptible=False,
        )
        root = _parse(twiml)
        relay = root.find("Connect/ConversationRelay")
        assert relay.attrib["welcomeGreeting"] == "Hello!"
        assert relay.attrib["ttsProvider"] == "amazon"
        assert relay.attrib["voice"] == "Joanna"
        assert relay.attrib["transcriptionProvider"] == "google"
        assert relay.attrib["language"] == "es-ES"
        assert relay.attrib["interruptible"] == "false"

    def test_xml_escaping(self):
        twiml = build_conversation_relay_twiml(
            "wss://test.com/ws",
            welcome_greeting='Hi & "welcome" <friend>!',
        )
        # Should not raise a parse error (properly escaped)
        root = _parse(twiml)
        relay = root.find("Connect/ConversationRelay")
        assert "&" in relay.attrib["welcomeGreeting"]

    def test_default_providers(self):
        twiml = build_conversation_relay_twiml("wss://test.com/ws")
        root = _parse(twiml)
        relay = root.find("Connect/ConversationRelay")
        assert relay.attrib["ttsProvider"] == "google"
        assert relay.attrib["voice"] == "en-US-Journey-D"
        assert relay.attrib["transcriptionProvider"] == "deepgram"
        assert relay.attrib["language"] == "en-US"


class TestBusyTwiml:
    def test_default_message(self):
        twiml = build_busy_twiml()
        root = _parse(twiml)
        say = root.find("Say")
        assert say is not None
        assert "another call" in say.text

    def test_custom_message(self):
        twiml = build_busy_twiml("Not available right now.")
        root = _parse(twiml)
        say = root.find("Say")
        assert say.text == "Not available right now."


class TestErrorTwiml:
    def test_default_message(self):
        twiml = build_error_twiml()
        root = _parse(twiml)
        say = root.find("Say")
        assert say is not None
        assert "error" in say.text.lower()

    def test_custom_message(self):
        twiml = build_error_twiml("Something went wrong.")
        root = _parse(twiml)
        say = root.find("Say")
        assert say.text == "Something went wrong."
