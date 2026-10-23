"""Public send-format compatibility required by Slack's verified behavior."""

import pytest

from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)


def test_old_two_field_send_policy_and_three_field_response_wire_are_exact():
    old = {"direct_prefix": False, "parts_configured_prefix": False}
    assert SendFormatPolicy(False, False).to_mapping() == old
    assert SendFormatPolicy.from_mapping(old).to_mapping() == old
    wire = {"streaming": True, "prepare": False, "completion_reaction": False}
    assert ResponsePolicy.from_mapping(wire).to_mapping() == wire
    assert ResponsePolicy.from_mapping(
        {**wire, "send_format": old}
    ).to_mapping() == {**wire, "send_format": old}


def test_optional_send_flags_preserve_defaults_and_slack_exact_wire():
    old = {"direct_prefix": False, "parts_configured_prefix": False}
    parsed = SendFormatPolicy.from_mapping(old)
    assert parsed.parts_metadata_prefix is True
    assert parsed.stream_prefix is True
    assert parsed.parts_strip_text is True
    slack = {
        **old,
        "parts_metadata_prefix": False,
        "stream_prefix": False,
        "parts_strip_text": False,
    }
    assert SendFormatPolicy.from_mapping(slack).to_mapping() == slack
    assert (
        SendFormatPolicy.from_mapping(
            {**old, "parts_metadata_prefix": True, "stream_prefix": True}
        ).to_mapping()
        == old
    )


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"direct_prefix": True},
        {"parts_configured_prefix": False},
        {
            "direct_prefix": True,
            "parts_configured_prefix": False,
            "unknown": False,
        },
    ],
)
def test_send_format_rejects_missing_required_and_unknown_fields(bad):
    with pytest.raises(ProtocolValidationError):
        SendFormatPolicy.from_mapping(bad)


@pytest.mark.parametrize(
    "field",
    [
        "direct_prefix",
        "parts_configured_prefix",
        "parts_metadata_prefix",
        "stream_prefix",
        "parts_strip_text",
    ],
)
@pytest.mark.parametrize("value", [0, 1, "false", None, [], {}])
def test_send_format_fields_are_strict_booleans(field, value):
    wire = {
        "direct_prefix": False,
        "parts_configured_prefix": False,
        field: value,
    }
    with pytest.raises(ProtocolValidationError):
        SendFormatPolicy.from_mapping(wire)
