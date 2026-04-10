# -*- coding: utf-8 -*-
"""TwiML generation helpers for the Voice channel."""
from __future__ import annotations

import xml.etree.ElementTree as ET


def build_conversation_relay_twiml(
    ws_url: str,
    *,
    welcome_greeting: str = "Hi! How can I help you?",
    tts_provider: str = "google",
    tts_voice: str = "en-US-Journey-D",
    stt_provider: str = "deepgram",
    language: str = "en-US",
    interruptible: bool = True,
) -> str:
    """Build TwiML ``<Response>`` that connects to ConversationRelay.

    Returns an XML string suitable as an HTTP response to Twilio's
    incoming call webhook.
    """
    response_el = ET.Element("Response")
    connect_el = ET.SubElement(response_el, "Connect")
    ET.SubElement(
        connect_el,
        "ConversationRelay",
        url=ws_url,
        welcomeGreeting=welcome_greeting,
        ttsProvider=tts_provider,
        voice=tts_voice,
        transcriptionProvider=stt_provider,
        language=language,
        interruptible=str(interruptible).lower(),
    )
    xml_body = ET.tostring(response_el, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>{xml_body}'


def build_busy_twiml(
    message: str = "On another call. Please try again later.",
) -> str:
    """Build TwiML that speaks a busy message.

    Twilio automatically ends the call after all verbs complete.
    """
    response_el = ET.Element("Response")
    say_el = ET.SubElement(response_el, "Say")
    say_el.text = message
    xml_body = ET.tostring(response_el, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>{xml_body}'


def build_error_twiml(
    message: str = "An error occurred. Please try again later.",
) -> str:
    """Build TwiML that speaks an error message.

    Twilio automatically ends the call after all verbs complete.
    """
    return build_busy_twiml(message)
