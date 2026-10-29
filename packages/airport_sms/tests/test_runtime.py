"""运行时行为测试。"""

from __future__ import annotations

from time import perf_counter

from airport_sms.domain import Role
from airport_sms.runtime import AgentRequest, Runtime
from airport_sms.runtime.hooks import Hooks
from airport_sms.session.principal import Principal


def _principal(role: Role = Role.REPORTER) -> Principal:
    return Principal("u1", "org-a", role, "site-1")


def test_single_entry_run() -> None:
    rt = Runtime.in_memory()
    assert hasattr(rt, "run")
    assert callable(rt.run)


def test_draft_via_chat() -> None:
    rt = Runtime.in_memory()
    events = list(
        rt.run(
            AgentRequest("s1", _principal(), text="please draft hazard")
        )
    )
    case_events = [e for e in events if e.get("type") == "case"]
    assert case_events
    assert case_events[0]["state"] == "draft"


def test_submit_via_tool_ask_or_submitted() -> None:
    rt = Runtime.in_memory()
    list(rt.run(AgentRequest("s1", _principal(), text="draft now")))
    events = list(
        rt.run(AgentRequest("s1", _principal(), command="submit"))
    )
    gov = [e for e in events if e.get("type") == "governance"]
    assert gov
    assert gov[0]["action"] in {"ask", "allow", "deny"}


def test_session_reload_cursor() -> None:
    rt = Runtime.in_memory()
    list(rt.run(AgentRequest("s1", _principal(), text="draft hello")))
    list(rt.run(AgentRequest("s1", _principal(), text="follow up")))
    assert rt.store.message_count("s1") >= 2


def test_command_submit_governance_source() -> None:
    rt = Runtime.in_memory()
    list(rt.run(AgentRequest("s1", _principal(), text="draft x")))
    events = list(
        rt.run(AgentRequest("s1", _principal(), command="submit"))
    )
    gov = [e for e in events if e.get("type") == "governance"]
    assert gov and gov[0]["source"]


def test_max_iters() -> None:
    rt = Runtime.in_memory()
    events = list(
        rt.run(
            AgentRequest("s1", _principal(), text="ping", max_iters=1)
        )
    )
    assert any(e.get("type") == "max_iters" for e in events)


def test_hook_failure_fails_closed() -> None:
    rt = Runtime.in_memory()
    rt.hooks = Hooks(fail_pre=True)
    events = list(rt.run(AgentRequest("s1", _principal(), text="draft")))
    assert events[0]["type"] == "error"
    assert not any(e.get("type") == "case" for e in events)


def test_stream_delta() -> None:
    rt = Runtime.in_memory()
    events = list(rt.run(AgentRequest("s1", _principal(), text="hello")))
    assert any(e.get("type") == "delta" for e in events)


def test_finalize_once() -> None:
    rt = Runtime.in_memory()
    list(rt.run(AgentRequest("s1", _principal(), text="draft")))
    assert rt.hooks.finalize_calls == 1
    assert rt.closed == 1


def test_scheduler_source() -> None:
    rt = Runtime.in_memory()
    events = list(
        rt.run(
            AgentRequest(
                "s1",
                _principal(Role.SYSTEM),
                text="ping",
                source="scheduler",
            )
        )
    )
    assert any(e.get("source") == "scheduler" for e in events)


def test_draft_turn_p95_under_100ms() -> None:
    rt = Runtime.in_memory()
    samples = []
    for i in range(10):
        start = perf_counter()
        list(
            rt.run(
                AgentRequest(f"s{i}", _principal(), text="draft hazard")
            )
        )
        samples.append((perf_counter() - start) * 1000)
    samples.sort()
    assert samples[8] < 100, samples
