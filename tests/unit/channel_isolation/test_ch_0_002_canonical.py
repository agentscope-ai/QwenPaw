# -*- coding: utf-8 -*-
"""Tests for CH-0-002 canonical JSON and Requirement contracts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path, PureWindowsPath

import pytest

from qwenpaw.channel_protocol import (
    DescriptorValidationError,
    canonical_json,
    canonicalize_requirement,
    canonicalize_requirements,
    domain_sha256,
    parse_json_value,
)


def test_canonical_json_matches_unicode_escape_vector() -> None:
    """The exact string-escape bytes and digest match Design section 11."""
    value = {"sample": "a\x01b\n/\u2028\u2029é"}
    expected = b'{"sample":"a\\u0001b\\n/' + "\u2028\u2029é".encode() + b'"}'

    assert canonical_json(value) == expected
    assert domain_sha256("qwenpaw.channel.canonical-json.v1", value) == (
        "5b086f7a2fbaa46869e971cc985df0b13d5422a3013b600ae9883e6e1d5e0b01"
    )


def test_canonical_json_normalizes_and_sorts_object_members() -> None:
    """NFC-equivalent strings and source key order yield identical bytes."""
    first = {"z": "Cafe\u0301", "a": [True, False, None]}
    second = {"a": [True, False, None], "z": "Café"}

    assert canonical_json(first) == canonical_json(second)
    assert (
        canonical_json(first) == b'{"a":[true,false,null],"z":"Caf\xc3\xa9"}'
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-(2**63), b"-9223372036854775808"),
        (2**63 - 1, b"9223372036854775807"),
        (Decimal("-0.000"), b"0"),
        (Decimal("1.2300"), b"1.23"),
        (Decimal("1E+3"), b"1000"),
        (Decimal("1E-3"), b"0.001"),
    ],
)
def test_canonical_json_number_forms(value: object, expected: bytes) -> None:
    """Integers and exact decimals use their unique non-exponent form."""
    assert canonical_json(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        2**63,
        -(2**63) - 1,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1E+128"),
        1.5,
        b"secret",
        bytearray(b"secret"),
        Path("secret"),
        PureWindowsPath("C:/secret"),
        ("array",),
    ],
)
def test_canonical_json_rejects_values_outside_v1(value: object) -> None:
    """Host-specific and non-canonical value types are rejected."""
    with pytest.raises(DescriptorValidationError) as raised:
        canonical_json(value)

    assert raised.value.code == "descriptor_invalid"


def test_canonical_json_rejects_surrogates_and_normalized_duplicate_keys() -> (
    None
):
    """Only Unicode scalar values and unique NFC keys are accepted."""
    with pytest.raises(DescriptorValidationError):
        canonical_json("\ud800")
    with pytest.raises(DescriptorValidationError):
        canonical_json({"é": 1, "e\u0301": 2})


def test_parse_json_value_preserves_decimals_and_rejects_duplicate_keys() -> (
    None
):
    """The strict decoder never routes decimal JSON numbers through float."""
    parsed = parse_json_value('{"number":1.2300,"integer":2}')

    assert parsed == {"number": Decimal("1.2300"), "integer": 2}
    assert canonical_json(parsed) == b'{"integer":2,"number":1.23}'
    with pytest.raises(DescriptorValidationError):
        parse_json_value('{"same":1,"same":2}')
    with pytest.raises(DescriptorValidationError):
        parse_json_value(b'"\xff"')


def test_hash_domain_separator_isolation() -> None:
    """Equal canonical values in distinct domains never share a digest."""
    assert domain_sha256("domain.v1", {}) != domain_sha256("domain.v2", {})
    with pytest.raises(DescriptorValidationError):
        domain_sha256("non-ascii-é", {})
    with pytest.raises(DescriptorValidationError):
        domain_sha256("bad\x00domain", {})


def test_requirement_canonicalizes_name_extras_specifiers_and_duplicates() -> (
    None
):
    """Equivalent producer spelling converges after PEP 508 parsing."""
    values = [
        "Requests[SOCKS,security]>=2.0,!=2.5,>=2.0",
        "requests[security,socks] != 2.5, >= 2.0",
    ]

    assert canonicalize_requirements(values) == (
        "requests[security,socks]!=2.5,>=2.0",
    )
    assert canonicalize_requirement("foo[bar,bar]>=1,>=1") == "foo[bar]>=1"
    assert canonicalize_requirement("foo==01.0.*") == "foo==1.0.*"
    assert canonicalize_requirement("foo===CuStOm") == "foo===CuStOm"


def test_requirement_canonicalizes_marker_tree_and_rejects_extra() -> None:
    """Canonicalize marker ordering, precedence, and v1 extra rules."""
    first = 'foo ; python_version >= "3.11" and os_name == "posix"'
    second = "FOO; os_name == 'posix' and python_version >= '3.11'"

    assert canonicalize_requirement(first) == canonicalize_requirement(second)
    assert canonicalize_requirement(first) == (
        'foo ; os_name == "posix" and python_version >= "3.11"'
    )
    assert canonicalize_requirement(
        'foo; python_version >= "3.11" or '
        'os_name == "posix" and sys_platform == "linux"',
    ) == (
        'foo ; os_name == "posix" and sys_platform == "linux" '
        'or python_version >= "3.11"'
    )
    with pytest.raises(DescriptorValidationError):
        canonicalize_requirement('foo; extra == "cli"')
    with pytest.raises(DescriptorValidationError):
        canonicalize_requirement(
            'foo; os_name == "posix" and os_name == "posix"',
        )


def test_requirement_canonicalizes_direct_url() -> None:
    """Direct URLs receive the frozen RFC 3986 normalization."""
    value = "Demo @ HTTPS://ExAmple.COM:443/a/../b/%7e?q=%41#frag"

    assert canonicalize_requirement(value) == (
        "demo @ https://example.com/b/~?q=A#frag"
    )
    assert canonicalize_requirement("demo @ https://example.com") == (
        "demo @ https://example.com/"
    )
    with pytest.raises(DescriptorValidationError):
        canonicalize_requirement("demo @ https://user@example.com/archive")
    with pytest.raises(DescriptorValidationError):
        canonicalize_requirement("demo @ https://example.com/%zz")


@pytest.mark.parametrize(
    "value",
    [
        "not a requirement ???",
        "demo @ relative/path",
        42,
    ],
)
def test_requirement_rejects_invalid_inputs(value: object) -> None:
    """Every Requirement failure uses the stable validation exception."""
    with pytest.raises(DescriptorValidationError) as raised:
        canonicalize_requirement(value)  # type: ignore[arg-type]

    assert raised.value.code == "descriptor_invalid"
