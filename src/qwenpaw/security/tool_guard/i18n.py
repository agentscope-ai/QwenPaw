# -*- coding: utf-8 -*-
"""Tool guard i18n bundles."""

from __future__ import annotations

_TOOL_GUARD_I18N: dict[str, dict[str, str]] = {
    "en": {
        "wait_title": "⏳ Waiting for approval",
        "risk_detected": "⚠️ **Risk detected**",
        "tool_blocked": "⛔ **Tool blocked**",
        "tool": "Tool",
        "severity": "Severity",
        "findings": "Findings",
        "risk_summary": "Risk summary",
        "triggered_by": "Triggered by",
        "parameters": "Parameters",
        "approve_hint": (
            "Type `/approve` to approve, or send any message to deny."
        ),
        "blocked_footer": ("This tool is blocked and cannot be approved."),
        "denied_list_msg": "This tool is on the deny list.",
        "word_unknown": "unknown",
        "risk_not_available": "not available",
        "na_count": "N/A",
        "severity_denied": "DENIED",
        "sev_CRITICAL": "Critical",
        "sev_HIGH": "High",
        "sev_MEDIUM": "Medium",
        "sev_LOW": "Low",
        "sev_INFO": "Info",
        "sev_SAFE": "Safe",
        "guard_label_mixed": "Tool Guard & File Guard",
        "guard_label_file": "File Guard",
        "guard_label_tool": "Tool Guard",
        "guard_hint_mixed": (
            "Triggered by tool and file guardrails "
            "(Security → Tool Guard / File Guard)."
        ),
        "guard_hint_file": (
            "Triggered by file guardrails (Security → File Guard)."
        ),
        "guard_hint_tool": (
            "Triggered by tool guardrails (Security → Tool Guard)."
        ),
    },
    "zh": {
        "wait_title": "⏳ 等待审批",
        "risk_detected": "⚠️ **检测到风险**",
        "tool_blocked": "⛔ **工具已拦截**",
        "tool": "工具",
        "severity": "严重性",
        "findings": "发现",
        "risk_summary": "风险说明",
        "triggered_by": "触发来源",
        "parameters": "参数",
        "approve_hint": "输入 `/approve` 批准执行，或发送任意消息拒绝。",
        "blocked_footer": "该工具已被禁止，无法批准执行。",
        "denied_list_msg": "该工具在禁止列表中。",
        "word_unknown": "未知",
        "risk_not_available": "暂不可用",
        "na_count": "不适用",
        "severity_denied": "已拦截",
        "sev_CRITICAL": "危急",
        "sev_HIGH": "高",
        "sev_MEDIUM": "中",
        "sev_LOW": "低",
        "sev_INFO": "提示",
        "sev_SAFE": "无风险",
        "guard_label_mixed": "工具护栏与文件护栏",
        "guard_label_file": "文件护栏",
        "guard_label_tool": "工具护栏",
        "guard_hint_mixed": ("由工具与文件护栏触发（可在「安全 → 工具护栏 / 文件护栏」" "调整）。"),
        "guard_hint_file": ("由文件护栏触发（可在「安全 → 文件护栏」调整）。"),
        "guard_hint_tool": ("由工具护栏触发（可在「安全 → 工具护栏」调整）。"),
    },
    "ru": {
        "wait_title": "⏳ Ожидание подтверждения",
        "risk_detected": "⚠️ **Обнаружен риск**",
        "tool_blocked": "⛔ **Инструмент заблокирован**",
        "tool": "Инструмент",
        "severity": "Уровень угрозы",
        "findings": "Находки",
        "risk_summary": "Описание риска",
        "triggered_by": "Источник",
        "parameters": "Параметры",
        "approve_hint": (
            "Введите `/approve` для согласования или отправьте любое "
            "сообщение для отказа."
        ),
        "blocked_footer": ("Инструмент заблокирован, утверждение невозможно."),
        "denied_list_msg": "Инструмент в списке запрета.",
        "word_unknown": "неизвестно",
        "risk_not_available": "недоступно",
        "na_count": "н/д",
        "severity_denied": "ЗАПРЕТ",
        "sev_CRITICAL": "Критический",
        "sev_HIGH": "Высокий",
        "sev_MEDIUM": "Средний",
        "sev_LOW": "Низкий",
        "sev_INFO": "Сведение",
        "sev_SAFE": "Безопасно",
        "guard_label_mixed": "Защита инструментов и файлов",
        "guard_label_file": "Защита файлов",
        "guard_label_tool": "Защита инструментов",
        "guard_hint_mixed": (
            "Сработали правила защиты инструментов и файлов "
            "(«Безопасность» → защита инструментов/файлов)."
        ),
        "guard_hint_file": (
            "Сработала защита файлов («Безопасность» → защита файлов)."
        ),
        "guard_hint_tool": (
            "Сработала защита инструментов («Безопасность» → "
            "защита инструментов)."
        ),
    },
    "ja": {
        "wait_title": "⏳ 承認待ち",
        "risk_detected": "⚠️ **リスクが検出されました**",
        "tool_blocked": "⛔ **ツールはブロックされました**",
        "tool": "ツール",
        "severity": "重要度",
        "findings": "検出件数",
        "risk_summary": "リスク概要",
        "triggered_by": "発火元",
        "parameters": "パラメータ",
        "approve_hint": ("`/approve` と入力して承認するか、" "拒否するには任意のメッセージを送信してください。"),
        "blocked_footer": ("このツールはブロックされており、承認できません。"),
        "denied_list_msg": "このツールは拒否リストにあります。",
        "word_unknown": "不明",
        "risk_not_available": "取得できません",
        "na_count": "該当なし",
        "severity_denied": "拒否",
        "sev_CRITICAL": "重大",
        "sev_HIGH": "高",
        "sev_MEDIUM": "中",
        "sev_LOW": "低",
        "sev_INFO": "情報",
        "sev_SAFE": "問題なし",
        "guard_label_mixed": "ツールガードとファイルガード",
        "guard_label_file": "ファイルガード",
        "guard_label_tool": "ツールガード",
        "guard_hint_mixed": (
            "ツールおよびファイルのガードにより発火しました（" "「セキュリティ」→ ツールガード / ファイルガードで変更）。"
        ),
        "guard_hint_file": ("ファイルガードにより発火しました（" "「セキュリティ」→ ファイルガードで変更）。"),
        "guard_hint_tool": ("ツールガードにより発火しました（" "「セキュリティ」→ ツールガードで変更）。"),
    },
}
