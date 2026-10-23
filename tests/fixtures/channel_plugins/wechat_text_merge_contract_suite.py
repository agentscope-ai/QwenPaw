"""Accepted opt-in policy validation, independent of any platform Driver."""

import pytest

from qwenpaw.channel_protocol import models
from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared import validate_channel_contract

BASE_POLICY = {
    "streaming": False,
    "prepare": False,
    "completion_reaction": False,
}


@pytest.mark.parametrize("delay", [0, 1, 250, 2**63 - 1])
def test_opted_in_merge_window_survives_policy_roundtrip(delay):
    wire = {**BASE_POLICY, "text_merge_delay_ms": delay}
    policy = ResponsePolicy.from_mapping(wire)
    assert policy.text_merge_delay_ms == delay
    assert policy.to_mapping() == wire


def test_disabled_merge_omits_new_field_and_keeps_old_policy_wire():
    assert ResponsePolicy.from_mapping(BASE_POLICY).to_mapping() == BASE_POLICY
    policy = ResponsePolicy.from_mapping(
        {**BASE_POLICY, "text_merge_delay_ms": None}
    )
    assert policy.text_merge_delay_ms is None
    assert policy.to_mapping() == BASE_POLICY


@pytest.mark.parametrize(
    "delay",
    [True, False, -1, 2**63, 0.0, 1.5, float("nan"), float("inf"), "0"],
)
def test_invalid_merge_windows_are_rejected_at_both_dto_entries(delay):
    with pytest.raises(ProtocolValidationError):
        ResponsePolicy.from_mapping(
            {**BASE_POLICY, "text_merge_delay_ms": delay}
        )
    with pytest.raises(ProtocolValidationError):
        ResponsePolicy(text_merge_delay_ms=delay)


def test_merge_policy_preserves_declared_send_format_fields():
    wire = {
        **BASE_POLICY,
        "send_format": {
            "direct_prefix": False,
            "parts_configured_prefix": True,
            "parts_metadata_prefix": False,
        },
        "text_merge_delay_ms": 0,
    }
    policy = ResponsePolicy.from_mapping(wire)
    assert policy.send_format == SendFormatPolicy(
        direct_prefix=False, parts_metadata_prefix=False
    )
    assert policy.to_mapping() == wire


def test_text_merge_capability_has_one_fixed_public_name():
    assert getattr(models, "TEXT_MERGE_CAPABILITY", None) == (
        "channel.text_merge.v1"
    )


@pytest.mark.parametrize(
    "capabilities",
    [
        ("channel.generic.v1", "channel.text_merge.v2"),
        (
            "channel.generic.v1",
            "channel.text_merge.v1",
            "channel.text_merge.v2",
        ),
        ("channel.text_merge.v1",),
    ],
)
def test_known_merge_contract_requires_v1_and_generic_opt_in(capabilities):
    # A legacy key must not bypass this new capability's generic precondition.
    with pytest.raises(ProtocolValidationError) as raised:
        validate_channel_contract("dingtalk", capabilities)
    assert raised.value.reason_code == "CHANNEL_CONTRACT_UNSUPPORTED"


def test_merge_contract_is_generic_and_unrelated_third_party_tags_stay_valid():
    validate_channel_contract(
        "independent_merge_owner",
        ("channel.generic.v1", "channel.text_merge.v1"),
    )
    validate_channel_contract(
        "old_third_party_owner", ("channel.generic.v1", "vendor.custom.v7")
    )


@pytest.mark.parametrize("state", ["requested", "sending", "deferred"])
def test_outbound_result_still_rejects_nonterminal_states(state):
    with pytest.raises(ProtocolValidationError):
        models.OutboundResult.from_mapping(
            {"delivery_id": "batch-A", "state": state}
        )


@pytest.mark.parametrize(
    "state", ["acknowledged", "failed", "timeout", "unknown"]
)
def test_original_terminal_delivery_receipts_keep_their_exact_wire(state):
    wire = {"delivery_id": "batch-A", "state": state, "retryable": False}
    assert models.OutboundResult.from_mapping(wire).to_mapping() == wire
