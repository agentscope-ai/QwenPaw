# -*- coding: utf-8 -*-
"""Driver card contracts and validation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .constants import (
    CREDENTIAL_KIND_NONE,
    PRINCIPAL_SUBJECT_USER,
)
from .errors import DriverCardError
from .policy_types import (
    ALLOWED_POLICY_EFFECTS,
    ALLOWED_POLICY_TARGET_KINDS,
    DriverPolicy,
    PolicyCondition,
    PolicyEffect,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
    TimeRange,
    coerce_driver_policy,
)

NO_CREDENTIAL_KIND = CREDENTIAL_KIND_NONE

__all__ = [
    "CredentialRef",
    "DriverCard",
    "DriverPolicy",
    "PolicyCondition",
    "PolicyEffect",
    "PolicyPrincipal",
    "PolicyRule",
    "PolicyTarget",
    "TimeRange",
    "coerce_card",
    "coerce_credential_ref",
    "coerce_credential_refs",
    "iter_credential_refs",
    "validate_card",
    "validate_card_name",
]


def validate_card_name(name: str) -> None:
    """Reject Driver names that cannot safely be used as storage keys."""
    if not name or not isinstance(name, str):
        raise DriverCardError("DriverCard.name must be a non-empty string")
    if "\x00" in name or "/" in name or "\\" in name or ".." in name:
        raise DriverCardError(
            "DriverCard.name must not contain path separators, null bytes, "
            "or '..'",
        )
    if name in {".", ".."}:
        raise DriverCardError("DriverCard.name must be a safe file name")


@dataclass(frozen=True)
class CredentialRef:
    """Reference from DriverCard to a credential source."""

    kind: str
    ref: str = ""


def coerce_credential_ref(value: Any) -> CredentialRef:
    """Normalize a loose credential mapping into ``CredentialRef``."""
    if isinstance(value, CredentialRef):
        return value
    if isinstance(value, dict):
        return CredentialRef(
            kind=str(value.get("kind") or ""),
            ref=str(value.get("ref") or ""),
        )
    if value is None:
        return CredentialRef(kind=NO_CREDENTIAL_KIND)
    return CredentialRef(
        kind=str(getattr(value, "kind", "") or ""),
        ref=str(getattr(value, "ref", "") or ""),
    )


def coerce_credential_refs(value: Any) -> dict[str, CredentialRef]:
    """Normalize a mapping of credential aliases to credential refs."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, CredentialRef] = {}
    for alias, raw_ref in value.items():
        alias_str = str(alias)
        if not alias_str:
            continue
        ref = coerce_credential_ref(raw_ref)
        if ref.kind and ref.kind != NO_CREDENTIAL_KIND:
            result[alias_str] = ref
    return result


@dataclass
class DriverCard:
    name: str
    protocol: str
    endpoint: dict[str, Any]
    credentials: dict[str, CredentialRef] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    policy: DriverPolicy = field(default_factory=DriverPolicy)

    def __post_init__(self) -> None:
        self.credentials = coerce_credential_refs(self.credentials)
        self.policy = coerce_driver_policy(self.policy)


def coerce_card(card: DriverCard) -> DriverCard:
    """Return a normalized DriverCard without mutating the input object."""
    return replace(
        card,
        credentials=coerce_credential_refs(card.credentials),
        policy=coerce_driver_policy(card.policy),
    )


def iter_credential_refs(card: DriverCard) -> dict[str, CredentialRef]:
    """Return the effective credential refs declared by a DriverCard."""
    return dict(card.credentials)


def validate_card(card: DriverCard) -> None:
    """Validate the public DriverCard contract without mutating it."""
    _validate_card_identity(card)
    _validate_card_credentials(card)
    _validate_driver_policy(card)
    _validate_endpoint_bindings(card)


def _validate_card_identity(card: DriverCard) -> None:
    validate_card_name(card.name)
    if not card.protocol or not isinstance(card.protocol, str):
        raise DriverCardError(
            f"DriverCard.protocol must be non-empty for {card.name}",
        )
    if not isinstance(card.endpoint, dict):
        raise DriverCardError(
            f"DriverCard.endpoint must be a mapping for {card.name}",
        )
    if not isinstance(card.config, dict):
        raise DriverCardError(
            f"DriverCard.config must be a mapping for {card.name}",
        )
    if not isinstance(card.policy, DriverPolicy):
        raise DriverCardError(
            f"DriverCard.policy must be DriverPolicy for {card.name}",
        )


