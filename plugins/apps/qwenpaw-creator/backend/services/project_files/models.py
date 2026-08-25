# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-boolean-expressions,too-many-branches
# pylint: disable=too-many-statements
"""Pydantic authority for Creator's single-file Project domain model.

The models in this module deliberately contain no SQLite or HTTP concerns.
They describe only the durable contents of one Project's ``project.json``.
Runtime state (tasks, reviews, locks and change sets) belongs under the
Project's ``runtime/`` directory and must not be added here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import math
from pathlib import PurePosixPath
import re
from typing import Annotated, Any, Generic, Literal, TypeVar
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


CURRENT_PROJECT_SCHEMA_VERSION = 8
DEFAULT_TIMELINE_ID = "timeline:main"
DEFAULT_TIMELINE_TICKS_PER_SECOND = 1_000

# Unified colour-grade preset names; the ffmpeg filters live in the local
# media renderer (keys must stay aligned with _COLOR_GRADE_FILTERS there).
COLOR_GRADE_PRESETS = (
    "warm_bright",
    "clean_cool",
    "cinematic",
    "vlog_fresh",
    "ink_wash",
    "stage_drama",
    "neon_vivid",
)
SHA256_PATTERN = r"^[a-f0-9]{64}$"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]
EntityId = Annotated[
    str,
    Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]


class StrictModel(BaseModel):
    """Base for persisted models: unknown fields are storage corruption."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_default=True,
        validate_assignment=True,
    )


T = TypeVar("T", bound=StrictModel)


class EntityCollection(StrictModel, Generic[T]):
    """Stable-ID collection with explicit presentation order."""

    items: dict[EntityId, T] = Field(default_factory=dict)
    order: list[EntityId] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_order(self) -> EntityCollection[T]:
        if len(self.order) != len(set(self.order)):
            raise ValueError("order contains duplicate ids")
        if set(self.order) != set(self.items):
            raise ValueError("order must contain every item id exactly once")
        return self


class ProviderModelScope(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ExecutionPreauthorization(StrictModel):
    max_cost: float = Field(ge=0)
    max_candidates: int = Field(ge=1)
    provider_models: list[ProviderModelScope] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_models(self) -> ExecutionPreauthorization:
        pairs = [(item.provider, item.model) for item in self.provider_models]
        if len(pairs) != len(set(pairs)):
            raise ValueError("provider/model scope cannot be duplicated")
        return self


class ProjectSettings(StrictModel):
    aspect_ratio: str = "16:9"
    resolution: str = "720P"
    platform: str = ""
    language: str = "zh-CN"
    target_duration_seconds: float | None = Field(default=None, ge=0)
    content_type: str | None = None
    execution_preauthorization: ExecutionPreauthorization | None = None


class CreativeStrategy(StrictModel):
    creative_brief: str = ""
    audience: str = ""
    creative_direction: str = ""
    constraints: str = ""
    success_criteria: str = ""


def motion_document_file_id(checksum: str) -> str:
    """Content-addressed file id of one externalized motion document.

    Single source of truth shared by the design pipeline (which publishes
    documents under this id) and Project graph validation (which rejects
    references whose id does not derive from the indexed checksum).
    """

    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:motion-document:{checksum}",
    ).hex
    return f"file-motion-{digest}"


class IndexedFile(StrictModel):
    file_id: EntityId
    kind: Literal[
        "source_original",
        "source_thumbnail",
        "source_intelligence",
        "artifact_payload",
        "artifact_thumbnail",
        "large_text",
        "model_native",
        "other",
    ]
    relative_uri: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    schema_name: str | None = None
    schema_version: int | None = Field(default=None, ge=1)
    created_at: UtcDateTime

    @field_validator("relative_uri")
    @classmethod
    def _validate_relative_uri(cls, value: str) -> str:
        if (
            not value
            or value != value.strip()
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("relative_uri must be a normalized POSIX path")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or len(path.parts) < 2
            or path.parts[0] != "assets"
        ):
            raise ValueError(
                "relative_uri must be relative to the Project assets directory",
            )
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("relative_uri cannot contain traversal segments")
        return path.as_posix()


class IndexedContentRef(StrictModel):
    file_id: EntityId


