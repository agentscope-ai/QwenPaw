# -*- coding: utf-8 -*-
"""Tests for DriverCard contract validation and credential coercion."""
from __future__ import annotations

import pytest

from qwenpaw.drivers.constants import CREDENTIAL_KIND_NONE
from qwenpaw.drivers.contracts import (
    CredentialRef,
    DriverCard,
    coerce_card,
    coerce_credential_ref,
    coerce_credential_refs,
    iter_credential_refs,
    validate_card,
    validate_card_name,
)
from qwenpaw.drivers.errors import DriverCardError
from qwenpaw.drivers.policy_types import (
    DriverPolicy,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
)


def _valid_card(name: str = "github", **overrides) -> DriverCard:
    """Build a minimal valid DriverCard for mutation-based tests."""
    base = {"name": name, "protocol": "mcp", "endpoint": {}}
    base.update(overrides)
    return DriverCard(**base)


class TestValidateCardName:
    """validate_card_name is the storage-key safety boundary — names
    that could escape the storage namespace must be rejected."""

    @pytest.mark.parametrize("bad", ["", "..", ".", "a/b", "a\\b", "a\x00b"])
    def test_rejects_unsafe_names(self, bad):
        with pytest.raises(DriverCardError):
            validate_card_name(bad)

    @pytest.mark.parametrize("ok", ["github", "my-driver", "driver_1", "a"])
    def test_accepts_safe_names(self, ok):
        validate_card_name(ok)  # no raise

    def test_rejects_non_string(self):
        with pytest.raises(DriverCardError):
            validate_card_name(None)  # type: ignore[arg-type]


class TestCoerceCredentialRef:
    """Credential references normalize loose input into a typed CredentialRef
    without ever raising on missing data."""

    def test_existing_ref_returned_as_is(self):
        ref = CredentialRef(kind="static", ref="s")
        assert coerce_credential_ref(ref) is ref

    def test_dict_mapping(self):
        ref = coerce_credential_ref({"kind": "static", "ref": "s"})
        assert ref == CredentialRef(kind="static", ref="s")

    def test_none_becomes_none_kind(self):
        ref = coerce_credential_ref(None)
        assert ref.kind == CREDENTIAL_KIND_NONE

    def test_object_with_kind_ref_attrs(self):
        ref = coerce_credential_ref(
            type("X", (), {"kind": "static", "ref": "s"})(),
        )
        assert ref.kind == "static"
        assert ref.ref == "s"

    def test_missing_attrs_become_empty(self):
        ref = coerce_credential_ref(type("X", (), {})())
        assert ref.kind == ""
        assert ref.ref == ""


class TestCoerceCredentialRefs:
    """Filters out empty/none-kind aliases so DriverCard never carries a
    dead credential reference that would always fail to resolve."""

    def test_none_returns_empty_dict(self):
        assert not coerce_credential_refs(None)

    def test_non_dict_returns_empty_dict(self):
        assert not coerce_credential_refs(["x"])

    def test_empty_alias_skipped(self):
        # "" alias would shadow real refs — always a config mistake.
        assert not coerce_credential_refs({"": {"kind": "static"}})

    def test_none_kind_ref_filtered(self):
        out = coerce_credential_refs({"default": {"kind": "none"}})
        assert not out

    def test_valid_ref_kept(self):
        out = coerce_credential_refs(
            {"default": {"kind": "static", "ref": "s"}},
        )
        assert "default" in out
        assert out["default"].kind == "static"