def _validate_card_credentials(card: DriverCard) -> None:
    if not isinstance(card.credentials, dict):
        raise DriverCardError(
            f"DriverCard {card.name} credentials must be a mapping",
        )
    for alias, credential_ref in card.credentials.items():
        if not alias or not isinstance(alias, str):
            raise DriverCardError(
                f"DriverCard {card.name} credentials aliases must be "
                "non-empty strings",
            )
        if not credential_ref.kind or not isinstance(credential_ref.kind, str):
            raise DriverCardError(
                f"DriverCard {card.name} credentials.{alias}.kind must be "
                "non-empty",
            )


def _validate_driver_policy(card: DriverCard) -> None:
    if card.policy.default_effect not in ALLOWED_POLICY_EFFECTS:
        raise DriverCardError(
            f"DriverCard {card.name} has invalid default policy effect: "
            f"{card.policy.default_effect}",
        )

    for rule in card.policy.rules:
        if rule.effect not in ALLOWED_POLICY_EFFECTS:
            raise DriverCardError(
                f"DriverCard {card.name} has invalid policy effect: "
                f"{rule.effect}",
            )
        if not rule.target.kind or not isinstance(rule.target.kind, str):
            raise DriverCardError(
                f"DriverCard {card.name} policy target.kind must be non-empty",
            )
        if rule.target.kind not in ALLOWED_POLICY_TARGET_KINDS:
            raise DriverCardError(
                f"DriverCard {card.name} has invalid policy target.kind: "
                f"{rule.target.kind}",
            )
        if not rule.target.name or not isinstance(rule.target.name, str):
            raise DriverCardError(
                f"DriverCard {card.name} policy target.name must be non-empty",
            )
        for field_name in (
            "source_type",
            "source_value",
            "subject_type",
            "subject_value",
        ):
            value = getattr(rule.principal, field_name)
            if not isinstance(value, str):
                raise DriverCardError(
                    f"DriverCard {card.name} policy principal."
                    f"{field_name} must be a string",
                )
        if (
            rule.principal.subject_type.strip().lower()
            == PRINCIPAL_SUBJECT_USER
            and not rule.principal.subject_value.strip()
        ):
            raise DriverCardError(
                f"DriverCard {card.name} policy principal.subject_value "
                "must be non-empty when subject_type is user",
            )


def _validate_endpoint_bindings(card: DriverCard) -> None:
    # Binding sections keep the DriverCard secret-free: public values are
    # literals, while secret_refs point into CredentialRecord.secrets.
    for section_name in ("env", "headers"):
        section = card.endpoint.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise DriverCardError(
                f"DriverCard {card.name} endpoint.{section_name} "
                "must be a mapping",
            )
        if "public" not in section and "secret_refs" not in section:
            _validate_value_source_bindings(card, section_name, section)
            continue
        _validate_binding_mapping(
            card.name,
            section_name,
            "public",
            section.get("public", {}),
        )
        _validate_binding_mapping(
            card.name,
            section_name,
            "secret_refs",
            section.get("secret_refs", {}),
        )


def _validate_value_source_bindings(
    card: DriverCard,
    section_name: str,
    section: dict[str, Any],
) -> None:
    aliases = set(iter_credential_refs(card))
    for output_name, spec in section.items():
        label = f"DriverCard {card.name} endpoint.{section_name}.{output_name}"
        if isinstance(spec, str):
            continue
        if not isinstance(spec, dict):
            raise DriverCardError(
                f"{label} must be a string or source mapping",
            )
        if "source" not in spec:
            raise DriverCardError(f"{label} source mapping must name source")
        source = str(spec.get("source") or "")
        if source == "literal":
            value = spec.get("value")
            if value is not None and not isinstance(value, str):
                raise DriverCardError(
                    f"{label} literal value must be a string",
                )
            continue
        if source != "credential":
            raise DriverCardError(f"{label} has invalid source: {source}")
        alias = str(spec.get("credential") or "")
        field_name = str(spec.get("field") or "")
        if not alias:
            raise DriverCardError(
                f"{label} credential source must name a credential alias",
            )
        if alias not in aliases:
            raise DriverCardError(
                f"{label} references unknown credential alias: {alias}",
            )
        if not field_name:
            raise DriverCardError(
                f"{label} credential source must name a field",
            )
        fmt = spec.get("format")
        if fmt is not None and not isinstance(fmt, str):
            raise DriverCardError(f"{label} format must be a string")


def _validate_binding_mapping(
    card_name: str,
    section_name: str,
    field_name: str,
    value: Any,
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise DriverCardError(
            f"DriverCard {card_name} endpoint.{section_name}.{field_name} "
            "must be a mapping",
        )
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise DriverCardError(
                f"DriverCard {card_name} endpoint.{section_name}."
                f"{field_name} keys must be non-empty strings",
            )
        if not isinstance(item, str):
            raise DriverCardError(
                f"DriverCard {card_name} endpoint.{section_name}."
                f"{field_name}.{key} must be a string",
            )
