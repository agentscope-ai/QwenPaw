# -*- coding: utf-8 -*-
"""Shared Channel descriptor values and validation helpers."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, cast, Literal, TypeAlias
from urllib.parse import urlsplit

from .canonical import normalize_string
from .errors import DescriptorValidationError, PathPart, validation_error


LocalizedText: TypeAlias = str | Mapping[str, str]
_ENTRYPOINT_FIELDS = frozenset({"scope", "module", "qualname"})
_DOTTED_NAME_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$",
)
_LOCALE_PATTERN = re.compile(r"^[a-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_URL_PERCENT_ESCAPE_PATTERN = re.compile(r"%[0-9A-Fa-f]{2}")
_URL_FORBIDDEN_CHARACTERS = frozenset('<>"{}|\\^`')
_ENTRYPOINT_SCOPES = frozenset({"core", "runner"})


def _error(message: str, *path: PathPart) -> DescriptorValidationError:
    return validation_error(message, path=path)


def _require_mapping(value: Any, *path: PathPart) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("Expected an object", *path)
    return value


def _closed_object(
    value: Any,
    expected: frozenset[str],
    *path: PathPart,
) -> Mapping[str, Any]:
    mapping = _require_mapping(value, *path)
    if any(not isinstance(key, str) for key in mapping):
        raise _error("Object field names must be strings", *path)
    keys = set(mapping)
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        details = f"missing={missing}, unknown={unknown}"
        raise _error(f"Object fields do not match v1 shape: {details}", *path)
    return mapping


def _string(value: Any, *path: PathPart, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise _error("Expected a string", *path)
    normalized = normalize_string(value, path=tuple(path))
    if nonempty and not normalized:
        raise _error("String must not be empty", *path)
    return normalized


def _enum(
    value: Any,
    allowed: Collection[str],
    *path: PathPart,
) -> str:
    normalized = _string(value, *path)
    if normalized not in allowed:
        raise _error("Value is not in the closed enum", *path)
    return normalized


def _http_url(value: str, *path: PathPart) -> str:
    if not value:
        return value
    if any(
        character.isspace()
        or ord(character) < 0x20
        or ord(character) == 0x7F
        or character in _URL_FORBIDDEN_CHARACTERS
        for character in value
    ):
        raise _error("HTTP(S) URL contains an invalid character", *path)
    for index, character in enumerate(value):
        if (
            character == "%"
            and _URL_PERCENT_ESCAPE_PATTERN.match(value, index) is None
        ):
            raise _error("HTTP(S) URL percent escape is invalid", *path)
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise _error("HTTP(S) URL is invalid", *path) from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise _error("Expected an absolute HTTP(S) URL", *path)
    if port is not None and not 0 < port < 65536:
        raise _error("HTTP(S) URL port is invalid", *path)
    return value


def _localized_text(
    value: Any,
    *path: PathPart,
    url: bool = False,
) -> LocalizedText:
    if isinstance(value, str):
        normalized = _string(value, *path)
        return _http_url(normalized, *path) if url else normalized
    mapping = _require_mapping(value, *path)
    if not mapping:
        raise _error("LocalizedText map must not be empty", *path)
    output: dict[str, str] = {}
    for locale, text in mapping.items():
        normalized_locale = _string(locale, *path, "locale", nonempty=True)
        if not _LOCALE_PATTERN.fullmatch(normalized_locale):
            raise _error("Locale key is not canonical BCP-47", *path, locale)
        if normalized_locale in output:
            raise _error("LocalizedText contains a duplicate locale", *path)
        normalized_text = _string(text, *path, normalized_locale)
        output[normalized_locale] = (
            _http_url(normalized_text, *path, normalized_locale)
            if url
            else normalized_text
        )
    return MappingProxyType(output)


@dataclass(frozen=True)
class Entrypoint:
    """Static import path interpreted only after descriptor validation."""

    scope: Literal["core", "runner"]
    module: str
    qualname: str

    def to_mapping(self) -> dict[str, str]:
        """Return the closed canonical JSON object."""
        return {
            "scope": self.scope,
            "module": self.module,
            "qualname": self.qualname,
        }


def _parse_entrypoint(value: Any, process_mode: str) -> Entrypoint:
    mapping = _closed_object(value, _ENTRYPOINT_FIELDS, "entrypoint")
    scope = _enum(
        mapping["scope"],
        _ENTRYPOINT_SCOPES,
        "entrypoint",
        "scope",
    )
    module = _string(
        mapping["module"],
        "entrypoint",
        "module",
        nonempty=True,
    )
    qualname = _string(
        mapping["qualname"],
        "entrypoint",
        "qualname",
        nonempty=True,
    )
    if not module.isascii() or not _DOTTED_NAME_PATTERN.fullmatch(module):
        raise _error("Entrypoint module is invalid", "entrypoint", "module")
    if not qualname.isascii() or not _DOTTED_NAME_PATTERN.fullmatch(qualname):
        raise _error(
            "Entrypoint qualname is invalid",
            "entrypoint",
            "qualname",
        )
    expected_scope = "core" if process_mode == "in_process" else "runner"
    if scope != expected_scope:
        raise _error(
            "Entrypoint scope does not match process mode",
            "entrypoint",
            "scope",
        )
    return Entrypoint(
        scope=cast(Literal["core", "runner"], scope),
        module=module,
        qualname=qualname,
    )
