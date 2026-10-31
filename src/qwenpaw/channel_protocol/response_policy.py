# -*- coding: utf-8 -*-
"""Immutable, route-specific optional response operations and formatting."""

from collections.abc import Mapping
from dataclasses import dataclass
from .errors import ProtocolValidationError


@dataclass(frozen=True)
class SendFormatPolicy:
    """Declarative legacy formatting for direct and content-part sends."""

    direct_prefix: bool = True
    parts_configured_prefix: bool = True
    parts_metadata_prefix: bool = True
    stream_prefix: bool = True
    parts_strip_text: bool = True
    parts_preserve_order: bool = False

    def __post_init__(self):
        if any(
            type(getattr(self, key)) is not bool
            for key in self.__dataclass_fields__
        ):
            raise ProtocolValidationError(
                "Send format policy requires booleans",
            )

    @classmethod
    def from_mapping(cls, value):
        required = {"direct_prefix", "parts_configured_prefix"}
        if not isinstance(value, Mapping) or not required <= set(value) <= set(
            cls.__dataclass_fields__,
        ):
            raise ProtocolValidationError("Invalid send format policy fields")
        return cls(**value)

    def to_mapping(self):
        return {
            key: getattr(self, key)
            for key, field in self.__dataclass_fields__.items()
            if key in {"direct_prefix", "parts_configured_prefix"}
            or getattr(self, key) != field.default
        }


@dataclass(frozen=True)
class ResponsePolicy:
    streaming: bool = False
    prepare: bool = False
    completion_reaction: bool = False
    send_format: SendFormatPolicy | None = None
    text_merge_delay_ms: int | None = None
    continue_on_delivery_error: bool = False
    raw_completed_text: str | None = None
    text_merge_flush_before_media: bool = True
    text_merge_separator_newlines: int = 1
    text_merge_format_on_flush: bool = False

    def __post_init__(self):
        if any(
            type(getattr(self, key)) is not bool
            for key in (
                "streaming",
                "prepare",
                "completion_reaction",
                "continue_on_delivery_error",
                "text_merge_flush_before_media",
                "text_merge_format_on_flush",
            )
        ):
            raise ProtocolValidationError("Response policy requires booleans")
        if self.send_format is not None and not isinstance(
            self.send_format,
            SendFormatPolicy,
        ):
            raise ProtocolValidationError("Invalid send format policy")
        if self.text_merge_delay_ms is not None and (
            type(self.text_merge_delay_ms) is not int
            or not 0 <= self.text_merge_delay_ms <= 2**63 - 1
        ):
            raise ProtocolValidationError("Invalid text merge delay")
        if (
            type(self.text_merge_separator_newlines) is not int
            or not 1 <= self.text_merge_separator_newlines <= 3
        ):
            raise ProtocolValidationError("Invalid text merge separator")
        if self.raw_completed_text is not None and (
            not isinstance(self.raw_completed_text, str)
            or self.raw_completed_text not in {"content", "text_sources"}
        ):
            raise ProtocolValidationError("Invalid raw completed text policy")

    @classmethod
    def from_mapping(cls, value):
        fields = {"streaming", "prepare", "completion_reaction"}
        if not isinstance(value, Mapping) or not fields <= set(value) <= (
            fields
            | {
                "send_format",
                "text_merge_delay_ms",
                "continue_on_delivery_error",
                "raw_completed_text",
                "text_merge_flush_before_media",
                "text_merge_separator_newlines",
                "text_merge_format_on_flush",
            }
        ):
            raise ProtocolValidationError("Invalid response policy fields")
        data = dict(value)
        if "send_format" in data:
            data["send_format"] = SendFormatPolicy.from_mapping(
                data["send_format"],
            )
        return cls(**data)

    def to_mapping(self):
        data = {
            key: getattr(self, key)
            for key in ("streaming", "prepare", "completion_reaction")
        }
        if self.send_format is not None:
            data["send_format"] = self.send_format.to_mapping()
        if self.text_merge_delay_ms is not None:
            data["text_merge_delay_ms"] = self.text_merge_delay_ms
        if self.continue_on_delivery_error:
            data["continue_on_delivery_error"] = True
        if self.raw_completed_text is not None:
            data["raw_completed_text"] = self.raw_completed_text
        if not self.text_merge_flush_before_media:
            data["text_merge_flush_before_media"] = False
        if self.text_merge_separator_newlines != 1:
            data[
                "text_merge_separator_newlines"
            ] = self.text_merge_separator_newlines
        if self.text_merge_format_on_flush:
            data["text_merge_format_on_flush"] = True
        return data
