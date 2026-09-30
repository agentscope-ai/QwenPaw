# -*- coding: utf-8 -*-
from __future__ import annotations

from click.testing import CliRunner

from qwenpaw.cli.main import cli


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class DummyClient:
    def __init__(
        self,
        responses: dict[tuple[str, str], DummyResponse],
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def __enter__(self) -> DummyClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, path: str, params: dict | None = None):
        self.calls.append(("GET", path, params, None))
        return self.responses[("GET", path)]

    def put(
        self,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ):
        self.calls.append(("PUT", path, params, json))
        return self.responses[("PUT", path)]


def test_models_routing_get_json(monkeypatch) -> None:
    dummy = DummyClient(
        {
            (
                "GET",
                "/config/agents/llm-routing",
            ): DummyResponse(
                {
                    "enabled": True,
                    "mode": "cloud_first",
                    "local": {
                        "provider_id": "openclaw-local",
                        "model": "Kimi K2.5",
                    },
                    "cloud": {
                        "provider_id": "opencode",
                        "model": "nemotron-3-super-free",
                    },
                },
            ),
        },
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd.http_client",
        lambda _base_url: dummy,
    )

    result = CliRunner().invoke(
        cli,
        [
            "models",
            "routing",
            "get",
            "--agent-id",
            "agent-1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"mode": "cloud_first"' in result.output
    assert dummy.calls == [
        (
            "GET",
            "/config/agents/llm-routing",
            {"agent_id": "agent-1"},
            None,
        ),
    ]


def test_models_routing_set_sends_expected_body(monkeypatch) -> None:
    dummy = DummyClient(
        {
            (
                "PUT",
                "/config/agents/llm-routing",
            ): DummyResponse(
                {
                    "enabled": True,
                    "mode": "local_first",
                    "local": {
                        "provider_id": "openclaw-local",
                        "model": "Kimi K2.5",
                    },
                    "cloud": {
                        "provider_id": "opencode",
                        "model": "nemotron-3-super-free",
                    },
                },
            ),
        },
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd.http_client",
        lambda _base_url: dummy,
    )

    result = CliRunner().invoke(
        cli,
        [
            "models",
            "routing",
            "set",
            "--mode",
            "local_first",
            "--local-provider",
            "openclaw-local",
            "--local-model",
            "Kimi K2.5",
            "--cloud-provider",
            "opencode",
            "--cloud-model",
            "nemotron-3-super-free",
            "--agent-id",
            "agent-1",
        ],
    )

    assert result.exit_code == 0
    assert "Enabled : True" in result.output
    assert dummy.calls == [
        (
            "PUT",
            "/config/agents/llm-routing",
            {"agent_id": "agent-1"},
            {
                "enabled": True,
                "mode": "local_first",
                "local": {
                    "provider_id": "openclaw-local",
                    "model": "Kimi K2.5",
                },
                "cloud": {
                    "provider_id": "opencode",
                    "model": "nemotron-3-super-free",
                },
            },
        ),
    ]


def test_models_routing_disable_preserves_current_slots(monkeypatch) -> None:
    dummy = DummyClient(
        {
            (
                "GET",
                "/config/agents/llm-routing",
            ): DummyResponse(
                {
                    "enabled": True,
                    "mode": "cloud_first",
                    "local": {
                        "provider_id": "openclaw-local",
                        "model": "Kimi K2.5",
                    },
                    "cloud": {
                        "provider_id": "opencode",
                        "model": "nemotron-3-super-free",
                    },
                },
            ),
            (
                "PUT",
                "/config/agents/llm-routing",
            ): DummyResponse(
                {
                    "enabled": False,
                    "mode": "cloud_first",
                    "local": {
                        "provider_id": "openclaw-local",
                        "model": "Kimi K2.5",
                    },
                    "cloud": {
                        "provider_id": "opencode",
                        "model": "nemotron-3-super-free",
                    },
                },
            ),
        },
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd.http_client",
        lambda _base_url: dummy,
    )

    result = CliRunner().invoke(
        cli,
        ["models", "routing", "disable"],
    )

    assert result.exit_code == 0
    assert "Enabled : False" in result.output
    assert dummy.calls == [
        ("GET", "/config/agents/llm-routing", None, None),
        (
            "PUT",
            "/config/agents/llm-routing",
            None,
            {
                "enabled": False,
                "mode": "cloud_first",
                "local": {
                    "provider_id": "openclaw-local",
                    "model": "Kimi K2.5",
                },
                "cloud": {
                    "provider_id": "opencode",
                    "model": "nemotron-3-super-free",
                },
            },
        ),
    ]


def test_models_routing_set_requires_complete_cloud_pair() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "models",
            "routing",
            "set",
            "--mode",
            "local_first",
            "--local-provider",
            "openclaw-local",
            "--local-model",
            "Kimi K2.5",
            "--cloud-provider",
            "opencode",
        ],
    )

    assert result.exit_code != 0
    assert "Provide both --cloud-provider and --cloud-model together." in (
        result.output
    )
