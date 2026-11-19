# -*- coding: utf-8 -*-
"""Bounded data-only projections of completed text, without rendering."""

from dataclasses import dataclass
import json

from ..plugins.execution.models import _closed, _object, _string
from .errors import ProtocolValidationError
from ..plugins.execution.framing import FramingLimits


def _capacity():
    raise ProtocolValidationError(
        "Completed text exceeds the transport budget",
        reason_code="RAW_COMPLETED_TEXT_CAPACITY",
    )


def _size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ProtocolValidationError("Invalid completed text data") from exc


@dataclass(frozen=True)
class RawCompletedTextSources:
    getter_state: str
    getter_texts: tuple[str, ...] = ()
    top_texts: tuple[str, ...] = ()
    nested_texts: tuple[str, ...] = ()
    error_source: str | None = None

    def __post_init__(self):
        if not isinstance(self.getter_state, str) or self.getter_state not in {
            "not_requested",
            "absent",
            "values",
            "error",
        }:
            raise ProtocolValidationError(
                "Invalid completed text accessor state",
            )
        for values in (self.getter_texts, self.top_texts, self.nested_texts):
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ProtocolValidationError(
                    "Invalid completed text candidates",
                )
        if len(self.top_texts) > 1 or len(self.nested_texts) > 1:
            raise ProtocolValidationError(
                "Fallback text contains more than its first candidate",
            )
        if self.error_source is not None and (
            not isinstance(self.error_source, str)
            or self.error_source not in {"getter", "content", "message"}
        ):
            raise ProtocolValidationError(
                "Invalid completed text error source",
            )
        if (self.getter_state == "error") != (self.error_source == "getter"):
            raise ProtocolValidationError(
                "Accessor failure must remain explicit",
            )
        if self.getter_state != "values" and self.getter_texts:
            raise ProtocolValidationError("Unexpected accessor values")
        if (
            (self.getter_texts and (self.top_texts or self.nested_texts))
            or (self.top_texts and self.nested_texts)
            or (
                self.error_source
                and (self.getter_texts or self.top_texts or self.nested_texts)
            )
        ):
            raise ProtocolValidationError(
                "Completed text sources violate precedence",
            )
        if _size(self.to_mapping()) > FramingLimits().max_frame_bytes:
            _capacity()

    @classmethod
    def from_mapping(cls, value):
        data = _object(value)
        _closed(
            data,
            {
                "getter_state",
                "getter_texts",
                "top_texts",
                "nested_texts",
                "error_source",
            },
        )
        values = {}
        for name in ("getter_texts", "top_texts", "nested_texts"):
            if not isinstance(data.get(name), list):
                raise ProtocolValidationError(
                    "Completed text candidates must be arrays",
                )
            values[name] = tuple(_string(item, name) for item in data[name])
        return cls(
            _string(data.get("getter_state"), "getter_state"),
            error_source=data.get("error_source"),
            **values,
        )

    def to_mapping(self):
        result = {
            "getter_state": self.getter_state,
            "getter_texts": list(self.getter_texts),
            "top_texts": list(self.top_texts),
            "nested_texts": list(self.nested_texts),
        }
        if self.error_source is not None:
            result["error_source"] = self.error_source
        return result


class _Budget:
    def __init__(self):
        self.remaining = FramingLimits().max_frame_bytes

    def take(self, size):
        self.remaining -= size
        if self.remaining < 0:
            _capacity()

    def items(self, values):
        for value in values:
            # Bound even an iterator consisting entirely of ignored entries.
            self.take(4)
            yield value

    def text(self, value):
        if not isinstance(value, str):
            raise TypeError("Completed text is not a string")
        self.take(_size(value) + 1)
        return value


def project_completed_text(event, mode="content"):
    """Return raw parts plus optional provenance; never serialize an object.

    The content projection never accesses a text accessor or nested message.
    Text-source projection evaluates fallbacks lazily and records failures.
    """
    budget = _Budget()
    if mode == "content":
        parts = []
        for part in budget.items(getattr(event, "content", None) or ()):
            kind = getattr(part, "type", None)
            kind = getattr(kind, "value", kind)
            if kind != "text" and kind != "refusal":
                continue
            value = getattr(part, kind, None)
            if value is not None:
                parts.append(
                    {
                        "type": "text",
                        "text": budget.text(value),
                        "role": "refusal" if kind == "refusal" else "message",
                    },
                )
        return parts, None
    if mode != "text_sources":
        raise ProtocolValidationError("Invalid raw completed text projection")

    state, source = "absent", "getter"
    getter, top, nested = (), (), ()
    try:
        absent = object()
        accessor = getattr(event, "get_text_content", absent)
        if accessor is not absent:
            state = "values"
            values = accessor()
            if values:
                candidates = []
                for part in budget.items(values):
                    value = getattr(part, "text", None)
                    if value:
                        candidates.append(budget.text(value))
                getter = tuple(candidates)
        if not getter:
            source = "content"
            for part in budget.items(getattr(event, "content", None) or ()):
                value = getattr(part, "text", None)
                if value:
                    top = (budget.text(value),)
                    break
        if not getter and not top:
            source = "message"
            message = getattr(event, "message", None)
            if message:
                for part in budget.items(
                    getattr(message, "content", None) or (),
                ):
                    value = getattr(part, "text", None)
                    if value:
                        nested = (budget.text(value),)
                        break
    except Exception as error:
        if (
            isinstance(error, ProtocolValidationError)
            and error.reason_code == "RAW_COMPLETED_TEXT_CAPACITY"
        ):
            raise
        # Preserve accessor failure rather than treating it as absence. Do
        # not leak exception text or try later fallbacks after a failure.
        return [], RawCompletedTextSources(
            "error" if source == "getter" else state,
            error_source=source,
        )
    sources = RawCompletedTextSources(state, getter, top, nested)
    return [
        {"type": "text", "text": value, "role": "message"}
        for value in (getter or top or nested)
    ], sources
