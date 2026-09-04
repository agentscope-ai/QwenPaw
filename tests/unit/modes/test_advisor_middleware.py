# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,redefined-outer-name
"""Tests for AdvisorMiddleware: opening plan, mid-run intervention, the
request-in-flight injection, and transcript persistence."""
from __future__ import annotations

import json

import pytest
from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
    UserMsg,
)

from qwenpaw.modes.advisor.middleware import (
    CONSULT_BUDGET_EXHAUSTED,
    DEFAULT_MAX_CONSULTS,
    FOLLOWUP_TOOL_NAME,
    PLAN_TOOL_NAME,
    AdvisorMiddleware,
    _FOLLOWUP_CALL_ARGS,
    _PLAN_CALL_ARGS,
    _clip,
    _format_recent,
    _parse_followup,
    _result_text,
    _workspace_listing,
)
from qwenpaw.modes.advisor.trigger import (
    InterventionTrigger,
    ObservedStep,
    TriggerConfig,
)

FAIL = "Command failed with exit code 1."
OK = "done"


class _State:
    def __init__(self):
        self.context = []


class _Agent:
    name = "test-agent"

    def __init__(self):
        self.state = _State()


class _Advisor:
    """Scripted advisor: replies come from ``replies`` in order (an
    Exception entry raises); the last entry repeats."""

    label = "stub:advisor"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def ask(self, messages, *, on_text=None):
        self.calls.append(messages)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        if on_text is not None:
            # Stream it the way providers do: cumulative text per chunk.
            step = max(1, len(reply) // 3)
            for end in range(step, len(reply), step):
                on_text(reply[:end])
            on_text(reply)
        return reply


def make_mw(
    replies=("ADJUST\nStop retrying that; take another route.",),
    *,
    log_dir=None,
    **trigger_kw,
):
    """A middleware past the opening plan, with a scripted advisor."""
    cfg = TriggerConfig(
        consecutive_failures=3,
        window_size=10,
        window_failures=4,
        **trigger_kw,
    )
    advisor = _Advisor(replies)
    mw = AdvisorMiddleware(
        advisor=advisor,
        trigger=InterventionTrigger(config=cfg),
        log_dir=log_dir,
        session_id="sess-1",
        agent_id="agent-1",
    )
    mw._plan_injected = True
    mw._baselined = True  # already past the first model call of the turn
    mw.advisor = advisor
    return mw


def add_result(agent, tool, args, output, call_id=None):
    """Append one finished tool call (call + result) as plain dict blocks,
    the shape the trigger scan must accept alongside pydantic blocks."""
    call_id = call_id or f"c{len(agent.state.context)}"
    agent.state.context.append(
        type(
            "Msg",
            (),
            {
                "content": [
                    {
                        "type": "tool_call",
                        "id": call_id,
                        "name": tool,
                        "input": json.dumps(args),
                    },
                    {
                        "type": "tool_result",
                        "id": call_id,
                        "name": tool,
                        "output": output,
                    },
                ],
            },
        )(),
    )


def followups(agent):
    return [
        block
        for msg in agent.state.context
        for block in getattr(msg, "content", [])
        if not isinstance(block, dict)
        and getattr(block, "name", None) == FOLLOWUP_TOOL_NAME
        and getattr(block, "type", None) == "tool_result"
    ]


async def _next_handler(**kwargs):
    return kwargs


def _fail_n(agent, n):
    for i in range(n):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)


# ── triggering ──────────────────────────────────────────────────────────


async def test_no_intervention_while_healthy():
    mw, agent = make_mw(), _Agent()
    for i in range(6):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, OK)
        await mw._check_and_intervene(agent)
    assert not mw.advisor.calls
    assert followups(agent) == []


async def test_intervenes_after_consecutive_failures():
    mw, agent = make_mw(), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 1
    assert len(followups(agent)) == 1


