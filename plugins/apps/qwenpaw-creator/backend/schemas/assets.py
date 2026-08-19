# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_serializer, model_validator

from .common import StrictModel


class TextOrUrlAssetRequest(StrictModel):
    client_request_id: str = Field(alias="clientRequestId")
    kind: Literal["url", "text"]
    name: str
    value: str
    post_ingest_action: Literal["NONE", "ATTACH_SOURCE"] = Field(
        "NONE",
        alias="postIngestAction",
    )


CoverageMode = Literal["available", "unavailable", "not_applicable"]
CoverageProducer = Literal[
    "model_native",
    "runtime_existing",
    "user_provided",
    "document_reader",
]


class SourceCoverage(StrictModel):
    mode: CoverageMode
    producer: CoverageProducer | None = None
    ratio: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_availability(self) -> "SourceCoverage":
        if self.mode == "available":
            if self.producer is None:
                raise ValueError("available coverage requires a producer")
            if self.ratio is None:
                # Only the document reader may declare an honestly-unknown
                # share (row-capped reads with unknowable totals); the
                # index additionally confines this to document ocr.
                if self.producer != "document_reader":
                    raise ValueError(
                        "available coverage requires a ratio in (0, 1]",
                    )
            elif self.ratio <= 0:
                raise ValueError(
                    "available coverage requires a ratio in (0, 1]",
                )
        elif self.producer is not None or self.ratio is not None:
            raise ValueError(
                "unavailable/not_applicable coverage cannot declare producer or ratio",
            )
        return self


