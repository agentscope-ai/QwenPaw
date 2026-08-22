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


class _Teacher:
    """Scripted teacher: replies come from ``replies`` in order (an
    Exception entry raises); the last entry repeats."""

    label = "stub:teacher"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def ask(self, messages):
        self.calls.append(messages)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_mw(
    replies=("ADJUST\nStop retrying that; take another route.",),
    *,
    log_dir=None,
    **trigger_kw,
):
    """A middleware past the opening plan, with a scripted teacher."""
    cfg = TriggerConfig(
        consecutive_failures=3,
        window_size=10,
        window_failures=4,
        **trigger_kw,
    )
    teacher = _Teacher(replies)
    mw = AdvisorMiddleware(
        teacher=teacher,
        trigger=InterventionTrigger(config=cfg),
        log_dir=log_dir,
        session_id="sess-1",
        agent_id="agent-1",
    )
    mw._plan_injected = True
    mw._baselined = True  # already past the first model call of the turn
    mw.teacher = teacher
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
    assert not mw.teacher.calls
    assert followups(agent) == []


async def test_intervenes_after_consecutive_failures():
    mw, agent = make_mw(), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.teacher.calls) == 1
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
        teacher=_Teacher(["ADJUST\nx"]),
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
    mw._teacher_history = [
        {"role": "user", "content": "plan req"},
        {"role": "assistant", "content": "the plan"},
    ]
    for i in range(9):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    calls = mw.teacher.calls
    assert len(calls) >= 2
    # Every follow-up starts with the system prompt, then the earlier
    # exchange: the first one sees the plan, later ones see more.
    assert all(c[0]["role"] == "system" for c in calls)
    assert calls[0][1:3] == mw._teacher_history[:2]
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
    assert not mw.teacher.calls, "two failures must not reach the threshold"


async def test_injected_advice_is_not_read_back_as_a_failure():
    mw, agent = make_mw(max_interventions=5), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    before = len(mw.teacher.calls)
    for _ in range(4):  # advice now sits in context; rescanning ignores it
        await mw._check_and_intervene(agent)
    assert len(mw.teacher.calls) == before


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
    assert len(mw.teacher.calls) == 1


async def test_cap_is_enforced():
    mw = make_mw(max_interventions=2)
    agent = _Agent()
    for i in range(20):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.teacher.calls) == 2


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
    msg = mw.teacher.calls[0][-1]["content"]
    assert "write_file" in msg
    assert "backtest.py" in msg
    assert "'content' is a required property" in msg
    # Identical repeated call => the directive "stuck" wording.
    assert "repeated with identical arguments" in msg
    assert "CONTINUE" in msg and "ADJUST" in msg


async def test_teacher_failure_does_not_break_the_agent():
    mw, agent = make_mw([RuntimeError("teacher unreachable")]), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)  # must not raise
    assert followups(agent) == []
    assert "teacher unreachable" in mw.interventions[-1]["error"]


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
    assert len(mw.teacher.calls) == 1, "the teacher is still consulted"
    assert followups(agent) == [], "CONTINUE must not reach the agent"
    assert mw._teacher_history[-1]["content"] == "CONTINUE"
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
    assert len(mw.teacher.calls) == 3, "retries until the verdict parses"
    sent = {c[-1]["content"] for c in mw.teacher.calls}
    assert len(sent) == 1, "the SAME request is re-asked"
    assert followups(agent)[0].output == "Do it this way."


async def test_persistently_malformed_reply_is_treated_as_adjust():
    mw, agent = make_mw(["I think you should try something else."]), _Agent()
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw._check_and_intervene(agent)
    assert len(mw.teacher.calls) == 3, "gives up after the retry budget"
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
    assert transcript["teacher"] == "stub:teacher"
    assert transcript["interventions"][0]["action"] == "ADJUST"
    assert transcript["interventions"][0]["index"] == 1


# ── plan injection: retry, and never claim success falsely ──────────────


async def _no_sleep(_seconds):
    """Skip the retry backoff so the tests do not actually wait."""


def _plan_mw(replies, **kw):
    teacher = _Teacher(replies)
    mw = AdvisorMiddleware(teacher=teacher, **kw)
    mw.teacher = teacher
    return mw


def _agent_with_task(text="do the task"):
    agent = _Agent()
    agent.state.context.append(UserMsg(name="user", content=text))
    return agent


async def test_plan_injected_on_first_success():
    mw, agent = _plan_mw(["THE PLAN"]), _agent_with_task()
    injected = await mw._inject_plan(agent, tools=[])
    assert injected is not None
    assert len(mw.teacher.calls) == 1
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
    messages = mw.teacher.calls[0]
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
    request = mw.teacher.calls[0][-1]["content"]
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
    assert len(mw.teacher.calls) == 2, "retries after a rejected call"
    assert agent.state.context[-1].content[1].output == "THE PLAN"


