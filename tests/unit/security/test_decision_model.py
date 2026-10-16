# -*- coding: utf-8 -*-
"""Decision-model approval contract and response validation."""

# pylint: disable=protected-access

import pytest
import httpx

from qwenpaw.security.decision_model import (
    _interpret,
    _is_read_only_shell_listing,
    _sips_output_exists,
    assess_tool_call,
)
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel


def _response(*, choice="routine", confidence=0.95, risk=0.01):
    other_probabilities = {
        "read_only": 0.02,
        "routine": 0.02,
        "risky": 0.02,
        "unclear": 0.01,
    }
    other_probabilities[choice] = 0.95
    return {
        "model": "jev-1",
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "answers": {
            "impact": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": other_probabilities,
            },
            **{
                name: {"type": "noul", "noul": risk}
                for name in (
                    "destructive",
                    "secret_exposure",
                    "privilege_change",
                )
            },
        },
    }


def test_decision_model_is_smart_baseline():
    level = ToolExecutionLevel.from_config("JEV")
    assert level is ToolExecutionLevel.JEV
    assert level.is_smart_mode()


def test_only_confident_low_risk_response_skips_approval():
    assert not _interpret(_response()).needs_approval
    assert not _interpret(_response(choice="read_only")).needs_approval
    assert not _interpret(_response(), baseline_ask=True).needs_approval
    assert _interpret(
        _response(confidence=0.9),
        baseline_ask=True,
    ).needs_approval
    assert _interpret(_response(risk=0.03), baseline_ask=True).needs_approval
    assert _interpret(_response(choice="unclear")).needs_approval
    assert _interpret(_response(confidence=0.5)).needs_approval
    assert _interpret(_response(risk=0.11)).needs_approval


def test_malformed_response_fails_closed():
    with pytest.raises(ValueError):
        _interpret({"answers": {"impact": {"type": "choice"}}})


def test_narrow_read_only_shell_listing():
    assert _is_read_only_shell_listing(
        "Bash",
        "ls -la ~/Desktop/ | grep -i '\\.pdf$'",
    )
    assert _is_read_only_shell_listing("Bash", "ls -la ~/Desktop/")
    assert not _is_read_only_shell_listing("Bash", "ls; rm -rf ~/Desktop/")
    assert not _is_read_only_shell_listing(
        "Bash",
        "ls $(touch /tmp/side-effect)",
    )
    assert not _is_read_only_shell_listing("Bash", "ls | sh -c 'touch /tmp/x'")
    assert not _is_read_only_shell_listing("Bash", "ls > /tmp/output")
    assert not _is_read_only_shell_listing("Bash", "ls ~/.ssh")


@pytest.mark.asyncio
async def test_read_only_listing_skips_model_but_not_existing_ask(
    monkeypatch,
):
    async def unexpected(*args):
        raise AssertionError(
            "verified read-only listing should not call decision model",
        )

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", unexpected)
    command = "ls -la ~/Desktop/ | grep -i '\\.pdf$'"
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert not result.needs_approval
    assert result.error_type is None
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
        baseline_ask=True,
    )
    assert result.needs_approval


