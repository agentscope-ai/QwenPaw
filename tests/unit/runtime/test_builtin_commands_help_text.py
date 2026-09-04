# -*- coding: utf-8 -*-
"""help_text for built-in commands comes from the definition site."""
from __future__ import annotations

from qwenpaw.agents.command_handler import SYSTEM_COMMAND_DESCRIPTIONS
from qwenpaw.runtime.builtin_commands import (
    _collect_control_specs,
    _collect_conversation_specs,
)


def test_control_specs_use_handler_description() -> None:
    """Control help_text is handler.description, not a secondary map."""
    by_name = {spec.name: spec for spec in _collect_control_specs()}

    assert by_name["model"].help_text == "Show or switch AI model"
    assert by_name["skills"].help_text == (
        "List chat-available skills and expose explicit skill commands"
    )
    # Handlers without description stay non-advertisable.
    assert by_name["stop"].help_text == ""
    assert by_name["approval"].help_text == ""


def test_conversation_specs_use_system_command_descriptions() -> None:
    """Conversation help_text comes from SYSTEM_COMMAND_DESCRIPTIONS."""
    by_name = {spec.name: spec for spec in _collect_conversation_specs()}

    # Every curated conversation command is advertised with its description.
    for name, desc in SYSTEM_COMMAND_DESCRIPTIONS.items():
        assert by_name[name].help_text == desc, name
    # Commands absent from SYSTEM_COMMAND_DESCRIPTIONS remain hidden from
    # autocomplete.
    assert by_name["dump_history"].help_text == ""
    assert by_name["load_history"].help_text == ""
    assert by_name["proactive"].help_text == ""