async def test_advice_is_injected_where_the_agent_can_see_it():
    mw, agent = make_mw(), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    block = followups(agent)[0]
    assert block.output == "Stop retrying that; take another route."
    assert agent.state.context[-1].content[0].name == FOLLOWUP_TOOL_NAME


async def test_on_model_call_adds_followup_to_the_request_in_flight():
    """``messages`` is built before the hook runs, so the advice must be
    appended to the outgoing request too — not only to the context."""
    mw, agent = make_mw(), _Agent()
    _fail_n(agent, 3)
    messages = ["system", *agent.state.context]
    out = await mw.on_model_call(
        agent,
        {"messages": messages, "tools": []},
        _next_handler,
    )
    assert len(followups(agent)) == 1
    assert out["messages"][-1] is agent.state.context[-1]
    assert out["messages"][-1] not in messages, "original list untouched"


async def test_followup_can_be_disabled():
    mw = AdvisorMiddleware(
        advisor=_Advisor(["ADJUST\nx"]),
        followup_enabled=False,
    )
    mw._plan_injected = True
    agent = _Agent()
    for i in range(6):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert mw.followup_enabled is False
    assert followups(agent) == []


# ── statefulness ────────────────────────────────────────────────────────


async def test_followups_are_stateful_and_accumulate():
    mw = make_mw(max_interventions=5)
    agent = _Agent()
    mw._advisor_history = [
        {"role": "user", "content": "plan req"},
        {"role": "assistant", "content": "the plan"},
    ]
    for i in range(9):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    calls = mw.advisor.calls
    assert len(calls) >= 2
    # Every follow-up starts with the system prompt, then the earlier
    # exchange: the first one sees the plan, later ones see more.
    assert all(c[0]["role"] == "system" for c in calls)
    assert calls[0][1:3] == mw._advisor_history[:2]
    lens = [len(c) for c in calls]
    assert all(b > a for a, b in zip(lens, lens[1:]))


# ── not double-counting ─────────────────────────────────────────────────


async def test_each_result_is_counted_once():
    """The whole context is rescanned per call; old results must not
    re-fire."""
    mw, agent = make_mw(), _Agent()
    add_result(agent, "execute_shell_command", {"command": "a"}, FAIL)
    add_result(agent, "execute_shell_command", {"command": "b"}, FAIL)
    for _ in range(5):  # repeated scans of the same two failures
        await mw._check_and_intervene(agent)
    assert not mw.advisor.calls, "two failures must not reach the threshold"


async def test_injected_advice_is_not_read_back_as_a_failure():
    mw, agent = make_mw(max_interventions=5), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    before = len(mw.advisor.calls)
    for _ in range(4):  # advice now sits in context; rescanning ignores it
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == before


async def test_pydantic_tool_results_are_scanned_too():
    """Real AgentScope contexts hold pydantic blocks with TextBlock
    outputs, not dicts; the scan must read those as well."""
    mw, agent = make_mw(), _Agent()
    for i in range(3):
        call_id = f"p{i}"
        agent.state.context.append(
            type(
                "Msg",
                (),
                {
                    "content": [
                        ToolCallBlock(
                            id=call_id,
                            name="execute_shell_command",
                            input=json.dumps({"command": f"c{i}"}),
                            state=ToolCallState.FINISHED,
                        ),
                        ToolResultBlock(
                            id=call_id,
                            name="execute_shell_command",
                            output=[TextBlock(text=FAIL)],
                            state=ToolResultState.ERROR,
                        ),
                    ],
                },
            )(),
        )
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 1


async def test_cap_is_enforced():
    mw = make_mw(max_interventions=2)
    agent = _Agent()
    for i in range(20):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 2


# ── request contents ────────────────────────────────────────────────────


