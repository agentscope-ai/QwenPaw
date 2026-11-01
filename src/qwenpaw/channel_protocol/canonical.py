# -*- coding: utf-8 -*-
"""Canonical JSON primitives for Channel identifiers and descriptors."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any, cast

from .errors import DescriptorValidationError, PathPart, validation_error


_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def normalize_string(value: str, *, path: tuple[PathPart, ...] = ()) -> str:
    """Normalize a string to NFC and reject non-scalar code points."""
    normalized = unicodedata.normalize("NFC", value)
    if any(0xD800 <= ord(char) <= 0xDFFF for char in normalized):
        raise validation_error(
            "Unicode surrogate code points are not allowed",
            path=path,
        )
    return normalized


def _escape_string(value: str, *, path: tuple[PathPart, ...]) -> str:
    value = normalize_string(value, path=path)
    escaped: list[str] = ['"']
    for char in value:
        replacement = _SHORT_ESCAPES.get(char)
        if replacement is not None:
            escaped.append(replacement)
        elif ord(char) < 0x20:
            escaped.append(f"\\u00{ord(char):02x}")
        else:
            escaped.append(char)
    escaped.append('"')
    return "".join(escaped)


def _decimal_text(
    value: Decimal,
    *,
    path: tuple[PathPart, ...],
) -> str:
    if not value.is_finite():
        raise validation_error("Decimal must be finite", path=path)
    if value.is_zero():
        return "0"

    sign, raw_digits, exponent = value.as_tuple()
    exponent = cast(int, exponent)
    digits = list(raw_digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    body_digits = "".join(str(digit) for digit in digits)
    point = len(body_digits) + exponent
    sign_length = int(bool(sign))

    if point <= 0:
        output_length = sign_length + 2 - point + len(body_digits)
    elif point < len(body_digits):
        output_length = sign_length + len(body_digits) + 1
    else:
        output_length = sign_length + point
    if output_length > 128:
        raise validation_error(
            "Canonical decimal exceeds 128 characters",
            path=path,
        )

    if point <= 0:
        body = f"0.{('0' * -point)}{body_digits}"
    elif point < len(body_digits):
        body = f"{body_digits[:point]}.{body_digits[point:]}"
    else:
        body = f"{body_digits}{('0' * (point - len(body_digits)))}"
    return f"{'-' if sign else ''}{body}"


# Canonical JSON needs one explicit branch for each permitted value kind.
# pylint: disable=too-many-branches,too-many-return-statements
def _encode(
    value: Any,
    *,
    path: tuple[PathPart, ...],
) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if not _INT64_MIN <= value <= _INT64_MAX:
            raise validation_error(
                "Integer is outside the signed 64-bit range",
                path=path,
            )
        return str(value)
    if isinstance(value, Decimal):
        return _decimal_text(value, path=path)
    if isinstance(value, float):
        raise validation_error("Binary floats are not allowed", path=path)
    if isinstance(value, str):
        return _escape_string(value, path=path)
    if isinstance(value, list):
        encoded = [
            _encode(item, path=(*path, index))
            for index, item in enumerate(value)
        ]
        return f"[{','.join(encoded)}]"
    if isinstance(value, Mapping):
        normalized_items: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise validation_error(
                    "Object keys must be strings",
                    path=path,
                )
            normalized_key = normalize_string(key, path=(*path, key))
            if normalized_key in normalized_items:
                raise validation_error(
                    "Object contains duplicate keys after NFC normalization",
                    path=(*path, normalized_key),
                )
            normalized_items[normalized_key] = item
        members = []
        for key in sorted(normalized_items):
            encoded_key = _escape_string(key, path=(*path, key))
            encoded_value = _encode(
                normalized_items[key],
                path=(*path, key),
            )
            members.append(f"{encoded_key}:{encoded_value}")
        return f"{{{','.join(members)}}}"
    if isinstance(value, (bytes, bytearray, Path)):
        kind = type(value).__name__
        raise validation_error(f"{kind} values are not allowed", path=path)
    raise validation_error(
        f"Unsupported canonical JSON value: {type(value).__name__}",
        path=path,
    )


# pylint: enable=too-many-branches,too-many-return-statements


def canonical_json(value: Any) -> bytes:
    """Encode a value using the Channel canonical JSON v1 rules."""
    return _encode(value, path=()).encode("utf-8")


def _reject_constant(value: str) -> None:
    raise validation_error(f"Non-finite JSON number is not allowed: {value}")


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        normalized_key = normalize_string(key, path=(key,))
        if normalized_key in result:
            raise validation_error(
                "JSON object contains duplicate keys",
                path=(normalized_key,),
            )
        result[normalized_key] = value
    return result


def parse_json_value(data: str | bytes) -> Any:
    """Parse JSON with exact decimals and strict duplicate-key handling."""
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as exc:
        raise validation_error("JSON input must be valid UTF-8") from exc
    try:
        value = json.loads(
            text,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_from_pairs,
        )
    except DescriptorValidationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise validation_error("Invalid JSON input") from exc
    canonical_json(value)
    return value


def domain_sha256(domain: str, value: Any) -> str:
    """Hash canonical JSON with an ASCII domain separator and one NUL."""
    try:
        domain_bytes = domain.encode("ascii")
    except UnicodeEncodeError as exc:
        raise validation_error("Hash domain must be ASCII") from exc
    if not domain or "\x00" in domain:
        raise validation_error("Hash domain must be non-empty and NUL-free")
    payload = domain_bytes + b"\x00" + canonical_json(value)
    return hashlib.sha256(payload).hexdigest()
