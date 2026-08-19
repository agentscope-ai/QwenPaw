# -*- coding: utf-8 -*-
"""Unit tests for shared knowledge-base store, mount, and binding."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.agents.agent_types import (
    BUSINESS_ANALYSIS_AGENT_TYPE,
    DEFAULT_AGENT_TYPE,
    agent_type_has_knowledge_base,
    get_agent_type,
)
from qwenpaw.agents.knowledge.binding import (
    WorkspaceConflictError,
    assert_unique_workspace,
    bind_knowledge_base,
)
from qwenpaw.agents.knowledge.mount import ensure_knowledge_mount
from qwenpaw.agents.knowledge.store import (
    ensure_kb,
    kb_root,
    list_knowledge_bases,
    resolve_kb_id,
)
from qwenpaw.app.agent_startup import AgentStartupStatus
from qwenpaw.app.routers.agents import router as agents_router
from qwenpaw.app.routers.knowledge_bases import router as kb_router
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef


def test_business_analysis_has_knowledge_capability():
    assert agent_type_has_knowledge_base(DEFAULT_AGENT_TYPE) is False
    assert agent_type_has_knowledge_base(BUSINESS_ANALYSIS_AGENT_TYPE) is True
    ba = get_agent_type(BUSINESS_ANALYSIS_AGENT_TYPE)
    assert ba is not None
    assert ba.capabilities.knowledge_base is True


def test_resolve_kb_id_defaults_to_agent_private(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    assert resolve_kb_id(agent_id="a1", knowledge_base_id=None) == "kb_a1"
    assert resolve_kb_id(agent_id="a1", knowledge_base_id="shared") == "shared"


def test_ensure_kb_creates_skeleton(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    meta = ensure_kb("demo_kb", name="Demo", domain="business")
    root = kb_root("demo_kb")
    assert meta.id == "demo_kb"
    assert (root / "KB.md").is_file()
    # Domain-namespaced buckets.
    assert (root / "business" / "personal").is_dir()
    assert (root / "business" / "procedure").is_dir()
    assert (root / "business" / "wiki").is_dir()
    assert (root / "test" / "test_design").is_dir()
    assert (root / "test" / "test_cases").is_dir()
    assert (root / "_inbox").is_dir()
    assert (root / ".locks").is_dir()
    ids = {item.id for item in list_knowledge_bases()}
    assert "demo_kb" in ids


def test_ensure_knowledge_mount_links_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.ensure_kb",
        ensure_kb,
    )
    ensure_kb("shared_kb")
    workspace = tmp_path / "workspaces" / "agent_a"
    workspace.mkdir(parents=True)
    mount = ensure_knowledge_mount(workspace, "shared_kb")
    assert mount.exists()
    # Resolve should land on the shared KB root.
    assert mount.resolve() == (tmp_path / "knowledge_bases" / "shared_kb").resolve()


def test_two_agents_share_one_kb(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    ensure_kb("team_kb")
    ws_a = tmp_path / "workspaces" / "a"
    ws_b = tmp_path / "workspaces" / "b"
    ws_a.mkdir(parents=True)
    ws_b.mkdir(parents=True)
    mount_a = ensure_knowledge_mount(ws_a, "team_kb")
    mount_b = ensure_knowledge_mount(ws_b, "team_kb")
    assert mount_a.resolve() == mount_b.resolve()
    marker = mount_a / "business" / "wiki" / "shared.md"
    marker.write_text("# shared\n", encoding="utf-8")
    assert (mount_b / "business" / "wiki" / "shared.md").is_file()


def test_assert_unique_workspace_rejects_reuse(tmp_path):
    profiles = {
        "other": AgentProfileRef(
            id="other",
            workspace_dir=str(tmp_path / "shared_ws"),
        ),
    }
    (tmp_path / "shared_ws").mkdir()
    with pytest.raises(WorkspaceConflictError):
        assert_unique_workspace(
            tmp_path / "shared_ws",
            agent_id="new",
            profiles=profiles,
        )


def test_bind_knowledge_base_ignores_default_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    cfg = AgentProfileConfig(
        id="d1",
        name="Default",
        workspace_dir=str(tmp_path / "ws"),
        agent_type=DEFAULT_AGENT_TYPE,
    )
    assert bind_knowledge_base(cfg) is None
    assert not (tmp_path / "ws" / "knowledge").exists()


def test_bind_knowledge_base_for_ba(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    ws = tmp_path / "ws_ba"
    ws.mkdir()
    cfg = AgentProfileConfig(
        id="ba1",
        name="BA",
        workspace_dir=str(ws),
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    kb_id = bind_knowledge_base(cfg, knowledge_base_id="shared_biz")
    assert kb_id == "shared_biz"
    assert cfg.running.reme_light_memory_config.knowledge_base_id == "shared_biz"
    assert (ws / "knowledge").exists()


@pytest.fixture
def manager_mock():
    mgr = MagicMock(name="MultiAgentManager")
    mgr.schedule_agent_startup = MagicMock()
    mgr.get_agent_startup_status.side_effect = lambda _agent_id, *, enabled: (
        AgentStartupStatus.RUNNING if enabled else AgentStartupStatus.DISABLED
    )
    return mgr


@pytest.fixture
def client(manager_mock) -> TestClient:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(agents_router, prefix="/api")
    application.include_router(kb_router, prefix="/api")
    return TestClient(application)


@pytest.fixture
def fake_config():
    config = MagicMock(name="AppConfig")
    config.agents = MagicMock()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir="/tmp/ws/default",
        ),
    }
    config.agents.agent_order = ["default"]
    config.agents.language = "en"
    return config


def test_knowledge_bases_api_create_list(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    created = client.post(
        "/api/knowledge-bases",
        json={"id": "kb_api", "name": "API KB", "domain": "business"},
    )
    assert created.status_code == 201
    assert created.json()["id"] == "kb_api"
    listed = client.get("/api/knowledge-bases")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["knowledge_bases"]}
    assert "kb_api" in ids


def test_create_ba_agent_binds_kb(client, fake_config, tmp_path):
    saved: list[AgentProfileConfig] = []

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=lambda _id, cfg: saved.append(cfg),
        ),
        patch(
            "qwenpaw.app.routers.agents._initialize_agent_workspace",
        ),
        patch(
            "qwenpaw.app.routers.agents.WORKING_DIR",
            str(tmp_path),
        ),
        patch(
            "qwenpaw.agents.knowledge.store.WORKING_DIR",
            tmp_path,
        ),
        patch(
            "qwenpaw.app.routers.agents.assert_unique_workspace",
        ),
    ):
        response = client.post(
            "/api/agents",
            json={
                "id": "biz-kb",
                "name": "Biz",
                "agent_type": BUSINESS_ANALYSIS_AGENT_TYPE,
                "knowledge_base_id": "team_shared",
                "workspace_dir": str(tmp_path / "biz-kb"),
            },
        )

    assert response.status_code == 201
    assert len(saved) == 1
    assert saved[0].agent_type == BUSINESS_ANALYSIS_AGENT_TYPE
    assert (
        saved[0].running.reme_light_memory_config.knowledge_base_id
        == "team_shared"
    )
    assert (tmp_path / "biz-kb" / "knowledge").exists()


def test_create_ba_agent_auto_binds_private_kb(client, fake_config, tmp_path):
    saved: list[AgentProfileConfig] = []

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=lambda _id, cfg: saved.append(cfg),
        ),
        patch(
            "qwenpaw.app.routers.agents._initialize_agent_workspace",
        ),
        patch(
            "qwenpaw.app.routers.agents.WORKING_DIR",
            str(tmp_path),
        ),
        patch(
            "qwenpaw.agents.knowledge.store.WORKING_DIR",
            tmp_path,
        ),
        patch(
            "qwenpaw.app.routers.agents.assert_unique_workspace",
        ),
    ):
        response = client.post(
            "/api/agents",
            json={
                "id": "biz-auto",
                "name": "BizAuto",
                "agent_type": BUSINESS_ANALYSIS_AGENT_TYPE,
                "workspace_dir": str(tmp_path / "biz-auto"),
            },
        )

    assert response.status_code == 201
    assert saved[0].running.reme_light_memory_config.knowledge_base_id == (
        "kb_biz-auto"
    )
    assert (tmp_path / "biz-auto" / "knowledge").exists()


def test_knowledge_bases_api_rejects_invalid_and_duplicate(
    client,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    bad = client.post(
        "/api/knowledge-bases",
        json={"id": "bad id!", "name": "x"},
    )
    assert bad.status_code == 400
    first = client.post(
        "/api/knowledge-bases",
        json={"id": "dup_kb", "name": "One"},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/knowledge-bases",
        json={"id": "dup_kb", "name": "Two"},
    )
    assert second.status_code == 409
    missing = client.get("/api/knowledge-bases/no_such_kb")
    assert missing.status_code == 404


def test_mount_refuses_nonempty_directory(tmp_path, monkeypatch):
    from qwenpaw.agents.knowledge.mount import (
        KnowledgeMountError,
        ensure_knowledge_mount,
    )

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    ensure_kb("kb_block")
    workspace = tmp_path / "ws_block"
    workspace.mkdir()
    occupied = workspace / "knowledge"
    occupied.mkdir()
    (occupied / "file.md").write_text("x", encoding="utf-8")
    with pytest.raises(KnowledgeMountError):
        ensure_knowledge_mount(workspace, "kb_block")


def test_detect_dangling_mount_returns_none_for_healthy(tmp_path, monkeypatch):
    from qwenpaw.agents.knowledge.mount import detect_dangling_mount

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.ensure_kb",
        ensure_kb,
    )
    ensure_kb("kb_ok")
    workspace = tmp_path / "ws_ok"
    workspace.mkdir()
    ensure_knowledge_mount(workspace, "kb_ok")
    # Healthy mount → not dangling.
    assert detect_dangling_mount(workspace) is None
    # Absent mount → not dangling.
    assert detect_dangling_mount(tmp_path / "no_mount_yet") is None


def test_detect_dangling_mount_flags_deleted_target(tmp_path, monkeypatch):
    from qwenpaw.agents.knowledge.mount import detect_dangling_mount

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.ensure_kb",
        ensure_kb,
    )
    ensure_kb("kb_gone")
    workspace = tmp_path / "ws_gone"
    workspace.mkdir()
    ensure_knowledge_mount(workspace, "kb_gone")
    # Simulate a human deleting the shared KB directory on disk.
    import shutil

    shutil.rmtree(tmp_path / "knowledge_bases" / "kb_gone")
    dangling = detect_dangling_mount(workspace)
    assert dangling is not None
    assert dangling.name == "knowledge"


def test_ensure_knowledge_mount_refuses_to_recreate_dangling(tmp_path, monkeypatch):
    """A dangling mount must surface an error, not silently recreate the KB."""
    import shutil

    from qwenpaw.agents.knowledge.mount import (
        KnowledgeMountError,
        ensure_knowledge_mount,
    )

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.mount.ensure_kb",
        ensure_kb,
    )
    ensure_kb("kb_dangle")
    workspace = tmp_path / "ws_dangle"
    workspace.mkdir()
    ensure_knowledge_mount(workspace, "kb_dangle")
    # Human deletes the KB directory.
    shutil.rmtree(tmp_path / "knowledge_bases" / "kb_dangle")
    with pytest.raises(KnowledgeMountError, match="missing shared knowledge"):
        ensure_knowledge_mount(workspace, "kb_dangle")
    # The KB directory must NOT have been silently recreated.
    assert not (tmp_path / "knowledge_bases" / "kb_dangle").exists()


def test_bind_knowledge_base_raises_on_dangling(tmp_path, monkeypatch):
    """bind_knowledge_base surfaces dangling mount before recreating KB."""
    import shutil

    from qwenpaw.agents.knowledge.binding import bind_knowledge_base
    from qwenpaw.agents.knowledge.mount import KnowledgeMountError

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    ws = tmp_path / "ws_bind"
    ws.mkdir()
    cfg = AgentProfileConfig(
        id="ba1",
        name="BA",
        workspace_dir=str(ws),
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    bind_knowledge_base(cfg, knowledge_base_id="shared_bind")
    # Human deletes the shared KB directory.
    shutil.rmtree(tmp_path / "knowledge_bases" / "shared_bind")
    cfg2 = AgentProfileConfig(
        id="ba2",
        name="BA2",
        workspace_dir=str(ws),
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    with pytest.raises(KnowledgeMountError, match="missing shared"):
        bind_knowledge_base(cfg2, knowledge_base_id="shared_bind")
    assert not (tmp_path / "knowledge_bases" / "shared_bind").exists()


def test_manager_surfaces_dangling_mount_warning(tmp_path, monkeypatch):
    """The memory manager captures a dangling mount as a user-facing warning."""
    import shutil

    from types import SimpleNamespace

    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    ws = tmp_path / "ws_mgr"
    ws.mkdir()
    cfg = AgentProfileConfig(
        id="ba1",
        name="BA",
        workspace_dir=str(ws),
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    bind_knowledge_base(cfg, knowledge_base_id="shared_mgr")
    # Human deletes the shared KB directory.
    shutil.rmtree(tmp_path / "knowledge_bases" / "shared_mgr")

    # Bypass __init__ (would import ReMe); call the mount helper directly.
    mgr = object.__new__(ReMeLightMemoryManager)
    mgr._knowledge_mount_warning = None
    mgr._ensure_knowledge_mount(cfg)

    warning = mgr.knowledge_mount_warning()
    assert warning is not None
    assert "missing shared knowledge" in warning
    # The KB must NOT have been silently recreated.
    assert not (tmp_path / "knowledge_bases" / "shared_mgr").exists()


def test_manager_reme_status_attaches_mount_warning(tmp_path, monkeypatch):
    """reme_status surfaces the dangling-mount warning via response metadata."""
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )

    mgr = object.__new__(ReMeLightMemoryManager)
    mgr._knowledge_mount_warning = "dangling!"
    mgr._reme = None
    # _run_reme_job returns None when reme is None → reme_status returns None.
    # Force a response with metadata to verify attachment.
    response = SimpleNamespace(success=True, answer="ok", metadata={})

    async def _fake_run(name, **kwargs):
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    result = asyncio.run(mgr.reme_status())
    assert result is response
    assert response.metadata["knowledge_mount_warning"] == "dangling!"


def _dedup_manager_with_hits(hits):
    """Build a memory manager whose node_search returns the given hits."""
    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )

    mgr = object.__new__(ReMeLightMemoryManager)
    response = SimpleNamespace(success=True, answer="", metadata={"hits": hits})

    async def _fake_run(name, **kwargs):
        assert name == "node_search"
        prefixes = kwargs.get("prefixes") or []
        assert any(str(p).endswith("business/") or str(p).endswith("wiki/") for p in prefixes)
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    return mgr


def _dedup_cfg(threshold=0.78, knowledge_dir_name="knowledge"):
    return SimpleNamespace(
        knowledge_dir_name=knowledge_dir_name,
        knowledge_dedup_threshold=threshold,
    )


def test_dedup_search_flags_similar_kb_node_name():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [{"path": "knowledge/wiki/客户画像.md", "name": "客户画像", "score": 0.9}],
    )
    probe = mgr._build_knowledge_dedup_search(_dedup_cfg())
    # "客户画像分析" vs "客户画像" → ratio 0.8 >= 0.78 → duplicate.
    assert asyncio.run(probe("客户画像分析", "基于订单")) is True


def test_dedup_search_skips_dissimilar_kb_node_name():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [{"path": "knowledge/wiki/退款政策.md", "name": "退款政策", "score": 0.9}],
    )
    probe = mgr._build_knowledge_dedup_search(_dedup_cfg())
    # "退款政策" vs "退款流程" → ratio 0.5 < 0.78 → not a duplicate.
    assert asyncio.run(probe("退款流程", "退货")) is False


def test_dedup_search_ignores_inbox_nodes():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [
            {"path": "knowledge/_inbox/客户画像.md", "name": "客户画像", "score": 0.95},
            {"path": "knowledge/wiki/其他.md", "name": "其他", "score": 0.3},
        ],
    )
    probe = mgr._build_knowledge_dedup_search(_dedup_cfg())
    # Inbox hit must be ignored; the only published node is unrelated.
    assert asyncio.run(probe("客户画像分析", "x")) is False


def test_dedup_search_flags_extract_alias_name():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [{"path": "knowledge/wiki/退款政策.md", "name": "退款政策", "score": 0.9}],
    )
    probe = mgr._build_knowledge_dedup_search(_dedup_cfg())
    assert asyncio.run(probe("退款政策-补充", "7天无理由")) is True


def test_dedup_search_flags_claim_overlap_near_miss_titles():
    import asyncio

    shared = "消费者在收货后7天内可无理由退换，商品须完好。"
    mgr = _dedup_manager_with_hits(
        [{
            "path": "knowledge/wiki/退款口径.md",
            "name": "退款口径",
            "description": shared,
            "score": 0.9,
        }],
    )
    probe = mgr._build_knowledge_dedup_search(_dedup_cfg())
    assert asyncio.run(probe("退款规则", shared)) is True
    assert asyncio.run(probe("退款规则", "GMV统计口径不含增值税")) is False


def _merge_cfg(
    *,
    merge_threshold=0.82,
    margin=0.15,
    related_threshold=0.45,
    dedup_threshold=0.78,
    knowledge_dir_name="knowledge",
):
    return SimpleNamespace(
        knowledge_dir_name=knowledge_dir_name,
        knowledge_merge_threshold=merge_threshold,
        knowledge_merge_margin=margin,
        knowledge_related_threshold=related_threshold,
        knowledge_dedup_threshold=dedup_threshold,
    )


def test_merge_search_alias_name_is_clear_target():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [{"path": "knowledge/business/wiki/退款政策.md", "name": "退款政策", "score": 0.9}],
    )
    probe = mgr._build_knowledge_merge_search(_merge_cfg())
    cand = asyncio.run(probe("退款政策-补充", "7天无理由"))
    assert cand is not None
    assert cand.is_clear is True
    assert cand.path.endswith("business/wiki/退款政策.md")
    assert cand.path.startswith("business/") or "退款政策" in cand.path


def test_merge_search_claim_overlap_is_clear_target():
    import asyncio

    shared = "消费者在收货后7天内可无理由退换，商品须完好。"
    mgr = _dedup_manager_with_hits(
        [{
            "path": "knowledge/business/wiki/退款口径.md",
            "name": "退款口径",
            "description": shared,
            "score": 0.9,
        }],
    )
    probe = mgr._build_knowledge_merge_search(_merge_cfg())
    cand = asyncio.run(probe("退款规则", shared))
    assert cand is not None
    assert cand.is_clear is True
    assert cand.path.endswith("business/wiki/退款口径.md")


def test_merge_search_near_dup_keeps_path_for_inbox():
    """Name similar enough to dedup but not to auto-merge → path + not clear."""
    import asyncio

    mgr = _dedup_manager_with_hits(
        [{"path": "knowledge/wiki/客户画像.md", "name": "客户画像", "score": 0.9}],
    )
    probe = mgr._build_knowledge_merge_search(_merge_cfg())
    cand = asyncio.run(probe("客户画像分析", "基于订单"))
    assert cand is not None
    assert cand.is_clear is False
    assert cand.path  # must not be empty (would CREATE a near-dup)


def test_catalog_search_returns_name_and_bucket():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [
            {
                "path": "knowledge/business/wiki/退款政策.md",
                "name": "退款政策",
                "score": 0.9,
            },
            {
                "path": "knowledge/_inbox/草稿.md",
                "name": "草稿",
                "score": 0.99,
            },
        ],
    )
    probe = mgr._build_knowledge_catalog_search(_merge_cfg())
    hits = asyncio.run(probe("今天讨论退款"))
    assert hits == [("退款政策", "business/wiki")]


def test_catalog_search_failure_returns_empty():
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )

    mgr = object.__new__(ReMeLightMemoryManager)

    async def _boom(name, **kwargs):
        raise RuntimeError("down")

    mgr._run_reme_job = _boom  # type: ignore[method-assign]
    probe = mgr._build_knowledge_catalog_search(_merge_cfg())
    assert asyncio.run(probe("退款")) == []


def test_merge_search_related_only_uses_empty_path():
    import asyncio

    mgr = _dedup_manager_with_hits(
        [
            {"path": "knowledge/wiki/订单流程.md", "name": "订单流程", "score": 0.5},
        ],
    )
    probe = mgr._build_knowledge_merge_search(_merge_cfg())
    # "退款政策" vs "订单流程" is weak; if it clears related floor it is
    # synapse-only (empty path). If it does not, probe returns None.
    cand = asyncio.run(probe("退款政策", "退货"))
    if cand is not None:
        assert cand.is_clear is False
        assert cand.path == ""


def test_dedup_search_failure_is_non_blocking():
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
    )

    mgr = object.__new__(ReMeLightMemoryManager)

    async def _failing_run(name, **kwargs):
        raise RuntimeError("index unavailable")

    mgr._run_reme_job = _failing_run  # type: ignore[method-assign]
    probe = mgr._build_knowledge_dedup_search(_dedup_cfg())
    # Failure → False (do not block publishing).
    assert asyncio.run(probe("客户画像", "s")) is False


def test_validate_kb_id_rejects_bad_values():
    from qwenpaw.agents.knowledge.store import validate_kb_id

    with pytest.raises(ValueError):
        validate_kb_id("")
    with pytest.raises(ValueError):
        validate_kb_id("../x")
    assert validate_kb_id("ok_1") == "ok_1"


def test_create_default_rejects_knowledge_base_id(client, fake_config, tmp_path):
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch("qwenpaw.app.routers.agents.save_agent_config"),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch(
            "qwenpaw.app.routers.agents.WORKING_DIR",
            str(tmp_path),
        ),
        patch("qwenpaw.app.routers.agents.assert_unique_workspace"),
    ):
        response = client.post(
            "/api/agents",
            json={
                "id": "no-kb",
                "name": "NoKB",
                "agent_type": DEFAULT_AGENT_TYPE,
                "knowledge_base_id": "should_fail",
                "workspace_dir": str(tmp_path / "no-kb"),
            },
        )
    assert response.status_code == 400
