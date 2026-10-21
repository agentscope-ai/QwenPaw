# -*- coding: utf-8 -*-
"""Decision-model approval contract and response validation."""

# pylint: disable=protected-access

import json
from types import SimpleNamespace

import httpx2
import pytest
from agentscope.classifier import (
    BinaryAnswer,
    ChoiceAnswer,
    ClassifierResponse,
    RefusalAnswer,
)

from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.typesafe_provider import TypeSafeProvider
from qwenpaw.security.decision_model import (
    _decision_provider,
    _interpret,
    _is_read_only_shell_listing,
    _sips_output_exists,
    assess_tool_call,
)
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel


@pytest.fixture(name="typesafe_provider", autouse=True)
def configured_typesafe_provider(monkeypatch):
    provider = TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        base_url="https://api.typesafe.ai",
        api_key="test-key",
    )
    manager = SimpleNamespace(
        get_provider=lambda provider_id: (
            provider if provider_id == "typesafe" else None
        ),
        default_models={},
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    return provider


def _probabilities(choice):
    probabilities = {
        "read_only": 0.02,
        "routine": 0.02,
        "risky": 0.02,
        "unclear": 0.01,
    }
    probabilities[choice] = 0.95
    return probabilities


_RISK_QUESTIONS = ("destructive", "secret_exposure", "privilege_change")


def _response(*, choice="routine", confidence=0.95, risk=0.01):
    return ClassifierResponse(
        model="jev-1",
        content={
            "impact": ChoiceAnswer(
                choice=choice,
                confidence=confidence,
                probabilities=_probabilities(choice),
            ),
            **{
                name: BinaryAnswer(probability=risk)
                for name in _RISK_QUESTIONS
            },
        },
    )


def _wire_response(*, choice="routine", confidence=0.95, risk=0.01):
    """The System One JSON body equivalent to :func:`_response`."""
    return {
        "model": "jev-1",
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "answers": {
            "impact": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": _probabilities(choice),
            },
            **{
                name: {"type": "noul", "noul": risk}
                for name in _RISK_QUESTIONS
            },
        },
    }


def test_decision_model_is_smart_baseline():
    level = ToolExecutionLevel.from_config("JEV")
    assert level is ToolExecutionLevel.JEV
    assert level.is_smart_mode()


def test_selected_decision_model_comes_from_provider_manager(
    monkeypatch,
    typesafe_provider,
):
    manager = SimpleNamespace(
        get_provider=lambda provider_id: (
            typesafe_provider if provider_id == "typesafe" else None
        ),
        default_models={
            "decision": SimpleNamespace(provider_id="typesafe", model="jev-2"),
        },
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    assert _decision_provider() == (typesafe_provider, "jev-2")


def test_agent_decision_model_takes_priority_over_global(
    monkeypatch,
    typesafe_provider,
):
    manager = SimpleNamespace(
        get_provider=lambda provider_id: (
            typesafe_provider if provider_id == "typesafe" else None
        ),
        default_models={
            "decision": SimpleNamespace(provider_id="typesafe", model="jev-b"),
        },
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda agent_id: SimpleNamespace(
            decision_model=SimpleNamespace(
                provider_id="typesafe",
                model="jev-a",
            ),
        ),
    )
    assert _decision_provider("agent-a") == (typesafe_provider, "jev-a")


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
    refused = _response()
    refused.content["destructive"] = RefusalAnswer()
    with pytest.raises(ValueError):
        _interpret(refused)
    partial = _response()
    partial.content["impact"].probabilities.pop("unclear")
    with pytest.raises(ValueError):
        _interpret(partial)
    out_of_range = _response(risk=1.5)
    with pytest.raises(ValueError):
        _interpret(out_of_range)


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
    assert not _is_read_only_shell_listing(
        "Bash",
        "ls /missing || cp replacement.txt important.txt",
    )
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

    monkeypatch.setattr(TypeSafeProvider, "evaluate", unexpected)
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
async def test_target_free_builtin_read_skips_model_but_not_existing_ask(
    monkeypatch,
):
    from qwenpaw.agents.tools.get_current_time import get_current_time
    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )
    from qwenpaw.agents.context.visual_compression.runtime.recall_tool import (
        make_recall_context_tool,
    )

    assert (
        get_current_time._tool_descriptor.metadata[
            "decision_model_no_target_read"
        ]
        is True
    )

    async def unexpected(*args):
        raise AssertionError("target-free read must not call decision model")

    monkeypatch.setattr(TypeSafeProvider, "evaluate", unexpected)
    assert not (
        await assess_tool_call(
            "GetCurrentTime",
            "",
            tool_func=get_current_time,
        )
    ).needs_approval
    assert not (
        await assess_tool_call(
            "MemorySearch",
            "",
            tool_func=ReMeLightMemoryManager.memory_search,
        )
    ).needs_approval
    assert not (
        await assess_tool_call(
            "RecallContext",
            "",
            tool_func=make_recall_context_tool(),
        )
    ).needs_approval
    assert (
        await assess_tool_call(
            "GetCurrentTime",
            "",
            tool_func=get_current_time,
            baseline_ask=True,
        )
    ).needs_approval
    assert (
        await assess_tool_call(
            "MemorySearch",
            "",
            tool_func=ReMeLightMemoryManager.memory_search,
            baseline_ask=True,
        )
    ).needs_approval
    assert (await assess_tool_call("MemorySearch", "")).needs_approval
    assert (await assess_tool_call("GetCurrentTime", "")).needs_approval

    async def memory_search():
        return None

    assert (
        await assess_tool_call("MemorySearch", "", tool_func=memory_search)
    ).needs_approval
    assert (await assess_tool_call("OtherTool", "")).needs_approval


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

    monkeypatch.setattr(TypeSafeProvider, "evaluate", unexpected)
    target = str(tmp_path / "desktop_screenshot_small.jpg")
    assert not (await assess_tool_call("ViewImage", target)).needs_approval
    assert (
        await assess_tool_call("ViewImage", target, baseline_ask=True)
    ).needs_approval


