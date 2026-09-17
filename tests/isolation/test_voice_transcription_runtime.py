"""ASR snapshots, secrets, offline cache and attachment lifecycle boundaries."""

import asyncio
import base64
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request

from qwenpaw.agents.utils import audio_transcription as audio
from qwenpaw.app.routers import console
from qwenpaw.config.config import Config
from qwenpaw.providers.openai_provider import OpenAIProvider


@pytest.fixture
def remote(monkeypatch, tmp_path):
    config = Config()
    config.agents.transcription_provider_type = "whisper_api"
    config.agents.transcription_provider_id = "fake"
    provider = OpenAIProvider(
        id="fake",
        name="Fake",
        base_url="http://asr.invalid/v1",
        api_key="SYNTHETIC_KEY",
        custom_headers={"X-Secret": "SYNTHETIC_HEADER"},
    )
    manager = SimpleNamespace(
        get_provider=lambda _id: provider,
        builtin_providers={"fake": provider},
        custom_providers={},
        plugin_providers={},
    )
    monkeypatch.setattr(audio, "_get_manager", lambda: manager)
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: config)
    monkeypatch.setattr("qwenpaw.models.runtime.is_multi_user_enabled", lambda: False)
    client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(text="private transcript")
                )
            )
        ),
        close=AsyncMock(),
    )
    construct = Mock(return_value=client)
    monkeypatch.setattr("openai.AsyncOpenAI", construct)
    path = tmp_path / "sample.wav"
    path.write_bytes(b"sample")
    return SimpleNamespace(
        config=config, provider=provider, client=client, construct=construct, path=path
    )


@pytest.mark.asyncio
async def test_remote_closes_and_snapshots_headers(remote, caplog):
    caplog.set_level("DEBUG")
    assert await audio.transcribe_audio(str(remote.path)) == "private transcript"
    remote.client.close.assert_awaited_once()
    assert remote.construct.call_args.kwargs["default_headers"] == {
        "X-Secret": "SYNTHETIC_HEADER"
    }
    assert "private transcript" not in caplog.text
    assert "SYNTHETIC" not in caplog.text
    assert "asr.invalid" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["constructor", "create", "close"])
async def test_remote_failures_are_safe(remote, caplog, stage):
    caplog.set_level("DEBUG")
    error = RuntimeError("SYNTHETIC_KEY http://asr.invalid/v1 SYNTHETIC_HEADER")
    target = {
        "constructor": remote.construct,
        "create": remote.client.audio.transcriptions.create,
        "close": remote.client.close,
    }[stage]
    target.side_effect = error
    assert await audio.transcribe_audio(str(remote.path)) is None
    assert "SYNTHETIC" not in caplog.text
    assert "asr.invalid" not in caplog.text


def test_local_readiness_requires_existing_weights(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.shutil, "which", lambda _: "ffmpeg")
    loader = Mock()
    monkeypatch.setitem(
        __import__("sys").modules, "whisper", SimpleNamespace(load_model=loader)
    )
    assert hasattr(audio, "local_cache_root")
    monkeypatch.setattr(audio, "local_cache_root", lambda: tmp_path)
    status = audio.check_local_whisper_available("base")
    assert status["available"] is False
    assert status["model_ready"] is False
    loader.assert_not_called()


def test_local_models_use_cache_root_key_without_downloading(monkeypatch, tmp_path):
    assert hasattr(audio, "local_cache_root")
    root = tmp_path / "one"
    root.mkdir()
    (root / "base.pt").write_bytes(b"fake")
    (root / "tiny.pt").write_bytes(b"fake")
    loader = Mock(side_effect=lambda path, **kwargs: object())
    monkeypatch.setitem(
        __import__("sys").modules, "whisper", SimpleNamespace(load_model=loader)
    )
    monkeypatch.setattr(audio, "local_cache_root", lambda: root)
    first = audio._get_local_whisper_model("base")
    assert audio._get_local_whisper_model("base") is first
    assert audio._get_local_whisper_model("tiny") is not first
    assert loader.call_args_list[0].args[0] == str(root / "base.pt")
    with pytest.raises(Exception):
        audio._get_local_whisper_model("../../bad")
    assert loader.call_count == 2