class TestDriverCardPostInit:
    """DriverCard.__post_init__ coerces credentials and policy so callers
    can pass loose legacy shapes."""

    def test_post_init_coerces_credentials(self):
        card = DriverCard(
            name="d",
            protocol="mcp",
            endpoint={},
            credentials={"default": {"kind": "static", "ref": "s"}},
        )
        assert isinstance(card.credentials["default"], CredentialRef)

    def test_post_init_coerces_policy_from_dict(self):
        card = DriverCard(
            name="d",
            protocol="mcp",
            endpoint={},
            policy={"default_effect": "allow", "rules": []},
        )
        assert isinstance(card.policy, DriverPolicy)
        assert card.policy.default_effect == "allow"

    def test_post_init_filters_none_kind_credential(self):
        card = DriverCard(
            name="d",
            protocol="mcp",
            endpoint={},
            credentials={"default": {"kind": "none"}},
        )
        assert "default" not in card.credentials


class TestCoerceCard:
    """coerce_card returns a normalized copy without mutating the input."""

    def test_returns_new_object(self):
        card = _valid_card()
        assert coerce_card(card) is not card

    def test_does_not_mutate_input_credentials(self):
        card = DriverCard(
            name="d",
            protocol="mcp",
            endpoint={},
            credentials={"default": {"kind": "static", "ref": "s"}},
        )
        snapshot = dict(card.credentials)
        coerce_card(card)
        assert card.credentials == snapshot

    def test_iter_credential_refs_returns_copy(self):
        card = DriverCard(
            name="d",
            protocol="mcp",
            endpoint={},
            credentials={"default": {"kind": "static", "ref": "s"}},
        )
        refs = iter_credential_refs(card)
        refs["injected"] = CredentialRef(kind="static")
        assert "injected" not in card.credentials


class TestValidateCard:
    """validate_card is the public contract gate — invalid configs must
    be rejected before they reach the registry."""

    def test_valid_minimal_card(self):
        validate_card(_valid_card())

    def test_invalid_protocol_rejected(self):
        card = _valid_card(protocol="")
        with pytest.raises(DriverCardError, match="protocol"):
            validate_card(card)

    def test_invalid_endpoint_type_rejected(self):
        card = _valid_card(endpoint=[])  # type: ignore[arg-type]
        with pytest.raises(DriverCardError, match="endpoint"):
            validate_card(card)

    def test_invalid_config_type_rejected(self):
        card = _valid_card(config=[])  # type: ignore[arg-type]
        with pytest.raises(DriverCardError, match="config"):
            validate_card(card)

    def test_invalid_default_effect_rejected(self):
        # Bypass __post_init__ coercion: assign an invalid effect directly.
        card = _valid_card()
        bad_policy = DriverPolicy()
        bad_policy.default_effect = "maybe"
        card.policy = bad_policy
        with pytest.raises(DriverCardError, match="default policy effect"):
            validate_card(card)

    def test_rule_invalid_effect_rejected(self):
        card = _valid_card()
        rule = PolicyRule(
            effect="deny",
            target=PolicyTarget(kind="tool", name="x"),
        )
        rule.effect = "maybe"
        card.policy = DriverPolicy(default_effect="deny", rules=[rule])
        with pytest.raises(DriverCardError, match="invalid policy effect"):
            validate_card(card)

    def test_rule_invalid_target_kind_rejected(self):
        card = _valid_card()
        rule = PolicyRule(
            effect="allow",
            target=PolicyTarget(kind="not-a-kind", name="x"),
            principal=PolicyPrincipal(),
        )
        card.policy = DriverPolicy(default_effect="deny", rules=[rule])
        with pytest.raises(DriverCardError, match="target.kind"):
            validate_card(card)

    def test_rule_empty_target_name_rejected(self):
        card = _valid_card()
        rule = PolicyRule(
            effect="allow",
            target=PolicyTarget(kind="tool", name=""),
            principal=PolicyPrincipal(),
        )
        card.policy = DriverPolicy(default_effect="deny", rules=[rule])
        with pytest.raises(DriverCardError, match="target.name"):
            validate_card(card)

    def test_rule_user_subject_empty_value_rejected(self):
        card = _valid_card()
        rule = PolicyRule(
            effect="allow",
            target=PolicyTarget(kind="tool", name="x"),
            principal=PolicyPrincipal(subject_type="user", subject_value=""),
        )
        card.policy = DriverPolicy(default_effect="deny", rules=[rule])
        with pytest.raises(DriverCardError, match="subject_value"):
            validate_card(card)

    def test_credential_alias_empty_rejected(self):
        card = _valid_card()
        # Inject directly to reach _validate_card_credentials.
        card.credentials = {"": CredentialRef(kind="static", ref="s")}
        with pytest.raises(DriverCardError, match="aliases must be"):
            validate_card(card)

    def test_credential_kind_empty_rejected(self):
        card = _valid_card()
        card.credentials = {"default": CredentialRef(kind="", ref="s")}
        with pytest.raises(DriverCardError, match="kind must be"):
            validate_card(card)