@pytest.mark.asyncio
async def test_remote_media_read_still_reaches_decision_model(monkeypatch):
    from qwenpaw.agents.tools.view_media import view_image

    assert (
        view_image._tool_descriptor.metadata["decision_model_local_read"]
        is True
    )
    seen = []

    async def evaluate(_provider, **request):
        seen.append(request)
        return _response()

    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
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

    monkeypatch.setattr(TypeSafeProvider, "evaluate", unexpected)
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert result.needs_approval
    assert "output already exists" in result.reason


@pytest.mark.asyncio
async def test_sips_new_output_supplies_verified_fact(monkeypatch, tmp_path):
    output = tmp_path / "small.jpg"
    command = (
        f"sips -Z 1600 -s format jpeg {tmp_path}/input.png --out {output}"
    )
    seen = []

    async def evaluate(_provider, **request):
        seen.append(request)
        return _response()

    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert not result.needs_approval
    assert seen[0]["state"]["verified_facts"] == {"output_exists": False}


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

    async def evaluate(_provider, **request):
        seen.append(request)
        return _response(choice="read_only")

    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
    command = 'ls -lh ~/Desktop/*.pdf 2>/dev/null || echo "NO_PDF_FOUND"'
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert not result.needs_approval
    assert len(seen) == 1
    assert seen[0]["state"]["target"] == command
    assert "read_only" in seen[0]["questions"]["impact"].criteria
    assert "Listing filenames or file metadata alone does not count" in (
        seen[0]["questions"]["secret_exposure"].instructions
    )


@pytest.mark.asyncio
async def test_shell_or_command_is_not_skipped_as_read_only(monkeypatch):
    seen = []

    async def evaluate(_provider, **request):
        seen.append(request)
        return _response(choice="risky")

    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
    command = "ls /missing || cp replacement.txt important.txt"
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert result.needs_approval
    assert seen[0]["state"]["target"] == command


@pytest.mark.asyncio
async def test_shell_command_is_available_to_decision_model(monkeypatch):
    seen = []

    async def evaluate(_provider, **request):
        seen.append(request)
        return _response()

    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
    command = "printf 'Quarterly revenue is 123456'"
    await assess_tool_call("Bash", command, params={"command": command})
    state = seen[0]["state"]
    assert state["target"] == command
    assert state["parameter_names"] == ["command"]


@pytest.mark.asyncio
async def test_shell_write_is_available_to_decision_model(
    monkeypatch,
):
    seen = []

    async def evaluate(_provider, **request):
        seen.append(request)
        return _response(choice="risky")

    monkeypatch.setattr(TypeSafeProvider, "evaluate", evaluate)
    command = "printf 'Quarterly revenue is 123456' > report.txt"
    result = await assess_tool_call(
        "Bash",
        command,
        params={"command": command},
    )
    assert result.needs_approval
    assert seen[0]["state"]["target"] == command
    assert (await assess_tool_call("Bash", "cp a.txt b.txt")).needs_approval
    assert seen[1]["state"]["target"] == "cp a.txt b.txt"


@pytest.mark.asyncio
async def test_literal_secret_is_not_sent_to_decision_model(monkeypatch):
    async def unexpected(*args):
        raise AssertionError("secret must not reach service")

    monkeypatch.setattr(TypeSafeProvider, "evaluate", unexpected)
    result = await assess_tool_call("Bash", "echo sk-1234567890abcdefghijkl")
    assert result.needs_approval


@pytest.mark.asyncio
async def test_sensitive_target_never_reaches_service(monkeypatch):
    async def unexpected(*args):
        raise AssertionError("service should not be contacted")

    monkeypatch.setattr(TypeSafeProvider, "evaluate", unexpected)
    result = await assess_tool_call(
        "Bash",
        "curl -H 'Authorization: Bearer abc'",
    )
    assert result.needs_approval


@pytest.mark.asyncio
async def test_unconfigured_effectful_call_requires_approval(
    typesafe_provider,
):
    typesafe_provider.api_key = ""
    result = await assess_tool_call("Write", "notes.txt")
    assert result.needs_approval
    assert result.error_type == "not_configured"
    assert not (await assess_tool_call("Read", "notes.txt")).needs_approval
    assert (
        await assess_tool_call("Read", "notes.txt", baseline_ask=True)
    ).needs_approval


@pytest.mark.asyncio
async def test_typed_request_and_response(mock_typesafe):
    def handler(request):
        assert request.url.path == "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "jev-latest"
        assert set(body["questions"]) == {
            "impact",
            "destructive",
            "secret_exposure",
            "privilege_change",
        }
        assert body["state"]["parameter_names"] == ["content"]
        assert body["state"]["target"] == "notes.txt"
        assert "private content" not in str(body)
        return httpx2.Response(200, json=_wire_response())

    mock_typesafe(handler)
    result = await assess_tool_call(
        "Write",
        "notes.txt",
        params={"content": "private content"},
    )
    assert not result.needs_approval
