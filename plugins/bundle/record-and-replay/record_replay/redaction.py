# -*- coding: utf-8 -*-
"""Final plugin privacy guard applied before recording persistence."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from .errors import RecordingPrivacyError
from .models import RecordingEvent

_EVENT_EXCLUSIONS = frozenset(
    {
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.bitwarden.desktop",
        "com.lastpass.lastpass",
    },
)
_FORBIDDEN_KEYS = frozenset(
    {
        "characters",
        "clipboard",
        "clipboard_content",
        "content",
        "key_code",
        "key_text",
        "password",
        "raw_text",
        "secret",
        "text",
        "value",
    },
)
_APP_KEYS = frozenset({"bundle_id", "name", "pid"})
_WINDOW_KEYS = frozenset({"bounds", "role", "title", "window_id"})
_TARGET_KEYS = frozenset(
    {"bounds", "identifier", "name", "role", "secure", "subrole"},
)
_INPUT_KEYS = frozenset(
    {
        "button",
        "click_count",
        "delta_x",
        "delta_y",
        "duration_ms",
        "key_class",
        "length",
        "modifiers",
        "phase",
        "sample_count",
        "start_x",
        "start_y",
        "x",
        "y",
    },
)
_ENRICHMENT_KEYS = frozenset(
    {
        "app_status",
        "duration_ms",
        "queue_delay_ms",
        "reason",
        "status",
        "total_latency_ms",
    },
)
_BOUNDS_KEYS = frozenset({"x", "y", "width", "height"})
_STRING_KEYS = frozenset(
    {
        "bundle_id",
        "name",
        "role",
        "title",
        "identifier",
        "subrole",
        "button",
        "key_class",
        "phase",
        "app_status",
        "reason",
        "status",
    },
)
_INTEGER_KEYS = frozenset(
    {"pid", "window_id", "click_count", "length", "sample_count"},
)
_NUMBER_KEYS = frozenset(
    {
        "delta_x",
        "delta_y",
        "duration_ms",
        "start_x",
        "start_y",
        "x",
        "y",
        "queue_delay_ms",
        "total_latency_ms",
    },
)
_MODIFIER_NAMES = frozenset(
    {"caps_lock", "shift", "control", "option", "command", "fn"},
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|password|secret)[\"']?\s*[:=]"
    r"\s*\S+|\b(?:(?:sk|ghp|xox[baprs])-|gh[pousr]_|github_pat_)"
    r"[A-Za-z0-9_-]{8,}\b",
)


class RecordingRedactor:
    """Convert an untrusted native event into a persistence-safe model.

    This guard intentionally uses an allowlist. Unknown native fields are not
    persisted because a future OS/framework field could otherwise bypass the
    privacy contract merely by receiving a new name.
    """

    def redact_event(self, raw: Mapping[str, Any]) -> RecordingEvent:
        """Validate, minimize, and redact one untrusted native event."""
        if not isinstance(raw, Mapping):
            raise RecordingPrivacyError("event_not_an_object")
        self._reject_forbidden_fields(raw)

        app = self._allow_mapping(raw.get("app"), _APP_KEYS, "app")
        bundle_id = (app or {}).get("bundle_id", "").casefold()
        if any(
            bundle_id == root or bundle_id.startswith(root + ".")
            for root in _EVENT_EXCLUSIONS
        ):
            raise RecordingPrivacyError("excluded_recording_app")
        window = self._allow_mapping(
            raw.get("window"),
            _WINDOW_KEYS,
            "window",
        )
        target = self._allow_mapping(
            raw.get("target"),
            _TARGET_KEYS,
            "target",
        )
        event_input = (
            self._allow_mapping(
                raw.get("input", {}),
                _INPUT_KEYS,
                "input",
            )
            or {}
        )
        enrichment = (
            self._allow_mapping(
                raw.get("enrichment"),
                _ENRICHMENT_KEYS,
                "enrichment",
            )
            or {}
        )

        reasons: list[str] = []
        secure_target = target is not None and (
            target.get("secure") is True
            or target.get("role") == "AXSecureTextField"
            or target.get("subrole") == "AXSecureTextField"
        )
        if secure_target and target is not None:
            target["secure"] = True
            target.pop("name", None)
            reasons.append("secure_field")
        for container in (app, window, target):
            if container is not None:
                self._redact_sensitive_strings(container, reasons)

        supplied_redaction = raw.get("redaction")
        if supplied_redaction is not None:
            if not isinstance(supplied_redaction, Mapping):
                raise RecordingPrivacyError("invalid_native_redaction")
            if supplied_redaction.get("redacted"):
                reasons.append("native_guard")

        payload = {
            "event_schema_version": raw.get("event_schema_version"),
            "seq": raw.get("seq"),
            "t_monotonic_ms": raw.get("t_monotonic_ms"),
            "type": raw.get("type"),
            "app": app,
            "window": window,
            "target": target,
            "input": event_input,
            "enrichment": enrichment,
            # Source ranges are Python-owned normalization metadata. Never
            # accept them from the native transport as facts.
            "source": {},
            "redaction": {
                "redacted": bool(reasons),
                "reasons": sorted(set(reasons)),
            },
        }
        try:
            return RecordingEvent.model_validate(payload)
        except ValueError as exc:
            raise RecordingPrivacyError("invalid_event_contract") from exc

    def _reject_forbidden_fields(
        self,
        value: Any,
        *,
        prefix: str = "",
    ) -> None:
        if isinstance(value, list | tuple):
            for index, nested in enumerate(value):
                self._reject_forbidden_fields(
                    nested,
                    prefix=f"{prefix}[{index}]",
                )
            return
        if not isinstance(value, Mapping):
            return
        for key, nested in value.items():
            normalized = str(key).casefold()
            field = f"{prefix}.{key}" if prefix else str(key)
            if normalized in _FORBIDDEN_KEYS:
                raise RecordingPrivacyError(
                    f"forbidden_plaintext_field:{field}",
                )
            self._reject_forbidden_fields(nested, prefix=field)

    @classmethod
    def _allow_mapping(
        cls,
        value: Any,
        allowed: frozenset[str],
        field: str,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise RecordingPrivacyError(f"invalid_{field}")
        return {
            key: cls._project_field(key, value[key], f"{field}_{key}")
            for key in allowed
            if key in value
        }

    @classmethod
    def _project_field(cls, key: str, value: Any, field: str) -> Any:
        """Enforce shape as well as names at the untrusted import boundary."""
        if key == "bounds":
            return cls._project_bounds(value, field)
        elif key == "modifiers":
            if isinstance(value, list) and all(
                isinstance(item, str) and item in _MODIFIER_NAMES
                for item in value
            ):
                return list(value)
        elif key in _STRING_KEYS:
            if isinstance(value, str):
                return value
        elif key in _INTEGER_KEYS:
            if type(value) is int and value >= 0 and cls._finite_number(value):
                return value
        elif key in _NUMBER_KEYS:
            if cls._finite_number(value):
                return value
        elif key == "secure" and type(value) is bool:
            return value
        # Do not coerce an object/array/bool to a scalar or log its contents.
        # Adding an allowlist key must also require a field-type decision.
        raise RecordingPrivacyError(f"invalid_{field}")

    @classmethod
    def _project_bounds(cls, value: Any, field: str) -> dict | list:
        if isinstance(value, Mapping):
            bounds = {key: value[key] for key in _BOUNDS_KEYS if key in value}
            if all(cls._finite_number(item) for item in bounds.values()):
                return bounds
        # Preserve legacy [x, y, width, height] only for four finite numbers.
        elif isinstance(value, list) and len(value) == 4:
            if all(cls._finite_number(item) for item in value):
                return list(value)
        raise RecordingPrivacyError(f"invalid_{field}")

    @staticmethod
    def _finite_number(value: Any) -> bool:
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    @staticmethod
    def _redact_sensitive_strings(
        value: dict[str, Any],
        reasons: list[str],
    ) -> None:
        for key, item in tuple(value.items()):
            if isinstance(item, str) and _SENSITIVE_TEXT.search(item):
                value[key] = "[REDACTED]"
                reasons.append(f"sensitive_{key}")


__all__ = ["RecordingRedactor"]
