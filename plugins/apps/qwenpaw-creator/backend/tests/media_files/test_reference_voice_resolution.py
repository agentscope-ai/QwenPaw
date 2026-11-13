# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Character-voice pairing for R2V references (resolution layer)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from models import config as model_config
from services.media_files import r2v_execution
from services.project_files.models import (
    CharacterVoice,
    Project,
    VisualEntity,
    VisualVariant,
)

pytestmark = pytest.mark.unit


def _project_with_voiced_character() -> Project:
    project = Project.new(project_id="p-voice", name="Voice")
    variant = VisualVariant(
        variant_id="var:base",
        selected_artifact_version_id="artifact:rusty-image",
    )
    entity = VisualEntity(
        entity_id="char:rusty",
        kind="character",
        name="锈锈",
        required_variant_ids=["var:base"],
        canonical_variant_id="var:base",
        variants={"items": {"var:base": variant}, "order": ["var:base"]},
        voice=CharacterVoice(
            voice_id="voice-1",
            target_model="cosyvoice-v3.5-plus",
            sample_source_version_id="source:rusty-sample",
            created_at=datetime.now(timezone.utc),
        ),
    )
    project.visual.entities.items["char:rusty"] = entity
    project.visual.entities.order.append("char:rusty")
    return project


def _gate(monkeypatch, supported: bool) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v" if supported else "happyhorse-1.1-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")


def _stub_sample_resolution(monkeypatch) -> None:
    def fake_resolve(
        *,
        project,
        project_root,
        version_id,
        media_prefix,
        label,
    ):
        # The fake mirrors the real keyword-only signature.
        del project, project_root
        assert media_prefix == "audio/"
        assert label == "characterVoiceSample"
        return (
            f"file:///samples/{version_id}.mp3",
            "sha-sample",
            f"source-version:{version_id}",
            {"ref": version_id},
        )

    monkeypatch.setattr(
        r2v_execution,
        "_resolve_single_media_version",
        fake_resolve,
    )


def test_voice_rides_with_its_characters_reference(monkeypatch) -> None:
    _gate(monkeypatch, supported=True)
    _stub_sample_resolution(monkeypatch)
    project = _project_with_voiced_character()
    creation = SimpleNamespace(character_refs=["char:rusty"])

    voice_urls, entries = r2v_execution._resolve_reference_voices(
        project=project,
        project_root=Path("/tmp"),
        creation=creation,
        version_ids=("artifact:storyboard", "artifact:rusty-image"),
    )

    assert voice_urls == (
        "",
        "file:///samples/source:rusty-sample.mp3",
    )
    assert entries == [{"ref": "source:rusty-sample"}]


def test_non_qualifying_contexts_resolve_nothing(monkeypatch) -> None:
    _stub_sample_resolution(monkeypatch)

    # Unsupported model family: nothing resolves even for a voiced ref.
    _gate(monkeypatch, supported=False)
    project = _project_with_voiced_character()
    creation = SimpleNamespace(character_refs=["char:rusty"])
    voice_urls, entries = r2v_execution._resolve_reference_voices(
        project=project,
        project_root=Path("/tmp"),
        creation=creation,
        version_ids=("artifact:rusty-image",),
    )
    assert not voice_urls
    assert not entries

    # The character's image is not part of this submission's references.
    _gate(monkeypatch, supported=True)
    voice_urls, entries = r2v_execution._resolve_reference_voices(
        project=project,
        project_root=Path("/tmp"),
        creation=creation,
        version_ids=("artifact:unrelated",),
    )
    assert not voice_urls
    assert not entries

    # A character without an enrolled voice never resolves a sample.
    project.visual.entities.items["char:rusty"].voice = None
    voice_urls, entries = r2v_execution._resolve_reference_voices(
        project=project,
        project_root=Path("/tmp"),
        creation=creation,
        version_ids=("artifact:rusty-image",),
    )
    assert not voice_urls
    assert not entries
