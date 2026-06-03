# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tool_guard_mixin.

Covers:
- _normalize_tool_guard_ui_lang
- _tool_guard_t
- _GuardAction
- ToolGuardMixin._should_require_approval
- ToolGuardMixin._get_tool_execution_level
- ToolGuardMixin._tool_guard_ui_lang
- ToolGuardMixin._decide_guard_action
- ToolGuardMixin._create_info_guard_result
- ToolGuardMixin._severity_emoji_and_localized_name
- ToolGuardMixin._acting (partial)
"""
# pylint: disable=protected-access,unused-argument

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.agents.tool_guard_mixin import (
    _GuardAction,
    _normalize_tool_guard_ui_lang,
    _tool_guard_t,
)
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel
from qwenpaw.security.tool_guard.models import (
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


# ---------------------------------------------------------------------------
# Helper to create a test mixin instance
# ---------------------------------------------------------------------------


def _make_mixin(**overrides):
    """Create a ToolGuardMixin instance with injected dependencies."""
    from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin

    instance = ToolGuardMixin()

    # Inject required attributes
    instance._tool_guard_engine = MagicMock()
    instance._tool_guard_approval_service = MagicMock()
    instance._tool_guard_pending_info = None
    instance._tool_guard_lock = asyncio.Lock()
    instance._request_context = overrides.pop(
        "_request_context",
        {"session_id": "test-session"},
    )
    instance._agent_config = overrides.pop("_agent_config", None)
    instance._language = overrides.pop("_language", "en")
    instance.name = "TestAgent"
    instance.memory = MagicMock()

    for k, v in overrides.items():
        setattr(instance, k, v)

    return instance


# ---------------------------------------------------------------------------
# _normalize_tool_guard_ui_lang
# ---------------------------------------------------------------------------


class TestNormalizeToolGuardUiLang:
    """Tests for _normalize_tool_guard_ui_lang."""

    def test_en(self):
        assert _normalize_tool_guard_ui_lang("en") == "en"

    def test_zh(self):
        assert _normalize_tool_guard_ui_lang("zh") == "zh"

    def test_ru(self):
        assert _normalize_tool_guard_ui_lang("ru") == "ru"

    def test_ja(self):
        assert _normalize_tool_guard_ui_lang("ja") == "ja"

    def test_zh_cn_prefix(self):
        assert _normalize_tool_guard_ui_lang("zh-CN") == "zh"

    def test_unknown_defaults_to_en(self):
        assert _normalize_tool_guard_ui_lang("fr") == "en"

    def test_empty_defaults_to_en(self):
        assert _normalize_tool_guard_ui_lang("") == "en"

    def test_none_defaults_to_en(self):
        assert _normalize_tool_guard_ui_lang(None) == "en"

    def test_whitespace_stripped(self):
        assert _normalize_tool_guard_ui_lang("  en  ") == "en"


# ---------------------------------------------------------------------------
# _tool_guard_t
# ---------------------------------------------------------------------------


class TestToolGuardT:
    """Tests for _tool_guard_t."""

    def test_returns_string(self):
        result = _tool_guard_t("en", "tool_blocked")
        assert isinstance(result, str)

    def test_fallback_to_en(self):
        result = _tool_guard_t("xx", "tool_blocked")
        assert isinstance(result, str)

    def test_unknown_key_returns_key(self):
        result = _tool_guard_t("en", "nonexistent_key_xyz")
        assert result == "nonexistent_key_xyz"


# ---------------------------------------------------------------------------
# _GuardAction
# ---------------------------------------------------------------------------


class TestGuardAction:
    """Tests for _GuardAction."""

    def test_init(self):
        action = _GuardAction(
            "auto_denied",
            "rm",
            {"command": "rm -rf /"},
            guard_result=MagicMock(),
        )
        assert action.kind == "auto_denied"
        assert action.tool_name == "rm"
        assert action.tool_input == {"command": "rm -rf /"}
        assert action.guard_result is not None

    def test_default_guard_result(self):
        action = _GuardAction("needs_approval", "ls", {})
        assert action.guard_result is None


# ---------------------------------------------------------------------------
# ToolGuardMixin._should_require_approval
# ---------------------------------------------------------------------------


class TestShouldRequireApproval:
    """Tests for _should_require_approval."""

    def test_with_session_id(self):
        m = _make_mixin(_request_context={"session_id": "s1"})
        assert m._should_require_approval() is True

    def test_without_session_id(self):
        m = _make_mixin(_request_context={})
        assert m._should_require_approval() is False

    def test_empty_session_id(self):
        m = _make_mixin(_request_context={"session_id": ""})
        assert m._should_require_approval() is False


# ---------------------------------------------------------------------------
# ToolGuardMixin._get_tool_execution_level
# ---------------------------------------------------------------------------


class TestGetToolExecutionLevel:
    """Tests for _get_tool_execution_level."""

    def test_no_config_returns_auto(self):
        m = _make_mixin(_agent_config=None)
        assert m._get_tool_execution_level() == ToolExecutionLevel.AUTO

    def test_dict_config_strict(self):
        m = _make_mixin(_agent_config={"approval_level": "STRICT"})
        assert m._get_tool_execution_level() == ToolExecutionLevel.STRICT

    def test_dict_config_smart(self):
        m = _make_mixin(_agent_config={"approval_level": "smart"})
        assert m._get_tool_execution_level() == ToolExecutionLevel.SMART

    def test_pydantic_config(self):
        mock_config = MagicMock()
        mock_config.approval_level = "OFF"
        # Make getattr work normally for non-approval_level attrs
        del mock_config.__getitem__
        m = _make_mixin(_agent_config=mock_config)
        assert m._get_tool_execution_level() == ToolExecutionLevel.OFF

    def test_invalid_defaults_to_auto(self):
        m = _make_mixin(_agent_config={"approval_level": "invalid"})
        assert m._get_tool_execution_level() == ToolExecutionLevel.AUTO


# ---------------------------------------------------------------------------
# ToolGuardMixin._tool_guard_ui_lang
# ---------------------------------------------------------------------------


class TestToolGuardUiLang:
    """Tests for _tool_guard_ui_lang."""

    def test_with_language(self):
        m = _make_mixin(_language="zh-CN")
        assert m._tool_guard_ui_lang() == "zh"

    def test_without_language(self):
        m = _make_mixin(_language=None)
        assert m._tool_guard_ui_lang() == "en"

    def test_empty_language(self):
        m = _make_mixin(_language="")
        assert m._tool_guard_ui_lang() == "en"


# ---------------------------------------------------------------------------
# ToolGuardMixin._decide_guard_action
# ---------------------------------------------------------------------------


class TestDecideGuardAction:
    """Tests for _decide_guard_action."""

    @pytest.mark.asyncio
    async def test_empty_tool_name_returns_none(self):
        m = _make_mixin()
        m._tool_guard_engine.enabled = True
        result = await m._decide_guard_action({"name": "", "input": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_engine_disabled_returns_none(self):
        m = _make_mixin()
        m._tool_guard_engine.enabled = False
        result = await m._decide_guard_action(
            {"name": "rm", "input": {}},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_off_mode_returns_none(self):
        m = _make_mixin(_agent_config={"approval_level": "OFF"})
        m._tool_guard_engine.enabled = True
        result = await m._decide_guard_action(
            {"name": "rm", "input": {}},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_denied_tool_auto_denies(self):
        m = _make_mixin(_agent_config={"approval_level": "AUTO"})
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = True
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[MagicMock()],
        )
        result = await m._decide_guard_action(
            {"name": "dangerous_tool", "input": {}},
        )
        assert result is not None
        assert result.kind == "auto_denied"

    @pytest.mark.asyncio
    async def test_strict_mode_needs_approval(self):
        m = _make_mixin(
            _agent_config={"approval_level": "STRICT"},
            _request_context={"session_id": "s1"},
        )
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = False
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[],
            max_severity=GuardSeverity.INFO,
        )
        m._tool_guard_engine.should_auto_deny_result.return_value = False
        result = await m._decide_guard_action(
            {"name": "any_tool", "input": {}},
        )
        assert result is not None
        assert result.kind == "needs_approval"

    @pytest.mark.asyncio
    async def test_auto_mode_no_findings_returns_none(self):
        m = _make_mixin(_agent_config={"approval_level": "AUTO"})
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = False
        m._tool_guard_engine.is_guarded.return_value = True
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[],
        )
        result = await m._decide_guard_action(
            {"name": "safe_tool", "input": {}},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_mode_with_findings_auto_denies(self):
        m = _make_mixin(_agent_config={"approval_level": "AUTO"})
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = False
        m._tool_guard_engine.is_guarded.return_value = True
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[MagicMock()],
            max_severity=GuardSeverity.CRITICAL,
        )
        m._tool_guard_engine.should_auto_deny_result.return_value = True
        result = await m._decide_guard_action(
            {"name": "risky_tool", "input": {}},
        )
        assert result is not None
        assert result.kind == "auto_denied"

    @pytest.mark.asyncio
    async def test_smart_mode_low_risk_auto_allows(self):
        m = _make_mixin(_agent_config={"approval_level": "SMART"})
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = False
        m._tool_guard_engine.is_guarded.return_value = True
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[MagicMock()],
            max_severity=GuardSeverity.LOW,
        )
        m._tool_guard_engine.should_auto_deny_result.return_value = False
        result = await m._decide_guard_action(
            {"name": "low_risk_tool", "input": {}},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_smart_mode_high_risk_needs_approval(self):
        m = _make_mixin(
            _agent_config={"approval_level": "SMART"},
            _request_context={"session_id": "s1"},
        )
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = False
        m._tool_guard_engine.is_guarded.return_value = True
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[MagicMock()],
            max_severity=GuardSeverity.HIGH,
        )
        m._tool_guard_engine.should_auto_deny_result.return_value = False
        result = await m._decide_guard_action(
            {"name": "high_risk_tool", "input": {}},
        )
        assert result is not None
        assert result.kind == "needs_approval"

    @pytest.mark.asyncio
    async def test_auto_mode_no_session_no_approval(self):
        m = _make_mixin(
            _agent_config={"approval_level": "AUTO"},
            _request_context={},
        )
        m._tool_guard_engine.enabled = True
        m._tool_guard_engine.is_denied.return_value = False
        m._tool_guard_engine.is_guarded.return_value = True
        m._tool_guard_engine.guard.return_value = MagicMock(
            findings=[MagicMock()],
            max_severity=GuardSeverity.HIGH,
        )
        m._tool_guard_engine.should_auto_deny_result.return_value = False
        # No session_id → cannot require approval → returns None
        result = await m._decide_guard_action(
            {"name": "tool", "input": {}},
        )
        assert result is None


# ---------------------------------------------------------------------------
# ToolGuardMixin._create_info_guard_result
# ---------------------------------------------------------------------------


class TestCreateInfoGuardResult:
    """Tests for _create_info_guard_result."""

    def test_creates_result_with_info_finding(self):
        m = _make_mixin()
        result = m._create_info_guard_result("rm", {"command": "rm -rf"})
        assert isinstance(result, ToolGuardResult)
        assert result.tool_name == "rm"
        assert len(result.findings) == 1
        assert result.findings[0].severity == GuardSeverity.INFO
        assert result.findings[0].rule_id == "strict_mode"

    def test_finding_has_correct_category(self):
        m = _make_mixin()
        result = m._create_info_guard_result("ls", {})
        assert (
            result.findings[0].category == GuardThreatCategory.RESOURCE_ABUSE
        )


# ---------------------------------------------------------------------------
# ToolGuardMixin._severity_emoji_and_localized_name
# ---------------------------------------------------------------------------


class TestSeverityEmojiAndLocalizedName:
    """Tests for _severity_emoji_and_localized_name."""

    def test_critical_emoji(self):
        from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin

        emoji, _ = ToolGuardMixin._severity_emoji_and_localized_name(
            GuardSeverity.CRITICAL,
            "en",
        )
        assert emoji == "\U0001f534"

    def test_high_emoji(self):
        from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin

        emoji, _ = ToolGuardMixin._severity_emoji_and_localized_name(
            GuardSeverity.HIGH,
            "en",
        )
        assert emoji == "\U0001f534"

    def test_medium_emoji(self):
        from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin

        emoji, _ = ToolGuardMixin._severity_emoji_and_localized_name(
            GuardSeverity.MEDIUM,
            "en",
        )
        assert emoji == "\U0001f7e1"

    def test_returns_localized_name(self):
        from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin

        _, loc_name = ToolGuardMixin._severity_emoji_and_localized_name(
            GuardSeverity.HIGH,
            "en",
        )
        assert isinstance(loc_name, str)
        assert len(loc_name) > 0


# ---------------------------------------------------------------------------
# ToolGuardMixin._ensure_tool_guard
# ---------------------------------------------------------------------------


class TestEnsureToolGuard:
    """Tests for _ensure_tool_guard."""

    def test_already_initialized(self):
        m = _make_mixin()
        # _tool_guard_engine already set by _make_mixin
        m._ensure_tool_guard()
        # Should not re-init

    @patch("qwenpaw.security.tool_guard.engine.get_guard_engine")
    @patch("qwenpaw.app.approvals.get_approval_service")
    def test_lazy_init(self, mock_approval, mock_engine):
        mock_engine.return_value = MagicMock()
        mock_approval.return_value = MagicMock()
        m = _make_mixin()
        # Remove the injected attributes to trigger lazy init
        del m._tool_guard_engine
        m._ensure_tool_guard()
        assert hasattr(m, "_tool_guard_engine")
        assert hasattr(m, "_tool_guard_approval_service")
        assert hasattr(m, "_tool_guard_lock")
