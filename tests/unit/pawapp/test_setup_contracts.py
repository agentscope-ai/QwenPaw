# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Generic setup declarations stay scoped, typed and registration-bound."""

import time
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from qwenpaw.pawapp import (
    PawApp,
    PrepareResult,
    ReadinessResult,
    SetupCheckRegistration,
    SetupEntryDescriptor,
    SetupEntryRegistration,
    SetupOpenAction,
    SetupRequirement,
    SuggestedValue,
)
from qwenpaw.pawapp.tasks import ActionDescriptor
from qwenpaw.pawapp.tasks.binding import ActionRegistration
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture
def fresh_registry():
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = previous


def _entry() -> SetupEntryDescriptor:
    return SetupEntryDescriptor(
        id="video-model",
        entry_ref="creator.model-settings",
        focus="video-generation",
        presentations=("app_entry",),
    )


def _requirement() -> SetupRequirement:
    return SetupRequirement(
        id="shot-video",
        summary="Configure a video generation model",
        required_for=("create-video",),
        authority="AppLocal",
        setup_entry_ref="video-model",
        check_ref="creator.video-model-ready",
        type_ref="model@1",
    )


async def _open_setup(request):
    return SetupOpenAction(
        app_id=request.scope.app_id,
        request_id=request.request_id,
        entry_id=request.entry_id,
        presentation=request.presentation,
        path=f"/apps/{request.scope.app_id}/models?setup={request.request_id}",
    )


async def _check_setup(_scope, _inputs):
    now = time.time()
    return ReadinessResult(
        requirement_id="shot-video",
        state="needs_configuration",
        reason_code="video_model_missing",
        checked_at=now,
        expires_at=now + 30,
    )


def test_contracts_reject_inconsistent_readiness_and_prepare() -> None:
    now = time.time()
    with pytest.raises(ValidationError, match="require a reason_code"):
        ReadinessResult(
            requirement_id="shot-video",
            state="needs_configuration",
            checked_at=now,
            expires_at=now + 30,
        )

    result = ReadinessResult(
        requirement_id="shot-video",
        state="needs_configuration",
        reason_code="video_model_missing",
        checked_at=now,
        expires_at=now + 30,
    )
    with pytest.raises(ValidationError, match="does not match"):
        PrepareResult(
            app_id="qwenpaw-creator",
            action_id="create-video",
            descriptor_digest="digest",
            state="ready",
            requirements=(_requirement(),),
            results=(result,),
            checked_at=now,
            expires_at=now + 30,
        )


def test_setup_navigation_cannot_leave_own_app() -> None:
    with pytest.raises(ValidationError, match="belong to the App"):
        SetupOpenAction(
            app_id="qwenpaw-creator",
            request_id="request-1",
            entry_id="video-model",
            presentation="app_entry",
            path="/apps/other/settings",
        )

    with pytest.raises(ValidationError, match="cannot contain credentials"):
        SuggestedValue(
            name="provider_api_key",
            value="must-not-enter-setup-context",
            provenance="caller",
        )


def test_manifest_configuration_is_typed_and_rejects_duplicates() -> None:
    manifest = PluginManifest.from_dict(
        {
            "id": "qwenpaw-creator",
            "version": "1.0.0",
            "pawapp": {
                "configuration": {
                    "version": 1,
                    "setup_entries": [
                        {
                            "id": "video-model",
                            "entry_ref": "creator.model-settings",
                            "focus": "video-generation",
                            "presentations": ["app_entry"],
                        },
                    ],
                },
            },
        },
    )
    assert manifest.pawapp.configuration.setup_entries[0].id == "video-model"

    payload = manifest.model_dump(mode="json")
    payload["pawapp"]["configuration"]["setup_entries"] *= 2
    with pytest.raises(ValidationError, match="entry IDs must be unique"):
        PluginManifest.model_validate(payload)


def test_sdk_requires_manifest_and_handler_declarations_to_match() -> None:
    api = MagicMock()
    api.manifest = {
        "id": "qwenpaw-creator",
        "version": "1.0.0",
        "pawapp": {
            "configuration": {
                "setup_entries": [
                    {
                        "id": "video-model",
                        "entry_ref": "creator.model-settings",
                        "focus": "video-generation",
                        "presentations": ["app_entry"],
                    },
                ],
            },
        },
    }
    app = PawApp("Creator", app_id="qwenpaw-creator")
    entry = SetupEntryRegistration(descriptor=_entry(), opener=_open_setup)
    check = SetupCheckRegistration(
        requirement=_requirement(),
        checker=_check_setup,
    )
    app.setup_entry(entry).setup_check(check)

    app.register(api)

    api.register_pawapp_setup_entry.assert_called_once_with(entry)
    api.register_pawapp_setup_check.assert_called_once_with(check)

    api.manifest["pawapp"]["configuration"]["setup_entries"][0][
        "focus"
    ] = "image-generation"
    with pytest.raises(ValueError, match="setup_entries do not match"):
        other = PawApp("Creator", app_id="qwenpaw-creator")
        other.setup_entry(entry).register(api)


def test_registry_scopes_setup_and_validates_action_requirements(
    fresh_registry,
) -> None:
    entry = SetupEntryRegistration(descriptor=_entry(), opener=_open_setup)
    check = SetupCheckRegistration(
        requirement=_requirement(),
        checker=_check_setup,
    )
    fresh_registry.register_pawapp_setup_entry("qwenpaw-creator", entry)
    fresh_registry.register_pawapp_setup_check("qwenpaw-creator", check)

    action = ActionDescriptor(
        app_id="qwenpaw-creator",
        action_id="create-video",
        summary="Create a video",
        engagements=("delegated", "direct"),
        input_schema={"type": "object", "properties": {}},
        adapter_ref="creator.video",
    )
    registration = ActionRegistration(
        action=action,
        factory=MagicMock(),
        settings_entry="/apps/qwenpaw-creator",
        requirement_ids=("shot-video",),
    )
    fresh_registry.register_task_action("qwenpaw-creator", registration)
    stored = fresh_registry.get_task_actions()[
        ("qwenpaw-creator", "create-video")
    ]
    assert stored.requirement_ids == ("shot-video",)

    fresh_registry.unregister_plugin("qwenpaw-creator")
    assert not fresh_registry.get_task_actions()
    assert not fresh_registry.get_pawapp_setup_checks()
    assert not fresh_registry.get_pawapp_setup_entries()


def test_registry_rejects_unregistered_setup_requirement(
    fresh_registry,
) -> None:
    action = ActionDescriptor(
        app_id="qwenpaw-creator",
        action_id="create-video",
        summary="Create a video",
        engagements=("delegated",),
        input_schema={"type": "object", "properties": {}},
        adapter_ref="creator.video",
    )
    with pytest.raises(ValueError, match="unregistered setup requirements"):
        fresh_registry.register_task_action(
            "qwenpaw-creator",
            ActionRegistration(
                action=action,
                factory=MagicMock(),
                settings_entry="/apps/qwenpaw-creator",
                requirement_ids=("shot-video",),
            ),
        )
