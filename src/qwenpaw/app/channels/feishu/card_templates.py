# -*- coding: utf-8 -*-
"""Feishu interactive-card templates.

Pure, side-effect-free helpers that build card JSON payloads and parse
``card.action.trigger`` values. Grouped by card kind; when more card
kinds are added (e.g. poll, form), put their builders + parsers here.

Kept separate from :mod:`card_handler` so the templates are easy to
unit-test and reuse without pulling in any channel-level dependency.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


# =====================================================================
# Shared utilities
# =====================================================================


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


# =====================================================================
# Tool-guard approval card
# =====================================================================

# Marker in ``CallBackAction.value`` that identifies tool-guard
# approve/deny buttons; avoids clashing with other interactive cards.
TOOL_GUARD_ACTION_TYPE = "tool_guard_approval"

_TOOL_GUARD_SEVERITY_TEMPLATE = {
    "critical": "red",
    "high": "red",
    "medium": "orange",
    "low": "yellow",
}


def _tool_guard_severity_template(severity: str) -> str:
    return _TOOL_GUARD_SEVERITY_TEMPLATE.get(
        (severity or "").lower(),
        "orange",
    )


def build_tool_guard_approval_card(
    *,
    request_id: str,
    tool_name: str,
    severity: str,
    body_text: str,
    session_ctx: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the tool-guard approval card JSON string.

    ``body_text`` is the pre-rendered markdown body produced by
    tool_guard_mixin and used verbatim.

    A snapshot of ``body_text`` plus ``session_ctx`` (session_id /
    sender_id / receive_id / chat_id / ...) is embedded in each button's
    ``value``, so the inbound handler can rebuild the resolved card and
    re-inject a ``/approval`` command without any extra API call.
    """
    text = body_text or ""
    markdown_content = _truncate(text, 1800)
    body_snapshot = _truncate(text, 1500)
    ctx_snapshot = dict(session_ctx or {})
    approve_value = {
        "type": TOOL_GUARD_ACTION_TYPE,
        "action": "approve",
        "request_id": request_id,
        "tool_name": tool_name,
        "severity": severity or "medium",
        "body": body_snapshot,
        "session_ctx": ctx_snapshot,
    }
    deny_value = {**approve_value, "action": "deny"}

    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": _tool_guard_severity_template(severity),
            "title": {
                "tag": "plain_text",
                "content": "🛡️ Tool Approval Required",
            },
        },
        "elements": [
            {"tag": "markdown", "content": markdown_content},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ Approve",
                        },
                        "type": "primary",
                        "value": approve_value,
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ Deny",
                        },
                        "type": "danger",
                        "value": deny_value,
                    },
                ],
            },
        ],
    }
    return json.dumps(card, ensure_ascii=False)


def build_tool_guard_resolved_card(
    *,
    tool_name: str,
    action: str,
    operator_display: str = "",
    body_text: str = "",
) -> str:
    """Card that replaces the original one after a button click.

    ``action`` is the raw button action string (``"approve"`` /
    ``"deny"``); any other value falls back to an expired/unknown
    state.  Kept free of the tool-guard enum so templates stay pure-data.

    ``body_text`` (the original approval body) is preserved; only the
    button row is replaced by a single status line.
    """
    by = f" by `{operator_display}`" if operator_display else ""
    if action == "approve":
        title = "✅ Approved"
        template = "green"
        status_line = f"Tool `{tool_name}` approved{by}."
    elif action == "deny":
        title = "🚫 Denied"
        template = "red"
        status_line = f"Tool `{tool_name}` denied{by}."
    else:
        title = "⌛ Expired"
        template = "grey"
        status_line = f"Approval for `{tool_name}` has expired."

    elements: list = []
    if body_text:
        elements.append(
            {"tag": "markdown", "content": _truncate(body_text, 1800)},
        )
        elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": status_line})

    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }
    return json.dumps(card, ensure_ascii=False)


def parse_tool_guard_action_value(
    action_value: Any,
) -> Optional[Dict[str, Any]]:
    """Extract tool-guard action fields from a card.action.trigger payload.

    Returns ``None`` if the value does not look like a tool-guard button.
    """
    if not isinstance(action_value, dict):
        return None
    if action_value.get("type") != TOOL_GUARD_ACTION_TYPE:
        return None
    action = str(action_value.get("action") or "").strip().lower()
    request_id = str(action_value.get("request_id") or "").strip()
    if not request_id or action not in ("approve", "deny"):
        return None
    raw_ctx = action_value.get("session_ctx")
    session_ctx = raw_ctx if isinstance(raw_ctx, dict) else {}
    return {
        "action": action,
        "request_id": request_id,
        "tool_name": str(action_value.get("tool_name") or ""),
        "severity": str(action_value.get("severity") or "medium"),
        "body": str(action_value.get("body") or ""),
        "session_ctx": session_ctx,
    }


def build_tool_guard_toast(
    action: str,
    tool_name: str,
) -> Dict[str, Any]:
    """Build a toast payload for the card.action.trigger response.

    ``action`` is the raw button action string; unknown values fall
    back to an expired/unknown warning.
    """
    if action == "approve":
        return {
            "type": "success",
            "content": f"Approved tool {tool_name}",
        }
    if action == "deny":
        return {
            "type": "info",
            "content": f"Denied tool {tool_name}",
        }
    return {
        "type": "warning",
        "content": "Approval request has expired",
    }