async def test_exhausted_retries_report_failure(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.middleware.asyncio.sleep",
        _no_sleep,
    )
    mw, agent = _plan_mw([RuntimeError("400 filtered")]), _agent_with_task()
    assert await mw._inject_plan(agent, tools=[]) is None
    assert len(mw.teacher.calls) == 3
    assert len(agent.state.context) == 1, "nothing injected"
    assert "400 filtered" in mw.plan_error, "the failure is recorded"


async def test_failed_plan_does_not_consume_the_injected_flag(monkeypatch):
    """A rejected call must not disable advisor mode for the run."""
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.middleware.asyncio.sleep",
        _no_sleep,
    )
    mw, agent = _plan_mw([RuntimeError("boom")]), _agent_with_task()
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert mw.plan_injected is False, "a later step must try again"


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
    assert len(mw.teacher.calls) == 1


async def test_no_instruction_means_no_plan():
    mw, agent = _plan_mw(["THE PLAN"]), _Agent()  # empty context
    assert await mw._inject_plan(agent, tools=[]) is None
    assert not mw.teacher.calls


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
    assert not mw.teacher.calls, "old failures were baselined, not counted"
    # Failures produced from now on count as usual.
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"n{i}"}, FAIL)
        await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(mw.teacher.calls) == 1


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


async def test_shared_teacher_history_is_the_same_list():
    shared = [{"role": "user", "content": "earlier plan request"}]
    mw = _plan_mw(["THE PLAN"], teacher_history=shared)
    await mw._inject_plan(_agent_with_task(), tools=[])
    assert mw.teacher_history is shared
    assert len(shared) == 3, "the new exchange was appended to the list"
    # The plan request replayed the earlier exchange to the teacher.
    assert mw.teacher.calls[0][1]["content"] == "earlier plan request"


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
    request = mw.teacher.calls[-1][-1]["content"]
    assert "Consultation 1 of 2" in request
    assert "Should I keep building or switch to X?" in request
    assert "make" in request and "FAILED" in request, "recent calls attached"
    assert mw.consults[-1]["question"].startswith("Should I")
    assert mw.consults[-1]["reply"] == "Try the other route."
    # The exchange is remembered for later follow-ups.
    assert mw._teacher_history[-1]["content"] == "Try the other route."


async def test_consult_budget_exhaustion_returns_notice_without_a_call():
    mw = make_mw(["ok"])
    mw._max_consults = 1
    assert await mw.consult("q1") == "ok"
    assert await mw.consult("q2") == CONSULT_BUDGET_EXHAUSTED
    assert len(mw.teacher.calls) == 1
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
    assert len(mw.teacher.calls) == 1, "only the consult reached the teacher"


async def test_consult_empty_question_and_teacher_failure():
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
    assert not mw.teacher.calls, "no plan request"
    assert mw.plan_injected is False and mw.plan_enabled is False
    for i in range(3):
        add_result(agent, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(mw.teacher.calls) == 1, "auto intervention still works"
    request = mw.teacher.calls[0][-1]["content"]
    assert (
        "# Task" in request and "build it" in request
    ), "the follow-up carries the task itself, since no plan exists"


async def test_consult_request_carries_the_task():
    mw = _plan_mw(["answer"])
    agent = _agent_with_task("write report.md")
    await mw.on_model_call(agent, {"messages": []}, _next_handler)  # plan
    await mw.consult("which format?")
    request = mw.teacher.calls[-1][-1]["content"]
    assert "write report.md" in request and "which format?" in request


# ── surfacing injected exchanges to the UI ──────────────────────────────


class _SurfacingAgent(_Agent):
    def __init__(self):
        super().__init__()
        self.surfaced = []

    def queue_injected_exchange(self, **kw):
        self.surfaced.append(kw)


async def test_injected_plan_and_followup_are_surfaced_to_the_agent():
    mw = _plan_mw(["THE PLAN", "ADJUST\nSwitch."])
    agent = _SurfacingAgent()
    agent.state.context.append(UserMsg(name="user", content="do it"))
    await mw.on_model_call(agent, {"messages": []}, _next_handler)
    assert len(agent.surfaced) == 1
    plan = agent.surfaced[0]
    assert plan["name"] == PLAN_TOOL_NAME and plan["output"] == "THE PLAN"
    assert json.loads(plan["arguments"]) == _PLAN_CALL_ARGS
    assert plan["call_id"] == agent.state.context[-1].content[0].id

    mw2 = make_mw(["ADJUST\nSwitch."])
    agent2 = _SurfacingAgent()
    for i in range(3):
        add_result(agent2, "execute_shell_command", {"command": f"c{i}"}, FAIL)
        await mw2._check_and_intervene(agent2)
    assert [s["name"] for s in agent2.surfaced] == [FOLLOWUP_TOOL_NAME]
    assert agent2.surfaced[0]["output"] == "Switch."


async def test_agents_without_the_hook_are_fine():
    mw, agent = _plan_mw(["THE PLAN"]), _agent_with_task()
    assert await mw._inject_plan(agent, tools=[]) is not None
