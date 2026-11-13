# -*- coding: utf-8 -*-
"""i18n bundles for the /approval control command replies.

Mirrors the layout of ``security/tool_guard/i18n.py``: one flat
``{lang: {key: template}}`` mapping. Templates use ``str.format``
placeholders.
"""

from __future__ import annotations

from typing import Any

# Language used when neither the channel nor the agent config carries one.
# Matches the defaults of ``BaseChannel._language`` and
# ``AgentProfileConfig.language``.
DEFAULT_LANGUAGE = "zh"

_APPROVAL_I18N: dict[str, dict[str, str]] = {
    "en": {
        "identity_denied": (
            "❌ **Permission denied**\n\n"
            "This approval can only be handled by the same user, channel "
            "and session that made the request."
        ),
        "no_pending": (
            "❌ **No pending approvals**\n\n"
            "There are no tool calls awaiting approval in this session."
        ),
        "not_found": (
            "❌ **Approval request not found**\n\n"
            "Request ID: `{request_id}`\n\n"
            "It may have already been handled or timed out."
        ),
        "approve_other_agent": (
            "❌ **Permission denied**\n\n"
            "Cannot approve tool requests of another agent.\n"
            "- Request agent: `{owner_agent_id}`\n"
            "- Current agent: `{agent_id}`"
        ),
        "deny_other_agent": (
            "❌ **Permission denied**\n\n"
            "Cannot deny tool requests of another agent.\n"
            "- Request agent: `{owner_agent_id}`\n"
            "- Current agent: `{agent_id}`"
        ),
        "already_resolved": (
            "The approval request was already handled or timed out.\n\n"
            "Request ID: `{request_id}`"
        ),
        "approve_cross_session": (
            "\n\n🔗 **Cross-session action**\n"
            "Approved a tool from another session: `{session_id}`"
        ),
        "approve_cross_subagent": (
            "\n\n🔗 **Cross-session action**\n"
            "Approved a sub-agent tool (Session: `{session_id}`)"
        ),
        "deny_cross_session": (
            "\n\n🔗 **Cross-session action**\n"
            "Denied a tool from another session: `{session_id}`"
        ),
        "deny_cross_subagent": (
            "\n\n🔗 **Cross-session action**\n"
            "Denied a sub-agent tool (Session: `{session_id}`)"
        ),
        "approved": (
            "✅ **Tool approved**\n\n"
            "- Tool: `{tool_name}`\n"
            "- Request ID: `{request_id}`\n"
            "- Status: executing...{hint}"
        ),
        "denied": (
            "🚫 **Tool denied**\n\n"
            "- Tool: `{tool_name}`\n"
            "- Request ID: `{request_id}`\n"
            "- Reason: {reason}{hint}"
        ),
        "default_deny_reason": "Denied by user",
        "list_header_all": (
            "📋 **All pending approvals** (visible to current caller)\n"
        ),
        "list_header_session": ("📋 **Pending approvals** (current session)\n"),
        "list_empty": (
            "✅ **No pending approvals**\n\n"
            "There are no tool calls awaiting approval."
        ),
        "list_subsession": " [Sub-session: `{session_id}`]",
        "list_session": " [Session: `{session_id}`]",
        "list_item": (
            "{index}. `{tool_name}` {emoji} `{severity}` "
            "- {elapsed}s ago{session_info}\n"
            "   Request ID: `{request_id}`\n"
            "   Findings: {findings_count}\n"
        ),
        "list_footer": (
            "\n💡 **Tips**\n"
            "- Approve: `/approval approve <request_id>` "
            "(works across sessions)\n"
            "- Deny: `/approval deny <request_id>`\n"
            "- Show all: `/approval list --all` or `/approval list -a`"
        ),
        "cancel_missing_id": (
            "❌ **Missing argument**\n\n"
            "Usage: `/approval cancel <request_id>`\n\n"
            "Use `/approval list` to see pending approvals and their IDs."
        ),
        "cancel_not_found": (
            "❌ **Approval request not found**\n\n" "Request ID: `{request_id}`"
        ),
        "cancelled": (
            "✅ **Approval request cancelled**\n\n"
            "- Tool: `{tool_name}`\n"
            "- Request ID: `{request_id}`"
        ),
        "usage": (
            "**Usage: /approval**\n\n"
            "Manage tool approval requests\n\n"
            "**Subcommands**:\n"
            "- `approve [request_id] [--exact|--pattern]` - approve a tool "
            "call\n"
            "  (`--pattern` records a generalized rule; default/`--exact` "
            "records the literal call only)\n"
            "- `deny [request_id] [reason]` - deny a tool call\n"
            "- `list` - list all pending approvals\n"
            "- `cancel <request_id>` - cancel a specific approval\n\n"
            "**Examples**:\n"
            "```\n"
            "/approval approve          # approve the queue head\n"
            "/approval deny             # deny the queue head\n"
            "/approval list             # show pending approvals\n"
            "/approval approve abc123   # approve a specific request\n"
            "```"
        ),
    },
    "zh": {
        "identity_denied": ("❌ **权限不足**\n\n" "此审批只能由发起请求的同一用户、频道和会话处理。"),
        "no_pending": ("❌ **无待审批工具**\n\n" "当前会话没有需要审批的工具调用。"),
        "not_found": (
            "❌ **审批请求不存在**\n\n" "请求 ID: `{request_id}`\n\n" "可能已被处理或已超时。"
        ),
        "approve_other_agent": (
            "❌ **权限不足**\n\n"
            "无法审批其他Agent的工具请求。\n"
            "- 请求所属Agent: `{owner_agent_id}`\n"
            "- 当前Agent: `{agent_id}`"
        ),
        "deny_other_agent": (
            "❌ **权限不足**\n\n"
            "无法拒绝其他Agent的工具请求。\n"
            "- 请求所属Agent: `{owner_agent_id}`\n"
            "- 当前Agent: `{agent_id}`"
        ),
        "already_resolved": ("审批请求已处理或已超时。\n\n" "请求 ID: `{request_id}`"),
        "approve_cross_session": (
            "\n\n🔗 **跨Session操作**\n" "审批了其他会话的工具: `{session_id}`"
        ),
        "approve_cross_subagent": (
            "\n\n🔗 **跨Session操作**\n" "审批了子Agent的工具 (Session: `{session_id}`)"
        ),
        "deny_cross_session": (
            "\n\n🔗 **跨Session操作**\n" "拒绝了其他会话的工具: `{session_id}`"
        ),
        "deny_cross_subagent": (
            "\n\n🔗 **跨Session操作**\n" "拒绝了子Agent的工具 (Session: `{session_id}`)"
        ),
        "approved": (
            "✅ **工具已批准**\n\n"
            "- 工具: `{tool_name}`\n"
            "- 请求 ID: `{request_id}`\n"
            "- 状态: 正在执行...{hint}"
        ),
        "denied": (
            "🚫 **工具已拒绝**\n\n"
            "- 工具: `{tool_name}`\n"
            "- 请求 ID: `{request_id}`\n"
            "- 原因: {reason}{hint}"
        ),
        "default_deny_reason": "用户拒绝",
        "list_header_all": "📋 **全局待审批工具列表** (当前调用者可见)\n",
        "list_header_session": "📋 **待审批工具列表** (当前会话)\n",
        "list_empty": "✅ **无待审批工具**\n\n当前无需要审批的工具调用。",
        "list_subsession": " [子Session: `{session_id}`]",
        "list_session": " [Session: `{session_id}`]",
        "list_item": (
            "{index}. `{tool_name}` {emoji} `{severity}` "
            "- {elapsed}s 前{session_info}\n"
            "   请求 ID: `{request_id}`\n"
            "   发现问题: {findings_count} 个\n"
        ),
        "list_footer": (
            "\n💡 **操作提示**\n"
            "- 批准: `/approval approve <request_id>` (支持跨session审批)\n"
            "- 拒绝: `/approval deny <request_id>`\n"
            "- 全局查看: `/approval list --all` 或 `/approval list -a`"
        ),
        "cancel_missing_id": (
            "❌ **缺少参数**\n\n"
            "用法: `/approval cancel <request_id>`\n\n"
            "使用 `/approval list` 查看待审批列表及其 ID。"
        ),
        "cancel_not_found": "❌ **审批请求不存在**\n\n请求 ID: `{request_id}`",
        "cancelled": (
            "✅ **审批请求已取消**\n\n"
            "- 工具: `{tool_name}`\n"
            "- 请求 ID: `{request_id}`"
        ),
        "usage": (
            "**使用说明: /approval**\n\n"
            "管理工具审批请求\n\n"
            "**子命令**:\n"
            "- `approve [request_id] [--exact|--pattern]` - 批准工具执行\n"
            "  (`--pattern` 记录泛化规则; 默认/`--exact` 仅记录原文)\n"
            "- `deny [request_id] [reason]` - 拒绝工具执行\n"
            "- `list` - 列出所有待审批工具\n"
            "- `cancel <request_id>` - 取消指定审批\n\n"
            "**示例**:\n"
            "```\n"
            "/approval approve          # 批准队首工具\n"
            "/approval deny             # 拒绝队首工具\n"
            "/approval list             # 查看待审批列表\n"
            "/approval approve abc123   # 批准指定工具\n"
            "```"
        ),
    },
}


def normalize_approval_language(language: Any) -> str:
    """Map an agent/channel language to a bundle key (``zh`` or ``en``).

    Same rule as ``BaseChannel._acl_msg``: ``zh*`` maps to ``zh``, any
    other non-empty language falls back to ``en``. An unknown (empty)
    language keeps the project default.
    """
    lang = str(language or "").strip().lower()
    if not lang:
        return DEFAULT_LANGUAGE
    return "zh" if lang.startswith("zh") else "en"


def approval_text(language: str, key: str, **kwargs: Any) -> str:
    """Return the reply text *key* in *language*, formatted with kwargs."""
    bundle = _APPROVAL_I18N.get(
        normalize_approval_language(language),
        _APPROVAL_I18N["en"],
    )
    template = bundle[key]
    return template.format(**kwargs) if kwargs else template