async def test_request_carries_recent_calls_and_severity():
    mw, agent = make_mw(), _Agent()
    same = {"file_path": "backtest.py"}
    for _ in range(3):
        add_result(
            agent,
            "write_file",
            same,
            "Input validation failed for tool 'write_file': "
            "'content' is a required property",
        )
        await mw._check_and_intervene(agent)
    msg = mw.advisor.calls[0][-1]["content"]
    assert "write_file" in msg
    assert "backtest.py" in msg
    assert "'content' is a required property" in msg
    # Identical repeated call => the directive "stuck" wording.
    assert "repeated with identical arguments" in msg
    assert "CONTINUE" in msg and "ADJUST" in msg


async def test_advisor_failure_does_not_break_the_agent():
    mw, agent = make_mw([RuntimeError("advisor unreachable")]), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)  # must not raise
    assert followups(agent) == []
    assert "advisor unreachable" in mw.interventions[-1]["error"]


# ── verdict handling ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "reply,action,body",
    [
        ("CONTINUE", "CONTINUE", ""),
        ("**CONTINUE**", "CONTINUE", ""),
        ("CONTINUE\nkeep going", "CONTINUE", "keep going"),
        ("ADJUST\nStop X. Do Y.", "ADJUST", "Stop X. Do Y."),
        ("**ADJUST**\n\nStop X.", "ADJUST", "Stop X."),
        ("adjust\nfix it", "ADJUST", "fix it"),
        ("ADJUST — inline body", "", ""),  # verdict must be alone on line 1
        ("no verdict at all", "", ""),
        ("", "", ""),
    ],
)
def test_parse_followup(reply, action, body):
    assert _parse_followup(reply) == (action, body)


async def test_continue_is_not_injected_but_is_remembered():
    mw, agent = make_mw(["CONTINUE"]), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 1, "the advisor is still consulted"
    assert followups(agent) == [], "CONTINUE must not reach the agent"
    assert mw._advisor_history[-1]["content"] == "CONTINUE"
    assert mw.interventions[-1]["action"] == "CONTINUE"


async def test_adjust_injects_only_the_body_not_the_verdict_line():
    mw, agent = (
        make_mw(["ADJUST\nStop using heredocs; write a file."]),
        _Agent(),
    )
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert followups(agent)[0].output == "Stop using heredocs; write a file."


async def test_malformed_reply_retries_the_same_request():
    replies = [
        "no verdict here",
        "still no verdict",
        "ADJUST\nDo it this way.",
    ]
    mw, agent = make_mw(replies), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 3, "retries until the verdict parses"
    sent = {c[-1]["content"] for c in mw.advisor.calls}
    assert len(sent) == 1, "the SAME request is re-asked"
    assert followups(agent)[0].output == "Do it this way."


async def test_persistently_malformed_reply_is_treated_as_adjust():
    mw, agent = make_mw(["I think you should try something else."]), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 3, "gives up after the retry budget"
    assert (
        followups(agent)[0].output == "I think you should try something else."
    )
    assert mw.interventions[-1]["action"] == "ADJUST"


async def test_injected_call_args_are_a_fixed_stand_in():
    """The agent sees a short stand-in, not its own failures echoed
    back."""
    mw, agent = make_mw(), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    call = agent.state.context[-1].content[0]
    args = json.loads(call.input)
    assert args == _FOLLOWUP_CALL_ARGS
    assert "Progress Check" not in call.input, "the raw request must not leak"
    assert len(call.input) < 200


async def test_transcript_is_written(tmp_path):
    mw, agent = make_mw(log_dir=tmp_path / "adv"), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    transcript = json.loads(
        (tmp_path / "adv" / "sess-1.json").read_text(encoding="utf-8"),
    )
    assert transcript["agent_id"] == "agent-1"
    assert transcript["advisor"] == "stub:advisor"
    assert transcript["interventions"][0]["action"] == "ADJUST"
    assert transcript["interventions"][0]["index"] == 1


# ── plan injection: retry, and never claim success falsely ──────────────


async def _no_sleep(_seconds):
    """Skip the retry backoff so the tests do not actually wait."""


