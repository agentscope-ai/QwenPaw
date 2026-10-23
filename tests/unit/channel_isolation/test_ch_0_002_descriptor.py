# -*- coding: utf-8 -*-
"""Current shared descriptor validation stays static, closed and detached."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from qwenpaw.channel_protocol import DescriptorValidationError
from qwenpaw.channel_protocol.descriptor import _localized_text
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor


def test_value_model_imports_no_channel_implementation_modules() -> None:
    """The pure package does not load Registry, Channel, or platform SDKs."""
    script = (
        "import json, sys; "
        "import qwenpaw.channel_protocol; "
        "print(json.dumps(sorted(name for name in sys.modules "
        "if name.startswith('qwenpaw.app.channels.'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def _descriptor() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/channel_plugins/sample_chat/channel.json"
    )
    value = json.loads(path.read_text())
    value["label"] = {"zh": "示例", "en": "Fixture\u0301"}
    return value


def _validate(value: dict[str, Any]) -> SharedChannelDescriptor:
    return SharedChannelDescriptor.from_mapping(value)


def test_descriptor_localized_maps_are_immutable_and_defensively_copied():
    value = _descriptor()
    descriptor = _validate(value)
    label: Any = descriptor.label
    with pytest.raises(TypeError):
        label["en"] = "Changed"
    output = descriptor.to_mapping()
    output["label"]["en"] = "Changed output"
    value["label"]["en"] = "Changed source"
    assert descriptor.label["en"] == "Fixturé"
    assert descriptor.to_mapping()["label"]["en"] == "Fixturé"


def test_descriptor_json_decoder_preserves_decimal_numbers():
    value = _descriptor()
    value["config_schema"]["properties"]["ratio"] = {
        "type": "number",
        "default": Decimal("1.2300"),
    }
    value["config_fields"].append("ratio")
    descriptor = _validate(value)
    parsed = SharedChannelDescriptor.from_json(
        json.dumps(descriptor.to_mapping(), allow_nan=False),
    )
    ratio = parsed.config_schema["properties"]["ratio"]["default"]
    assert type(ratio) is float
    assert Decimal(str(ratio)) == Decimal("1.23")
    assert parsed.to_mapping() == descriptor.to_mapping()


def test_descriptor_does_not_import_entrypoint() -> None:
    """Static validation treats entrypoint as data and imports no module."""
    module = "qwenpaw.fixture.never_imported"
    value = _descriptor()
    value["entrypoint"]["module"] = module

    assert module not in sys.modules
    assert _validate(value).entrypoint.module == module
    assert module not in sys.modules


@pytest.mark.parametrize(
    "label",
    [{}, {"en": "English"}, {"zh": "中文"}, {"en": "", "zh": "中文"}],
)
def test_shared_descriptor_requires_both_localized_labels(label):
    value = _descriptor()
    value["label"] = label
    with pytest.raises(DescriptorValidationError):
        _validate(value)


def test_localized_text_rejects_non_http_urls_and_empty_maps():
    with pytest.raises(DescriptorValidationError):
        _localized_text({"en": "file:///tmp/docs"}, "doc_url", url=True)
    with pytest.raises(DescriptorValidationError):
        _localized_text({}, "label")


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("icon", "https://exa mple.com/icon.png"),
        ("icon", "https://example.com/a b"),
        ("icon", "https://example.com/\\path"),
        ("doc_url", "https://example.com/\x01docs"),
        ("doc_url", "https:///docs"),
        ("doc_url", "https://example.com/%zz"),
        ("doc_url", "https://example.com/<docs>"),
    ],
)
def test_descriptor_rejects_malformed_http_urls(field: str, url: str) -> None:
    """Display URLs must be syntactically valid absolute HTTP(S) URLs."""
    with pytest.raises(DescriptorValidationError) as raised:
        _localized_text(url, field, url=True)

    assert raised.value.code == "descriptor_invalid"


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("schema_version", 1),
        ("process_mode", "thread"),
        ("dependency_mode", "dedicated"),
        ("requirements_file", "nested/requirements.txt"),
    ],
)
def test_descriptor_rejects_each_closed_enum(field, invalid):
    value = _descriptor()
    value[field] = invalid
    with pytest.raises(DescriptorValidationError) as raised:
        _validate(value)
    assert raised.value.code == "descriptor_invalid"


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("scope", "worker"),
        ("scope", "core"),
        ("module", "fixture-invalid"),
        ("module", "非英文"),
        ("qualname", "Driver()"),
        ("qualname", "nested..Driver"),
    ],
)
def test_descriptor_rejects_invalid_entrypoint(field, invalid):
    value = _descriptor()
    value["entrypoint"][field] = invalid
    with pytest.raises(DescriptorValidationError) as raised:
        _validate(value)
    assert raised.value.code == "descriptor_invalid"
    assert raised.value.path[:1] == ("entrypoint",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value["entrypoint"].update({"unknown": True}),
    ],
)
def test_descriptor_rejects_unknown_fields(mutate):
    value = _descriptor()
    mutate(value)
    with pytest.raises(DescriptorValidationError):
        _validate(value)


def test_descriptor_failure_has_stable_code_and_diagnostic_path():
    value = deepcopy(_descriptor())
    value["entrypoint"]["module"] = "invalid/path"
    with pytest.raises(DescriptorValidationError) as raised:
        _validate(value)
    assert raised.value.code == "descriptor_invalid"
    assert raised.value.path[:1] == ("entrypoint",)
