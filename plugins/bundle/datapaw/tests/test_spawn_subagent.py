# -*- coding: utf-8 -*-
"""Tests for plugins/bundle/datapaw/core/agents/spawn_subagent.py."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo))
sys.path.insert(0, str(_repo.parent.parent.parent / "src"))

from core.agents.spawn_subagent import (  # noqa: E402
    _build_sub_prompt,
    _extract_text,
    _extract_tool_call_info,
    _extract_tool_result_name,
    _is_tool_call,
    _should_stream,
    make_spawn_subagent_fn,
)
from agentscope.message import Msg  # noqa: E402


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestBuildSubPrompt:
    def test_with_upstream(self):
        prompt = _build_sub_prompt(
            "查询数据", "上下文", {"n0": "结果"},
            builtin_tool_names=["read_file"],
            mcp_tool_names=["search_metrics", "execute_sql"],
        )
        assert "查询数据" in prompt
        assert "n0" in prompt
        assert "结果" in prompt
        assert "read_file" in prompt
        assert "search_metrics" in prompt
        assert "语义层" in prompt

    def test_empty_upstream(self):
        prompt = _build_sub_prompt("test", "", {}, [], [])
        assert "根节点" in prompt

    def test_anti_premature_exit_rules(self):
        prompt = _build_sub_prompt("test", "", {}, [], [])
        assert "同一条 assistant 消息" in prompt
        assert "纯文本且无 `tool_use`" in prompt
        assert "最终回答" in prompt

    def test_includes_datapaw_environment(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        prompt = _build_sub_prompt(
            "查询数据",
            "",
            {},
            ["execute_shell_command"],
            [],
            workspace_dir=workspace_dir,
            artifacts_root=workspace_dir / "artifacts",
            session_id="s1",
            graph_id="graph_abc",
            node_id="n1",
        )

        assert str(workspace_dir) in prompt
        assert "artifacts/s1/graph_abc/n1/" in prompt
        assert "s1/graph_abc/n1/<filename>" in prompt


class TestShouldStream:
    def test_assistant_streams(self):
        assert _should_stream(Msg("a", content="hi", role="assistant")) is True

    def test_system_does_not_stream(self):
        assert _should_stream(Msg("s", content="r", role="system")) is False


class TestIsToolCall:
    def test_true(self):
        msg = Msg(
            "a",
            content=[{"type": "tool_use", "id": "t1", "name": "foo", "input": {}}],
            role="assistant",
        )
        assert _is_tool_call(msg) is True

    def test_false(self):
        msg = Msg("a", content=[{"type": "text", "text": "hi"}], role="assistant")
        assert _is_tool_call(msg) is False

    def test_string_content(self):
        msg = Msg("a", content="hello", role="assistant")
        assert _is_tool_call(msg) is False


class TestExtractText:
    def test_string_content(self):
        assert _extract_text(Msg("a", content="plain", role="assistant")) == "plain"

    def test_thinking_block(self):
        msg = Msg(
            "a",
            content=[{"type": "thinking", "text": "hmm"}],
            role="assistant",
        )
        assert _extract_text(msg) == "hmm"

    def test_text_block(self):
        msg = Msg(
            "a",
            content=[{"type": "text", "text": "hello"}],
            role="assistant",
        )
        assert _extract_text(msg) == "hello"

    def test_system_tool_result(self):
        msg = Msg(
            "system",
            content=[
                {
                    "type": "tool_result",
                    "id": "tc1",
                    "name": "execute_sql",
                    "output": [{"type": "text", "text": "rows: 42"}],
                }
            ],
            role="system",
        )
        assert "rows: 42" in _extract_text(msg)


class TestExtractToolResultName:
    def test_basic(self):
        msg = Msg(
            "system",
            content=[
                {
                    "type": "tool_result",
                    "id": "tc1",
                    "name": "execute_sql",
                    "output": [{"type": "text", "text": "ok"}],
                }
            ],
            role="system",
        )
        assert _extract_tool_result_name(msg) == "execute_sql"

    def test_no_name(self):
        msg = Msg(
            "system",
            content=[{"type": "tool_result", "id": "tc1"}],
            role="system",
        )
        assert _extract_tool_result_name(msg) == "tool"

    def test_string_content(self):
        msg = Msg("system", content="plain text", role="system")
        assert _extract_tool_result_name(msg) == "tool"


class TestExtractToolCallInfo:
    def test_basic(self):
        msg = Msg(
            "a",
            content=[
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "execute_sql",
                    "input": {"query": "SELECT 1"},
                }
            ],
            role="assistant",
        )
        info = _extract_tool_call_info(msg)
        assert info["name"] == "execute_sql"
        assert info["input"] == {"query": "SELECT 1"}

    def test_no_tool_use(self):
        msg = Msg("a", content="text", role="assistant")
        info = _extract_tool_call_info(msg)
        assert info["name"] == "tool"


# ---------------------------------------------------------------------------
# Async spawn function tests
# ---------------------------------------------------------------------------


def _make_runtime_state():
    rs = MagicMock()
    plan = MagicMock()
    plan.id = "graph_1"
    rs.current_plan = plan
    node = MagicMock()
    node.node_id = "n1"
    rs.get_current_in_progress_node.return_value = node
    rs.get_upstream_outputs.return_value = {}
    return rs


@pytest.mark.asyncio
async def test_unsupported_role():
    fn = make_spawn_subagent_fn(
        runtime_state=_make_runtime_state(),
        get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
        get_builtin_tools=lambda: [],
        get_mcp_clients=lambda: [],
        get_skill_dirs_for_role=lambda r: [],
    )
    results = []
    async for resp in fn(task="test", role="bad_role"):
        results.append(resp)

    assert len(results) == 1
    assert results[0].is_last is True
    assert "不支持" in results[0].content[0]["text"]


@pytest.mark.asyncio
async def test_model_failure():
    def _fail():
        raise RuntimeError("model broken")

    fn = make_spawn_subagent_fn(
        runtime_state=_make_runtime_state(),
        get_model_and_formatter=_fail,
        get_builtin_tools=lambda: [],
        get_mcp_clients=lambda: [],
        get_skill_dirs_for_role=lambda r: [],
    )
    results = []
    async for resp in fn(task="test", role="data_fetcher"):
        results.append(resp)

    assert len(results) == 1
    assert results[0].is_last is True
    assert "模型创建失败" in results[0].content[0]["text"]


@pytest.mark.asyncio
async def test_successful_run():
    reply_msg = Msg("agent", content="done", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "thinking", "text": "let me think"}],
                        role="assistant",
                    ),
                    False,
                    None,
                )
            )
            await q.put(
                (Msg("agent", content="任务完成", role="assistant"), True, None)
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="do it", role="data_fetcher"):
            results.append(resp)

        assert len(results) >= 2
        assert results[-1].is_last is True
        assert results[0].content[0]["text"] == "let me think"


@pytest.mark.asyncio
async def test_subagent_sets_qwenpaw_tool_context(tmp_path):
    from qwenpaw.config.context import (
        get_current_recent_max_bytes,
        get_current_session_id,
        get_current_shell_command_executable,
        get_current_shell_command_timeout,
        get_current_toolkit,
        get_current_workspace_dir,
        set_current_workspace_dir,
    )

    workspace_dir = tmp_path / "workspace"
    parent_workspace_dir = tmp_path / "parent"
    captured = {}
    reply_msg = Msg("agent", content="done", role="assistant")
    set_current_workspace_dir(parent_workspace_dir)

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            captured["workspace_dir"] = get_current_workspace_dir()
            captured["session_id"] = get_current_session_id()
            captured["recent_max_bytes"] = get_current_recent_max_bytes()
            captured["shell_timeout"] = get_current_shell_command_timeout()
            captured["shell_executable"] = (
                get_current_shell_command_executable()
            )
            captured["toolkit"] = get_current_toolkit()
            q = instance._stored_queue
            await q.put(
                (Msg("agent", content="任务完成", role="assistant"), True, None)
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
            get_workspace_dir=lambda: workspace_dir,
            get_artifacts_root=lambda: workspace_dir / "artifacts",
            get_session_id=lambda: "s1",
            get_recent_max_bytes=lambda: 4096,
            get_shell_command_timeout=lambda: 120.0,
            get_shell_command_executable=lambda: "/bin/sh",
        )
        results = []
        async for resp in fn(task="do it", role="data_fetcher"):
            results.append(resp)

    assert results[-1].is_last is True
    assert captured["workspace_dir"] == workspace_dir
    assert captured["session_id"] == "s1"
    assert captured["recent_max_bytes"] == 4096
    assert captured["shell_timeout"] == 120.0
    assert captured["shell_executable"] == "/bin/sh"
    assert captured["toolkit"] is not None
    assert get_current_workspace_dir() == parent_workspace_dir


@pytest.mark.asyncio
async def test_tool_call_and_result():
    reply_msg = Msg("agent", content="分析完成", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            # thinking
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "thinking", "text": "need data"}],
                        role="assistant",
                    ),
                    False,
                    None,
                )
            )
            # tool_call (final reasoning frame)
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[
                            {"type": "thinking", "text": "need data"},
                            {
                                "type": "tool_use",
                                "id": "tc1",
                                "name": "execute_sql",
                                "input": {"query": "SELECT 1"},
                            },
                        ],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            # tool_result
            await q.put(
                (
                    Msg(
                        "system",
                        content=[
                            {
                                "type": "tool_result",
                                "id": "tc1",
                                "name": "execute_sql",
                                "output": [{"type": "text", "text": "rows: 42"}],
                            }
                        ],
                        role="system",
                    ),
                    True,
                    None,
                )
            )
            # final text
            await q.put(
                (Msg("agent", content="分析完成", role="assistant"), True, None)
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="query", role="data_fetcher"):
            results.append(resp)

        texts = [r.content[0]["text"] for r in results]
        assert any("need data" in t for t in texts), f"missing thinking: {texts}"
        assert any("[tool_call]" in t for t in texts), f"missing tool_call: {texts}"
        assert any("rows: 42" in t for t in texts), f"missing tool_result: {texts}"
        assert results[-1].is_last is True


@pytest.mark.asyncio
async def test_text_and_tool_call_same_message_streams_text_first():
    reply_msg = Msg("agent", content="完成", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[
                            {
                                "type": "text",
                                "text": "我先查询可用指标，再执行 SQL。",
                            },
                            {
                                "type": "tool_use",
                                "id": "tc1",
                                "name": "execute_sql",
                                "input": {"query": "SELECT 1"},
                            },
                        ],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            await q.put(
                (
                    Msg(
                        "system",
                        content=[
                            {
                                "type": "tool_result",
                                "id": "tc1",
                                "name": "execute_sql",
                                "output": [{"type": "text", "text": "rows: 1"}],
                            }
                        ],
                        role="system",
                    ),
                    True,
                    None,
                )
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="query", role="data_fetcher"):
            results.append(resp)

        texts = [r.content[0]["text"] for r in results]
        progress_idx = next(
            i for i, text in enumerate(texts)
            if "我先查询可用指标" in text
        )
        tool_idx = next(i for i, text in enumerate(texts) if "[tool_call]" in text)
        assert progress_idx < tool_idx
        assert any("rows: 1" in t for t in texts)

        final = results[-1]
        entries = final.metadata["entries"]
        assert {"type": "thinking", "text": "我先查询可用指标，再执行 SQL。"} in entries
        assert any(
            e["type"] == "tool_call" and e["name"] == "execute_sql"
            for e in entries
        )


@pytest.mark.asyncio
async def test_timeout():
    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent, patch(
        "core.agents.spawn_subagent.TIMEOUT_SECONDS", 0.5
    ):

        async def _hang(task_msg):
            await asyncio.sleep(999)
            return Msg("agent", content="", role="assistant")

        instance = AsyncMock(side_effect=_hang)
        instance.set_msg_queue_enabled = MagicMock()
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="hang", role="data_fetcher"):
            results.append(resp)

        assert len(results) >= 1
        assert results[-1].is_last is True
        assert "超时" in results[-1].content[0]["text"]


@pytest.mark.asyncio
async def test_trace_persisted_to_runtime_state():
    """Verify sub-agent trace is written to the node via runtime_state."""
    reply_msg = Msg("agent", content="done", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            # thinking
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "thinking", "text": "planning"}],
                        role="assistant",
                    ),
                    False,
                    None,
                )
            )
            # tool_call
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[
                            {
                                "type": "tool_use",
                                "id": "tc1",
                                "name": "execute_sql",
                                "input": {"query": "SELECT 1"},
                            },
                        ],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            # tool_result
            await q.put(
                (
                    Msg(
                        "system",
                        content=[
                            {
                                "type": "tool_result",
                                "id": "tc1",
                                "name": "execute_sql",
                                "output": [{"type": "text", "text": "42 rows"}],
                            }
                        ],
                        role="system",
                    ),
                    True,
                    None,
                )
            )
            # final text
            await q.put(
                (Msg("agent", content="完成", role="assistant"), True, None)
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        rs = _make_runtime_state()

        fn = make_spawn_subagent_fn(
            runtime_state=rs,
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="query", role="data_fetcher"):
            results.append(resp)

        # Trace flows through ToolResponse metadata (not append_to_trace)
        final = results[-1]
        assert final.is_last is True
        assert final.metadata is not None
        assert final.metadata["type"] == "subagent_trace"

        entries = final.metadata["entries"]
        types = [e["type"] for e in entries]
        assert "thinking" in types
        assert "tool_call" in types
        assert "tool_result" in types

        tool_call_entry = next(e for e in entries if e["type"] == "tool_call")
        assert tool_call_entry["name"] == "execute_sql"
        assert tool_call_entry["input"] == {"query": "SELECT 1"}

        tool_result_entry = next(e for e in entries if e["type"] == "tool_result")
        assert tool_result_entry["name"] == "execute_sql"
        assert "42 rows" in tool_result_entry["output"]


@pytest.mark.asyncio
async def test_trace_in_metadata_without_plan():
    """When no plan exists (node_id=None), trace is NOT written to
    node trace but IS carried in the final ToolResponse metadata."""
    reply_msg = Msg("agent", content="done", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "thinking", "text": "thinking"}],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        # No plan → node_id is None
        rs = MagicMock()
        rs.get_current_in_progress_node.return_value = None
        rs.get_upstream_outputs.return_value = {}

        fn = make_spawn_subagent_fn(
            runtime_state=rs,
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="simple", role="data_fetcher"):
            results.append(resp)

        # append_to_trace should NOT be called (no node)
        rs.append_to_trace.assert_not_called()

        # But final ToolResponse metadata should carry the trace
        final = results[-1]
        assert final.metadata is not None
        assert final.metadata["type"] == "subagent_trace"


@pytest.mark.asyncio
async def test_streaming_yields_delta_not_cumulative():
    """Consecutive thinking chunks with cumulative text yield only deltas."""
    reply_msg = Msg("agent", content="done", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            # Simulate cumulative streaming from LLM
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "text", "text": "Hello"}],
                        role="assistant",
                    ),
                    False,
                    None,
                )
            )
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "text", "text": "Hello world"}],
                        role="assistant",
                    ),
                    False,
                    None,
                )
            )
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[
                            {"type": "text", "text": "Hello world!"},
                        ],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="test", role="data_fetcher"):
            results.append(resp)

        # Streaming chunks should be deltas, not cumulative
        streaming = [r for r in results if not r.is_last]
        assert len(streaming) == 3
        assert streaming[0].content[0]["text"] == "Hello"
        assert streaming[1].content[0]["text"] == " world"
        assert streaming[2].content[0]["text"] == "!"


@pytest.mark.asyncio
async def test_delta_resets_after_tool_result():
    """Delta tracking resets when a tool result arrives."""
    reply_msg = Msg("agent", content="summary", role="assistant")

    with patch("core.agents.spawn_subagent.ReActAgent") as MockAgent:

        async def _call(task_msg):
            q = instance._stored_queue
            # First thinking round
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "text", "text": "AAA"}],
                        role="assistant",
                    ),
                    False,
                    None,
                )
            )
            # Tool call
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[
                            {
                                "type": "tool_use",
                                "id": "tc1",
                                "name": "foo",
                                "input": {},
                            },
                        ],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            # Tool result
            await q.put(
                (
                    Msg(
                        "system",
                        content=[
                            {
                                "type": "tool_result",
                                "id": "tc1",
                                "name": "foo",
                                "output": [{"type": "text", "text": "ok"}],
                            }
                        ],
                        role="system",
                    ),
                    True,
                    None,
                )
            )
            # Second thinking round — text starts fresh
            await q.put(
                (
                    Msg(
                        "agent",
                        content=[{"type": "text", "text": "BBB"}],
                        role="assistant",
                    ),
                    True,
                    None,
                )
            )
            return reply_msg

        instance = AsyncMock(side_effect=_call)

        def _set_q(enabled, q):
            instance._stored_queue = q

        instance.set_msg_queue_enabled = _set_q
        MockAgent.return_value = instance

        fn = make_spawn_subagent_fn(
            runtime_state=_make_runtime_state(),
            get_model_and_formatter=lambda: (MagicMock(), MagicMock()),
            get_builtin_tools=lambda: [],
            get_mcp_clients=lambda: [],
            get_skill_dirs_for_role=lambda r: [],
        )
        results = []
        async for resp in fn(task="test", role="data_fetcher"):
            results.append(resp)

        texts = [r.content[0]["text"] for r in results if not r.is_last]
        # "AAA" from first round, tool_call, tool_result, "BBB" from second
        # "BBB" should be full text (not delta from "AAA") since reset happened
        assert "AAA" in texts
        assert "BBB" in texts