def _plan_mw(replies, **kw):
    advisor = _Advisor(replies)
    mw = AdvisorMiddleware(advisor=advisor, **kw)
    mw.advisor = advisor
    return mw


def _agent_with_task(text="do the task"):
    agent = _Agent()
    agent.state.context.append(UserMsg(name="user", content=text))
    return agent


async def test_plan_injected_on_first_success():
    mw, agent = _plan_mw(["THE PLAN"]), _agent_with_task()
    injected = await mw._inject_plan(agent, tools=[])
    assert injected is not None
    assert len(mw.advisor.calls) == 1
    assert agent.state.context[-1] is injected
    call, result = injected.content
    assert call.name == PLAN_TOOL_NAME and result.name == PLAN_TOOL_NAME
    assert call.id == result.id
    assert json.loads(call.input) == _PLAN_CALL_ARGS
    assert result.output == "THE PLAN"
    assert result.state == ToolResultState.SUCCESS


async def test_plan_request_carries_task_tools_and_system_prompt():
    mw, agent = _plan_mw(["THE PLAN"]), _agent_with_task("Write report.md")
    tools = [
        {"function": {"name": "write_file", "description": "Write a file"}},
        {"function": {"name": "get_token_usage", "description": "x"}},
    ]
    await mw._inject_plan(agent, tools=tools)
    messages = mw.advisor.calls[0]
    assert messages[0]["role"] == "system"
    assert "planning advisor" in messages[0]["content"]
    request = messages[-1]["content"]
    assert "Write report.md" in request
    assert "- write_file: Write a file" in request
    assert "get_token_usage" not in request, "excluded tools stay out"


async def test_plan_uses_workspace_listing_as_env_context(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "input.csv").write_text("a,b\n1,2\n")
    mw = _plan_mw(["THE PLAN"], env_context_root=tmp_path)
    agent = _agent_with_task()
    await mw._inject_plan(agent, tools=[])
    request = mw.advisor.calls[0][-1]["content"]
    assert "Workspace file listing" in request
    assert "data/" in request and "data/input.csv 8" in request


async def test_plan_transcript_is_written(tmp_path):
    mw = _plan_mw(
        ["THE PLAN"],
        log_dir=tmp_path / "adv",
        session_id="s1",
        agent_id="a1",
    )
    await mw._inject_plan(_agent_with_task(), tools=[])
    transcript = json.loads(
        (tmp_path / "adv" / "s1.json").read_text(encoding="utf-8"),
    )
    assert transcript["plan"]["plan"] == "THE PLAN"
    assert transcript["plan"]["error"] is None


async def test_plan_call_is_retried(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.middleware.asyncio.sleep",
        _no_sleep,
    )
    mw = _plan_mw([RuntimeError("400 filtered"), "THE PLAN"])
    agent = _agent_with_task()
    injected = await mw._inject_plan(agent, tools=[])
    assert injected is not None
    assert len(mw.advisor.calls) == 2, "retries after a rejected call"
    assert agent.state.context[-1].content[1].output == "THE PLAN"


async def test_exhausted_retries_report_failure(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.middleware.asyncio.sleep",
        _no_sleep,
    )
    mw, agent = _plan_mw([RuntimeError("400 filtered")]), _agent_with_task()
    assert await mw._inject_plan(agent, tools=[]) is None
    assert len(mw.advisor.calls) == 3
    assert len(agent.state.context) == 1, "nothing injected"
    assert "400 filtered" in mw.plan_error, "the failure is recorded"


async def test_failed_plan_does_not_consume_the_injected_flag(monkeypatch):
    """A rejected call leaves the flag clear (the next turn tries again),
    but this run stops retrying once the attempts are used up."""
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.middleware.asyncio.sleep",
        _no_sleep,
    )
    mw, agent = _plan_mw([RuntimeError("boom")]), _agent_with_task()
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert mw.plan_injected is False
    assert len(mw.advisor.calls) == 3
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(mw.advisor.calls) == 3, "no new round of retries per step"


