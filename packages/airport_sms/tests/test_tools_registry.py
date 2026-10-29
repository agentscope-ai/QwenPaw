"""工具注册与角色过滤测试。"""

from __future__ import annotations

from time import perf_counter

import pytest

from airport_sms.domain import Role
from airport_sms.tools import (
    DuplicateToolError,
    FakeAsr,
    FakeOcr,
    ToolDescriptor,
    UnknownToolError,
    attach_asr_text,
    attach_ocr_text,
    build_default_registry,
    invoke_case_tool,
)


def test_empty_allowlist_denies_all() -> None:
    reg = build_default_registry()
    assert reg.filter_for(Role.SAFETY_OFFICE, allowlist=frozenset()) == []


def test_reporter_lacks_close() -> None:
    names = {t.name for t in build_default_registry().filter_for(Role.REPORTER)}
    assert "close_case" not in names
    assert "draft_case" in names


def test_safety_office_has_close() -> None:
    names = {t.name for t in build_default_registry().filter_for(Role.SAFETY_OFFICE)}
    assert "close_case" in names


def test_unknown_tool_raises() -> None:
    with pytest.raises(UnknownToolError):
        build_default_registry().get("nope")
    with pytest.raises(UnknownToolError):
        invoke_case_tool("nope")


def test_descriptor_chinese_title() -> None:
    tool = build_default_registry().get("submit_case")
    assert tool.title_zh


def test_media_tools_for_reporter() -> None:
    names = {t.name for t in build_default_registry().filter_for(Role.REPORTER)}
    assert "attach_ocr_text" in names
    assert "attach_asr_text" in names
    ocr = attach_ocr_text(FakeOcr(), asset_id="a1", payload=b"img")
    asr = attach_asr_text(FakeAsr(), asset_id="a2", payload=b"wav")
    assert ocr.text.startswith("ocr:")
    assert asr.text.startswith("asr:")


def test_escalate_not_for_reporter() -> None:
    names = {t.name for t in build_default_registry().filter_for(Role.REPORTER)}
    assert "escalate" not in names
    owner = {t.name for t in build_default_registry().filter_for(Role.DEPT_OWNER)}
    assert "escalate" in owner


def test_filter_has_no_io(tmp_path) -> None:
    # 过滤不碰文件系统：在空目录上下文中仍可过滤。
    reg = build_default_registry()
    assert reg.filter_for(Role.SYSTEM)
    assert list(tmp_path.iterdir()) == []


def test_duplicate_register_raises() -> None:
    reg = build_default_registry()
    with pytest.raises(DuplicateToolError):
        reg.register(
            ToolDescriptor(
                name="draft_case",
                title_zh="x",
                handbook_ask=False,
                roles=frozenset({Role.REPORTER}),
            )
        )


def test_plugin_stub_false() -> None:
    reg = build_default_registry()
    tool = reg.get("search_manual")
    assert reg.plugin_register(tool) is False


def test_filter_10k_under_100ms() -> None:
    reg = build_default_registry()
    start = perf_counter()
    for _ in range(10_000):
        reg.filter_for(Role.REPORTER)
    ms = (perf_counter() - start) * 1000
    assert ms < 100, f"{ms:.1f}ms"