class SourceModelRunRef(StrictModel):
    id: str
    provider: str
    model: str

    @field_validator("id", "provider", "model")
    @classmethod
    def nonempty_model_run_field(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model run fields cannot be empty")
        return value


class DocumentMetadata(StrictModel):
    """Document facts produced by the document reader (format + pages)."""

    format: str = Field(min_length=1)
    page_count: int = Field(alias="pageCount", strict=True, ge=1)


class DocumentTextCoverage(StrictModel):
    """Integrity + coverage facts for one read_document indexed text.

    Every field is mandatory: a partially populated textCoverage must be
    rejected instead of silently degrading the commit-time integrity
    checks (fail-closed).
    """

    indexed_chars: int = Field(alias="indexedChars", strict=True, ge=0)
    extracted_chars: int = Field(alias="extractedChars", strict=True, ge=0)
    extraction_complete: bool = Field(
        alias="extractionComplete",
        strict=True,
    )
    extraction_fraction: float | None = Field(
        alias="extractionFraction",
        strict=True,
        gt=0,
        le=1,
    )
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_consistency(self) -> "DocumentTextCoverage":
        if self.indexed_chars > self.extracted_chars:
            raise ValueError(
                "indexedChars cannot exceed extractedChars",
            )
        if self.extraction_complete:
            if self.extraction_fraction != 1.0:
                raise ValueError(
                    "complete extraction must declare "
                    "extractionFraction=1.0",
                )
        elif (
            self.extraction_fraction is not None
            and self.extraction_fraction >= 1.0
        ):
            # An incomplete extraction claiming full coverage would let a
            # truncated document persist ocr ratio=1.0.
            raise ValueError(
                "incomplete extraction requires extractionFraction to be "
                "None or below 1.0",
            )
        return self


class SourceMediaMetadata(StrictModel):
    media_kind: Literal[
        "image",
        "video",
        "audio",
        "document",
        "other",
    ] = Field(
        alias="mediaKind",
    )
    media_type: str = Field(alias="mediaType")
    duration_ms: int | None = Field(
        None,
        alias="durationMs",
        strict=True,
        ge=0,
    )
    width: int | None = Field(None, strict=True, gt=0)
    height: int | None = Field(None, strict=True, gt=0)
    sample_rate_hz: int | None = Field(
        None,
        alias="sampleRateHz",
        strict=True,
        gt=0,
    )
    channels: int | None = Field(None, strict=True, gt=0)
    document: DocumentMetadata | None = None

    @model_validator(mode="after")
    def validate_document_metadata(self) -> "SourceMediaMetadata":
        if self.document is not None and self.media_kind != "document":
            raise ValueError(
                "document metadata is only valid for document media",
            )
        return self


class SourceEvidenceRecord(StrictModel):
    asset_version_id: str = Field(alias="assetVersionId")
    source_checksum: str = Field(alias="sourceChecksum")
    confidence: float = Field(ge=0, le=1)
    model_run_id: str = Field(alias="modelRunId")
    evidence_frame_refs: list[str] = Field(
        alias="evidenceFrameRefs",
        min_length=1,
    )
    created_at: str = Field(alias="createdAt")

    @field_validator(
        "asset_version_id",
        "source_checksum",
        "model_run_id",
        "created_at",
    )
    @classmethod
    def nonempty_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source evidence identity fields cannot be empty")
        return value

    @field_validator("created_at")
    @classmethod
    def timezone_aware_created_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("createdAt must include a timezone")
        return value

    @field_validator("evidence_frame_refs")
    @classmethod
    def nonempty_unique_evidence_refs(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values) or len(values) != len(
            set(values),
        ):
            raise ValueError(
                "evidenceFrameRefs must contain unique non-empty refs",
            )
        return values


class SourceTimedEvidenceRecord(SourceEvidenceRecord):
    start_ms: int = Field(alias="startMs", strict=True, ge=0)
    end_ms: int = Field(alias="endMs", strict=True, gt=0)

    @model_validator(mode="after")
    def validate_half_open_range(self) -> "SourceTimedEvidenceRecord":
        if self.end_ms <= self.start_ms:
            raise ValueError(
                "source interval must be a non-empty half-open [startMs, endMs) range",
            )
        return self


class SourceShot(SourceTimedEvidenceRecord):
    id: str
    description: str
    events: list[str]
    keyframe_ref: str = Field(alias="keyframeRef")

    @model_validator(mode="after")
    def validate_keyframe_evidence(self) -> "SourceShot":
        if self.keyframe_ref not in self.evidence_frame_refs:
            raise ValueError("keyframeRef must be one of evidenceFrameRefs")
        return self


class TranscriptSegment(SourceTimedEvidenceRecord):
    id: str
    text: str
    speaker: str | None = None


class TranscriptWord(SourceTimedEvidenceRecord):
    id: str
    word: str


class OcrSegment(SourceTimedEvidenceRecord):
    id: str
    text: str


class AudioEvent(SourceTimedEvidenceRecord):
    id: str
    label: str
    description: str = ""


class SourceEntity(SourceEvidenceRecord):
    id: str
    kind: str
    label: str
    description: str = ""
    start_ms: int | None = Field(None, alias="startMs", strict=True, ge=0)
    end_ms: int | None = Field(None, alias="endMs", strict=True, gt=0)

    @model_validator(mode="after")
    def validate_optional_range(self) -> "SourceEntity":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError(
                "entity startMs/endMs must both be present or absent",
            )
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError(
                "entity interval must be a non-empty half-open range",
            )
        return self


class SemanticIndexEntry(SourceEvidenceRecord):
    id: str
    text: str
    tags: list[str]
    start_ms: int | None = Field(None, alias="startMs", strict=True, ge=0)
    end_ms: int | None = Field(None, alias="endMs", strict=True, gt=0)

    @model_validator(mode="after")
    def validate_optional_range(self) -> "SemanticIndexEntry":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError(
                "semantic entry startMs/endMs must both be present or absent",
            )
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError(
                "semantic interval must be a non-empty half-open range",
            )
        return self


class SourceAgentShotInput(StrictModel):
    """Visual shot facts authored by the outer Source Intelligence VLM."""

    start_ms: int = Field(alias="startMs", strict=True, ge=0)
    end_ms: int = Field(alias="endMs", strict=True, gt=0)
    description: str = Field(min_length=1)
    events: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_range(self) -> "SourceAgentShotInput":
        if self.end_ms <= self.start_ms:
            raise ValueError("shot endMs must be greater than startMs")
        if any(not item.strip() for item in self.events):
            raise ValueError("shot events cannot contain empty values")
        return self


class SourceAgentEntityInput(StrictModel):
    """Entity facts authored by the outer Source Intelligence VLM."""

    kind: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = ""
    start_ms: int | None = Field(None, alias="startMs", strict=True, ge=0)
    end_ms: int | None = Field(None, alias="endMs", strict=True, gt=0)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_optional_range(self) -> "SourceAgentEntityInput":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError(
                "entity startMs/endMs must both be present or absent",
            )
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("entity endMs must be greater than startMs")
        return self


class SourceAgentSemanticInput(StrictModel):
    """Search/edit semantics authored by the outer Source Intelligence VLM."""

    text: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    start_ms: int | None = Field(None, alias="startMs", strict=True, ge=0)
    end_ms: int | None = Field(None, alias="endMs", strict=True, gt=0)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_optional_range(self) -> "SourceAgentSemanticInput":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError(
                "semantic entry startMs/endMs must both be present or absent",
            )
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError(
                "semantic entry endMs must be greater than startMs",
            )
        if any(not item.strip() for item in self.tags):
            raise ValueError("semantic entry tags cannot contain empty values")
        return self


class SourceAgentModuleResultRefs(StrictModel):
    """Opaque Runtime-owned modality results selected by the outer VLM."""

    asr: str | None = None
    document: str | None = None


class SourceAgentIntelligenceInput(StrictModel):
    """Exact structured payload submitted by the outer Source Intelligence VLM."""

    summary: str = Field(min_length=1)
    shots: list[SourceAgentShotInput]
    entities: list[SourceAgentEntityInput]
    semantic_entries: list[SourceAgentSemanticInput] = Field(
        alias="semanticEntries",
    )
    module_result_refs: SourceAgentModuleResultRefs = Field(
        default_factory=SourceAgentModuleResultRefs,
        alias="moduleResultRefs",
    )


class SourceMemoryRef(StrictModel):
    """Pointer to the built long-source graph memory artifacts.

    Hydrated at read time from ``runtime/source-intelligence/<index-id>/
    memory``; never persisted inside the immutable index JSON, so the
    canonical payload of existing indexes stays byte-stable.
    """

    graph_path: str = Field(alias="graphPath", min_length=1)
    embeddings_path: str = Field(alias="embeddingsPath", min_length=1)
    built_at: str = Field(alias="builtAt", min_length=1)
    macro_count: int = Field(alias="macroCount", ge=0)

    @field_validator("built_at")
    @classmethod
    def timezone_aware_built_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("builtAt must include a timezone")
        return value


class SourceIntelligenceIndex(StrictModel):
    id: str
    asset_id: str = Field(alias="assetId")
    asset_version_id: str = Field(alias="assetVersionId")
    source_checksum: str = Field(alias="sourceChecksum")
    model_runs: list[SourceModelRunRef] = Field(alias="modelRuns")
    coverage: dict[str, SourceCoverage]
    media: SourceMediaMetadata
    summary: str
    shots: list[SourceShot]
    transcript: list[TranscriptSegment]
    words: list[TranscriptWord]
    ocr_segments: list[OcrSegment] = Field(alias="ocrSegments")
    audio_events: list[AudioEvent] = Field(alias="audioEvents")
    entities: list[SourceEntity]
    semantic_entries: list[SemanticIndexEntry] = Field(alias="semanticEntries")
    created_at: str = Field(alias="createdAt")
    memory_ref: SourceMemoryRef | None = Field(None, alias="memoryRef")

    @model_serializer(mode="wrap")
    def _omit_absent_memory_ref(self, handler: Any) -> dict[str, Any]:
        # Keep persisted/canonical dumps byte-identical to pre-memory
        # indexes: the hydrated-only field is emitted only when present.
        data = handler(self)
        if self.memory_ref is None:
            data.pop("memoryRef", None)
            data.pop("memory_ref", None)
        return data

    @field_validator("created_at")
    @classmethod
    def timezone_aware_created_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("createdAt must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_unknown_coverage_scope(self) -> "SourceIntelligenceIndex":
        # An honestly-unknown coverage share is confined to the document
        # reader's text extraction; every other available coverage keeps
        # the frozen ratio-in-(0,1] invariant.
        for modality, coverage in self.coverage.items():
            if (
                coverage.mode == "available"
                and coverage.ratio is None
                and not (
                    modality == "ocr"
                    and coverage.producer == "document_reader"
                    and self.media.media_kind == "document"
                )
            ):
                raise ValueError(
                    "an unknown coverage ratio is only allowed for "
                    "document ocr coverage produced by document_reader",
                )
        return self

    @model_validator(mode="after")
    def validate_complete_index(self) -> "SourceIntelligenceIndex":
        if set(self.coverage) != {"visual", "asr", "ocr", "audio"}:
            raise ValueError(
                "coverage must contain exactly visual/asr/ocr/audio",
            )
        if (
            not self.id.strip()
            or not self.asset_id.strip()
            or not self.asset_version_id.strip()
        ):
            raise ValueError("source intelligence identities cannot be empty")
        if not self.source_checksum.strip() or not self.model_runs:
            raise ValueError(
                "source intelligence checksum/modelRuns cannot be empty",
            )
        model_run_ids = [item.id for item in self.model_runs]
        if len(model_run_ids) != len(set(model_run_ids)):
            raise ValueError("modelRuns must contain unique ids")
        records_by_modality: dict[str, list[Any]] = {
            "visual": list(self.shots),
            "asr": [*self.transcript, *self.words],
            "ocr": list(self.ocr_segments),
            "audio": list(self.audio_events),
        }
        for modality, records in records_by_modality.items():
            if self.coverage[modality].mode != "available" and records:
                raise ValueError(
                    f"{modality} records require available coverage",
                )
        run_ids = {item.id for item in self.model_runs}
        all_records: list[SourceEvidenceRecord] = [
            *self.shots,
            *self.transcript,
            *self.words,
            *self.ocr_segments,
            *self.audio_events,
            *self.entities,
            *self.semantic_entries,
        ]
        for record in all_records:
            if record.asset_version_id != self.asset_version_id:
                raise ValueError("record assetVersionId does not match index")
            if record.source_checksum != self.source_checksum:
                raise ValueError("record sourceChecksum does not match index")
            if record.model_run_id not in run_ids:
                raise ValueError(
                    "record modelRunId does not exist in modelRuns",
                )
            end_ms = getattr(record, "end_ms", None)
            if (
                end_ms is not None
                and self.media.duration_ms is not None
                and end_ms > self.media.duration_ms
            ):
                raise ValueError(
                    "record interval exceeds authoritative media durationMs",
                )
        return self


class SourceIndexQueryItem(StrictModel):
    kind: Literal[
        "summary",
        "shot",
        "transcript",
        "word",
        "ocr",
        "audio",
        "entity",
        "semantic",
    ]
    record: dict[str, Any]


class SourceIndexQueryResult(StrictModel):
    index: SourceIntelligenceIndex
    query: str
    items: list[SourceIndexQueryItem]
