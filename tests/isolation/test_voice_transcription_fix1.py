"""Review fixes: atomic disk commit, fresh merge and pre-body admission."""

import asyncio
import json
import sys
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import File, Request, UploadFile

from qwenpaw.app import voice_service as voice
from qwenpaw.config import utils
from qwenpaw.config.config import Config
from qwenpaw.agents.utils import audio_transcription as audio


@pytest.mark.parametrize("failure", ["serialize", "replace", None])
def test_atomic_save_preserves_disk_and_cache_until_commit(
    tmp_path, monkeypatch, failure
):
    path = tmp_path / "config.json"
    original = b'{"agents":{"audio_mode":"auto"}}'
    path.write_bytes(original)
    cached = Config()
    monkeypatch.setattr(utils, "_config_cache", cached)
    monkeypatch.setattr(utils, "_config_mtime", 123)
    candidate = Config()
    candidate.agents.audio_mode = "native"
    if failure == "serialize":

        def broken_dump(payload, stream, **kwargs):
            stream.write('{"partial":')
            raise OSError("synthetic disk failure")

        monkeypatch.setattr(utils.json, "dump", broken_dump)
    elif failure == "replace":
        monkeypatch.setattr(
            utils.os, "replace", Mock(side_effect=OSError("replace failed"))
        )
    if failure:
        with pytest.raises(OSError):
            utils.save_config(candidate, path)
        assert path.read_bytes() == original
        assert utils._config_cache is cached
        assert utils._config_mtime == 123
    else:
        utils.save_config(candidate, path)
        assert (
            json.loads(path.read_text(encoding="utf-8"))["agents"]["audio_mode"]
            == "native"
        )
        assert utils._config_cache is None
        assert utils._config_mtime is None
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.asyncio
async def test_save_merges_only_voice_into_latest_config_after_projection(monkeypatch):
    state = [Config()]
    previous = state[0]
    entered, release = asyncio.Event(), asyncio.Event()

    async def projection(candidate):
        entered.set()
        await release.wait()
        return {"settings": voice.settings_from_config(candidate).model_dump()}

    monkeypatch.setattr(voice, "management_view", projection)
    save = Mock()
    body = voice.settings_from_config(previous).model_dump()
    body["audio_mode"] = "native"
    task = asyncio.create_task(
        voice.save_settings(body, load=lambda: state[0], save=save)
    )
    await entered.wait()
    latest = previous.model_copy(deep=True)
    latest.agents.language = "en"
    state[0] = latest
    release.set()
    result = await task
    committed = save.call_args.args[0]
    assert committed.agents.language == "en"
    assert committed.agents.audio_mode == "native"
    assert latest.agents.audio_mode == previous.agents.audio_mode == "auto"
    assert result["settings"] == body
    save.assert_called_once()


@pytest.mark.asyncio
async def test_fifth_upload_rejected_before_body_and_slots_released(monkeypatch):
    import threading

    monkeypatch.setattr(voice, "_uploads", threading.BoundedSemaphore(4))

    async def endpoint(file: UploadFile = File(...)):
        return {"ok": True}

    route_handler = voice.VoiceUploadRoute(
        "/workspace/transcribe", endpoint, methods=["POST"]
    ).get_route_handler()

    async def handler(request):
        async with AsyncExitStack() as stack:
            for key in (
                "fastapi_middleware_astack",
                "fastapi_inner_astack",
                "fastapi_function_astack",
            ):
                request.scope[key] = stack
            return await route_handler(request)

    entered = [asyncio.Event() for _ in range(4)]
    release = asyncio.Event()

    def request(index):
        async def receive():
            entered[index].set()
            await release.wait()
            return {"type": "http.request", "body": b"", "more_body": False}

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/workspace/transcribe",
                "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
                "query_string": b"",
            },
            receive,
        )

    tasks = [asyncio.create_task(handler(request(i))) for i in range(4)]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 3)
        read = Mock(
            return_value={"type": "http.request", "body": b"", "more_body": False}
        )

        async def fifth_receive():
            return read()

        fifth = request(0)
        fifth._receive = fifth_receive
        with pytest.raises(Exception) as exc:
            await handler(fifth)
        assert getattr(exc.value, "status_code", None) == 429
        assert exc.value.detail["code"] == "TRANSCRIPTION_BUSY"
        read.assert_not_called()
    finally:
        tasks[0].cancel()
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    acquired = [voice._uploads.acquire(blocking=False) for _ in range(4)]
    assert all(acquired)
    for got in acquired:
        if got:
            voice._uploads.release()


def test_cache_evicts_replaced_version_for_same_root_and_model(monkeypatch, tmp_path):
    monkeypatch.setattr(audio, "_local_models", {})
    monkeypatch.setattr(audio, "local_cache_root", lambda: tmp_path)
    monkeypatch.setitem(
        sys.modules, "whisper", SimpleNamespace(load_model=lambda *a, **kw: object())
    )
    path = tmp_path / "base.pt"
    for size in range(1, 5):
        path.write_bytes(b"x" * size)
        audio._get_local_whisper_model("base")
    assert len(audio._local_models) == 1
    assert next(iter(audio._local_models))[-1] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        "/private/audio.wav",
        "https://untrusted.invalid/audio.wav",
        "/api/console/attachments/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ],
)
async def test_background_audio_rejected_before_run_setup(monkeypatch, source):
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from fastapi import HTTPException
    from qwenpaw.app.routers import console
    from qwenpaw.access.actor import ActorContext, ActorType
    from qwenpaw.identity.models import PlatformRole

    repository = SimpleNamespace(get_attachment=AsyncMock(return_value=None))
    repository.with_user = lambda user: repository
    channel = SimpleNamespace(resolve_session_id=lambda **kwargs: "session")
    workspace = SimpleNamespace(
        agent_id="default",
        channel_manager=SimpleNamespace(get_channel=AsyncMock(return_value=channel)),
        chat_manager=SimpleNamespace(conversation_repository=repository),
    )
    monkeypatch.setattr(
        console, "get_agent_for_request", AsyncMock(return_value=workspace)
    )
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(console, "_resolve_personal_library_references", AsyncMock())
    monkeypatch.setattr(
        console,
        "_resolve_console_chat",
        AsyncMock(return_value=SimpleNamespace(id=str(uuid4()))),
    )
    monkeypatch.setattr("qwenpaw.models.runtime.prepare_console_model", AsyncMock())
    # Any attempt to proceed to run setup proves the authorization barrier was skipped.
    next_step = AsyncMock(side_effect=AssertionError("attachment reached run setup"))
    monkeypatch.setattr(console, "_apply_session_project_dir", next_step)
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="fix1",
    )
    payload = {
        "input": [{"role": "user", "content": [{"type": "audio", "data": source}]}],
        "session_id": "session",
        "user_id": "untrusted",
        "channel": "console",
    }
    with pytest.raises(HTTPException) as exc:
        await console.post_console_chat_task(payload, request)
    assert exc.value.status_code == 404
    next_step.assert_not_awaited()
