# -*- coding: utf-8 -*-
"""End-to-end tests for save_to_knowledge tool path."""

from __future__ import annotations

import asyncio

import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.agent_types import (
    BUSINESS_ANALYSIS_AGENT_TYPE,
    DEFAULT_AGENT_TYPE,
)
from qwenpaw.agents.knowledge.lock import KnowledgeLockTimeout
from qwenpaw.agents.knowledge.mount import ensure_knowledge_mount
from qwenpaw.agents.knowledge.store import ensure_kb
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.config.config import AgentProfileConfig


def _make_manager(agent_id: str) -> ReMeLightMemoryManager:
    mgr = object.__new__(ReMeLightMemoryManager)
    mgr.agent_id = agent_id
    mgr.working_dir = ""
    return mgr


def _chunk_text(chunk) -> str:
    return chunk.content[0].text


@pytest.fixture
def kb_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    root = lambda kb_id: tmp_path / "knowledge_bases" / kb_id
    monkeypatch.setattr("qwenpaw.agents.knowledge.lock.kb_root", root)
    monkeypatch.setattr("qwenpaw.agents.knowledge.dream.kb_root", root)
    ensure_kb("team_kb", name="Team")
    return tmp_path


def test_save_to_knowledge_writes_shared_node(kb_env, monkeypatch):
    ws_a = kb_env / "workspaces" / "ba_a"
    ws_b = kb_env / "workspaces" / "ba_b"
    ws_a.mkdir(parents=True)
    ws_b.mkdir(parents=True)
    mount_a = ensure_knowledge_mount(ws_a, "team_kb")
    mount_b = ensure_knowledge_mount(ws_b, "team_kb")

    cfg = AgentProfileConfig(
        id="ba_a",
        name="BA-A",
        workspace_dir=str(ws_a),
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    cfg.running.reme_light_memory_config.knowledge_base_id = "team_kb"

    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda _aid: cfg,
    )

    mgr = _make_manager("ba_a")
    chunk = asyncio.run(
        mgr.save_to_knowledge(
            title="GMV口径",
            content="GMV 不含退款。",
            bucket="wiki",
        ),
    )
    assert chunk.state == ToolResultState.SUCCESS
    assert "Saved to knowledge base team_kb" in _chunk_text(chunk)

    written = mount_a / "business" / "wiki" / "gmv口径.md"
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert "GMV 不含退款" in text
    assert "updated_by_agent: ba_a" in text
    assert "tool:save_to_knowledge" in text
    peer = mount_b / "business" / "wiki" / "gmv口径.md"
    assert peer.is_file()
    assert peer.read_text(encoding="utf-8") == text


def test_save_to_knowledge_rejects_default_agent(monkeypatch):
    cfg = AgentProfileConfig(
        id="default",
        name="Default",
        agent_type=DEFAULT_AGENT_TYPE,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda _aid: cfg,
    )
    mgr = _make_manager("default")
    chunk = asyncio.run(
        mgr.save_to_knowledge(title="X", content="Y"),
    )
    assert chunk.state == ToolResultState.ERROR
    assert "only available" in _chunk_text(chunk)


def test_save_to_knowledge_requires_title_and_content(kb_env, monkeypatch):
    cfg = AgentProfileConfig(
        id="ba_a",
        name="BA",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    cfg.running.reme_light_memory_config.knowledge_base_id = "team_kb"
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda _aid: cfg,
    )
    mgr = _make_manager("ba_a")
    empty = asyncio.run(
        mgr.save_to_knowledge(title="", content="body"),
    )
    assert empty.state == ToolResultState.ERROR
    assert "required" in _chunk_text(empty)


def test_save_to_knowledge_same_title_refines_content(kb_env, monkeypatch):
    cfg = AgentProfileConfig(
        id="ba_a",
        name="BA",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    cfg.running.reme_light_memory_config.knowledge_base_id = "team_kb"
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda _aid: cfg,
    )
    mgr = _make_manager("ba_a")
    first = asyncio.run(
        mgr.save_to_knowledge(
            title="退款政策",
            content="七天无理由",
            bucket="procedure",
        ),
    )
    second = asyncio.run(
        mgr.save_to_knowledge(
            title="退款政策",
            content="七天无理由，需包装完好",
            bucket="procedure",
        ),
    )
    assert first.state == ToolResultState.SUCCESS
    assert "Saved" in _chunk_text(first)
    assert second.state == ToolResultState.SUCCESS
    assert "Saved" in _chunk_text(second)
    procedure = kb_env / "knowledge_bases" / "team_kb" / "business" / "procedure"
    files = list(procedure.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "需包装完好" in text
    assert "merge_count: 1" in text


def test_save_to_knowledge_lock_timeout_returns_error(kb_env, monkeypatch):
    cfg = AgentProfileConfig(
        id="ba_a",
        name="BA",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    cfg.running.reme_light_memory_config.knowledge_base_id = "team_kb"
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda _aid: cfg,
    )

    def boom(**_kwargs):
        raise KnowledgeLockTimeout("busy")

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.integrate_units",
        boom,
    )

    mgr = _make_manager("ba_a")
    chunk = asyncio.run(
        mgr.save_to_knowledge(title="T", content="C"),
    )
    assert chunk.state == ToolResultState.ERROR
    assert "locked" in _chunk_text(chunk).lower()
