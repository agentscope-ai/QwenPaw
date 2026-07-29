# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=subprocess-run-check
"""Normalized speech-to-text clients for Creator Source Intelligence."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from models import config
from models.media_transport import upload_local_file_to_dashscope_temp
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from utils.logger import setup_logger
from utils.paths import local_path_from_file_url
from utils.remote_download import download_remote_file

logger = setup_logger("models.asr")


@dataclass(frozen=True, slots=True)
class ASRSegment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float = 1.0
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class ASRResult:
    provider: str
    model: str
    segments: tuple[ASRSegment, ...]


def _endpoint(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def _sentences(payload: Mapping[str, Any]) -> tuple[ASRSegment, ...]:
    values: list[ASRSegment] = []
    for transcript in payload.get("transcripts") or ():
        if not isinstance(transcript, Mapping):
            continue
        sentences = transcript.get("sentences") or ()
        if not sentences and transcript.get("text"):
            duration = int(
                transcript.get("content_duration_in_milliseconds") or 1,
            )
            sentences = (
                {
                    "begin_time": 0,
                    "end_time": duration,
                    "text": transcript["text"],
                },
            )
        for sentence in sentences:
            if not isinstance(sentence, Mapping):
                continue
            text = str(sentence.get("text") or "").strip()
            start = int(sentence.get("begin_time") or 0)
            end = int(sentence.get("end_time") or start + 1)
            if text and end > start:
                values.append(
                    ASRSegment(
                        start,
                        end,
                        text,
                        speaker=str(sentence.get("speaker_id") or "") or None,
                    ),
                )
    return tuple(values)


async def _fun_asr_file_url(media_url: str, api_key: str, model: str) -> str:
    """Return a URL Fun-ASR can fetch, uploading local media when needed.

    Local files go through DashScope's official model-bound temporary upload
    (48h TTL) and come back as ``oss://`` URLs which the transcription API
    resolves via the ``X-DashScope-OssResourceResolve: enable`` header.
    """
    parsed = urlparse(media_url)
    if parsed.scheme == "file":
        local_path = local_path_from_file_url(media_url)
        media_type = (
            mimetypes.guess_type(local_path.name)[0]
            or "application/octet-stream"
        )
        return await upload_local_file_to_dashscope_temp(
            local_path,
            api_key=api_key,
            model_name=model,
            media_type=media_type,
        )
    if parsed.scheme in {"http", "https"}:
        return media_url
    raise ValueError(
        "Fun-ASR input must be a local file or HTTP(S) media URL",
    )


async def _fun_asr(media_url: str) -> ASRResult:
    base = config.get_asr_base_url()
    key = config.get_asr_api_key()
    model = config.get_asr_model_name() or "fun-asr"
    if not key:
        raise ValueError(
            "Fun-ASR requires ASR API key or enabled LLM key reuse",
        )
    file_url = await _fun_asr_file_url(media_url, key, model)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        "X-DashScope-OssResourceResolve": "enable",
    }
    timeout = config.get_asr_timeout_seconds()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60)) as client:
        response = await client.post(
            _endpoint(base, "services/audio/asr/transcription"),
            headers=headers,
            json={
                "model": model,
                "input": {"file_urls": [file_url]},
                "parameters": {},
            },
        )
        response.raise_for_status()
        task_id = str(response.json().get("output", {}).get("task_id") or "")
        if not task_id:
            raise RuntimeError("Fun-ASR submit response has no task_id")
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Fun-ASR task {task_id} timed out")
            await asyncio.sleep(2)
            status_response = await client.get(
                _endpoint(base, f"tasks/{task_id}"),
                headers={"Authorization": f"Bearer {key}"},
            )
            status_response.raise_for_status()
            output = status_response.json().get("output", {})
            status = str(output.get("task_status") or "")
            if status in {"PENDING", "RUNNING"}:
                continue
            results = output.get("results") or ()
            succeeded = next(
                (
                    item
                    for item in results
                    if isinstance(item, Mapping)
                    and item.get("subtask_status") == "SUCCEEDED"
                ),
                None,
            )
            if status != "SUCCEEDED" or not succeeded:
                raise RuntimeError(f"Fun-ASR failed: {output}")
            with tempfile.TemporaryDirectory(
                prefix="creator-fun-asr-",
            ) as directory:
                result_path = Path(directory) / "transcription.json"
                await asyncio.to_thread(
                    download_remote_file,
                    str(succeeded["transcription_url"]),
                    str(result_path),
                )
                result_payload = json.loads(
                    result_path.read_text(encoding="utf-8"),
                )
            segments = _sentences(result_payload)
            result = ASRResult("dashscope", model, segments)
            logger.info(
                "Fun-ASR completed: %d segments from model=%s",
                len(segments),
                model,
            )
            for seg in segments:
                logger.debug(
                    "  [%d-%d] %s",
                    seg.start_ms,
                    seg.end_ms,
                    seg.text,
                )
            return result


def _local_media_path(media_url: str, directory: Path) -> Path:
    parsed = urlparse(media_url)
    if parsed.scheme == "file":
        return local_path_from_file_url(media_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "Whisper input must be a local file or HTTP(S) media URL",
        )
    target = directory / "source-media"
    download_remote_file(media_url, str(target))
    return target


def _extract_audio_chunks(source: Path, directory: Path) -> list[Path]:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required for Whisper audio extraction; set "
            "CREATOR_FFMPEG_PATH, install ffmpeg, or install imageio-ffmpeg",
        )
    pattern = directory / "audio-%04d.mp3"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "32k",
        "-f",
        "segment",
        "-segment_time",
        "3600",
        "-reset_timestamps",
        "1",
        str(pattern),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed: {(result.stderr or result.stdout)[-500:]}",
        )
    chunks = sorted(directory.glob("audio-*.mp3"))
    if not chunks or any(
        path.stat().st_size >= 25 * 1024 * 1024 for path in chunks
    ):
        raise RuntimeError(
            "Whisper audio extraction did not produce <25 MB chunks",
        )
    return chunks


async def _whisper(media_url: str) -> ASRResult:
    key = config.get_asr_api_key()
    model = config.get_asr_model_name() or "whisper-1"
    if not key:
        raise ValueError("Whisper requires an ASR API key")
    language = config.get_asr_language().strip()
    headers = {"Authorization": f"Bearer {key}"}
    normalized: list[ASRSegment] = []
    with tempfile.TemporaryDirectory(prefix="creator-asr-") as raw_directory:
        directory = Path(raw_directory)
        source = await asyncio.to_thread(
            _local_media_path,
            media_url,
            directory,
        )
        chunks = await asyncio.to_thread(
            _extract_audio_chunks,
            source,
            directory,
        )
        async with httpx.AsyncClient(
            timeout=config.get_asr_timeout_seconds(),
        ) as client:
            for index, chunk in enumerate(chunks):
                data = {"model": model, "response_format": "verbose_json"}
                if language:
                    data["language"] = language
                with chunk.open("rb") as handle:
                    response = await client.post(
                        _endpoint(
                            config.get_asr_base_url(),
                            "audio/transcriptions",
                        ),
                        headers=headers,
                        data=data,
                        files={"file": (chunk.name, handle, "audio/mpeg")},
                    )
                response.raise_for_status()
                offset = index * 3_600_000
                for raw in response.json().get("segments") or ():
                    text = str(raw.get("text") or "").strip()
                    start = offset + round(float(raw.get("start") or 0) * 1000)
                    end = offset + round(float(raw.get("end") or 0) * 1000)
                    if text and end > start:
                        normalized.append(ASRSegment(start, end, text))
    result = ASRResult("openai", model, tuple(normalized))
    logger.info(
        "Whisper completed: %d segments from model=%s",
        len(normalized),
        model,
    )
    for seg in normalized:
        logger.debug(
            "  [%d-%d] %s",
            seg.start_ms,
            seg.end_ms,
            seg.text,
        )
    return result


async def transcribe(media_url: str) -> ASRResult:
    provider = config.get_asr_provider()
    logger.info(
        "ASR transcribe started: provider=%s url=%s",
        provider,
        media_url[:120],
    )
    if provider == "whisper":
        return await _whisper(media_url)
    return await _fun_asr(media_url)


__all__ = ["ASRResult", "ASRSegment", "transcribe"]