@pytest.mark.asyncio
async def test_cancelled_local_inference_waits_for_reader(monkeypatch, tmp_path):
    started, release = threading.Event(), threading.Event()
    path = tmp_path / "sample.wav"
    path.write_bytes(b"sample")

    def read(*_args):
        started.set()
        release.wait(5)
        assert path.exists()
        return {"text": "ok"}

    monkeypatch.setattr(
        audio, "check_local_whisper_available", lambda *args: {"available": True}
    )
    monkeypatch.setattr(
        audio,
        "_get_local_whisper_model",
        lambda *args: SimpleNamespace(transcribe=read),
    )
    task = asyncio.create_task(audio._transcribe_local_whisper(str(path)))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0.02)
        assert (
            not task.done()
        ), "Cancelled task must retain the file until its worker exits"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["owner", "agent", "conversation", "deleted", "missing", "url", "path"]
)
async def test_audio_attachment_refs_reject_untrusted_scope(monkeypatch, tmp_path, bad):
    from qwenpaw.access.actor import ActorContext, ActorType
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.identity.models import PlatformRole

    user, conversation, aid = uuid4(), uuid4(), uuid4()
    path = tmp_path / "sample.wav"
    if bad != "missing":
        path.write_bytes(b"sample")
    record = SimpleNamespace(
        id=aid,
        owner_user_id=uuid4() if bad == "owner" else user,
        agent_id=agent_database_id("other" if bad == "agent" else "default"),
        conversation_id=uuid4() if bad == "conversation" else conversation,
        lifecycle="deleted" if bad == "deleted" else "temporary",
        storage_key=str(path),
    )
    repository = SimpleNamespace(get_attachment=AsyncMock(return_value=record))
    repository.with_user = lambda _: repository
    ws = SimpleNamespace(
        agent_id="default",
        chat_manager=SimpleNamespace(conversation_repository=repository),
    )
    req = Request({"type": "http", "headers": [], "app": FastAPI()})
    req.state.actor = ActorContext(
        user_id=user,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="voice",
    )
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    value = f"/api/console/attachments/{aid}"
    if bad == "url":
        value = "https://untrusted.invalid/audio.wav"
    if bad == "path":
        value = str(path)
    with pytest.raises(HTTPException) as exc:
        await console._resolve_console_attachment_refs(
            req,
            ws,
            {"content_parts": [{"type": "audio", "data": value}]},
            conversation_id=str(conversation),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_native_conversion_embeds_and_removes_only_derived_wav(
    monkeypatch, tmp_path
):
    from qwenpaw.agents.utils import message_processing as processing

    config = Config()
    config.agents.audio_mode = "native"
    monkeypatch.setattr(processing, "load_config", lambda: config)
    original, derived = tmp_path / "original.webm", tmp_path / "derived.wav"
    original.write_bytes(b"original")
    derived.write_bytes(b"wave")
    monkeypatch.setattr(processing, "_convert_audio_to_wav", lambda _: str(derived))
    block = {"type": "audio"}
    assert await processing._process_audio_block([block], 0, str(original), block)
    assert original.read_bytes() == b"original"
    assert not derived.exists()
    assert block["source"] == {
        "type": "base64",
        "data": base64.b64encode(b"wave").decode(),
        "media_type": "audio/wav",
    }


@pytest.mark.asyncio
async def test_real_sdk_transport_does_not_log_url_headers_or_text(
    remote, monkeypatch, caplog
):
    import httpx
    from openai import AsyncOpenAI

    # Reload the concrete class since the fixture patches the package attribute.
    from openai._client import AsyncOpenAI as ConcreteClient

    captured = []

    async def handle(request):
        captured.append(await request.aread())
        return httpx.Response(200, json={"text": "private transcript"})

    monkeypatch.setattr(
        "openai.AsyncOpenAI",
        lambda **kwargs: ConcreteClient(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ),
    )
    caplog.set_level("DEBUG")
    assert await audio.transcribe_audio(str(remote.path)) == "private transcript"
    assert b"sample" in captured[0]
    assert b"whisper-1" in captured[0]
    assert "SYNTHETIC" not in caplog.text
    assert "asr.invalid" not in caplog.text
    assert "private transcript" not in caplog.text


@pytest.mark.asyncio
async def test_snapshot_is_immutable_during_remote_call(remote):
    snapshot = audio.capture_snapshot()
    remote.provider.api_key = "CHANGED"
    remote.provider.custom_headers["X-Secret"] = "CHANGED"
    remote.config.agents.transcription_model = "changed"
    await audio.transcribe_snapshot(str(remote.path), snapshot)
    assert remote.construct.call_args.kwargs["api_key"] == "SYNTHETIC_KEY"
    assert (
        remote.construct.call_args.kwargs["default_headers"]["X-Secret"]
        == "SYNTHETIC_HEADER"
    )
    assert (
        remote.client.audio.transcriptions.create.call_args.kwargs["model"]
        == "whisper-1"
    )


@pytest.mark.asyncio
async def test_bound_audio_message_persists_protected_url_and_attachment_id(tmp_path):
    from qwenpaw.app.chats.run_persistence import PostgresChatRunPersistence

    persistence = PostgresChatRunPersistence(repository=object(), agent_id=uuid4())
    aid = uuid4()
    protected = f"/api/console/attachments/{aid}"
    message = persistence._user_message(
        conversation_id=uuid4(),
        run_id=uuid4(),
        initiated_by=uuid4(),
        sequence=1,
        payload={
            "content_parts": [
                {
                    "type": "audio",
                    "data": str(tmp_path / "private.wav"),
                    "attachment_url": protected,
                    "attachment_id": str(aid),
                }
            ]
        },
    )
    assert message.content["content"][0]["data"] == protected
    assert list(persistence._message_attachment_ids(message)) == [aid]


@pytest.mark.asyncio
async def test_voice_provider_and_model_deletion_are_reference_protected(monkeypatch):
    from qwenpaw.models import runtime

    config = Config()
    config.agents.transcription_provider_id = "fake"
    config.agents.transcription_model = "asr"
    monkeypatch.setattr("qwenpaw.config.utils.load_config", lambda: config)
    for model in (None, "asr"):
        with pytest.raises(ValueError, match="model_in_use: voice_transcription"):
            await runtime.require_no_model_references(
                SimpleNamespace(get_active_model=lambda: None), "fake", model
            )


@pytest.mark.asyncio
async def test_bounded_inference_rejects_fifth_request(remote):
    started = 0
    all_started, release = asyncio.Event(), asyncio.Event()

    async def waiting(**kwargs):
        nonlocal started
        started += 1
        if started == 4:
            all_started.set()
        await release.wait()
        return SimpleNamespace(text="ok")

    remote.client.audio.transcriptions.create.side_effect = waiting
    snapshot = audio.capture_snapshot()
    tasks = [
        asyncio.create_task(audio.transcribe_snapshot(str(remote.path), snapshot))
        for _ in range(4)
    ]
    try:
        await asyncio.wait_for(all_started.wait(), 3)
        with pytest.raises(audio.TranscriptionError) as exc:
            await audio.transcribe_snapshot(str(remote.path), snapshot)
        assert exc.value.code == "TRANSCRIPTION_BUSY"
    finally:
        release.set()
        await asyncio.gather(*tasks)


def test_converter_unexpected_failure_cleans_derived_file(
    monkeypatch, tmp_path, caplog
):
    from qwenpaw.agents.utils import message_processing as processing

    original = tmp_path / "original.webm"
    original.write_bytes(b"original")
    monkeypatch.setattr("shutil.which", lambda _: "ffmpeg")
    monkeypatch.setattr("subprocess.run", Mock(side_effect=OSError("SYNTHETIC_SECRET")))
    assert processing._convert_audio_to_wav(str(original)) is None
    assert list(tmp_path.iterdir()) == [original]
    assert "SYNTHETIC_SECRET" not in caplog.text
