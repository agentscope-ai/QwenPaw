# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Upgrade and active model resource ownership regression checks."""

import json
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import AsyncMock

from pydantic import SecretStr

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers import model_catalog
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import ProviderManager


@pytest.mark.usefixtures(f"isolated_secret_dir")
@pytest.mark.parametrize(f"legacy", [False, True])
def test_github_models_migrates_without_changing_identity(
    legacy,
):
    manager = ProviderManager()
    provider = OpenAIProvider(
        id=f"github-models",
        name=f"GitHub Models",
        api_key=f"test-secret",
        base_url=f"https://models.github.ai/inference",
        models=[ModelInfo(id=f"openai/gpt-test", name=f"GPT Test")],
    )
    selected = ModelSlotConfig(
        provider_id=provider.id,
        model=provider.models[0].id,
    )
    if legacy:
        (manager.root_path.parent / f"providers.json").write_text(
            json.dumps(
                {
                    f"providers": {
                        provider.id: {
                            f"api_key": provider.api_key,
                            f"base_url": provider.base_url,
                            f"extra_models": [provider.models[0].model_dump()],
                        },
                    },
                    f"active_llm": selected.model_dump(),
                },
            ),
            encoding=f"utf-8",
        )
    else:
        manager._save_provider(provider, is_builtin=True)
        manager.save_active_model(selected)
    for _ in range(2):
        reloaded = ProviderManager()
        migrated = reloaded.get_provider(provider.id)
        assert migrated.is_custom
        assert migrated.api_key == provider.api_key
        assert migrated.base_url == provider.base_url
        assert migrated.get_model_info(selected.model)
        assert reloaded.get_active_model() == selected
        assert provider.id not in reloaded.builtin_providers
    assert not (manager.builtin_path / f"github-models.json").exists()


@pytest.fixture(name=f"anthropic_server")
def _anthropic_server():
    """Serve real SDK requests without coupling to its HTTP dependency."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # pylint: disable=invalid-name
            self.rfile.read(int(self.headers.get(f"Content-Length", f"0")))
            requests.append(dict(self.headers))
            body = json.dumps(
                {
                    f"id": f"msg_test",
                    f"type": f"message",
                    f"role": f"assistant",
                    f"model": f"claude-sonnet-4-5",
                    f"content": [{f"type": f"text", f"text": f"ok"}],
                    f"stop_reason": f"end_turn",
                    f"usage": {f"input_tokens": 1, f"output_tokens": 1},
                },
            ).encode()
            self.send_response(200)
            self.send_header(f"Content-Type", f"application/json")
            self.send_header(f"Content-Length", f"{len(body)}")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer((f"127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.asyncio
@pytest.mark.usefixtures(f"isolated_secret_dir")
async def test_live_anthropic_model_survives_provider_replacement(
    anthropic_server,
):
    base_url, requests = anthropic_server
    manager = ProviderManager()
    provider = manager.get_provider(f"anthropic")
    provider.auth_mode = f"auth_token"
    provider.api_key = f"test-token"
    provider.base_url = base_url
    model = provider.get_chat_model_instance(f"claude-sonnet-4-5")
    model.stream = False
    sdk = model._get_or_create_client()
    probe_transport = provider._get_strip_http_client()
    await manager.update_provider_async(provider.id, {f"name": f"Renamed"})
    assert probe_transport.is_closed
    assert not sdk.is_closed()
    await model._call_api(f"claude-sonnet-4-5", [])
    assert sdk.is_closed()
    await model._call_api(f"claude-sonnet-4-5", [])
    assert len(requests) == 2
    for headers in requests:
        normalized = {key.lower(): value for key, value in headers.items()}
        assert f"x-api-key" not in normalized
        assert normalized[f"authorization"] == f"Bearer test-token"
    assert model._qp_cached_client.is_closed()


def test_catalog_checkout_preserves_hash_with_autocrlf(tmp_path):
    root = Path(__file__).resolve().parents[3]
    relative = Path(f"src/qwenpaw/providers/data")
    shutil.copytree(
        model_catalog.PACKAGED_CATALOG_PATH.parent,
        tmp_path / relative,
    )
    shutil.copy(root / f".gitattributes", tmp_path / f".gitattributes")
    for args in (
        [f"init", f"-q"],
        [f"config", f"core.autocrlf", f"true"],
        [f"add", f"."],
    ):
        subprocess.run(
            [f"git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    shard = tmp_path / relative / f"providers/openai.json"
    shard.unlink()
    subprocess.run(
        [f"git", f"checkout-index", f"--all", f"--force"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert b"\r\n" not in shard.read_bytes()
    assert model_catalog._read_document(
        tmp_path / relative / f"index.json",
        (f"openai",),
    )


@pytest.mark.usefixtures(f"isolated_secret_dir")
async def test_anthropic_replaced_credentials_close_old_client():
    provider = ProviderManager().get_provider(f"anthropic")
    provider.api_key = f"old-key"
    model = provider.get_chat_model_instance(f"claude-sonnet-4-5")
    old = await model._request_client()
    model.credential.api_key = SecretStr(f"new-key")
    new = await model._request_client()
    assert new is not old
    assert old.is_closed()
    await new.close()


@pytest.mark.usefixtures(f"isolated_secret_dir")
async def test_anthropic_owned_stream_closes_on_consumer_exit(monkeypatch):
    provider = ProviderManager().get_provider(f"anthropic")
    provider.auth_mode = f"auth_token"
    provider.api_key = f"test-token"
    model = provider.get_chat_model_instance(f"claude-sonnet-4-5")
    client = AsyncMock()

    async def chunks(*_args):
        yield f"first"
        yield f"second"

    monkeypatch.setattr(
        model,
        f"_parse_anthropic_stream_completion_response",
        chunks,
    )
    stream = model._owned_stream(None, None, client)
    assert await anext(stream) == f"first"
    client.close.assert_not_awaited()
    await stream.aclose()
    client.close.assert_awaited_once()