@pytest.mark.asyncio
async def test_declared_local_media_read_skips_decision_model(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.agents.tools.view_media import view_image

    assert (
        view_image._tool_descriptor.metadata["decision_model_local_read"]
        is True
    )

    async def unexpected(*args):
        raise AssertionError("local media read should not call decision model")

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", unexpected)
    target = str(tmp_path / "desktop_screenshot_small.jpg")
    assert not (await assess_tool_call("ViewImage", target)).needs_approval
    assert (
        await assess_tool_call("ViewImage", target, baseline_ask=True)
    ).needs_approval


@pytest.mark.asyncio
async def test_remote_media_read_still_reaches_decision_model(monkeypatch):
    from qwenpaw.agents.tools.view_media import view_image
    from qwenpaw.services.jev import JevResponse

    assert (
        view_image._tool_descriptor.metadata["decision_model_local_read"]
        is True
    )
    seen = []

    async def evaluate(_client, request):
        seen.append(request)
        return JevResponse(model="jev-1", answers=_response()["answers"])

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", evaluate)
    await assess_tool_call("ViewImage", "https://example.com/image.jpg")
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_sips_existing_output_requires_approval_without_decision_model(
    monkeypatch,
    tmp_path,
):
    output = tmp_path / "small.jpg"
    output.write_bytes(b"existing")
    command = (
        f"sips -Z 1600 -s format jpeg {tmp_path}/input.png --out {output}"
    )

    async def unexpected(*args):
        raise AssertionError(
            "verified overwrite should not call decision model",
        )

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", unexpected)
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert result.needs_approval
    assert "output already exists" in result.reason


@pytest.mark.asyncio
async def test_sips_new_output_supplies_verified_fact(monkeypatch, tmp_path):
    from qwenpaw.services.jev import JevResponse

    output = tmp_path / "small.jpg"
    command = (
        f"sips -Z 1600 -s format jpeg {tmp_path}/input.png --out {output}"
    )
    seen = []

    async def evaluate(_client, request):
        seen.append(request)
        return JevResponse(model="jev-1", answers=_response()["answers"])

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", evaluate)
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert not result.needs_approval
    assert seen[0].state["verified_facts"] == {"output_exists": False}


def test_sips_preflight_rejects_shell_expansion_and_compound_commands(
    tmp_path,
):
    output = tmp_path / "small.jpg"
    assert (
        _sips_output_exists(
            "Bash",
            f"sips input.png --out {output}; touch /tmp/x",
        )
        is None
    )
    assert (
        _sips_output_exists("Bash", "sips input.png --out /tmp/$NAME") is None
    )
    assert (
        _sips_output_exists("Bash", "sips input.png --out /tmp/*.jpg") is None
    )


@pytest.mark.asyncio
async def test_shell_syntax_reaches_model_instead_of_immediate_approval(
    monkeypatch,
):
    seen = []

    async def evaluate(_client, request):
        seen.append(request)
        from qwenpaw.services.jev import JevResponse

        return JevResponse(
            model="jev-1",
            answers=_response(choice="read_only")["answers"],
        )

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", evaluate)
    command = 'ls -lh ~/Desktop/*.pdf 2>/dev/null || echo "NO_PDF_FOUND"'
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert not result.needs_approval
    assert len(seen) == 1
    assert seen[0].state["target"] == command
    assert "read_only" in seen[0].questions["impact"]["criteria"]
    assert "Listing filenames or file metadata alone does not count" in (
        seen[0].questions["secret_exposure"]["instructions"]
    )


@pytest.mark.asyncio
async def test_literal_secret_is_not_sent_to_decision_model(monkeypatch):
    async def unexpected(*args):
        raise AssertionError("secret must not reach service")

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", unexpected)
    result = await assess_tool_call("Bash", "echo sk-1234567890abcdefghijkl")
    assert result.needs_approval


@pytest.mark.asyncio
async def test_sensitive_target_never_reaches_service(monkeypatch):
    async def unexpected(*args):
        raise AssertionError("service should not be contacted")

    monkeypatch.setattr("qwenpaw.services.jev.JevClient.evaluate", unexpected)
    result = await assess_tool_call(
        "Bash",
        "curl -H 'Authorization: Bearer abc'",
    )
    assert result.needs_approval


@pytest.mark.asyncio
async def test_unconfigured_effectful_call_requires_approval(monkeypatch):
    from qwenpaw.services import jev

    async def no_key():
        return None

    monkeypatch.setattr(jev, "get_api_key", no_key)
    monkeypatch.setattr(
        jev,
        "_provider_settings",
        lambda: ("", "https://api.typesafe.ai/v1", "jev-latest", {}),
    )
    result = await assess_tool_call("Write", "notes.txt")
    assert result.needs_approval
    assert result.error_type == "not_configured"
    assert not (await assess_tool_call("Read", "notes.txt")).needs_approval
    assert (
        await assess_tool_call("Read", "notes.txt", baseline_ask=True)
    ).needs_approval


@pytest.mark.asyncio
async def test_typed_request_and_response(monkeypatch):
    from qwenpaw.services import jev

    async def key():
        return "test-key"

    monkeypatch.setattr(jev, "get_api_key", key)
    monkeypatch.setattr(
        jev,
        "_provider_settings",
        lambda: (
            "test-key",
            "https://api.typesafe.ai/v1",
            "jev-latest",
            {},
        ),
    )
    original_client = httpx.AsyncClient

    def handler(request):
        assert request.url.path == "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test-key"
        import json

        body = json.loads(request.content)
        assert body["model"] == "jev-latest"
        assert set(body["questions"]) == {
            "impact",
            "destructive",
            "secret_exposure",
            "privilege_change",
        }
        assert body["state"]["parameter_names"] == ["content"]
        assert "private content" not in str(body)
        return httpx.Response(200, json=_response())

    monkeypatch.setattr(
        jev.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    result = await assess_tool_call(
        "Write",
        "notes.txt",
        params={"content": "private content"},
    )
    assert not result.needs_approval