class TestEndpointBindingValidation:
    """Endpoint bindings keep DriverCards secret-free: public values are
    literals, secret_refs point into CredentialRecord.secrets. Mis-shaped
    bindings or unknown credential aliases must be rejected."""

    def test_endpoint_section_non_dict_rejected(self):
        card = _valid_card(endpoint={"env": "not-a-dict"})
        with pytest.raises(DriverCardError, match="endpoint.env must be"):
            validate_card(card)

    def test_endpoint_legacy_flat_string_allowed(self):
        card = _valid_card(endpoint={"env": {"VAR": "literal-value"}})
        validate_card(card)

    def test_endpoint_value_source_missing_source_rejected(self):
        card = _valid_card(endpoint={"env": {"VAR": {"value": "x"}}})
        with pytest.raises(
            DriverCardError,
            match="source mapping must name source",
        ):
            validate_card(card)

    def test_endpoint_value_source_invalid_source_rejected(self):
        card = _valid_card(endpoint={"env": {"VAR": {"source": "magic"}}})
        with pytest.raises(DriverCardError, match="invalid source"):
            validate_card(card)

    def test_endpoint_literal_value_non_string_rejected(self):
        card = _valid_card(
            endpoint={"env": {"VAR": {"source": "literal", "value": 123}}},
        )
        with pytest.raises(
            DriverCardError,
            match="literal value must be a string",
        ):
            validate_card(card)

    def test_endpoint_literal_string_value_allowed(self):
        card = _valid_card(
            endpoint={"env": {"VAR": {"source": "literal", "value": "x"}}},
        )
        validate_card(card)

    def test_endpoint_credential_source_unknown_alias_rejected(self):
        card = _valid_card(
            endpoint={
                "env": {
                    "VAR": {
                        "source": "credential",
                        "credential": "nope",
                        "field": "token",
                    },
                },
            },
        )
        with pytest.raises(DriverCardError, match="unknown credential alias"):
            validate_card(card)

    def test_endpoint_credential_source_missing_field_rejected(self):
        card = _valid_card(
            credentials={"default": CredentialRef(kind="static", ref="s")},
            endpoint={
                "env": {
                    "VAR": {
                        "source": "credential",
                        "credential": "default",
                    },
                },
            },
        )
        with pytest.raises(DriverCardError, match="must name a field"):
            validate_card(card)

    def test_endpoint_credential_source_valid(self):
        card = _valid_card(
            credentials={"default": CredentialRef(kind="static", ref="s")},
            endpoint={
                "env": {
                    "VAR": {
                        "source": "credential",
                        "credential": "default",
                        "field": "token",
                    },
                },
            },
        )
        validate_card(card)

    def test_endpoint_public_non_string_value_rejected(self):
        card = _valid_card(endpoint={"env": {"public": {"VAR": 123}}})
        with pytest.raises(
            DriverCardError,
            match="public.VAR must be a string",
        ):
            validate_card(card)

    def test_endpoint_public_empty_key_rejected(self):
        card = _valid_card(endpoint={"env": {"public": {"": "x"}}})
        with pytest.raises(DriverCardError, match="keys must be non-empty"):
            validate_card(card)
