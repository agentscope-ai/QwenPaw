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

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


CURRENT_PROJECT_SCHEMA_VERSION = 2
DEFAULT_TIMELINE_ID = "timeline:main"
DEFAULT_TIMELINE_TICKS_PER_SECOND = 1_000
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


class VisualEntity(StrictModel):
    entity_id: EntityId
    kind: Literal["character", "scene", "prop"]
    name: str = Field(min_length=1)
    description: str = ""
    continuity: str = ""
    variants: EntityCollection[VisualVariant] = Field(
        default_factory=EntityCollection,
    )
    selected_artifact_version_id: EntityId | None = None


class VisualDevelopment(StrictModel):
    visual_bible: str = ""
    style: str = ""
    entities: EntityCollection[VisualEntity] = Field(
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
    shots: EntityCollection[Shot] = Field(default_factory=EntityCollection)
    recipe: GenerationRecipe | None = None
    storyboard_prompt: str = ""
    storyboard_reference_version_ids: list[EntityId] = Field(
        default_factory=list,
    )
    video_prompt: str = ""
    video_reference_version_ids: list[EntityId] = Field(default_factory=list)

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
    """One self-contained deterministic HTML/CSS animation document.

    ``html`` is a complete standalone document that draws on a transparent
    background and animates exclusively through CSS animations, so any
    conforming renderer can seek it frame by frame.  External network
    resources are never loaded during rendering.
    """

    format: Literal["html_css"] = "html_css"
    html: str = Field(min_length=32, max_length=200_000)
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

    ``motion`` carries one generated presentation document.  It is the whole
    payload of an ``overlay_kind="motion"`` decoration, and the optional
    generated styling of a text overlay (``pet_os`` / ``interview_summary``),
    whose ``text`` stays the authoritative content either way.
    """

    type: Literal["overlay"] = "overlay"
    overlay_kind: Literal["pet_os", "interview_summary", "motion", "media"]
    text: str = ""
    vibe: str = "chill"
    prompt: str = ""
    reference_version_ids: list[EntityId] = Field(default_factory=list)
    motion: MotionGraphic | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> OverlayCreation:
        if (
            self.overlay_kind in {"pet_os", "interview_summary"}
            and not self.text.strip()
        ):
            raise ValueError("text overlay requires non-empty text")
        if self.overlay_kind in {"motion", "media"} and not (
            self.prompt.strip() or self.reference_version_ids
        ):
            raise ValueError(
                "generated overlay requires prompt or reference versions",
            )
        if self.motion is not None and self.overlay_kind == "media":
            raise ValueError(
                "motion payload is not valid for overlay_kind=media",
            )
        return self


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


class AudioCreation(StrictModel):
    """An exact audio version placed directly on the Timeline."""

    type: Literal["audio"] = "audio"
    source_asset_version_id: EntityId
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
    | EditCreation
    | OverlayCreation
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


class Timeline(StrictModel):
    """One time coordinate system containing freely overlapping Elements."""

    timeline_id: EntityId
    ticks_per_second: int = Field(
        default=DEFAULT_TIMELINE_TICKS_PER_SECOND,
        gt=0,
    )
    elements_by_id: dict[EntityId, TimelineElement] = Field(
        default_factory=dict,
    )

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
    schema_version: Literal[2] = CURRENT_PROJECT_SCHEMA_VERSION
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
            if entity.selected_artifact_version_id is not None:
                _require_key(
                    artifact_versions,
                    entity.selected_artifact_version_id,
                    "selected visual artifact",
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


__all__ = [
    "CURRENT_PROJECT_SCHEMA_VERSION",
    "DEFAULT_TIMELINE_ID",
    "DEFAULT_TIMELINE_TICKS_PER_SECOND",
    "ArtifactVersionRenderSource",
    "AudioCreation",
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
    "VisualDevelopment",
    "VisualEntity",
    "VisualVariant",
    "OverlayCreation",
]
