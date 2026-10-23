"""Independent opt-in Telegram presentation and authority contracts."""

import json
from pathlib import Path

import pytest

from qwenpaw.channel_protocol import models
from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.shared import validate_channel_contract

ROOT = Path(__file__).resolve().parents[3]


def test_official_payload_contains_native_algorithms_and_cards():
    source = ROOT / "plugins/channel/telegram"
    for relative in (
        "README.md",
        "requirements.txt",
        "qwenpaw_channel_telegram/__init__.py",
        "qwenpaw_channel_telegram/driver.py",
        "qwenpaw_channel_telegram/platform.py",
        "qwenpaw_channel_telegram/format_html.py",
        "qwenpaw_channel_telegram/cards/__init__.py",
        "qwenpaw_channel_telegram/cards/context.py",
        "qwenpaw_channel_telegram/cards/dispatcher.py",
        "qwenpaw_channel_telegram/cards/tool_guard.py",
    ):
        assert (source / relative).is_file(), (
            "Missing executable Telegram resource: " + relative
        )


def packet(**fields):
    return {
        "channel_key": "telegram",
        "instance_id": "workspace-A",
        "generation": 1,
        "delivery_id": "delivery-A",
        "to_handle": "response-A",
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": " raw "}],
        **fields,
    }


def test_content_source_has_four_closed_values_without_changing_legacy_wire():
    """Approved EVENT extension keeps all three existing source wire shapes."""
    enum = getattr(models, "ContentSource", None)
    assert enum is not None, "ContentSource opt-in contract is absent"
    assert {value.value for value in enum} == {
        "direct",
        "content_parts",
        "media",
        "event",
    }
    old = packet()
    assert models.SendParams.from_mapping(old).to_mapping() == old
    for source in ("direct", "content_parts"):
        value = packet(content_source=source)
        assert models.SendParams.from_mapping(value).to_mapping() == value
    media = packet(
        content_source="media",
        content_parts=[{"type": "image", "image_url": "https://x.test/i"}],
    )
    assert models.SendParams.from_mapping(media).to_mapping() == media
    event = packet(
        content_source="event",
        content_parts=[{"type": "text", "text": " raw ", "role": "message"}],
    )
    assert models.SendParams.from_mapping(event).to_mapping() == event


@pytest.mark.parametrize(
    "fields",
    [
        {"content_source": "guessed"},
        {"content_source": 1},
        {"content_source": "media"},
        {"content_source": "media", "content_parts": []},
        {
            "content_source": "media",
            "content_parts": [
                {"type": "image", "image_url": "https://x.test/i"},
                {"type": "image", "image_url": "https://x.test/j"},
            ],
        },
        {
            "operation": "message.update",
            "target_delivery_id": "original",
            "content_source": "direct",
        },
    ],
)
def test_source_cannot_smuggle_unknown_or_noncreate_media_shapes(fields):
    with pytest.raises(ProtocolValidationError):
        models.SendParams.from_mapping(packet(**fields))


def test_resolution_roundtrip_keeps_failed_and_race_loser_distinct():
    result_type = getattr(models, "ApprovalResolutionParams", None)
    assert result_type is not None, "Authoritative result DTO is absent"
    for outcome in (
        "approved",
        "denied",
        "unavailable",
        "forbidden",
        "failed",
    ):
        result = {
            "request_id": "pending-A",
            "outcome": outcome,
            "actor_user_id": "456",
        }
        if outcome in {"approved", "denied"}:
            result["tool_name"] = "shell"
        value = packet(content_parts=[], approval_resolution=result)
        assert models.SendParams.from_mapping(value).to_mapping() == {
            key: val for key, val in value.items() if key != "content_parts"
        }


@pytest.mark.parametrize(
    "result",
    [
        {"request_id": "r", "actor_user_id": "a", "outcome": "received"},
        {"request_id": "r", "actor_user_id": "a", "outcome": "approved"},
        {"request_id": "r" * 257, "actor_user_id": "a", "outcome": "failed"},
        {"request_id": "r", "actor_user_id": "a" * 513, "outcome": "failed"},
        {
            "request_id": "r",
            "actor_user_id": "a",
            "outcome": "approved",
            "tool_name": "x" * 1025,
        },
        {
            "request_id": "r",
            "actor_user_id": "a",
            "outcome": "failed",
            "metadata": {"approved": True},
        },
    ],
)
def test_resolution_is_closed_bounded_and_requires_success_record(result):
    with pytest.raises(ProtocolValidationError):
        models.SendParams.from_mapping(packet(approval_resolution=result))


@pytest.mark.parametrize(
    "capabilities",
    [
        ("channel.generic.v1", "send.content_source.v2"),
        ("channel.generic.v1", "send.approval_resolution.v2"),
        ("send.content_source.v1",),
        ("send.approval_resolution.v1",),
    ],
)
def test_known_optin_capability_versions_and_dependency_are_enforced(
    capabilities,
):
    with pytest.raises(ProtocolValidationError):
        validate_channel_contract("telegram", capabilities)


def test_existing_generic_and_unrelated_third_party_tags_still_validate():
    validate_channel_contract("third_party", ("channel.generic.v1",))
    validate_channel_contract(
        "third_party", ("channel.generic.v1", "vendor.custom.v99")
    )


def test_formal_descriptor_can_be_consumed_without_sdk_import():
    source = ROOT / "plugins/channel/telegram"
    assert (source / "channel.json").is_file(), "Telegram artifact absent"
    from qwenpaw.config.config import TelegramConfig
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    descriptor = describe_channel(source, manifest).descriptor
    assert manifest.id == descriptor.channel_key == "telegram"
    assert manifest.entry.descriptor == "channel.json"
    assert descriptor.schema_version == 2
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.module == "qwenpaw_channel_telegram.driver"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.requirements_file == "requirements.txt"
    assert {
        "channel.generic.v1",
        "send.content_source.v1",
        "send.approval_resolution.v1",
    }.issubset(descriptor.capabilities)
    assert set(descriptor.config_fields) == set(TelegramConfig.model_fields)
    for key, default in TelegramConfig().model_dump().items():
        assert (
            descriptor.config_schema["properties"][key].get("default")
            == default
        )