class SourceAssetVersion(StrictModel):
    version_id: EntityId
    logical_asset_id: EntityId
    name: str
    file_id: EntityId | None = None
    checksum: Sha256
    media_kind: Literal["image", "video", "audio", "document", "text", "other"]
    media_type: str = Field(min_length=1)
    provenance_refs: list[str] = Field(default_factory=list)
    thumbnail_file_id: EntityId | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    native_model_file_id: EntityId | None = None
    created_at: UtcDateTime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_source_location(self) -> SourceAssetVersion:
        if self.file_id is not None:
            return self
        source_url = str(self.metadata.get("publicSourceUrl") or "").strip()
        parsed = urlsplit(source_url)
        if (
            self.metadata.get("sourceKind") != "remote_url"
            or self.metadata.get("checksumKind") != "source_url_sha256"
            or parsed.scheme not in {"http", "https", "oss"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "source version without file_id must identify a public remote URL",
            )
        if (
            hashlib.sha256(source_url.encode("utf-8")).hexdigest()
            != self.checksum
        ):
            raise ValueError(
                "remote source checksum must be the public URL fingerprint",
            )
        return self


class SourceIntelligenceVersion(StrictModel):
    intelligence_version_id: EntityId
    source_asset_version_id: EntityId
    file_id: EntityId
    source_checksum: Sha256
    model_run_ids: list[EntityId] = Field(default_factory=list)
    coverage: dict[str, str] = Field(default_factory=dict)
    created_at: UtcDateTime


class ArtifactSlot(StrictModel):
    slot_id: EntityId
    kind: str
    owner_ref: str
    version_ids: list[EntityId] = Field(default_factory=list)
    selected_version_id: EntityId | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("version_ids")
    @classmethod
    def _validate_unique_versions(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError(
                "artifact slot version_ids cannot contain duplicates",
            )
        return value


# Every ArtifactSlot kind the media pipelines actually write. Slots are
# Runtime write-back records: a kind outside this set (or an empty slot)
# can only come from a hand-written jq_project transform fabricating a
# result, which later collides with the real pipeline write-back.
ARTIFACT_SLOT_KINDS = frozenset(
    {
        "cast_lineup_image",
        "element_video",
        "final_video",
        "r2v_storyboard_image",
        "visual_asset_image",
    },
)


class ArtifactVersion(StrictModel):
    version_id: EntityId
    slot_id: EntityId
    kind: str
    owner_ref: str
    name: str
    file_id: EntityId
    checksum: Sha256
    based_on_generation: int = Field(ge=0)
    provenance_refs: list[str] = Field(default_factory=list)
    thumbnail_file_id: EntityId | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    input_fingerprint: str | None = None
    stale: bool = False
    stale_reason: str | None = None
    created_at: UtcDateTime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetIndex(StrictModel):
    files_by_id: dict[EntityId, IndexedFile] = Field(default_factory=dict)
    source_versions_by_id: dict[EntityId, SourceAssetVersion] = Field(
        default_factory=dict,
    )
    intelligence_versions_by_id: dict[
        EntityId,
        SourceIntelligenceVersion,
    ] = Field(
        default_factory=dict,
    )
    artifact_slots_by_id: dict[EntityId, ArtifactSlot] = Field(
        default_factory=dict,
    )
    artifact_versions_by_id: dict[EntityId, ArtifactVersion] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def _validate_index(self) -> AssetIndex:
        _require_mapping_identity(self.files_by_id, "file_id", "files_by_id")
        _require_mapping_identity(
            self.source_versions_by_id,
            "version_id",
            "source_versions_by_id",
        )
        _require_mapping_identity(
            self.intelligence_versions_by_id,
            "intelligence_version_id",
            "intelligence_versions_by_id",
        )
        _require_mapping_identity(
            self.artifact_slots_by_id,
            "slot_id",
            "artifact_slots_by_id",
        )
        _require_mapping_identity(
            self.artifact_versions_by_id,
            "version_id",
            "artifact_versions_by_id",
        )

        for version in self.source_versions_by_id.values():
            if version.file_id is not None:
                payload = _require_key(
                    self.files_by_id,
                    version.file_id,
                    "source file",
                )
                if payload.sha256 != version.checksum:
                    raise ValueError(
                        f"source version checksum does not match file {version.file_id}",
                    )
            for file_id in (
                version.thumbnail_file_id,
                version.native_model_file_id,
            ):
                if file_id is not None:
                    _require_key(
                        self.files_by_id,
                        file_id,
                        "source auxiliary file",
                    )

        for intelligence in self.intelligence_versions_by_id.values():
            source = _require_key(
                self.source_versions_by_id,
                intelligence.source_asset_version_id,
                "source intelligence source version",
            )
            _require_key(
                self.files_by_id,
                intelligence.file_id,
                "source intelligence file",
            )
            if intelligence.source_checksum != source.checksum:
                raise ValueError(
                    "source intelligence checksum does not match its source version",
                )

        for version in self.artifact_versions_by_id.values():
            slot = _require_key(
                self.artifact_slots_by_id,
                version.slot_id,
                "artifact slot",
            )
            if version.version_id not in slot.version_ids:
                raise ValueError(
                    f"artifact version {version.version_id} is absent from its slot",
                )
            if (
                version.owner_ref != slot.owner_ref
                or version.kind != slot.kind
            ):
                raise ValueError(
                    f"artifact version {version.version_id} does not match its slot",
                )
            payload = _require_key(
                self.files_by_id,
                version.file_id,
                "artifact file",
            )
            if payload.sha256 != version.checksum:
                raise ValueError(
                    f"artifact version checksum does not match file {version.file_id}",
                )
            if version.thumbnail_file_id is not None:
                _require_key(
                    self.files_by_id,
                    version.thumbnail_file_id,
                    "artifact thumbnail",
                )

        for slot in self.artifact_slots_by_id.values():
            if slot.kind not in ARTIFACT_SLOT_KINDS:
                raise ValueError(
                    f"artifact slot {slot.slot_id} has unknown kind "
                    f"{slot.kind!r}; artifact slots are written back by "
                    "the media pipeline and must not be authored via "
                    "jq_project",
                )
            if not slot.version_ids:
                raise ValueError(
                    f"artifact slot {slot.slot_id} has no artifact "
                    "versions; artifact slots are written back by the "
                    "media pipeline and must not be authored via "
                    "jq_project",
                )
            for version_id in slot.version_ids:
                version = _require_key(
                    self.artifact_versions_by_id,
                    version_id,
                    "artifact slot version",
                )
                if version.slot_id != slot.slot_id:
                    raise ValueError(
                        f"artifact slot {slot.slot_id} contains a foreign version",
                    )
            if (
                slot.selected_version_id is not None
                and slot.selected_version_id not in slot.version_ids
            ):
                raise ValueError(
                    f"selected version is not a member of artifact slot {slot.slot_id}",
                )
        return self


class ProjectSource(StrictModel):
    source_id: EntityId
    display_name: str
    logical_asset_id: EntityId
    selected_asset_version_id: EntityId
    current_intelligence_version_id: EntityId | None = None
    user_notes: str = ""


class SourceCatalog(StrictModel):
    sources: EntityCollection[ProjectSource] = Field(
        default_factory=EntityCollection,
    )


class VisualVariant(StrictModel):
    variant_id: EntityId
    requirements: str = ""
    prompt: str = ""
    reference_asset_version_ids: list[EntityId] = Field(default_factory=list)
    reference_artifact_version_ids: list[EntityId] = Field(
        default_factory=list,
    )
    generated_artifact_version_ids: list[EntityId] = Field(
        default_factory=list,
    )
    selected_artifact_version_id: EntityId | None = None
    # Intra-character consistency: which variant this one was derived
    # from, and what it is allowed to change (costume_change, age_stage,
    # alternate_style ...). Core identity traits stay locked to the
    # entity's continuity.
    derived_from_variant_id: EntityId | None = None
    consistency_tags: list[str] = Field(default_factory=list)


class CharacterVoice(StrictModel):
    """An enrolled (cloned) voice bound to one character VisualEntity.

    Optional enhancement: characters work without a voice.  Once enrolled the
    binding travels with the entity; re-enrolling replaces it.  The record
    keeps the full rebuild inputs so a lapsed cloud voice can be re-enrolled.
    """

    voice_id: str = Field(min_length=1)
    target_model: str = Field(min_length=1)
    preferred_name: str = ""
    sample_source_version_id: EntityId | None = None
    enrollment_key: str = ""
    created_at: UtcDateTime


class VisualEntity(StrictModel):
    entity_id: EntityId
    kind: Literal["character", "scene", "prop"]
    name: str = Field(min_length=1)
    description: str = ""
    continuity: str = ""
    required_variant_ids: list[EntityId]
    variants: EntityCollection[VisualVariant] = Field(
        default_factory=EntityCollection,
    )
    selected_artifact_version_id: EntityId | None = None
    voice: CharacterVoice | None = None

    @model_validator(mode="after")
    def _validate_voice_owner(self) -> VisualEntity:
        if self.voice is not None and self.kind != "character":
            raise ValueError("only character entities can bind a voice")
        return self

    # The identity master: new variants reference this variant's selected
    # artifact first so the character does not drift across costumes and
    # stages.
    canonical_variant_id: EntityId | None = None

    @model_validator(mode="after")
    def _validate_required_variants(self) -> VisualEntity:
        if len(self.required_variant_ids) != len(
            set(self.required_variant_ids),
        ):
            raise ValueError("required_variant_ids cannot contain duplicates")
        undeclared = set(self.variants.order) - set(
            self.required_variant_ids,
        )
        if undeclared:
            raise ValueError(
                "visual variants must be declared in required_variant_ids: "
                + ", ".join(sorted(undeclared)),
            )
        if (
            self.canonical_variant_id is not None
            and self.canonical_variant_id not in self.variants.items
        ):
            raise ValueError(
                f"canonical_variant_id {self.canonical_variant_id} is not "
                "one of this entity's variants",
            )
        for variant in self.variants.items.values():
            if (
                variant.derived_from_variant_id is not None
                and variant.derived_from_variant_id not in self.variants.items
            ):
                raise ValueError(
                    f"variant {variant.variant_id} derives from missing "
                    f"variant {variant.derived_from_variant_id}",
                )
        return self


class VisualCastLineup(StrictModel):
    """One canonical multi-character reference image (cast lineup).

    Locks relative consistency — scale ratios, shared style baseline,
    palette, era and default spatial order — that per-entity continuity
    cannot express. Individual anchors stay authoritative for identity;
    the lineup is the group anchor referenced by storyboards and videos.
    """

    lineup_id: EntityId
    name: str = Field(min_length=1)
    description: str = ""
    # Order equals the default left-to-right placement in the image.
    character_refs: list[EntityId] = Field(default_factory=list)
    scene_ref: EntityId | None = None
    prop_refs: list[EntityId] = Field(default_factory=list)
    reference_asset_version_ids: list[EntityId] = Field(default_factory=list)
    reference_artifact_version_ids: list[EntityId] = Field(
        default_factory=list,
    )
    generated_artifact_version_ids: list[EntityId] = Field(
        default_factory=list,
    )
    selected_artifact_version_id: EntityId | None = None
    # Human/agent-authored relative notes, e.g. "A:B:C ≈ 175:165:150cm".
    relative_notes: str = ""

    @model_validator(mode="after")
    def _validate_lineup(self) -> VisualCastLineup:
        if len(self.character_refs) != len(set(self.character_refs)):
            raise ValueError(
                "cast lineup character_refs cannot contain duplicates",
            )
        if len(self.character_refs) < 2:
            raise ValueError(
                "a cast lineup needs at least two characters; single "
                "characters are covered by their own variants",
            )
        return self


class VisualDevelopment(StrictModel):
    visual_bible: str = ""
    style: str = ""
    entities: EntityCollection[VisualEntity] = Field(
        default_factory=EntityCollection,
    )
    cast_lineups: EntityCollection[VisualCastLineup] = Field(
        default_factory=EntityCollection,
    )


class ShotCamera(StrEnum):
    STATIC = "⊙ 静止"
    PUSH_IN = "↑ 推近"
    PULL_OUT = "↓ 拉远"
    PAN_RIGHT = "→ 横摇右"
    PAN_LEFT = "← 横摇左"
    CRANE = "↕ 升降"
    ORBIT = "◎ 环绕"
    HANDHELD = "～ 手持晃动"


class ShotFraming(StrEnum):
    WIDE = "全景"
    MEDIUM = "中景"
    CLOSE = "近景"
    CLOSE_UP = "特写"


class Shot(StrictModel):
    shot_id: EntityId
    description: str = ""
    camera: ShotCamera | None = None
    framing: ShotFraming | None = None
    camera_description: str = ""
    dialogue: str = ""
    duration_seconds: float = Field(ge=0)
    character_refs: list[EntityId] = Field(default_factory=list)
    scene_ref: EntityId | None = None
    prop_refs: list[EntityId] = Field(default_factory=list)


class GenerationRecipe(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    seed: int | None = None
    candidate_count: int = Field(default=1, ge=1)


class TimelineSpan(StrictModel):
    """One half-open interval on a Timeline: ``[start_tick, end_tick)``."""

    start_tick: int = Field(ge=0)
    duration_tick: int = Field(gt=0)

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.duration_tick

    def contains(self, tick: int) -> bool:
        return self.start_tick <= tick < self.end_tick

    def overlaps(self, other: TimelineSpan) -> bool:
        return (
            self.start_tick < other.end_tick
            and other.start_tick < self.end_tick
        )


class ElementLocation(StrictModel):
    """Normalized placement with ``x/y`` as the box anchor on the canvas.

    ``anchor_x/anchor_y`` select which point inside the content box is placed
    at ``x/y`` and is also the transform origin. A full-frame visual is
    therefore ``x=0.5, y=0.5, width=1, height=1``. Values may extend beyond the
    frame for intentional crops and motion.
    """

    coordinate_space: Literal["normalized_canvas"] = "normalized_canvas"
    x: float = 0.5
    y: float = 0.5
    width: float = Field(default=1.0, gt=0)
    height: float = Field(default=1.0, gt=0)
    anchor_x: float = Field(default=0.5, ge=0, le=1)
    anchor_y: float = Field(default=0.5, ge=0, le=1)
    rotation_degrees: float = 0.0
    opacity: float = Field(default=1.0, ge=0, le=1)

    @field_validator(
        "x",
        "y",
        "width",
        "height",
        "anchor_x",
        "anchor_y",
        "rotation_degrees",
        "opacity",
    )
    @classmethod
    def _validate_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("element location values must be finite")
        return value


class ElementOutput(StrictModel):
    """A stable named output backed by the generic ArtifactSlot index."""

    slot_id: EntityId


class SourceVersionRenderSource(StrictModel):
    type: Literal["source_asset_version"] = "source_asset_version"
    version_id: EntityId
    source_in_tick: int = Field(default=0, ge=0)
    source_out_tick: int | None = Field(default=None, gt=0)
    playback_rate: float = Field(default=1.0, gt=0)
    loop: bool = False

    @field_validator("playback_rate")
    @classmethod
    def _validate_rate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("playback_rate must be finite")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> SourceVersionRenderSource:
        if (
            self.source_out_tick is not None
            and self.source_out_tick <= self.source_in_tick
        ):
            raise ValueError(
                "source_out_tick must be greater than source_in_tick",
            )
        return self


class ArtifactVersionRenderSource(SourceVersionRenderSource):
    type: Literal["artifact_version"] = "artifact_version"


class ElementOutputRenderSource(StrictModel):
    type: Literal["element_output"] = "element_output"
    element_id: EntityId
    output_name: EntityId
    source_in_tick: int = Field(default=0, ge=0)
    source_out_tick: int | None = Field(default=None, gt=0)
    playback_rate: float = Field(default=1.0, gt=0)
    loop: bool = False

    @field_validator("playback_rate")
    @classmethod
    def _validate_rate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("playback_rate must be finite")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> ElementOutputRenderSource:
        if (
            self.source_out_tick is not None
            and self.source_out_tick <= self.source_in_tick
        ):
            raise ValueError(
                "source_out_tick must be greater than source_in_tick",
            )
        return self


RenderSource = Annotated[
    SourceVersionRenderSource
    | ArtifactVersionRenderSource
    | ElementOutputRenderSource,
    Field(discriminator="type"),
]


class R2VCreation(StrictModel):
    """Declarative R2V creative facts, independent of the executing Agent."""

    type: Literal["r2v"] = "r2v"
    intent: str = ""
    narrative: str = ""
    continuity: str = ""
    character_refs: list[EntityId] = Field(default_factory=list)
    scene_ref: EntityId | None = None
    prop_refs: list[EntityId] = Field(default_factory=list)
    visual_variant_refs: dict[EntityId, EntityId] = Field(
        default_factory=dict,
    )
    # Group anchors: cast lineups whose selected artifact should lead the
    # storyboard/video reference chain when several characters share the
    # frame.
    cast_lineup_refs: list[EntityId] = Field(default_factory=list)
    shots: EntityCollection[Shot] = Field(default_factory=EntityCollection)
    recipe: GenerationRecipe | None = None
    storyboard_prompt: str = ""
    storyboard_reference_version_ids: list[EntityId] = Field(
        default_factory=list,
    )
    video_prompt: str = ""
    video_reference_version_ids: list[EntityId] = Field(default_factory=list)
    # Minimum fraction of shots that must carry dialogue when the element
    # has character appearances. Default 0.3 (≈1 line per 2–3 shots);
    # the model sets this during planning and the review UI may override
    # it per element. The work-graph gate enforces it deterministically.
    min_dialogue_ratio: float = Field(default=0.3, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_shots(self) -> R2VCreation:
        _require_collection_identity(
            self.shots,
            "shot_id",
            "R2V creation shots",
        )
        for shot in self.shots.items.values():
            if shot.camera is None or shot.framing is None:
                raise ValueError(
                    "R2V creation shot requires camera and framing",
                )
        return self


class T2VCreation(StrictModel):
    """Pure text-to-video creative facts.

    The provider consumes nothing but the prompt, so the model carries only
    the narrative planning facts that produce it — no shots, storyboard or
    reference stacks.
    """

    type: Literal["t2v"] = "t2v"
    intent: str = ""
    narrative: str = ""
    continuity: str = ""
    video_prompt: str = ""
    recipe: GenerationRecipe | None = None


class I2VCreation(StrictModel):
    """First-frame-to-video creative facts.

    The provider consumes exactly one first-frame image plus the prompt;
    the frame is an exact version reference, not a storyboard pipeline.
    """

    type: Literal["i2v"] = "i2v"
    intent: str = ""
    narrative: str = ""
    continuity: str = ""
    first_frame_version_id: EntityId | None = None
    video_prompt: str = ""
    recipe: GenerationRecipe | None = None


class S2VCreation(StrictModel):
    """Digital-human (speech-to-video) creative facts.

    wan2.2-s2v consumes a portrait image and a driving audio track; the
    script is the necessary intermediate that produces that audio via TTS.
    Nothing else reaches the provider, so nothing else is modelled.
    """

    type: Literal["s2v"] = "s2v"
    intent: str = ""
    # Visual entity whose portrait (and enrolled voice) drives the clip.
    character_ref: EntityId | None = None
    # Exact image version used as the s2v reference portrait.
    portrait_version_id: EntityId | None = None
    # Spoken lines; TTS turns them into the driving audio below.
    script: str = ""
    # Exact audio version that drives the lip-sync.
    audio_version_id: EntityId | None = None
    recipe: GenerationRecipe | None = None


class EditCreation(StrictModel):
    """Creative facts for one selected source range.

    The exact source and range live in the Element's ``render_source``.  A
    multi-selection edit is represented by multiple Elements, never by a
    nested range list.
    """

    type: Literal["edit"] = "edit"
    intent: str = ""
    reason: str = ""
    original_sound: Literal["preserve"] = "preserve"
    source_intelligence_version_id: EntityId | None = None


class MotionGraphic(StrictModel):
    """One self-contained deterministic HTML animation document.

    The document payload lives in exactly one place: inline in ``html``
    (legacy projects) or externalized as an indexed Project file referenced
    by ``html_file_id`` (new writes).  ``format`` selects the animation
    contract: ``html_css`` documents animate exclusively through CSS
    animations; ``html_js`` documents drive a whitelisted vendored runtime
    from an inline script and expose the ``window.__hf`` seek protocol.
    External network resources are never loaded during rendering.
    """

    format: Literal["html_css", "html_js"] = "html_css"
    html: str | None = Field(
        default=None,
        min_length=32,
        max_length=200_000,
    )
    html_file_id: EntityId | None = None
    fps: int = Field(default=24, ge=8, le=60)
    loop: bool = True
    design_notes: str = ""
    motif: str = "custom"
    template_version: int | None = Field(default=None, ge=1)
    theme: str = "comic_patrol"
    variant: str = "sticker"
    emotion: str = "chill"
    entrance: str = "pop"
    exit: str = "soft_fade"
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_document_payload(self) -> MotionGraphic:
        if (self.html is None) == (self.html_file_id is None):
            raise ValueError(
                "motion document requires exactly one of html or"
                " html_file_id",
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _infer_template_metadata(cls, value: Any) -> Any:
        """Keep generated template metadata when loading older project JSON."""

        if not isinstance(value, dict) or not isinstance(
            value.get("html"),
            str,
        ):
            return value
        result = dict(value)
        html = value["html"]
        fields = (
            "motif",
            "theme",
            "variant",
            "emotion",
            "entrance",
            "exit",
            "intensity",
            "template-version",
        )
        for field in fields:
            key = "template_version" if field == "template-version" else field
            if key in result:
                continue
            match = re.search(
                rf'data-motion-{re.escape(field)}=["\']([^"\']+)["\']',
                html,
            )
            if match is None:
                continue
            raw: Any = match.group(1)
            if key == "intensity":
                try:
                    raw = float(raw)
                except ValueError:
                    continue
            elif key == "template_version":
                try:
                    raw = int(raw)
                except ValueError:
                    continue
            result[key] = raw
        return result


class OverlayCreation(StrictModel):
    """Procedural or generated overlay creative facts.

    The overlay's role is derived from its data instead of a kind tag:
    non-empty ``text`` makes it a caption card (``text`` stays the
    authoritative copy; ``motion`` is optional generated styling with a
    deterministic bubble fallback); empty ``text`` with a ``motion``
    document (or a ``prompt`` awaiting design) is a text-free decoration;
    a media sticker carries its payload on the Element's render_source.
    """

    type: Literal["overlay"] = "overlay"
    text: str = ""
    vibe: str = "chill"
    prompt: str = ""
    reference_version_ids: list[EntityId] = Field(default_factory=list)
    motion: MotionGraphic | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> OverlayCreation:
        if not self.text.strip() and not (
            self.prompt.strip() or self.reference_version_ids
        ):
            raise ValueError(
                "text-free overlay requires prompt or reference versions",
            )
        return self


def overlay_role(creation: OverlayCreation) -> str:
    """Derived overlay role: ``caption`` or ``decoration``.

    Media stickers are recognised at the Element level through their
    render_source; at the creation level they look like decorations.
    """

    return "caption" if creation.text.strip() else "decoration"


class TransitionCreation(StrictModel):
    """A time-bounded effect between two explicit Element endpoints."""

    type: Literal["transition"] = "transition"
    from_element_id: EntityId
    to_element_id: EntityId
    transition_kind: str = Field(min_length=1)
    easing: str = "linear"

    @model_validator(mode="after")
    def _validate_endpoints(self) -> TransitionCreation:
        if self.from_element_id == self.to_element_id:
            raise ValueError("transition endpoints must be different")
        return self


class MotionClipCreation(StrictModel):
    """A full-canvas motion document that carries a segment's whole picture.

    Pure motion-graphics cuts (no real or generated footage) place these
    elements on the main visual track: the document paints its own backdrop
    and animation, and the renderer rasterizes it over an opaque base for
    the Element's span. ``prompt`` holds the design brief while ``motion``
    is empty, awaiting the motion design pipeline.
    """

    type: Literal["motion_clip"] = "motion_clip"
    intent: str = ""
    prompt: str = ""
    motion: MotionGraphic | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> MotionClipCreation:
        if not self.prompt.strip() and self.motion is None:
            raise ValueError(
                "motion clip requires prompt or motion document",
            )
        return self


class AudioCreation(StrictModel):
    """An exact audio version placed directly on the Timeline."""

    type: Literal["audio"] = "audio"
    source_asset_version_id: EntityId
    # TTS-produced narration keeps its script here: editing the script and
    # applying the change re-synthesizes the audio. Uploaded/footage audio
    # leaves it empty.
    script: str = ""
    # Synthesis speed multiplier; only the CosyVoice family honours it,
    # other models keep the default 1.0.
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    gain_db: float = 0.0
    pan: float = Field(default=0.0, ge=-1, le=1)

    @field_validator("gain_db", "pan")
    @classmethod
    def _validate_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("audio values must be finite")
        return value


ElementCreation = Annotated[
    R2VCreation
    | T2VCreation
    | I2VCreation
    | S2VCreation
    | EditCreation
    | OverlayCreation
    | MotionClipCreation
    | TransitionCreation
    | AudioCreation,
    Field(discriminator="type"),
]


class TimelineElement(StrictModel):
    """The only persisted time/layer entity; no Track or Content indirection."""

    element_id: EntityId
    label: str = ""
    enabled: bool = True
    span: TimelineSpan
    location: ElementLocation | None = None
    z_index: int = 0
    creation: ElementCreation
    outputs: dict[EntityId, ElementOutput] = Field(default_factory=dict)
    render_source: RenderSource | None = None
    provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_element(self) -> TimelineElement:
        output_slots = [output.slot_id for output in self.outputs.values()]
        if len(output_slots) != len(set(output_slots)):
            raise ValueError("Element outputs cannot reuse one ArtifactSlot")
        if (
            isinstance(
                self.creation,
                (R2VCreation, EditCreation, OverlayCreation),
            )
            and self.location is None
        ):
            raise ValueError("visual Elements require location")
        if isinstance(self.creation, (TransitionCreation, AudioCreation)) and (
            self.location is not None
        ):
            raise ValueError(
                "transition/audio Elements cannot have visual location",
            )
        if isinstance(self.creation, TransitionCreation) and (
            self.outputs or self.render_source is not None
        ):
            raise ValueError(
                "Transition Element is procedural and has no output",
            )
        return self


class EditPlanDials(StrictModel):
    """Three taste dials from the upstream video-edit taste contract."""

    energy: Literal["low", "mid", "high"] = "mid"
    density: Literal["low", "mid", "high"] = "mid"
    decoration: Literal["low", "mid", "high"] = "mid"


class EditPlanDesignFloor(StrictModel):
    """The four designed slots every watchable deliverable declares.

    Upstream [design-floor]: Opening (1-3s hook), Transitions (hard-cut
    spine + one named accent family), Body (a designed beat per scene
    change), Ending (designed close, hard stop).
    """

    opening: str = ""
    transitions: str = ""
    body: str = ""
    ending: str = ""


class SceneLedgerRow(StrictModel):
    """One scene's lock state inside the scene-loop assembly."""

    scene_id: EntityId
    label: str = ""
    element_ids: list[EntityId] = Field(default_factory=list)
    status: Literal["draft", "locked"] = "draft"
    review_round: int = Field(default=0, ge=0)
    # Content fingerprint of the scene's elements at lock time: the compose
    # gate recomputes it, so a lock silently goes stale (and blocks the
    # master render) whenever any element inside the scene changed.
    locked_fingerprint: str | None = None


class EditPlan(StrictModel):
    """Taste contract for one Timeline (upstream video-edit methodology).

    Written by the AI editing director BEFORE placing Edit Elements;
    reviews grade against it and the plan advisory nudges the model to
    fill it in. ``mechanical_exemption`` is user-granted only.
    """

    concept: str = ""
    dials: EditPlanDials = Field(default_factory=EditPlanDials)
    signature_device: str = ""
    pacing: str = ""
    design_floor: EditPlanDesignFloor = Field(
        default_factory=EditPlanDesignFloor,
    )
    mechanical_exemption: bool = False
    scene_ledger: list[SceneLedgerRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_ledger(self) -> EditPlan:
        seen: set[str] = set()
        for row in self.scene_ledger:
            if row.scene_id in seen:
                raise ValueError(
                    f"duplicate scene_id in scene_ledger: {row.scene_id}",
                )
            seen.add(row.scene_id)
        return self


class Timeline(StrictModel):
    """One time coordinate system containing freely overlapping Elements."""

    timeline_id: EntityId
    ticks_per_second: int = Field(
        default=DEFAULT_TIMELINE_TICKS_PER_SECOND,
        gt=0,
    )
    # Named unified colour-grade preset applied to the whole composited
    # cut (empty string = no grading). Must be one of COLOR_GRADE_PRESETS
    # (warm_bright / clean_cool / cinematic) — free-form colour
    # descriptions are rejected at commit time so a typo can never
    # silently skip the grade pass.
    color_grade: str = ""
    edit_plan: EditPlan | None = None
    elements_by_id: dict[EntityId, TimelineElement] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def _validate_color_grade(self) -> Timeline:
        if self.color_grade and self.color_grade not in COLOR_GRADE_PRESETS:
            raise ValueError(
                "color_grade 必须是命名预设之一（不支持自由文本描述）："
                + ", ".join(COLOR_GRADE_PRESETS)
                + "；留空字符串表示不调色",
            )
        return self

    @model_validator(mode="after")
    def _validate_elements(self) -> Timeline:
        _require_mapping_identity(
            self.elements_by_id,
            "element_id",
            "timeline elements",
        )
        for element in self.elements_by_id.values():
            creation = element.creation
            if not isinstance(creation, TransitionCreation):
                continue
            source = _require_key(
                self.elements_by_id,
                creation.from_element_id,
                "transition source",
            )
            target = _require_key(
                self.elements_by_id,
                creation.to_element_id,
                "transition target",
            )
            if isinstance(source.creation, TransitionCreation) or isinstance(
                target.creation,
                TransitionCreation,
            ):
                raise ValueError("transition endpoints cannot be transitions")
            intersection_start = max(
                source.span.start_tick,
                target.span.start_tick,
            )
            intersection_end = min(source.span.end_tick, target.span.end_tick)
            if (
                element.span.start_tick < intersection_start
                or element.span.end_tick > intersection_end
            ):
                raise ValueError(
                    "transition span must be contained in its endpoint intersection",
                )
        return self

    def elements_at(
        self,
        tick: int,
        *,
        include_disabled: bool = False,
    ) -> list[TimelineElement]:
        if isinstance(tick, bool) or tick < 0:
            raise ValueError("tick must be a non-negative integer")
        return sorted(
            (
                element
                for element in self.elements_by_id.values()
                if (include_disabled or element.enabled)
                and element.span.contains(tick)
            ),
            key=lambda element: (element.span.start_tick, element.element_id),
        )


class Project(StrictModel):
    schema_version: Literal[8] = CURRENT_PROJECT_SCHEMA_VERSION
    project_id: EntityId
    generation: int = Field(default=0, ge=0)
    created_at: UtcDateTime
    updated_at: UtcDateTime
    name: str = Field(min_length=1)
    description: str = ""
    scenario: Literal["short_drama", "video_edit", "general"] = "general"
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    strategy: CreativeStrategy = Field(default_factory=CreativeStrategy)
    sources: SourceCatalog = Field(default_factory=SourceCatalog)
    visual: VisualDevelopment = Field(default_factory=VisualDevelopment)
    timelines: EntityCollection[Timeline] = Field(
        default_factory=lambda: EntityCollection(
            items={
                DEFAULT_TIMELINE_ID: Timeline(timeline_id=DEFAULT_TIMELINE_ID),
            },
            order=[DEFAULT_TIMELINE_ID],
        ),
    )
    assets: AssetIndex = Field(default_factory=AssetIndex)

    @model_validator(mode="before")
    @classmethod
    def _coerce_edit_duration(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        timelines = data.get("timelines")
        if not isinstance(timelines, dict):
            return data
        items = timelines.get("items")
        if not isinstance(items, dict):
            return data
        assets = data.get("assets")
        if not isinstance(assets, dict):
            return data
        source_versions = assets.get("source_versions_by_id", {})
        if not isinstance(source_versions, dict):
            source_versions = {}
        for timeline in items.values():
            if not isinstance(timeline, dict):
                continue
            ticks_per_second = timeline.get(
                "ticks_per_second",
                DEFAULT_TIMELINE_TICKS_PER_SECOND,
            )
            elements = timeline.get("elements_by_id")
            if not isinstance(elements, dict):
                continue
            for element in elements.values():
                if not isinstance(element, dict):
                    continue
                creation = element.get("creation")
                if not isinstance(creation, dict):
                    continue
                if creation.get("type") != "edit":
                    continue
                render_source = element.get("render_source")
                if not isinstance(render_source, dict):
                    continue
                if render_source.get("type") != "source_asset_version":
                    continue
                source_in = render_source.get("source_in_tick")
                source_out = render_source.get("source_out_tick")
                rate = render_source.get("playback_rate", 1.0)
                span = element.get("span")
                if (
                    not isinstance(span, dict)
                    or not isinstance(source_in, int)
                    or not isinstance(source_out, int)
                    or not isinstance(rate, (int, float))
                    or rate <= 0
                ):
                    continue
                expected = round((source_out - source_in) / rate)
                actual = span.get("duration_tick")
                if not isinstance(actual, int) or actual == expected:
                    continue
                version_id = render_source.get("version_id")
                source_version = (
                    source_versions.get(version_id, {})
                    if isinstance(version_id, str)
                    else {}
                )
                duration_seconds = (
                    source_version.get("duration_seconds")
                    if isinstance(source_version, dict)
                    else None
                )
                new_source_out = source_in + round(actual * rate)
                if (
                    isinstance(duration_seconds, (int, float))
                    and new_source_out > duration_seconds * ticks_per_second
                ):
                    span["duration_tick"] = expected
                else:
                    render_source["source_out_tick"] = new_source_out
        return data

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        # A Project id is also a host-filesystem segment and is intentionally
        # stricter than other EntityIds (which may contain ':').
        if ":" in value or value in {".", ".."}:
            raise ValueError("project_id must be a safe filesystem segment")
        return value

    @model_validator(mode="after")
    def _validate_graph(self) -> Project:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")

        _require_collection_identity(
            self.sources.sources,
            "source_id",
            "project sources",
        )
        _require_collection_identity(
            self.visual.entities,
            "entity_id",
            "visual entities",
        )
        source_versions = self.assets.source_versions_by_id
        artifact_versions = self.assets.artifact_versions_by_id

        for source in self.sources.sources.items.values():
            selected = _require_key(
                source_versions,
                source.selected_asset_version_id,
                "selected source version",
            )
            if selected.logical_asset_id != source.logical_asset_id:
                raise ValueError(
                    f"source {source.source_id} selected a foreign logical asset",
                )
            if source.current_intelligence_version_id is not None:
                intelligence = _require_key(
                    self.assets.intelligence_versions_by_id,
                    source.current_intelligence_version_id,
                    "selected source intelligence",
                )
                if (
                    intelligence.source_asset_version_id
                    != source.selected_asset_version_id
                ):
                    raise ValueError(
                        f"source {source.source_id} intelligence targets another version",
                    )

        visual_ids: dict[str, set[str]] = {
            "character": set(),
            "scene": set(),
            "prop": set(),
        }
        for entity in self.visual.entities.items.values():
            visual_ids[entity.kind].add(entity.entity_id)
            _require_collection_identity(
                entity.variants,
                "variant_id",
                "visual variants",
            )
            for variant in entity.variants.items.values():
                _require_all(
                    source_versions,
                    variant.reference_asset_version_ids,
                    "visual source",
                )
                _require_all(
                    artifact_versions,
                    variant.reference_artifact_version_ids,
                    "visual artifact reference",
                )
                _require_all(
                    artifact_versions,
                    variant.generated_artifact_version_ids,
                    "visual artifact",
                )
                if variant.selected_artifact_version_id is not None:
                    selected_variant_artifact = _require_key(
                        artifact_versions,
                        variant.selected_artifact_version_id,
                        "selected visual variant artifact",
                    )
                    if (
                        variant.selected_artifact_version_id
                        not in variant.generated_artifact_version_ids
                    ):
                        raise ValueError(
                            "selected visual variant artifact must be a "
                            "generated version of that variant",
                        )
                    artifact_variant_id = (
                        selected_variant_artifact.metadata.get(
                            "variantId",
                        )
                    )
                    if (
                        isinstance(artifact_variant_id, str)
                        and artifact_variant_id
                        and artifact_variant_id != variant.variant_id
                    ):
                        raise ValueError(
                            "selected visual variant artifact belongs to "
                            "another variant",
                        )
            if (
                len(entity.variants.order) > 1
                and entity.selected_artifact_version_id is not None
            ):
                raise ValueError(
                    "multi-Variant visual entities cannot use the legacy "
                    "entity-level selected artifact",
                )
            if entity.selected_artifact_version_id is not None:
                _require_key(
                    artifact_versions,
                    entity.selected_artifact_version_id,
                    "selected visual artifact",
                )
            if (
                entity.voice is not None
                and entity.voice.sample_source_version_id is not None
            ):
                _require_key(
                    source_versions,
                    entity.voice.sample_source_version_id,
                    "character voice sample version",
                )

        _require_collection_identity(
            self.visual.cast_lineups,
            "lineup_id",
            "visual cast lineups",
        )
        for lineup in self.visual.cast_lineups.items.values():
            for ref in lineup.character_refs:
                if ref not in visual_ids["character"]:
                    raise ValueError(
                        f"cast lineup {lineup.lineup_id} references "
                        f"missing character {ref}",
                    )
            if (
                lineup.scene_ref is not None
                and lineup.scene_ref not in visual_ids["scene"]
            ):
                raise ValueError(
                    f"cast lineup {lineup.lineup_id} references missing "
                    f"scene {lineup.scene_ref}",
                )
            for ref in lineup.prop_refs:
                if ref not in visual_ids["prop"]:
                    raise ValueError(
                        f"cast lineup {lineup.lineup_id} references "
                        f"missing prop {ref}",
                    )
            _require_all(
                source_versions,
                lineup.reference_asset_version_ids,
                "cast lineup source",
            )
            _require_all(
                artifact_versions,
                lineup.reference_artifact_version_ids,
                "cast lineup artifact reference",
            )
            _require_all(
                artifact_versions,
                lineup.generated_artifact_version_ids,
                "cast lineup artifact",
            )
            if lineup.selected_artifact_version_id is not None and (
                lineup.selected_artifact_version_id
                not in lineup.generated_artifact_version_ids
            ):
                raise ValueError(
                    f"cast lineup {lineup.lineup_id} selected artifact "
                    "must be one of its generated versions",
                )

        _require_collection_identity(
            self.timelines,
            "timeline_id",
            "timelines",
        )
        elements: dict[str, TimelineElement] = {}
        element_timelines: dict[str, Timeline] = {}
        for timeline in self.timelines.items.values():
            for element_id, element in timeline.elements_by_id.items():
                if element_id in elements:
                    raise ValueError(
                        f"element id {element_id} is duplicated across timelines",
                    )
                elements[element_id] = element
                element_timelines[element_id] = timeline

        for element_id, element in elements.items():
            creation = element.creation
            if isinstance(creation, R2VCreation):
                _require_version_refs(
                    source_versions,
                    artifact_versions,
                    creation.storyboard_reference_version_ids,
                    "storyboard reference",
                )
                _require_version_refs(
                    source_versions,
                    artifact_versions,
                    creation.video_reference_version_ids,
                    "video reference",
                )
                _validate_visual_refs(creation, visual_ids)
                for lineup_ref in creation.cast_lineup_refs:
                    if lineup_ref not in self.visual.cast_lineups.items:
                        raise ValueError(
                            f"element {element_id}: cast_lineup_refs "
                            f"references missing lineup {lineup_ref}",
                        )
                _validate_visual_variant_refs(
                    creation,
                    self.visual.entities.items,
                    element_id=element_id,
                )
                for shot in creation.shots.items.values():
                    _validate_visual_refs(shot, visual_ids)
            elif isinstance(creation, EditCreation):
                if not isinstance(
                    element.render_source,
                    SourceVersionRenderSource,
                ) or isinstance(
                    element.render_source,
                    ArtifactVersionRenderSource,
                ):
                    raise ValueError(
                        "Edit Element render_source must select one source asset range",
                    )
                if element.render_source.source_out_tick is None:
                    raise ValueError(
                        "Edit Element source range requires source_out_tick",
                    )
                source_duration_tick = (
                    element.render_source.source_out_tick
                    - element.render_source.source_in_tick
                )
                rendered_duration_tick = round(
                    source_duration_tick / element.render_source.playback_rate,
                )
                if rendered_duration_tick != element.span.duration_tick:
                    raise ValueError(
                        f"Edit content {element.element_id!r} duration mismatch: "
                        f"span.duration_tick={element.span.duration_tick}, but "
                        f"source range [{element.render_source.source_in_tick}, "
                        f"{element.render_source.source_out_tick}) at playback_rate="
                        f"{element.render_source.playback_rate} renders "
                        f"{rendered_duration_tick} ticks; set duration_tick to "
                        f"{rendered_duration_tick} or adjust the source range",
                    )
                if creation.source_intelligence_version_id is not None:
                    intelligence = _require_key(
                        self.assets.intelligence_versions_by_id,
                        creation.source_intelligence_version_id,
                        "edit source intelligence",
                    )
                    if (
                        intelligence.source_asset_version_id
                        != element.render_source.version_id
                    ):
                        raise ValueError(
                            "Edit Element intelligence targets another source version",
                        )
            elif isinstance(creation, OverlayCreation):
                _require_version_refs(
                    source_versions,
                    artifact_versions,
                    creation.reference_version_ids,
                    "overlay reference",
                )
                self._validate_committed_motion_document(
                    element_id,
                    creation.motion,
                )
            elif isinstance(creation, MotionClipCreation):
                self._validate_committed_motion_document(
                    element_id,
                    creation.motion,
                    require_externalized=True,
                )
            elif isinstance(creation, AudioCreation):
                _require_key(
                    source_versions,
                    creation.source_asset_version_id,
                    "audio source version",
                )

            for output_name, output in element.outputs.items():
                slot = _require_key(
                    self.assets.artifact_slots_by_id,
                    output.slot_id,
                    f"Element output {output_name} ArtifactSlot",
                )
                if slot.owner_ref != f"element:{element_id}":
                    raise ValueError(
                        f"Element output {output_name} references a foreign ArtifactSlot",
                    )

            render_source = element.render_source
            if isinstance(
                render_source,
                SourceVersionRenderSource,
            ) and not isinstance(
                render_source,
                ArtifactVersionRenderSource,
            ):
                version = _require_key(
                    source_versions,
                    render_source.version_id,
                    "Element render source",
                )
                _validate_render_range(
                    render_source,
                    version.duration_seconds,
                    element_timelines[element_id].ticks_per_second,
                )
                if isinstance(creation, AudioCreation) and (
                    creation.source_asset_version_id
                    != render_source.version_id
                ):
                    raise ValueError(
                        "audio render source must match its creation source",
                    )
            elif isinstance(render_source, ArtifactVersionRenderSource):
                version = _require_key(
                    artifact_versions,
                    render_source.version_id,
                    "Element render artifact",
                )
                _validate_render_range(
                    render_source,
                    version.duration_seconds,
                    element_timelines[element_id].ticks_per_second,
                )
            elif isinstance(render_source, ElementOutputRenderSource):
                output_element = _require_key(
                    elements,
                    render_source.element_id,
                    "Element output render source",
                )
                output = _require_key(
                    output_element.outputs,
                    render_source.output_name,
                    "Element named output",
                )
                slot = _require_key(
                    self.assets.artifact_slots_by_id,
                    output.slot_id,
                    "Element output ArtifactSlot",
                )
                if slot.selected_version_id is None:
                    raise ValueError(
                        "rendered Element output has no selected ArtifactVersion",
                    )
                version = _require_key(
                    artifact_versions,
                    slot.selected_version_id,
                    "Element output selected version",
                )
                _validate_render_range(
                    render_source,
                    version.duration_seconds,
                    element_timelines[element_id].ticks_per_second,
                )

        _validate_render_source_cycles(elements)
        return self

    def elements_at(
        self,
        timeline_id: str,
        tick: int,
        *,
        include_disabled: bool = False,
    ) -> list[TimelineElement]:
        timeline = _require_key(self.timelines.items, timeline_id, "timeline")
        return timeline.elements_at(tick, include_disabled=include_disabled)

    def _validate_committed_motion_document(
        self,
        element_id: str,
        motion: MotionGraphic | None,
        *,
        require_externalized: bool = False,
    ) -> None:
        if motion is None:
            return
        if require_externalized and motion.html is not None:
            # Main-track motion clips render exclusively from externalized
            # documents; accepting a hand-written inline body here would
            # only fail later at composition time, wasting a whole design
            # round. Fail closed at commit instead.
            raise ValueError(
                f"element {element_id!r} carries an inline motion clip "
                "document; motion clip documents must be created through "
                "the motion design pipeline (design_motion_overlays), "
                "which probes and externalizes the document before commit",
            )
        if motion.format == "html_js" and motion.html is not None:
            # html_js documents may only enter a committed Project through
            # the motion design pipeline, which probes the __hf contract
            # and externalizes the body to a content-addressed file.
            # Accepting inline script documents here would bypass every
            # render truth gate until composition time.
            raise ValueError(
                f"element {element_id!r} carries an inline html_js "
                "motion document; html_js motions must be created "
                "through the motion design pipeline "
                "(design_motion_overlays), which validates the "
                "window.__hf contract and externalizes the document "
                "before commit",
            )
        if motion.html_file_id is not None:
            # An externalized reference is only trusted when it provably
            # identifies a content-addressed motion document published by
            # the design pipeline: the file id must derive from the
            # indexed checksum, so a dangling id or a repointed
            # IndexedFile cannot smuggle an unprobed document past the
            # design gates.
            reference = motion.html_file_id
            indexed = self.assets.files_by_id.get(reference)
            if indexed is None:
                raise ValueError(
                    f"element {element_id!r} references motion "
                    f"document {reference!r} that does not exist in "
                    "assets.files_by_id",
                )
            if (
                indexed.kind != "large_text"
                or indexed.schema_name != "motion_document"
                or indexed.file_id != motion_document_file_id(indexed.sha256)
                or indexed.relative_uri
                != f"assets/motion/{indexed.sha256}.html"
            ):
                raise ValueError(
                    f"element {element_id!r} references "
                    f"{reference!r} which is not a content-addressed "
                    "motion document published by the motion design "
                    "pipeline",
                )

    @classmethod
    def new(
        cls,
        *,
        project_id: str,
        name: str,
        description: str = "",
        scenario: Literal["short_drama", "video_edit", "general"] = "general",
        settings: ProjectSettings | None = None,
        now: datetime | None = None,
    ) -> Project:
        timestamp = now or datetime.now(timezone.utc)
        return cls(
            project_id=project_id,
            created_at=timestamp,
            updated_at=timestamp,
            name=name,
            description=description,
            scenario=scenario,
            settings=settings or ProjectSettings(),
        )


def _require_mapping_identity(
    mapping: dict[str, Any],
    identity_field: str,
    label: str,
) -> None:
    for key, item in mapping.items():
        if getattr(item, identity_field) != key:
            raise ValueError(
                f"{label} key {key} does not match {identity_field}",
            )


def _require_collection_identity(
    collection: EntityCollection[Any],
    identity_field: str,
    label: str,
) -> None:
    _require_mapping_identity(collection.items, identity_field, label)


def _require_key(mapping: dict[str, T], key: str, label: str) -> T:
    try:
        return mapping[key]
    except KeyError as exc:
        raise ValueError(f"{label} references missing id {key}") from exc


def _require_all(mapping: dict[str, Any], keys: list[str], label: str) -> None:
    for key in keys:
        _require_key(mapping, key, label)


def _require_all_ids(known: set[str], keys: list[str], label: str) -> None:
    for key in keys:
        if key not in known:
            raise ValueError(f"{label} references missing id {key}")


def _require_version_refs(
    source_versions: dict[str, SourceAssetVersion],
    artifact_versions: dict[str, ArtifactVersion],
    keys: list[str],
    label: str,
) -> None:
    for key in keys:
        if key not in source_versions and key not in artifact_versions:
            raise ValueError(f"{label} references missing exact version {key}")


def _validate_render_range(
    source: SourceVersionRenderSource | ElementOutputRenderSource,
    duration_seconds: float | None,
    ticks_per_second: int,
) -> None:
    if source.source_out_tick is None or duration_seconds is None:
        return
    available_tick = round(duration_seconds * ticks_per_second)
    if source.source_out_tick > available_tick:
        raise ValueError(
            "Element render source range exceeds known media duration",
        )


def _validate_render_source_cycles(
    elements: dict[str, TimelineElement],
) -> None:
    edges = {
        element_id: element.render_source.element_id
        for element_id, element in elements.items()
        if isinstance(element.render_source, ElementOutputRenderSource)
        and element.render_source.element_id != element_id
    }
    complete: set[str] = set()
    visiting: set[str] = set()

    def visit(element_id: str) -> None:
        if element_id in complete:
            return
        if element_id in visiting:
            raise ValueError(
                "Element output render sources cannot form a cycle",
            )
        visiting.add(element_id)
        target_id = edges.get(element_id)
        if target_id is not None:
            visit(target_id)
        visiting.remove(element_id)
        complete.add(element_id)

    for element_id in edges:
        visit(element_id)


def _validate_visual_refs(
    value: Shot | R2VCreation,
    known: dict[str, set[str]],
) -> None:
    _require_all_ids(known["character"], value.character_refs, "character")
    _require_all_ids(known["prop"], value.prop_refs, "prop")
    if value.scene_ref is not None and value.scene_ref not in known["scene"]:
        raise ValueError(f"scene references missing id {value.scene_ref}")


def _validate_visual_variant_refs(
    value: R2VCreation,
    entities: dict[str, VisualEntity],
    *,
    element_id: str,
) -> None:
    referenced = {
        *value.character_refs,
        *value.prop_refs,
        *([value.scene_ref] if value.scene_ref is not None else []),
    }
    for entity_id, variant_id in value.visual_variant_refs.items():
        if entity_id not in referenced:
            raise ValueError(
                f"element {element_id}: visual variant binding targets "
                f"unreferenced entity {entity_id}; add it to this "
                "creation's character_refs/prop_refs/scene_ref in the "
                "same commit, or remove the visual_variant_refs entry",
            )
        entity = entities[entity_id]
        if (
            variant_id not in entity.variants.items
            or variant_id not in entity.variants.order
        ):
            raise ValueError(
                f"element {element_id}: visual variant binding references "
                f"missing variant {variant_id}",
            )


__all__ = [
    "CURRENT_PROJECT_SCHEMA_VERSION",
    "DEFAULT_TIMELINE_ID",
    "DEFAULT_TIMELINE_TICKS_PER_SECOND",
    "ArtifactVersionRenderSource",
    "AudioCreation",
    "CharacterVoice",
    "ArtifactSlot",
    "ArtifactVersion",
    "AssetIndex",
    "CreativeStrategy",
    "EditCreation",
    "ElementLocation",
    "ElementOutput",
    "ElementOutputRenderSource",
    "EntityCollection",
    "EntityId",
    "IndexedContentRef",
    "IndexedFile",
    "Project",
    "ProjectSettings",
    "ProjectSource",
    "R2VCreation",
    "RenderSource",
    "MotionGraphic",
    "Shot",
    "SourceAssetVersion",
    "SourceCatalog",
    "SourceIntelligenceVersion",
    "SourceVersionRenderSource",
    "Timeline",
    "TimelineElement",
    "TimelineSpan",
    "TransitionCreation",
    "VisualCastLineup",
    "VisualDevelopment",
    "VisualEntity",
    "VisualVariant",
    "OverlayCreation",
]