async def test_on_model_call_injects_plan_into_the_request_in_flight():
    mw, agent = _plan_mw(["THE PLAN"]), _agent_with_task()
    messages = ["system", *agent.state.context]
    out = await mw.on_model_call(
        agent,
        {"messages": messages, "tools": []},
        _next_handler,
    )
    assert mw.plan_injected is True
    injected = agent.state.context[-1]
    assert out["messages"][-1] is injected
    assert out["messages"][:-1] == messages
    # A second call must not ask for another plan.
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(mw.advisor.calls) == 1


async def test_no_instruction_means_no_plan():
    mw, agent = _plan_mw(["THE PLAN"]), _Agent()  # empty context
    assert await mw._inject_plan(agent, tools=[]) is None
    assert not mw.advisor.calls


# ── helpers ─────────────────────────────────────────────────────────────


def test_clip_keeps_both_ends():
    text = "HEAD" + "x" * 5000 + "TAIL"
    out = _clip(text, 100)
    assert out.startswith("HEAD") and out.endswith("TAIL")
    assert "omitted" in out and len(out) < 300


def test_result_text_flattens_textblocks():
    assert _result_text({"output": "plain"}) == "plain"
    assert (
        _result_text(
            {
                "output": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b"},
                ],
            },
        )
        == "a\nb"
    )
    assert _result_text({"output": [TextBlock(text="p")]}) == "p"


def test_format_recent_marks_failures():
    out = _format_recent(
        [
            ObservedStep(
                tool="read_file",
                args={"p": "x"},
                output="ok",
                failed=False,
            ),
            ObservedStep(
                tool="execute_shell_command",
                args={"command": "y"},
                output=FAIL,
                failed=True,
            ),
        ],
    )
    assert "-> ok" in out and "-> FAILED" in out


def test_extract_instruction_reads_text_blocks():
    agent = _Agent()
    agent.state.context.append(
        UserMsg(
            name="user",
            content=[TextBlock(text="hello"), TextBlock(text="world")],
        ),
    )
    assert AdvisorMiddleware._extract_instruction(agent.state.context) == (
        "hello\nworld"
    )


def test_workspace_listing_skips_vendor_dirs_and_caps(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n")
    (tmp_path / "README.md").write_text("hi")
    out = _workspace_listing(tmp_path)
    assert "node_modules" not in out
    assert "src/" in out and "src/main.py 9" in out and "README.md 2" in out

    for i in range(20):
        (tmp_path / f"f{i:02d}.txt").write_text("x")
    capped = _workspace_listing(tmp_path, max_entries=5)
    assert capped.count("\n") <= 5
    assert "listing capped" in capped


def test_workspace_listing_handles_missing_root(tmp_path):
    assert _workspace_listing(None) == ""
    assert _workspace_listing(tmp_path / "nope") == ""


# ── multi-turn: baseline, latest instruction, shared history ────────────


async def test_results_already_in_context_are_not_counted():
    """A new request re-scans the whole context; failures from earlier
    turns must not trigger an intervention now."""
    mw, agent = make_mw(), _Agent()
    mw._baselined = False  # fresh middleware for a new request
    _fail_n(agent, 5)  # earlier turn's failures already in context
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert not mw.advisor.calls, "old failures were baselined, not counted"
    # Failures produced from now on count as usual.
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"n{i}"}, FAIL)
        await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(mw.advisor.calls) == 1


def test_extract_instruction_uses_the_latest_user_message():
    agent = _Agent()
    agent.state.context.append(UserMsg(name="user", content="first task"))
    agent.state.context.append(
        type("Msg", (), {"role": "assistant", "content": "done"})(),
    )
    agent.state.context.append(UserMsg(name="user", content="second task"))
    assert (
        AdvisorMiddleware._extract_instruction(agent.state.context)
        == "second task"
    )


