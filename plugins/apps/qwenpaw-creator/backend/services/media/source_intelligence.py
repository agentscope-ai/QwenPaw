# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches,too-many-statements
"""Typed Source Intelligence contract and canonical Text Workspace codec."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, unquote

from domain.errors import StorageIntegrityError, ValidationError
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
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_INDEX_HEADER = "SOURCE_INTELLIGENCE_INDEX\t1"
_BASE_FILES = frozenset({"index.txt", "summary.md"})


def _enc(value: Any) -> str:
    return quote(str(value), safe="")


def _dec(value: str) -> str:
    return unquote(value)


def _enc_values(values: Sequence[Any]) -> str:
    return ",".join(_enc(item) for item in values) if values else "-"


def _dec_values(value: str) -> list[str]:
    return [] if value == "-" else [_dec(item) for item in value.split(",")]


def _optional(value: Any) -> str:
    return "-" if value is None else _enc(value)


def _float(value: float) -> str:
    return format(value, ".12g")


def _safe_id(value: str, *, label: str) -> str:
    if (
        not value
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
        or "--" in value
    ):
        raise ValidationError(f"{label} 不是安全稳定 id: {value!r}")
    return value


def _common_fields(record: Mapping[str, Any]) -> list[str]:
    return [
        _enc(record["id"]),
        _enc(record["assetVersionId"]),
        _enc(record["sourceChecksum"]),
        _float(float(record["confidence"])),
        _enc(record["modelRunId"]),
        _enc_values(record["evidenceFrameRefs"]),
        _enc(record["createdAt"]),
    ]


def _record_line(kind: str, record: Mapping[str, Any]) -> str:
    fields = [kind, *_common_fields(record)]
    if kind in {"shot", "transcript", "word", "ocr", "audio"}:
        fields.extend((str(record["startMs"]), str(record["endMs"])))
    elif kind in {"entity", "semantic"}:
        fields.extend(
            (_optional(record.get("startMs")), _optional(record.get("endMs"))),
        )
    if kind == "shot":
        fields.extend(
            (
                _enc(record["description"]),
                _enc_values(record["events"]),
                _enc(record["keyframeRef"]),
            ),
        )
    elif kind == "transcript":
        fields.extend((_enc(record["text"]), _optional(record.get("speaker"))))
    elif kind == "word":
        fields.append(_enc(record["word"]))
    elif kind == "ocr":
        fields.append(_enc(record["text"]))
    elif kind == "audio":
        fields.extend(
            (_enc(record["label"]), _enc(record.get("description") or "")),
        )
    elif kind == "entity":
        fields.extend(
            (
                _enc(record["kind"]),
                _enc(record["label"]),
                _enc(record.get("description") or ""),
            ),
        )
    elif kind == "semantic":
        fields.extend((_enc(record["text"]), _enc_values(record["tags"])))
    else:  # pragma: no cover - internal registry invariant
        raise ValidationError(f"未知 Source Intelligence record kind: {kind}")
    return "\t".join(fields)


def _index_text(index: SourceIntelligenceIndex) -> str:
    payload = index.model_dump(mode="json", by_alias=True)
    lines = [
        _INDEX_HEADER,
        f"id\t{_enc(payload['id'])}",
        f"assetId\t{_enc(payload['assetId'])}",
        f"assetVersionId\t{_enc(payload['assetVersionId'])}",
        f"sourceChecksum\t{_enc(payload['sourceChecksum'])}",
        f"createdAt\t{_enc(payload['createdAt'])}",
    ]
    for model_run in payload["modelRuns"]:
        lines.append(
            "\t".join(
                (
                    "modelRun",
                    _enc(model_run["id"]),
                    _enc(model_run["provider"]),
                    _enc(model_run["model"]),
                ),
            ),
        )
    for modality in _MODALITIES:
        coverage = payload["coverage"][modality]
        lines.append(
            "\t".join(
                (
                    "coverage",
                    modality,
                    coverage["mode"],
                    _optional(coverage.get("producer")),
                    "-"
                    if coverage.get("ratio") is None
                    else _float(coverage["ratio"]),
                ),
            ),
        )
    media = payload["media"]
    for key in (
        "mediaKind",
        "mediaType",
        "durationMs",
        "width",
        "height",
        "sampleRateHz",
        "channels",
    ):
        lines.append(f"media\t{key}\t{_optional(media.get(key))}")
    for kind, key in (
        ("shot", "shots"),
        ("transcript", "transcript"),
        ("word", "words"),
        ("ocr", "ocrSegments"),
        ("audio", "audioEvents"),
        ("entity", "entities"),
        ("semantic", "semanticEntries"),
    ):
        lines.extend(_record_line(kind, record) for record in payload[key])
    return "\n".join(lines) + "\n"


def _timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _vtt(
    records: Sequence[Mapping[str, Any]],
    *,
    text_key: str,
    asset_version_id: str,
    source_checksum: str,
) -> str:
    lines = [
        "WEBVTT",
        "X-CREATOR-UNITS: milliseconds",
        f"X-CREATOR-ASSET-VERSION: {asset_version_id}",
        f"X-CREATOR-SOURCE-CHECKSUM: {source_checksum}",
        "",
    ]
    for record in records:
        lines.extend(
            (
                str(record["id"]),
                f"{_timestamp(int(record['startMs']))} --> {_timestamp(int(record['endMs']))}",
                str(record[text_key]).replace("\r", " ").replace("\n", " "),
                "NOTE "
                + " ".join(
                    (
                        f"confidence={_float(float(record['confidence']))}",
                        f"modelRunId={record['modelRunId']}",
                        f"evidenceFrameRefs={','.join(record['evidenceFrameRefs'])}",
                        f"createdAt={record['createdAt']}",
                    ),
                ),
                "",
            ),
        )
    return "\n".join(lines)


def _markdown_table(
    title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> str:
    def clean(value: Any) -> str:
        return (
            str(value)
            .replace("|", "\\|")
            .replace("\r", " ")
            .replace("\n", " ")
        )

    lines = [
        f"# {title}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(clean(value) for value in row) + " |" for row in rows
    )
    return "\n".join(lines) + "\n"


def render_source_intelligence_files(
    index: SourceIntelligenceIndex,
) -> dict[str, str]:
    """Render the one canonical, non-JSON Workspace representation."""

    _safe_id(index.id, label="analysisVersionId")
    payload = index.model_dump(mode="json", by_alias=True)
    files: dict[str, str] = {
        "index.txt": _index_text(index),
        "summary.md": f"# Source Intelligence\n\n{index.summary.strip()}\n",
    }
    if payload["transcript"]:
        files["transcript.vtt"] = _vtt(
            payload["transcript"],
            text_key="text",
            asset_version_id=index.asset_version_id,
            source_checksum=index.source_checksum,
        )
    if payload["ocrSegments"]:
        files["ocr.vtt"] = _vtt(
            payload["ocrSegments"],
            text_key="text",
            asset_version_id=index.asset_version_id,
            source_checksum=index.source_checksum,
        )
    if payload["words"]:
        files["transcript-words.ctm"] = "\n".join(
            [
                ";; CREATOR_CTM_MS 1",
                f";; assetVersionId={index.asset_version_id}",
                f";; sourceChecksum={index.source_checksum}",
                *(
                    "\t".join(
                        (
                            str(item["id"]),
                            str(item["startMs"]),
                            str(item["endMs"]),
                            str(item["word"])
                            .replace("\t", " ")
                            .replace("\n", " "),
                            _float(float(item["confidence"])),
                            str(item["modelRunId"]),
                            ",".join(item["evidenceFrameRefs"]),
                            str(item["createdAt"]),
                        ),
                    )
                    for item in payload["words"]
                ),
                "",
            ],
        )
    if payload["audioEvents"]:
        files["audio.md"] = _markdown_table(
            "Audio Events",
            (
                "id",
                "startMs",
                "endMs",
                "label",
                "description",
                "confidence",
                "modelRunId",
                "evidenceFrameRefs",
                "createdAt",
            ),
            [
                (
                    item["id"],
                    item["startMs"],
                    item["endMs"],
                    item["label"],
                    item["description"],
                    _float(float(item["confidence"])),
                    item["modelRunId"],
                    ",".join(item["evidenceFrameRefs"]),
                    item["createdAt"],
                )
                for item in payload["audioEvents"]
            ],
        )
    if payload["entities"]:
        files["entities.md"] = _markdown_table(
            "Entities",
            (
                "id",
                "kind",
                "label",
                "description",
                "startMs",
                "endMs",
                "confidence",
                "modelRunId",
                "evidenceFrameRefs",
                "createdAt",
            ),
            [
                (
                    item["id"],
                    item["kind"],
                    item["label"],
                    item["description"],
                    item.get("startMs", "-"),
                    item.get("endMs", "-"),
                    _float(float(item["confidence"])),
                    item["modelRunId"],
                    ",".join(item["evidenceFrameRefs"]),
                    item["createdAt"],
                )
                for item in payload["entities"]
            ],
        )
    for order, shot in enumerate(payload["shots"], 1):
        shot_id = _safe_id(str(shot["id"]), label="source shot id")
        root = f"shots/{order * 1000:06d}--{shot_id}"
        files[
            f"{root}/time-range.txt"
        ] = f"[{shot['startMs']},{shot['endMs']})\n"
        files[f"{root}/description.md"] = (
            f"# {shot_id}\n\n{str(shot['description']).strip()}\n\n"
            f"Confidence: {_float(float(shot['confidence']))}\n"
            f"Model Run: {shot['modelRunId']}\n"
            f"Evidence: {', '.join(shot['evidenceFrameRefs'])}\n"
            f"Created At: {shot['createdAt']}\n"
        )
        files[f"{root}/events.md"] = (
            "# Events\n\n"
            + ("\n".join(f"- {event}" for event in shot["events"]) or "- None")
            + "\n"
        )
        files[f"{root}/keyframe.ref"] = str(shot["keyframeRef"])
    return dict(sorted(files.items()))


def _base_record(
    fields: Sequence[str],
    *,
    expected: int,
    kind: str,
) -> dict[str, Any]:
    if len(fields) != expected:
        raise StorageIntegrityError(
            f"Source Intelligence {kind} row field count mismatch",
            details={"expected": expected, "actual": len(fields)},
        )
    return {
        "id": _dec(fields[1]),
        "assetVersionId": _dec(fields[2]),
        "sourceChecksum": _dec(fields[3]),
        "confidence": float(fields[4]),
        "modelRunId": _dec(fields[5]),
        "evidenceFrameRefs": _dec_values(fields[6]),
        "createdAt": _dec(fields[7]),
    }


def _parse_record(fields: Sequence[str]) -> tuple[str, dict[str, Any]]:
    kind = fields[0]
    expected = {
        "shot": 13,
        "transcript": 12,
        "word": 11,
        "ocr": 11,
        "audio": 12,
        "entity": 13,
        "semantic": 12,
    }.get(kind)
    if expected is None:
        raise StorageIntegrityError(
            f"unknown Source Intelligence index row: {kind}",
        )
    record = _base_record(fields, expected=expected, kind=kind)
    if kind in {"shot", "transcript", "word", "ocr", "audio"}:
        record.update({"startMs": int(fields[8]), "endMs": int(fields[9])})
    else:
        record.update(
            {
                "startMs": None if fields[8] == "-" else int(_dec(fields[8])),
                "endMs": None if fields[9] == "-" else int(_dec(fields[9])),
            },
        )
    if kind == "shot":
        record.update(
            {
                "description": _dec(fields[10]),
                "events": _dec_values(fields[11]),
                "keyframeRef": _dec(fields[12]),
            },
        )
    elif kind == "transcript":
        record.update(
            {
                "text": _dec(fields[10]),
                "speaker": None if fields[11] == "-" else _dec(fields[11]),
            },
        )
    elif kind == "word":
        record["word"] = _dec(fields[10])
    elif kind == "ocr":
        record["text"] = _dec(fields[10])
    elif kind == "audio":
        record.update(
            {"label": _dec(fields[10]), "description": _dec(fields[11])},
        )
    elif kind == "entity":
        record.update(
            {
                "kind": _dec(fields[10]),
                "label": _dec(fields[11]),
                "description": _dec(fields[12]),
            },
        )
    else:
        record.update(
            {"text": _dec(fields[10]), "tags": _dec_values(fields[11])},
        )
    return kind, record


def parse_source_intelligence_files(
    files: Mapping[str, str],
) -> SourceIntelligenceIndex:
    """Parse and fully round-trip-validate one imported Workspace version."""

    if not _BASE_FILES.issubset(files):
        raise StorageIntegrityError(
            "Source Intelligence version is missing required files",
            details={"missing": sorted(_BASE_FILES.difference(files))},
        )
    index_lines = files["index.txt"].splitlines()
    if not index_lines or index_lines[0] != _INDEX_HEADER:
        raise StorageIntegrityError(
            "Source Intelligence index header/version is invalid",
        )
    scalars: dict[str, str] = {}
    model_runs: list[dict[str, Any]] = []
    coverage: dict[str, dict[str, Any]] = {}
    media: dict[str, Any] = {}
    records: dict[str, list[dict[str, Any]]] = {
        "shot": [],
        "transcript": [],
        "word": [],
        "ocr": [],
        "audio": [],
        "entity": [],
        "semantic": [],
    }
    for line in index_lines[1:]:
        fields = line.split("\t")
        if fields[0] in {
            "id",
            "assetId",
            "assetVersionId",
            "sourceChecksum",
            "createdAt",
        }:
            if len(fields) != 2 or fields[0] in scalars:
                raise StorageIntegrityError(
                    f"invalid or duplicate Source Intelligence scalar: {line}",
                )
            scalars[fields[0]] = _dec(fields[1])
        elif fields[0] == "modelRun":
            if len(fields) != 4:
                raise StorageIntegrityError(
                    "invalid Source Intelligence modelRun row",
                )
            model_runs.append(
                {
                    "id": _dec(fields[1]),
                    "provider": _dec(fields[2]),
                    "model": _dec(fields[3]),
                },
            )
        elif fields[0] == "coverage":
            if len(fields) != 5 or fields[1] in coverage:
                raise StorageIntegrityError(
                    "invalid or duplicate Source Intelligence coverage row",
                )
            coverage[fields[1]] = {
                "mode": fields[2],
                "producer": None if fields[3] == "-" else _dec(fields[3]),
                "ratio": None if fields[4] == "-" else float(fields[4]),
            }
        elif fields[0] == "media":
            if len(fields) != 3 or fields[1] in media:
                raise StorageIntegrityError(
                    "invalid or duplicate Source Intelligence media row",
                )
            value: Any = None if fields[2] == "-" else _dec(fields[2])
            if value is not None and fields[1] not in {
                "mediaKind",
                "mediaType",
            }:
                value = int(value)
            media[fields[1]] = value
        else:
            kind, record = _parse_record(fields)
            records[kind].append(record)
    expected_scalars = {
        "id",
        "assetId",
        "assetVersionId",
        "sourceChecksum",
        "createdAt",
    }
    if set(scalars) != expected_scalars:
        raise StorageIntegrityError(
            "Source Intelligence index identity fields are incomplete",
        )
    summary_prefix = "# Source Intelligence\n\n"
    summary_text = files["summary.md"]
    if not summary_text.startswith(
        summary_prefix,
    ) or not summary_text.endswith("\n"):
        raise StorageIntegrityError(
            "Source Intelligence summary.md does not use the canonical template",
        )
    payload = {
        **scalars,
        "modelRuns": model_runs,
        "coverage": coverage,
        "media": media,
        "summary": summary_text[len(summary_prefix) : -1],
        "shots": records["shot"],
        "transcript": records["transcript"],
        "words": records["word"],
        "ocrSegments": records["ocr"],
        "audioEvents": records["audio"],
        "entities": records["entity"],
        "semanticEntries": records["semantic"],
    }
    try:
        index = SourceIntelligenceIndex.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise StorageIntegrityError(
            f"Source Intelligence index payload is invalid: {exc}",
        ) from exc
    expected_files = render_source_intelligence_files(index)
    if set(files) != set(expected_files):
        raise StorageIntegrityError(
            "Source Intelligence version contains missing or unvalidated files",
            details={
                "missing": sorted(set(expected_files).difference(files)),
                "extra": sorted(set(files).difference(expected_files)),
            },
        )
    mismatches = sorted(
        path for path, text in expected_files.items() if files[path] != text
    )
    if mismatches:
        raise StorageIntegrityError(
            "Source Intelligence Workspace projections do not match index.txt",
            details={"paths": mismatches},
        )
    return index


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
    """Validate provider semantics, inject authoritative provenance, and freeze a version."""

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
            "Source Understanding provider output keys are not the frozen schema",
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
            "Source Understanding coverage must contain exactly visual/asr/ocr/audio",
        )
    coverage: dict[str, SourceCoverage] = {}
    for modality in _MODALITIES:
        try:
            item = SourceCoverage.model_validate(raw_coverage[modality])
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Source Understanding {modality} coverage is invalid: {exc}",
            ) from exc
        policy = dict(coverage_policy.get(modality) or {})
        if item.mode != policy.get("mode") or item.producer != policy.get(
            "producer",
        ):
            raise ValidationError(
                f"Source Understanding provider claimed unsupported {modality} coverage",
            )
        coverage[modality] = item

    provenance = set(provenance_refs)
    default_base = {
        "assetVersionId": asset_version_id,
        "sourceChecksum": source_checksum,
        "createdAt": created_at,
    }

    def records(
        key: str,
        model: type[Any],
        allowed_fields: set[str],
    ) -> list[Any]:
        values = raw.get(key)
        if not isinstance(values, list):
            raise ValidationError(
                f"Source Understanding provider {key} must be an array",
            )
        result: list[Any] = []
        seen: set[str] = set()
        for number, value in enumerate(values, 1):
            if not isinstance(value, Mapping) or not set(value).issubset(
                allowed_fields,
            ):
                raise ValidationError(
                    f"Source Understanding {key}[{number}] has invalid fields",
                )
            evidence = value.get("evidenceFrameRefs")
            if (
                not isinstance(evidence, list)
                or not evidence
                or not set(map(str, evidence)).issubset(provenance)
            ):
                raise ValidationError(
                    f"Source Understanding {key}[{number}] evidenceFrameRefs lack Runtime provenance",
                )
            record = dict(value)
            record_model_run_id = str(record.pop("modelRunId", model_run.id))
            known_model_runs = {
                model_run.id,
                *(item.id for item in additional_model_runs),
            }
            if record_model_run_id not in known_model_runs:
                raise ValidationError(
                    f"Source Understanding {key}[{number}] has unknown modelRunId",
                )
            try:
                item = model.model_validate(
                    {
                        **record,
                        **default_base,
                        "modelRunId": record_model_run_id,
                    },
                )
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Source Understanding {key}[{number}] is invalid: {exc}",
                ) from exc
            if item.id in seen:
                raise ValidationError(
                    f"Source Understanding {key} contains duplicate id: {item.id}",
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
    }
    entities = records(
        "entities",
        SourceEntity,
        optional_range | {"kind", "label", "description"},
    )
    semantic = records(
        "semanticEntries",
        SemanticIndexEntry,
        optional_range | {"text", "tags", "modelRunId"},
    )
    if coverage["visual"].mode != "available" and shots:
        raise ValidationError(
            "Source Understanding shots require available visual coverage",
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
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Source Understanding index is invalid: {exc}",
        ) from exc


__all__ = [
    "build_source_intelligence_index",
    "parse_source_intelligence_files",
    "render_source_intelligence_files",
]
