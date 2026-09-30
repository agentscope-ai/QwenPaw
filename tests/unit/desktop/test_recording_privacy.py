# -*- coding: utf-8 -*-
"""Independent Python guard tests, including malformed native artifacts."""

from __future__ import annotations

import json

import pytest

from record_replay.errors import RecordingPrivacyError
from record_replay.redaction import RecordingRedactor


def _event() -> dict:
    return {
        "event_schema_version": 1,
        "seq": 0,
        "t_monotonic_ms": 1,
        "type": "scroll",
        "app": {"bundle_id": "test.fixture", "name": "Fixture", "pid": 42},
        "window": {"role": "AXWindow", "title": "Fixture", "window_id": 1},
        "target": {"role": "AXButton", "name": "Continue", "secure": False},
        "input": {"delta_x": 0, "delta_y": 1, "modifiers": ["shift"]},
        "enrichment": {"status": "ok", "duration_ms": 0.5},
    }


@pytest.mark.parametrize(
    "identity",
    [
        {
            "role": "AXTextField",
            "subrole": "AXSecureTextField",
            "secure": False,
        },
        {"role": "AXTextField", "subrole": "AXSecureTextField"},
        {"role": "AXSecureTextField", "secure": False},
        {"role": "AXTextField", "secure": True},
    ],
)
def test_secure_target_identity_does_not_trust_native_boolean(identity):
    raw = _event()
    raw["target"] = {**identity, "name": "UNCLASSIFIED_PRIVATE_CANARY"}
    event = RecordingRedactor().redact_event(raw)
    assert event.target["secure"] is True
    assert "name" not in event.target
    assert "secure_field" in event.redaction["reasons"]
    assert "UNCLASSIFIED_PRIVATE_CANARY" not in event.model_dump_json()
    assert raw["target"]["name"] == "UNCLASSIFIED_PRIVATE_CANARY"


def test_ordinary_target_name_is_not_blanket_removed():
    raw = _event()
    event = RecordingRedactor().redact_event(raw)
    assert event.target == raw["target"]


@pytest.mark.parametrize("container", ["window", "target"])
def test_python_bounds_projection_drops_unknown_nested_values(container):
    raw = _event()
    raw[container]["bounds"] = {
        "x": -2,
        "y": 1.5,
        "width": 30,
        "height": 40,
        "annotation": {"note": "password=FAKE_PRIVATE_CANARY"},
    }
    event = RecordingRedactor().redact_event(raw)
    assert getattr(event, container)["bounds"] == {
        "x": -2,
        "y": 1.5,
        "width": 30,
        "height": 40,
    }
    assert "FAKE_PRIVATE_CANARY" not in event.model_dump_json()
    # Project into owned dictionaries; never modify the producer's evidence.
    assert "annotation" in raw[container]["bounds"]


@pytest.mark.parametrize(
    "container,key",
    [
        ("app", "bundle_id"),
        ("app", "name"),
        ("app", "pid"),
        ("window", "role"),
        ("window", "title"),
        ("window", "window_id"),
        ("target", "identifier"),
        ("target", "name"),
        ("target", "secure"),
        ("target", "subrole"),
        ("input", "x"),
        ("input", "click_count"),
        ("input", "key_class"),
        ("input", "phase"),
        ("enrichment", "status"),
        ("enrichment", "duration_ms"),
        ("enrichment", "reason"),
        ("enrichment", "app_status"),
    ],
)
@pytest.mark.parametrize(
    "invalid",
    [{"annotation": "FAKE_PRIVATE_CANARY"}, ["FAKE_PRIVATE_CANARY"]],
)
def test_python_rejects_containers_in_scalar_fields(container, key, invalid):
    raw = _event()
    raw[container][key] = invalid
    with pytest.raises(RecordingPrivacyError, match="invalid_") as failure:
        RecordingRedactor().redact_event(raw)
    assert "FAKE_PRIVATE_CANARY" not in str(failure.value)


@pytest.mark.parametrize(
    "invalid",
    [
        True,
        "1",
        None,
        {"annotation": "FAKE_PRIVATE_CANARY"},
        [1],
        float("nan"),
        float("inf"),
        float("-inf"),
        10**400,
    ],
)
def test_python_bounds_require_finite_numbers_without_coercion(invalid):
    raw = _event()
    raw["target"]["bounds"] = {"x": invalid}
    with pytest.raises(RecordingPrivacyError, match="invalid_"):
        RecordingRedactor().redact_event(raw)


