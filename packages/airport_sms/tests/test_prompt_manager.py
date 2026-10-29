"""系统提示组装行为。"""

from __future__ import annotations

import hashlib
import statistics
import time
from pathlib import Path

import pytest

from airport_sms.context.manual_index import (
    DEFAULT_MANUALS_DIR,
    ManualIndex,
    ManualNotFoundError,
)
from airport_sms.context.prompt_manager import (
    PromptContext,
    build_sms_prompt_manager,
    count_tokens,
)
from airport_sms.domain import CaseId, Role, new_draft

_CHANNEL_NAMES = ("wecom", "slack", "whatsapp", "telegram")


def _index() -> ManualIndex:
    """加载示例手册。"""
    index = ManualIndex(DEFAULT_MANUALS_DIR)
    index.load_file("sample.md")
    return index


def _manager(token_budget: int = 800):
    """默认管理器。"""
    return build_sms_prompt_manager(_index(), token_budget=token_budget)


def _case():
    """默认草稿。"""
    return new_draft(
        case_id=CaseId("C-9"),
        hazard="FOD on taxiway",
        location="TWY A",
    )


def test_hints_live_under_system_sections_only() -> None:
    """动态提示只出现在系统段，不会伪装成用户发言。"""
    assembled = _manager().build(
        PromptContext(
            role=Role.REPORTER,
            site_id="PEK",
            case=_case(),
            hints=("remember evidence photos",),
        )
    )
    assert "## system_hint" in assembled.system
    assert "remember evidence photos" in assembled.system
    lowered = assembled.system.lower()
    assert "user:" not in lowered
    assert "fake user" not in lowered


def test_reporter_prompt_has_duties_without_close_tools() -> None:
    """报告人提示含职责，不含关闭工具文案。"""
    assembled = _manager().build(
        PromptContext(role=Role.REPORTER, site_id="PEK", case=_case())
    )
    assert "报告隐患" in assembled.system
    assert "close_case" not in assembled.system
    assert "关闭案件权限" not in assembled.system


def test_safety_office_prompt_has_close_authority() -> None:
    """安全处提示含关闭权限。"""
    assembled = _manager().build(
        PromptContext(role=Role.SAFETY_OFFICE, site_id="PEK", case=_case())
    )
    assert "关闭案件权限" in assembled.system


def test_case_snapshot_includes_id_and_state() -> None:
    """案件快照含 id 与状态。"""
    case = _case()
    assembled = _manager().build(
        PromptContext(role=Role.DEPT_OWNER, site_id="PEK", case=case)
    )
    assert "C-9" in assembled.system
    assert "draft" in assembled.system


def test_cite_two_manual_clauses_on_proposal() -> None:
    """提案载荷列出两条手册条款。"""
    case = _case()
    ctx = PromptContext(
        role=Role.SAFETY_OFFICE,
        site_id="PEK",
        case=case,
        clause_ids=("SMS-1.1", "SMS-2.3"),
    )
    assembled, proposal, updated = _manager().propose(ctx, "ALARP close")
    assert "SMS-1.1" in assembled.system
    assert "SMS-2.3" in assembled.system
    assert proposal.cited_clause_ids == ("SMS-1.1", "SMS-2.3")
    assert updated is not None
    assert updated.cited_clauses == ("SMS-1.1", "SMS-2.3")
    assert updated.version == case.version + 1


def test_overflow_drops_lowest_priority_first() -> None:
    """超预算先丢掉优先级最低的 hint 段。"""
    huge_hint = "x" * 400
    assembled = _manager(token_budget=80).build(
        PromptContext(
            role=Role.REPORTER,
            site_id="PEK",
            case=_case(),
            hints=(huge_hint,),
        )
    )
    assert "hint" in assembled.dropped
    assert huge_hint not in assembled.system
    assert assembled.token_count <= 80
    assert "报告隐患" in assembled.system


def test_missing_manual_file_fails_closed() -> None:
    """手册缺失时抛出类型化错误。"""
    index = ManualIndex(DEFAULT_MANUALS_DIR)
    with pytest.raises(ManualNotFoundError):
        index.load_file("does-not-exist.md")


def test_missing_manuals_dir_fails_closed(tmp_path: Path) -> None:
    """手册目录不存在时失败关闭。"""
    index = ManualIndex(tmp_path / "nope")
    with pytest.raises(ManualNotFoundError):
        index.load_all()


def test_site_rule_section_includes_site_id() -> None:
    """场站规则段包含 site id。"""
    assembled = _manager().build(
        PromptContext(
            role=Role.REPORTER,
            site_id="CAN",
            site_rules="ramp speed limit 25",
        )
    )
    assert "site_id=CAN" in assembled.system
    assert "ramp speed limit 25" in assembled.system


def test_no_channel_marketing_text() -> None:
    """系统提示不含通道产品名。"""
    assembled = _manager().build(
        PromptContext(role=Role.REPORTER, site_id="PEK", case=_case())
    )
    lowered = assembled.system.lower()
    for name in _CHANNEL_NAMES:
        assert name not in lowered


def test_contributor_order_is_stable() -> None:
    """两次组装哈希相同。"""
    ctx = PromptContext(
        role=Role.SAFETY_OFFICE,
        site_id="PEK",
        case=_case(),
        clause_ids=("SMS-4.1",),
        hints=("keep citations",),
    )
    manager = _manager()
    first = manager.build(ctx)
    second = manager.build(ctx)
    assert first.digest() == second.digest()
    assert first.digest() == hashlib.sha256(first.system.encode()).hexdigest()
    assert manager.names() == [
        "role",
        "site_rules",
        "case_snapshot",
        "manual_clauses",
        "hint",
    ]


def test_prompt_build_p95_under_50ms() -> None:
    """完整组装 100 次 p95 低于 50ms。"""
    manager = _manager()
    ctx = PromptContext(
        role=Role.SAFETY_OFFICE,
        site_id="PEK",
        case=_case(),
        clause_ids=("SMS-1.1", "SMS-2.3"),
        hints=("cite manuals",),
    )
    samples: list[float] = []
    for _ in range(100):
        start = time.perf_counter()
        manager.build(ctx)
        samples.append((time.perf_counter() - start) * 1000)
    p95 = statistics.quantiles(samples, n=20)[-1]
    assert p95 < 50, f"p95 {p95:.1f}ms"


def test_count_tokens_matches_budget_units() -> None:
    """token 粗算与预算单位一致。"""
    assert count_tokens("") == 0
    assert count_tokens("abcd") == 1
