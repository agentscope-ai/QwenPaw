# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio

from models import config
from models import asr_model
from models.asr_model import _sentences


def test_fun_asr_result_normalizes_sentence_timestamps() -> None:
    result = _sentences(
        {
            "transcripts": [
                {
                    "sentences": [
                        {"begin_time": 100, "end_time": 900, "text": "欢迎使用。"},
                    ],
                },
            ],
        },
    )
    assert [(item.start_ms, item.end_ms, item.text) for item in result] == [
        (100, 900, "欢迎使用。"),
    ]


def test_fun_asr_can_reuse_llm_key(monkeypatch) -> None:
    monkeypatch.delenv("ASR_API_KEY", raising=False)
    monkeypatch.setattr(
        config,
        "_get_user_config",
        lambda: {"asr": {"enabled": True, "reuse_llm_key": True}},
    )
    monkeypatch.setattr(config, "get_text_api_key", lambda: "llm-key")
    token = config.set_request_tool_configs({})
    try:
        assert config.is_asr_enabled()
        assert config.get_asr_api_key() == "llm-key"
    finally:
        config.reset_request_tool_configs(token)


def test_fun_asr_uploads_local_media_via_dashscope_temp(
    monkeypatch,
    tmp_path,
) -> None:
    media = tmp_path / "voiceover.mp3"
    media.write_bytes(b"audio")
    observed = {}

    async def fake_upload(path, *, api_key, model_name, media_type):
        observed["call"] = (path, api_key, model_name, media_type)
        return "oss://dashscope-instant/voiceover.mp3"

    monkeypatch.setattr(
        asr_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )

    url = asyncio.run(
        asr_model._fun_asr_file_url(media.as_uri(), "asr-key", "fun-asr"),
    )

    assert url == "oss://dashscope-instant/voiceover.mp3"
    assert observed["call"] == (media, "asr-key", "fun-asr", "audio/mpeg")


def test_fun_asr_passes_public_urls_through() -> None:
    url = asyncio.run(
        asr_model._fun_asr_file_url(
            "https://cdn.test/a.mp3",
            "asr-key",
            "fun-asr",
        ),
    )

    assert url == "https://cdn.test/a.mp3"


def test_fun_asr_base_strips_token_portal_transcription_path() -> None:
    suffix = "services/audio/asr/transcription"
    assert (
        asr_model._fun_asr_base(f"https://proxy.example.com/api/v1/{suffix}")
        == "https://proxy.example.com/api/v1"
    )
    assert (
        asr_model._fun_asr_base(f"https://proxy.example.com/api/v1/{suffix}/")
        == "https://proxy.example.com/api/v1"
    )


def test_fun_asr_base_keeps_plain_api_roots() -> None:
    assert (
        asr_model._fun_asr_base(
            "https://dashscope.aliyuncs.com/api/v1",
        )
        == "https://dashscope.aliyuncs.com/api/v1"
    )
    assert (
        asr_model._fun_asr_base(
            "https://dashscope.aliyuncs.com/api/v1/",
        )
        == "https://dashscope.aliyuncs.com/api/v1"
    )


def test_whisper_posts_extracted_audio_and_normalizes_chunk_offsets(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    chunks = [tmp_path / "audio-0000.mp3", tmp_path / "audio-0001.mp3"]
    for chunk in chunks:
        chunk.write_bytes(b"audio")

    monkeypatch.setattr(config, "get_asr_api_key", lambda: "whisper-key")
    monkeypatch.setattr(config, "get_asr_model_name", lambda: "whisper-1")
    monkeypatch.setattr(config, "get_asr_language", lambda: "zh")
    monkeypatch.setattr(
        config,
        "get_asr_base_url",
        lambda: "https://api.openai.test/v1",
    )
    monkeypatch.setattr(config, "get_asr_timeout_seconds", lambda: 30)
    monkeypatch.setattr(asr_model, "_local_media_path", lambda *_args: source)
    monkeypatch.setattr(
        asr_model,
        "_extract_audio_chunks",
        lambda *_args: chunks,
    )

    requests = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"segments": [{"start": 1.25, "end": 2.5, "text": "测试语音"}]}

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url, *, headers, data, files):
            requests.append((url, headers, data, files["file"][0]))
            return Response()

    monkeypatch.setattr(asr_model.httpx, "AsyncClient", Client)

    result = asyncio.run(asr_model._whisper(source.as_uri()))

    assert [
        (item.start_ms, item.end_ms, item.text) for item in result.segments
    ] == [
        (1_250, 2_500, "测试语音"),
        (3_601_250, 3_602_500, "测试语音"),
    ]
    assert [item[0] for item in requests] == [
        "https://api.openai.test/v1/audio/transcriptions",
        "https://api.openai.test/v1/audio/transcriptions",
    ]
    assert all(
        item[2]
        == {
            "model": "whisper-1",
            "response_format": "verbose_json",
            "language": "zh",
        }
        for item in requests
    )
