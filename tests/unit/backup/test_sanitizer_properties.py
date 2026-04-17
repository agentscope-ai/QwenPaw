# -*- coding: utf-8 -*-
"""Property-based tests for preference sanitization.

**Property 3: 敏感数据脱敏完整性**
**Validates: Requirements 7.1, 7.2, 7.3**
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from qwenpaw.backup.sanitizer import (
    REDACTED,
    SENSITIVE_FIELDS,
    sanitize_preferences,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty strings for sensitive field values
_nonempty_str = st.text(min_size=1, max_size=50)

# Arbitrary JSON-like leaf values (not dict/list)
_leaf_value = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)

# Keys that are NOT sensitive
_safe_key = st.text(min_size=1, max_size=20).filter(
    lambda k: k not in SENSITIVE_FIELDS,
)

# Keys that ARE sensitive
_sensitive_key = st.sampled_from(sorted(SENSITIVE_FIELDS))


@st.composite
def _nested_config(draw: st.DrawFn, max_depth: int = 3) -> dict:
    """Generate arbitrarily nested config dicts."""
    num_keys = draw(st.integers(min_value=0, max_value=6))
    result: dict = {}
    for _ in range(num_keys):
        key = draw(st.one_of(_safe_key, _sensitive_key))
        if max_depth <= 0:
            value = draw(_leaf_value)
        else:
            choice = draw(st.integers(min_value=0, max_value=2))
            if choice == 0:
                value = draw(_leaf_value)
            elif choice == 1:
                value = draw(_nested_config(max_depth=max_depth - 1))
            else:
                list_size = draw(st.integers(min_value=0, max_value=4))
                items = []
                for _ in range(list_size):
                    is_dict = draw(st.booleans())
                    if is_dict:
                        items.append(
                            draw(_nested_config(max_depth=max_depth - 1)),
                        )
                    else:
                        items.append(draw(_leaf_value))
                value = items
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def _collect_sensitive_values(d: dict) -> list[tuple[str, object]]:
    """Walk *d* and return (key, value) for every sensitive key."""
    results: list[tuple[str, object]] = []
    for key, value in d.items():
        if key in SENSITIVE_FIELDS:
            results.append((key, value))
        if isinstance(value, dict):
            results.extend(_collect_sensitive_values(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    results.extend(_collect_sensitive_values(item))
    return results


def _collect_nonsensitive_values(d: dict) -> list[tuple[str, object]]:
    """Walk *d* and return (key, value) for every
    non-sensitive, non-container key.
    """
    results: list[tuple[str, object]] = []
    for key, value in d.items():
        if key not in SENSITIVE_FIELDS:
            if isinstance(value, dict):
                results.extend(_collect_nonsensitive_values(value))
            elif isinstance(value, list):
                # list values at non-sensitive keys are preserved as-is
                # (only dict items inside are recursed,
                # but the key itself is safe)
                results.append((key, value))
            else:
                results.append((key, value))
    return results


@given(config=_nested_config())
@settings(max_examples=200)
def test_sensitive_fields_redacted(config: dict) -> None:
    """All SENSITIVE_FIELDS with non-empty string values must be replaced
    with REDACTED after sanitization.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """
    sanitized = sanitize_preferences(config)
    # Direct check: walk sanitized and verify
    _assert_all_sensitive_redacted(config, sanitized)


def _assert_all_sensitive_redacted(original: dict, sanitized: dict) -> None:
    """Recursively verify sensitive fields are properly redacted."""
    for key in original:
        orig_val = original[key]
        san_val = sanitized[key]

        if key in SENSITIVE_FIELDS:
            if isinstance(orig_val, str) and orig_val:
                # Non-empty string sensitive value → must be REDACTED
                assert san_val == REDACTED, (
                    f"Sensitive key {key!r} with non-empty string value "
                    f"should be REDACTED, got {san_val!r}"
                )
            elif isinstance(orig_val, dict):
                # Dict value under sensitive key → recursively sanitized
                assert isinstance(san_val, dict)
                _assert_all_sensitive_redacted(orig_val, san_val)
            elif isinstance(orig_val, list):
                # List value under sensitive key → list items recursed
                assert isinstance(san_val, list)
                _assert_list_sanitized(orig_val, san_val)
            else:
                # Non-string or empty string: value preserved as-is
                assert san_val == orig_val, (
                    f"Sensitive key {key!r} with non-string/empty value "
                    f"should be preserved, got {san_val!r}"
                )
        elif isinstance(orig_val, str) and orig_val.startswith("ENC:"):
            # ENC:-prefixed values are redacted regardless of key name
            assert san_val == REDACTED, (
                f"ENC:-prefixed value at non-sensitive key {key!r} "
                f"should be REDACTED, got {san_val!r}"
            )
        elif isinstance(orig_val, dict):
            assert isinstance(san_val, dict)
            _assert_all_sensitive_redacted(orig_val, san_val)
        elif isinstance(orig_val, list):
            assert isinstance(san_val, list)
            _assert_list_sanitized(orig_val, san_val)
        else:
            assert san_val == orig_val, (
                f"Non-sensitive key {key!r} value changed: "
                f"{orig_val!r} -> {san_val!r}"
            )


def _assert_list_sanitized(original: list, sanitized: list) -> None:
    """Verify list elements are properly sanitized."""
    assert len(sanitized) == len(original)
    for o_item, s_item in zip(original, sanitized):
        if isinstance(o_item, dict):
            assert isinstance(s_item, dict)
            _assert_all_sensitive_redacted(o_item, s_item)
        else:
            assert s_item == o_item


@given(config=_nested_config())
@settings(max_examples=200)
def test_nonsensitive_fields_unchanged(config: dict) -> None:
    """Non-sensitive fields must remain unchanged after sanitization.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """
    sanitized = sanitize_preferences(config)
    _assert_all_sensitive_redacted(config, sanitized)


# ---------------------------------------------------------------------------
# ENC: prefix strategies
# ---------------------------------------------------------------------------

# Generate strings that start with "ENC:" (Fernet-encrypted values)
_enc_value = st.text(min_size=1, max_size=40).map(lambda s: f"ENC:{s}")


@st.composite
def _config_with_enc_values(draw: st.DrawFn, max_depth: int = 3) -> dict:
    """Generate nested config dicts that include ENC:-prefixed values
    under non-sensitive keys, to test encrypted value redaction.
    """
    num_keys = draw(st.integers(min_value=1, max_value=6))
    result: dict = {}
    for _ in range(num_keys):
        key = draw(_safe_key)
        if max_depth <= 0:
            # At leaf level, mix ENC: values with normal values
            value = draw(st.one_of(_enc_value, _leaf_value))
        else:
            choice = draw(st.integers(min_value=0, max_value=3))
            if choice == 0:
                value = draw(_enc_value)
            elif choice == 1:
                value = draw(_leaf_value)
            elif choice == 2:
                value = draw(_config_with_enc_values(max_depth=max_depth - 1))
            else:
                list_size = draw(st.integers(min_value=0, max_value=3))
                items = []
                for _ in range(list_size):
                    is_dict = draw(st.booleans())
                    if is_dict:
                        items.append(
                            draw(
                                _config_with_enc_values(
                                    max_depth=max_depth - 1,
                                ),
                            ),
                        )
                    else:
                        items.append(draw(st.one_of(_enc_value, _leaf_value)))
                value = items
        result[key] = value
    return result


def _collect_enc_values(
    d: dict,
) -> list[tuple[list[str], str]]:
    """Walk *d* and return (key_path, value) for every ENC:-prefixed string."""
    results: list[tuple[list[str], str]] = []
    for key, value in d.items():
        if isinstance(value, str) and value.startswith("ENC:"):
            results.append(([key], value))
        elif isinstance(value, dict):
            for path, v in _collect_enc_values(value):
                results.append(([key] + path, v))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for path, v in _collect_enc_values(item):
                        results.append(([key, f"[{i}]"] + path, v))
    return results


def _assert_enc_values_redacted(original: dict, sanitized: dict) -> None:
    """Recursively verify all ENC:-prefixed values are redacted,
    regardless of key name.
    """
    for key in original:
        orig_val = original[key]
        san_val = sanitized[key]

        if key in SENSITIVE_FIELDS:
            # Sensitive keys are handled by the other property test
            continue

        if isinstance(orig_val, str) and orig_val.startswith("ENC:"):
            assert san_val == REDACTED, (
                f"ENC:-prefixed value at key {key!r} should be REDACTED, "
                f"got {san_val!r}"
            )
        elif isinstance(orig_val, dict):
            assert isinstance(san_val, dict)
            _assert_enc_values_redacted(orig_val, san_val)
        elif isinstance(orig_val, list):
            assert isinstance(san_val, list)
            assert len(san_val) == len(orig_val)
            for o_item, s_item in zip(orig_val, san_val):
                if isinstance(o_item, dict):
                    assert isinstance(s_item, dict)
                    _assert_enc_values_redacted(o_item, s_item)
        else:
            # Non-ENC, non-sensitive, non-container → preserved
            assert san_val == orig_val


@given(config=_config_with_enc_values())
@settings(max_examples=200)
def test_enc_prefixed_values_redacted(config: dict) -> None:
    """All values starting with 'ENC:' prefix must be replaced with REDACTED
    after sanitization, regardless of key name.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """
    sanitized = sanitize_preferences(config)
    _assert_enc_values_redacted(config, sanitized)