async def test_shared_advisor_history_is_the_same_list():
    shared = [{"role": "user", "content": "earlier plan request"}]
    mw = _plan_mw(["THE PLAN"], advisor_history=shared)
    await mw._inject_plan(_agent_with_task(), tools=[])
    assert mw.advisor_history is shared
    assert len(shared) == 3, "the new exchange was appended to the list"
    # The plan request replayed the earlier exchange to the advisor.
    assert mw.advisor.calls[0][1]["content"] == "earlier plan request"


# ── on-demand consultation ──────────────────────────────────────────────


async def test_consult_answers_with_recent_calls_and_counts_budget():
    mw, agent = (
        make_mw(["Try the other route."], max_interventions=9),
        _Agent(),
    )
    mw._max_consults = 2
    add_result(agent, "execute_shell_command", {"command": "make"}, FAIL)
    await mw._check_and_intervene(agent)  # one failure observed
    reply = await mw.consult("Should I keep building or switch to X?")
    assert reply == "Try the other route."
    assert mw.consults_used == 1 and mw.consults_left == 1
    request = mw.advisor.calls[-1][-1]["content"]
    assert "Consultation 1 of 2" in request
    assert "Should I keep building or switch to X?" in request
    assert "make" in request and "FAILED" in request, "recent calls attached"
    assert mw.consults[-1]["question"].startswith("Should I")
    assert mw.consults[-1]["reply"] == "Try the other route."
    # The exchange is remembered for later follow-ups.
    assert mw._advisor_history[-1]["content"] == "Try the other route."


async def test_consult_budget_exhaustion_returns_notice_without_a_call():
    mw = make_mw(["ok"])
    mw._max_consults = 1
    assert await mw.consult("q1") == "ok"
    assert await mw.consult("q2") == CONSULT_BUDGET_EXHAUSTED
    assert len(mw.advisor.calls) == 1
    assert mw.consults_left == 0


async def test_consult_resets_the_failure_counters():
    """Asking the advisor must not be followed by an automatic intervention
    for the very same failures."""
    mw, agent = make_mw(["answer"]), _Agent()
    for i in range(2):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    await mw.consult("what now?")
    add_result(agent, "execute_shell_command", {"command": "c2"}, FAIL)
    await mw._check_and_intervene(agent)
    assert len(mw.advisor.calls) == 1, "only the consult reached the advisor"


async def test_consult_empty_question_and_advisor_failure():
    mw = make_mw([RuntimeError("down")])
    assert "concrete question" in await mw.consult("   ")
    reply = await mw.consult("help")
    assert "could not be reached" in reply
    assert "down" in mw.consults[-1]["error"]
    assert mw.consults_used == 1, "a failed call still spends the budget"


async def test_consults_are_persisted_in_the_transcript(tmp_path):
    mw = make_mw(["answer"], log_dir=tmp_path / "adv")
    await mw.consult("q")
    transcript = json.loads(
        (tmp_path / "adv" / "sess-1.json").read_text(encoding="utf-8"),
    )
    assert transcript["consults"][0]["question"] == "q"
    assert transcript["consults"][0]["reply"] == "answer"


# ── optional opening plan ───────────────────────────────────────────────


async def test_plan_can_be_switched_off_while_interventions_stay():
    mw = _plan_mw(["ADJUST\nTry another route."], plan_enabled=False)
    agent = _agent_with_task("build it")
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert not mw.advisor.calls, "no plan request"
    assert mw.plan_injected is False and mw.plan_enabled is False
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(mw.advisor.calls) == 1, "auto intervention still works"
    request = mw.advisor.calls[0][-1]["content"]
    assert (
        "# Task" in request and "build it" in request
    ), "the follow-up carries the task itself, since no plan exists"


