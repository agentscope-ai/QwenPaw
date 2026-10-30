# -*- coding: utf-8 -*-
"""Ollama CLI selection through the real SDK, HTTP, and provider storage."""
# pylint: disable=redefined-outer-name

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from click.testing import CliRunner
import pytest

from qwenpaw.cli import providers_cmd
from qwenpaw.exceptions import ModelNotFoundException
from qwenpaw.providers import model_catalog
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.provider_manager import ProviderManager


@pytest.fixture
def ollama_endpoint():
    state = {"status": 200, "models": ["qwen3:32b"], "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # pylint: disable=invalid-name
            state["requests"].append(
                (self.path, self.headers.get("Authorization")),
            )
            payload = {
                "object": "list",
                "data": [
                    {"id": name, "object": "model", "created": 0}
                    for name in state["models"]
                ],
            }
            if state["status"] != 200:
                payload = {"error": {"message": "Ollama access denied"}}
            body = json.dumps(payload).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        state["url"] = f"http://127.0.0.1:{server.server_port}/ollama-proxy/v1"
        try:
            yield state
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def manager(monkeypatch, tmp_path, ollama_endpoint):
    monkeypatch.setenv("QWENPAW_DISABLE_KEYRING", "1")
    for name in (
        "METADATA_CACHE_PATH",
        "OTA_CATALOG_PATH",
        "LOCAL_CATALOG_PATH",
    ):
        monkeypatch.setattr(model_catalog, name, tmp_path / f"{name}.json")
    instance = ProviderManager.get_instance()
    instance.update_provider(
        "ollama",
        {
            "base_url": ollama_endpoint["url"],
            "custom_headers": {"Authorization": "Bearer test-ollama-key"},
        },
    )
    # Only replace human choices. SDK, discovery, activation and disk I/O
    # remain the actual production implementations.
    monkeypatch.setattr(
        providers_cmd,
        "prompt_choice",
        lambda _question, options, default=None: next(
            (option for option in options if option.startswith("Ollama (")),
            options[0],
        ),
    )
    return instance


@pytest.mark.parametrize("command", ["set-llm", "config"])
def test_discovers_and_persists_selected_ollama_model(
    manager,
    ollama_endpoint,
    command,
):
    assert manager.get_provider("ollama").all_models() == []
    ollama_endpoint["models"] = ["qwen3:32b", "qwen3.5:9b"]
    result = CliRunner().invoke(
        providers_cmd.models_group,
        [command],
        input="\n",
    )
    assert result.exit_code == 0, result.output
    assert ollama_endpoint["requests"] == [
        ("/ollama-proxy/v1/models", "Bearer test-ollama-key"),
    ]
    reloaded = ProviderManager()
    assert reloaded.get_active_model().provider_id == "ollama"
    assert reloaded.get_active_model().model == "qwen3:32b"
    assert [m.id for m in reloaded.get_provider("ollama").all_models()] == [
        "qwen3:32b",
    ]
    with pytest.raises(ModelNotFoundException):
        asyncio.run(reloaded.activate_model("ollama", "missing-model"))


@pytest.mark.parametrize("status, models", [(200, []), (401, ["qwen3:32b"])])
def test_discovery_failure_preserves_active_model(
    manager,
    ollama_endpoint,
    status,
    models,
):
    asyncio.run(
        manager.add_model_to_provider(
            "ollama",
            ModelInfo(
                id="old-model",
                name="Existing",
                supports_multimodal=False,
            ),
        ),
    )
    asyncio.run(manager.activate_model("ollama", "old-model"))
    original = manager.get_active_model()
    ollama_endpoint.update(status=status, models=models)
    result = CliRunner().invoke(
        providers_cmd.models_group,
        ["set-llm"],
        input="qwen3:32b\n",
    )
    assert result.exit_code == 1
    assert ollama_endpoint["requests"]
    assert "Ollama" in result.output
    assert ProviderManager().get_active_model() == original
    assert [m.id for m in manager.get_provider("ollama").all_models()] == [
        "old-model",
    ]


def test_selection_preserves_configured_model_metadata(
    manager,
    ollama_endpoint,
):
    asyncio.run(
        manager.add_model_to_provider(
            "ollama",
            ModelInfo(
                id="qwen3:32b",
                name="My Qwen",
                max_input_length=12345,
                supports_image=False,
            ),
        ),
    )
    result = CliRunner().invoke(providers_cmd.models_group, ["set-llm"])
    assert result.exit_code == 0, result.output
    assert ollama_endpoint["requests"]
    model = (
        ProviderManager().get_provider("ollama").get_model_info("qwen3:32b")
    )
    assert model.name == "My Qwen"
    assert model.max_input_length == 12345
    assert model.supports_image is False


def test_defaults_do_not_discover_ollama_models(manager, ollama_endpoint):
    provider = manager.get_provider("ollama")
    assert (
        providers_cmd._select_llm_model(  # pylint: disable=protected-access
            provider,
            "ollama",
            None,
            use_defaults=True,
        )
        == ""
    )
    asyncio.run(
        manager.add_model_to_provider(
            "ollama",
            ModelInfo(
                id="old-model",
                name="Existing",
                supports_multimodal=False,
            ),
        ),
    )
    asyncio.run(manager.activate_model("ollama", "old-model"))
    assert (
        providers_cmd._select_llm_model(  # pylint: disable=protected-access
            manager.get_provider("ollama"),
            "ollama",
            manager.get_active_model(),
            use_defaults=True,
        )
        == "old-model"
    )
    assert ollama_endpoint["requests"] == []
