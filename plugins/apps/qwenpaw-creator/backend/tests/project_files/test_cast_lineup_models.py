# -*- coding: utf-8 -*-
"""Master cast lineup and canonical-variant data model (relative consistency).

P0 backend scope of docs/proposals/master-cast-lineup: the lineup is the
group anchor for cross-character scale/style/palette consistency; the
canonical variant locks intra-character identity across costumes.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.project_files.models import (
    EntityCollection,
    Project,
    VisualCastLineup,
    VisualEntity,
    VisualVariant,
)


pytestmark = pytest.mark.unit


def _character(entity_id: str, **extra) -> VisualEntity:
    return VisualEntity(
        entity_id=entity_id,
        kind="character",
        name=entity_id.split(":")[-1].title(),
        required_variant_ids=list(
            (extra.get("variants") or EntityCollection()).order,
        ),
        **extra,
    )


def _project_with_cast() -> Project:
    project = Project.new(project_id="project-lineup", name="Lineup")
    project.visual.entities = EntityCollection(
        items={
            "char:hero": _character("char:hero"),
            "char:rival": _character("char:rival"),
        },
        order=["char:hero", "char:rival"],
    )
    return project


def test_cast_lineup_roundtrips_with_validation():
    project = _project_with_cast()
    project.visual.cast_lineups = EntityCollection(
        items={
            "lineup:main": VisualCastLineup(
                lineup_id="lineup:main",
                name="主卡司定妆照",
                character_refs=["char:hero", "char:rival"],
                relative_notes="hero:rival ≈ 190:175cm",
            ),
        },
        order=["lineup:main"],
    )

    validated = Project.model_validate(project.model_dump(mode="json"))
    lineup = validated.visual.cast_lineups.items["lineup:main"]
    assert lineup.character_refs == ["char:hero", "char:rival"]


def test_cast_lineup_rejects_missing_characters():
    project = _project_with_cast()
    project.visual.cast_lineups = EntityCollection(
        items={
            "lineup:main": VisualCastLineup(
                lineup_id="lineup:main",
                name="主卡司定妆照",
                character_refs=["char:hero", "char:ghost"],
            ),
        },
        order=["lineup:main"],
    )

    with pytest.raises(
        ValidationError,
        match="missing character char:ghost",
    ):
        Project.model_validate(project.model_dump(mode="json"))


def test_cast_lineup_needs_at_least_two_characters():
    with pytest.raises(ValidationError, match="at least two characters"):
        VisualCastLineup(
            lineup_id="lineup:solo",
            name="单人",
            character_refs=["char:hero"],
        )


def test_element_cast_lineup_refs_must_exist():
    project = _project_with_cast()
    raw = project.model_dump(mode="json")
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "elem:duo"
    ] = {
        "element_id": "elem:duo",
        "span": {"start_tick": 0, "duration_tick": 1000},
        "location": {},
        "creation": {
            "type": "r2v",
            "character_refs": ["char:hero", "char:rival"],
            "cast_lineup_refs": ["lineup:missing"],
        },
    }

    with pytest.raises(
        ValidationError,
        match="references missing lineup lineup:missing",
    ):
        Project.model_validate(raw)


def test_canonical_variant_must_be_one_of_the_entitys_variants():
    variants = EntityCollection(
        items={"var:default": VisualVariant(variant_id="var:default")},
        order=["var:default"],
    )
    entity = _character(
        "char:hero",
        variants=variants,
        canonical_variant_id="var:default",
    )
    assert entity.canonical_variant_id == "var:default"

    with pytest.raises(ValidationError, match="canonical_variant_id"):
        _character(
            "char:hero",
            variants=variants,
            canonical_variant_id="var:ghost",
        )


def test_variant_derivation_must_reference_an_existing_variant():
    variants = EntityCollection(
        items={
            "var:default": VisualVariant(variant_id="var:default"),
            "var:armor": VisualVariant(
                variant_id="var:armor",
                derived_from_variant_id="var:default",
                consistency_tags=["costume_change"],
            ),
        },
        order=["var:default", "var:armor"],
    )
    entity = _character("char:hero", variants=variants)
    armor = entity.variants.items["var:armor"]
    assert armor.derived_from_variant_id == "var:default"

    broken = EntityCollection(
        items={
            "var:armor": VisualVariant(
                variant_id="var:armor",
                derived_from_variant_id="var:ghost",
            ),
        },
        order=["var:armor"],
    )
    with pytest.raises(ValidationError, match="derives from missing"):
        _character("char:hero", variants=broken)


def test_legacy_projects_without_lineups_still_validate():
    raw = Project.new(project_id="p", name="n").model_dump(mode="json")
    raw["visual"].pop("cast_lineups", None)

    validated = Project.model_validate(raw)
    assert validated.visual.cast_lineups.order == []