async def test_consult_request_carries_the_task():
    mw = _plan_mw(["answer"])
    agent = _agent_with_task("write report.md")
    await mw.on_model_call(agent, {"messages": []}, _next_handler)  # plan
    await mw.consult("which format?")
    request = mw.advisor.calls[-1][-1]["content"]
    assert "write report.md" in request and "which format?" in request


async def test_agents_without_the_hook_are_fine():
    mw, agent = _plan_mw(["THE PLAN"]), _agent_with_task()
    assert await mw._inject_plan(agent, tools=[]) is not None


# ── live surfacing: the exchange streams while the advisor talks ────────


class _LiveAgent(_Agent):
    """Agent with the live hooks; records every UI update in order."""

    def __init__(self):
        super().__init__()
        self.events: list[tuple] = []

    def begin_injected_exchange(self, **kw):
        self.events.append(("begin", kw))

    def stream_injected_output(self, **kw):
        self.events.append(("delta", kw))

    def finish_injected_exchange(self, **kw):
        self.events.append(("finish", kw))


def _streamed(agent):
    return "".join(kw["delta"] for kind, kw in agent.events if kind == "delta")


async def test_plan_is_opened_before_the_advisor_answers_and_streamed():
    mw = _plan_mw(["THE PLAN, in full"])
    agent = _LiveAgent()
    agent.state.context.append(UserMsg(name="user", content="do it"))

    opened_before_reply = []
    real_ask = mw.advisor.ask

    async def ask(messages, *, on_text=None):
        opened_before_reply.append(
            agent.events[0][0] if agent.events else None,
        )
        return await real_ask(messages, on_text=on_text)

    mw.advisor.ask = ask
    await mw.on_model_call(agent, {"messages": []}, _next_handler)

    assert opened_before_reply == [
        "begin",
    ], "call shown before the advisor ran"
    kinds = [kind for kind, _ in agent.events]
    assert kinds[0] == "begin" and kinds[-1] == "finish"
    assert kinds.count("delta") >= 2, "reply relayed in pieces"
    assert _streamed(agent) == "THE PLAN, in full"
    begin = agent.events[0][1]
    assert begin["name"] == PLAN_TOOL_NAME
    assert json.loads(begin["arguments"]) == _PLAN_CALL_ARGS
    call_id = begin["call_id"]
    assert all(kw["call_id"] == call_id for _, kw in agent.events)
    assert (
        agent.state.context[-1].content[0].id == call_id
    ), "same id in context"
    assert agent.events[-1][1]["state"] == ToolResultState.SUCCESS


async def test_plan_failure_closes_the_exchange_as_an_error(monkeypatch):
    import qwenpaw.modes.advisor.middleware as mw_module

    monkeypatch.setattr(mw_module, "_PLAN_RETRY_DELAY_S", 0)
    mw = _plan_mw([RuntimeError("advisor down")])
    agent = _LiveAgent()
    agent.state.context.append(UserMsg(name="user", content="do it"))
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    kinds = [kind for kind, _ in agent.events]
    assert kinds[0] == "begin" and kinds[-1] == "finish"
    assert agent.events[-1][1]["state"] == ToolResultState.ERROR
    assert "advisor down" in _streamed(agent)
    assert "retrying" in _streamed(agent), "retries are narrated"
    assert mw.plan_injected is False


async def test_followup_continue_is_shown_but_not_injected():
    mw = make_mw(["CONTINUE\nLooks fine, carry on."])
    agent = _LiveAgent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert followups(agent) == [], "CONTINUE adds nothing to the context"
    kinds = [kind for kind, _ in agent.events]
    assert kinds[0] == "begin" and kinds[-1] == "finish"
    assert agent.events[0][1]["name"] == FOLLOWUP_TOOL_NAME
    assert _streamed(agent) == "CONTINUE\nLooks fine, carry on."


async def test_followup_adjust_streams_and_injects_the_body():
    mw = make_mw(["ADJUST\nSwitch."])
    agent = _LiveAgent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert [f.output for f in followups(agent)] == ["Switch."]
    assert _streamed(agent) == "ADJUST\nSwitch."
    call_id = agent.events[0][1]["call_id"]
    assert agent.state.context[-1].content[0].id == call_id