@pytest.mark.parametrize(
    "invalid",
    [[1, 2, 3], [1, 2, 3, 4, 5], [1, True, 3, 4], [1, "2", 3, 4]],
)
def test_python_rejects_malformed_legacy_bounds(invalid):
    raw = _event()
    raw["target"]["bounds"] = invalid
    with pytest.raises(RecordingPrivacyError, match="invalid_"):
        RecordingRedactor().redact_event(raw)


def test_python_preserves_valid_legacy_bounds_and_numeric_geometry():
    raw = _event()
    raw["target"]["bounds"] = [-1, 2.5, 30, 40]
    raw["window"]["bounds"] = {"x": 1}
    event = RecordingRedactor().redact_event(raw)
    assert event.target["bounds"] == [-1, 2.5, 30, 40]
    assert event.window["bounds"] == {"x": 1}
    assert event.input["modifiers"] == ["shift"]
    assert json.loads(event.model_dump_json())["app"]["pid"] == 42


@pytest.mark.parametrize(
    "invalid",
    [
        [{"annotation": "FAKE_PRIVATE_CANARY"}],
        ["FAKE_PRIVATE_CANARY"],
        "shift",
        [True],
    ],
)
def test_python_modifiers_are_only_known_names(invalid):
    raw = _event()
    raw["input"]["modifiers"] = invalid
    with pytest.raises(RecordingPrivacyError, match="invalid_"):
        RecordingRedactor().redact_event(raw)


def test_python_still_rejects_nested_forbidden_fields_independently():
    raw = _event()
    raw["target"]["bounds"] = {"x": 1, "text": "FAKE_PRIVATE_CANARY"}
    with pytest.raises(RecordingPrivacyError, match="forbidden_plaintext"):
        RecordingRedactor().redact_event(raw)


@pytest.mark.parametrize(
    "container,key",
    [("window", "title"), ("target", "name"), ("app", "name")],
)
@pytest.mark.parametrize(
    "label",
    [
        "Account ghp_FAKE_TOKEN_CANARY_12345678",
        "Account github_pat_FAKE_TOKEN_CANARY_12345678",
        "Account gho_FAKE_TOKEN_CANARY_12345678",
        "Account ghu_FAKE_TOKEN_CANARY_12345678",
        "Account ghs_FAKE_TOKEN_CANARY_12345678",
        "Account ghr_FAKE_TOKEN_CANARY_12345678",
        '{"password": "FAKE_LABEL_CANARY"}',
        "{'api_key': 'FAKE_LABEL_CANARY'}",
        '{"access_token" : "FAKE_LABEL_CANARY"}',
        'SECRET="FAKE_LABEL_CANARY"',
        "api_key=sk-FAKE_LABEL_CANARY",
        "xoxb-FAKE_LABEL_CANARY",
    ],
)
def test_credential_labels_are_redacted_without_touching_source(
    container,
    key,
    label,
):
    raw = _event()
    raw[container][key] = label
    event = RecordingRedactor().redact_event(raw)
    assert getattr(event, container)[key] == "[REDACTED]"
    assert f"sensitive_{key}" in event.redaction["reasons"]
    assert raw[container][key] == label


@pytest.mark.parametrize(
    "label",
    [
        "Password settings",
        "API key guide",
        "Github pull requests",
        "普通输入框",
        "Calculator",
    ],
)
def test_ordinary_labels_remain_useful(label):
    raw = _event()
    raw["window"]["title"] = label
    assert RecordingRedactor().redact_event(raw).window["title"] == label


@pytest.mark.parametrize("field", ["key_code", "KEY_CODE"])
def test_raw_keyboard_codes_are_rejected_even_in_unknown_containers(field):
    raw = _event()
    raw["unknown"] = {field: 42}
    with pytest.raises(
        RecordingPrivacyError,
        match="forbidden_plaintext_field",
    ):
        RecordingRedactor().redact_event(raw)


@pytest.mark.parametrize(
    "bundle_id",
    [
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.bitwarden.desktop",
        "com.lastpass.LastPass",
        "COM.BITWARDEN.DESKTOP.extension",
    ],
)
def test_excluded_app_events_rejected_by_independent_import_guard(bundle_id):
    raw = _event()
    raw["app"]["bundle_id"] = bundle_id
    with pytest.raises(RecordingPrivacyError, match="excluded_recording_app"):
        RecordingRedactor().redact_event(raw)


def test_exclusion_does_not_match_an_unrelated_prefix():
    raw = _event()
    raw["app"]["bundle_id"] = "com.bitwarden.desktop-fixture"
    assert RecordingRedactor().redact_event(raw).app == raw["app"]
