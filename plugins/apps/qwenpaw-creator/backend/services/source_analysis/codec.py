# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-statements
"""Canonical provider-output normalization for file-native Source Intelligence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from domain.errors import ValidationError
from schemas.assets import (
    AudioEvent,
    OcrSegment,
    SemanticIndexEntry,
    SourceCoverage,
    SourceEntity,
    SourceIntelligenceIndex,
    SourceMediaMetadata,
    SourceModelRunRef,
    SourceShot,
    TranscriptSegment,
    TranscriptWord,
)


_MODALITIES = ("visual", "asr", "ocr", "audio")


def build_source_intelligence_index(
    raw: Mapping[str, Any],
    *,
    analysis_version_id: str,
    asset_id: str,
    asset_version_id: str,
    source_checksum: str,
    model_run: SourceModelRunRef,
    additional_model_runs: Sequence[SourceModelRunRef] = (),
    created_at: str,
    media: SourceMediaMetadata,
    coverage_policy: Mapping[str, Mapping[str, Any]],
    provenance_refs: Sequence[str],
) -> SourceIntelligenceIndex:
    """Inject authority-owned identity/provenance and validate exact model output."""

    allowed = {
        "summary",
        "coverage",
        "shots",
        "transcript",
        "words",
        "ocrSegments",
        "audioEvents",
        "entities",
        "semanticEntries",
    }
    if set(raw) != allowed:
        raise ValidationError(
            "Source Intelligence provider output keys are not the frozen schema",
            details={
                "missing": sorted(allowed.difference(raw)),
                "extra": sorted(set(raw).difference(allowed)),
            },
        )
    raw_coverage = raw.get("coverage")
    if not isinstance(raw_coverage, Mapping) or set(raw_coverage) != set(
        _MODALITIES,
    ):
        raise ValidationError(
            "Source Intelligence coverage must contain exactly visual/asr/ocr/audio",
        )
    coverage: dict[str, SourceCoverage] = {}
    for modality in _MODALITIES:
        try:
            item = SourceCoverage.model_validate(raw_coverage[modality])
        except (TypeError, ValueError) as error:
            raise ValidationError(
                f"Source Intelligence {modality} coverage is invalid: {error}",
            ) from error
        policy = dict(coverage_policy.get(modality) or {})
        if (
            item.mode != policy.get("mode")
            or item.producer != policy.get("producer")
            or item.ratio != policy.get("ratio")
        ):
            raise ValidationError(
                f"Source Intelligence provider claimed unsupported {modality} coverage",
            )
        coverage[modality] = item

    provenance = set(provenance_refs)
    if not provenance or len(provenance) != len(provenance_refs):
        raise ValidationError(
            "Source Intelligence Runtime provenance refs must be unique and non-empty",
        )
    if any(not item.strip() for item in provenance):
        raise ValidationError(
            "Source Intelligence Runtime provenance refs must be unique and non-empty",
        )
    default_base = {
        "assetVersionId": asset_version_id,
        "sourceChecksum": source_checksum,
        "createdAt": created_at,
    }
    known_model_runs = {
        model_run.id,
        *(item.id for item in additional_model_runs),
    }

    def records(
        key: str,
        model: type[Any],
        allowed_fields: set[str],
    ) -> list[Any]:
        values = raw.get(key)
        if not isinstance(values, list):
            raise ValidationError(
                f"Source Intelligence provider {key} must be an array",
            )
        result: list[Any] = []
        seen: set[str] = set()
        for number, value in enumerate(values, 1):
            if not isinstance(value, Mapping) or not set(value).issubset(
                allowed_fields,
            ):
                raise ValidationError(
                    f"Source Intelligence {key}[{number}] has invalid fields",
                )
            evidence = value.get("evidenceFrameRefs")
            if (
                not isinstance(evidence, list)
                or not evidence
                or not set(map(str, evidence)).issubset(provenance)
            ):
                raise ValidationError(
                    f"Source Intelligence {key}[{number}] evidence lacks Runtime provenance",
                )
            record = dict(value)
            record_model_run_id = str(record.pop("modelRunId", model_run.id))
            if record_model_run_id not in known_model_runs:
                raise ValidationError(
                    f"Source Intelligence {key}[{number}] has unknown modelRunId",
                )
            try:
                item = model.model_validate(
                    {
                        **record,
                        **default_base,
                        "modelRunId": record_model_run_id,
                    },
                )
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    f"Source Intelligence {key}[{number}] is invalid: {error}",
                ) from error
            if item.id in seen:
                raise ValidationError(
                    f"Source Intelligence {key} contains duplicate id: {item.id}",
                )
            seen.add(item.id)
            result.append(item)
        return result

    timed = {
        "id",
        "startMs",
        "endMs",
        "confidence",
        "evidenceFrameRefs",
        "modelRunId",
    }
    shots = records(
        "shots",
        SourceShot,
        timed | {"description", "events", "keyframeRef"},
    )
    transcript = records(
        "transcript",
        TranscriptSegment,
        timed | {"text", "speaker"},
    )
    words = records("words", TranscriptWord, timed | {"word"})
    ocr = records("ocrSegments", OcrSegment, timed | {"text"})
    audio = records(
        "audioEvents",
        AudioEvent,
        timed | {"label", "description"},
    )
    optional_range = {
        "id",
        "startMs",
        "endMs",
        "confidence",
        "evidenceFrameRefs",
        "modelRunId",
    }
    entities = records(
        "entities",
        SourceEntity,
        optional_range | {"kind", "label", "description"},
    )
    semantic = records(
        "semanticEntries",
        SemanticIndexEntry,
        optional_range | {"text", "tags"},
    )
    if coverage["visual"].mode != "available" and shots:
        raise ValidationError(
            "Source Intelligence shots require available visual coverage",
        )
    try:
        return SourceIntelligenceIndex(
            id=analysis_version_id,
            assetId=asset_id,
            assetVersionId=asset_version_id,
            sourceChecksum=source_checksum,
            modelRuns=[model_run, *additional_model_runs],
            coverage=coverage,
            media=media,
            summary=str(raw["summary"]).strip(),
            shots=shots,
            transcript=transcript,
            words=words,
            ocrSegments=ocr,
            audioEvents=audio,
            entities=entities,
            semanticEntries=semantic,
            createdAt=created_at,
        )
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"Source Intelligence index is invalid: {error}",
        ) from error


__all__ = ["build_source_intelligence_index"]