async def test_advisor_without_streaming_support_still_works():
    """A advisor whose ``ask`` takes no ``on_text`` (older plugin, test
    double) gets a plain call: the exchange is opened live and completed
    with the whole reply at the end."""

    class _PlainAdvisor:
        label = "plain"

        async def ask(self, messages):
            return "PLAN"

    mw = _plan_mw(["ignored"])
    mw._advisor = _PlainAdvisor()
    agent = _LiveAgent()
    agent.state.context.append(UserMsg(name="user", content="do it"))
    # ``_call_advisor`` passes ``on_text`` only when it is not None; make
    # the live path hand over None for this advisor.
    real = mw._call_advisor

    async def call(message, stateful=False, on_text=None):
        return await real(message, stateful=stateful, on_text=None)

    mw._call_advisor = call
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert _streamed(agent) == "PLAN"
    assert agent.events[-1][0] == "finish"


# ── consult_stream: the on-demand answer as deltas ──────────────────────


async def _pieces(mw, question):
    return [piece async for piece in mw.consult_stream(question)]


async def test_consult_stream_yields_the_reply_in_pieces():
    mw = _plan_mw(["THE PLAN", "Take the other route, it is shorter."])
    agent = _agent_with_task()
    await mw.on_model_call(agent, {"messages": []}, _next_handler)  # plan
    pieces = await _pieces(mw, "which route?")
    assert len(pieces) >= 2, "streamed, not delivered in one go"
    assert "".join(pieces) == "Take the other route, it is shorter."
    assert mw.consults_left == DEFAULT_MAX_CONSULTS - 1, "counted once"
    assert "which route?" in mw.advisor.calls[-1][-1]["content"]


async def test_consult_stream_delivers_a_notice_as_one_piece():
    mw = make_mw(["x"])
    mw._max_consults = 0
    pieces = await _pieces(mw, "anything?")
    assert pieces == [CONSULT_BUDGET_EXHAUSTED]
    assert not mw.advisor.calls, "no advisor call past the cap"


async def test_consult_stream_without_advisor_streaming():
    class _PlainAdvisor:
        label = "plain"

        async def ask(self, messages, *, on_text=None):
            return "  whole answer  "  # never calls on_text

    mw = make_mw(["x"])
    mw._advisor = _PlainAdvisor()
    pieces = await _pieces(mw, "q?")
    assert "".join(pieces) == "whole answer", "stripped like consult()"


async def test_consult_stream_reports_a_failed_advisor_call():
    mw = make_mw([RuntimeError("down")])
    pieces = await _pieces(mw, "q?")
    assert len(pieces) == 1 and "could not be reached" in pieces[0]


async def test_rejected_followup_samples_do_not_enter_the_history():
    mw = make_mw(["no verdict here", "ADJUST\nSwitch."])
    agent = _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert [f.output for f in followups(agent)] == ["Switch."]
    assert len(mw.advisor.calls) == 2, "re-asked once"
    assistant_turns = [
        m for m in mw.advisor_history if m["role"] == "assistant"
    ]
    assert [m["content"] for m in assistant_turns] == ["ADJUST\nSwitch."]


def test_advisor_never_sees_its_own_tool():
    """Listing ``consult_advisor`` made the advisor open every plan with
    "first, call consult_advisor"."""
    schemas = [
        {"function": {"name": PLAN_TOOL_NAME, "description": "ask"}},
        {"function": {"name": FOLLOWUP_TOOL_NAME, "description": "x"}},
        {"function": {"name": "write_file", "description": "Write a file"}},
    ]
    listing = AdvisorMiddleware._format_tool_list(schemas)
    assert "consult_advisor" not in listing
    assert "- write_file: Write a file" in listing
