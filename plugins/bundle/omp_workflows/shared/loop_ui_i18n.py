# -*- coding: utf-8 -*-
"""OMP loop UI copy: names, menu summaries, and full help texts.

Menu short copy is bilingual (en / zh-CN). Full ``help`` is English for now;
zh-CN can be added later without changing call sites.
"""

from __future__ import annotations

from typing import Any

LOOP_UI_I18N: dict[str, dict[str, Any]] = {
    "ultrawork": {
        "name": {
            "en": "Ultrawork",
            "zh-CN": "Ultrawork",
        },
        "description": {
            "en": "**Ultrawork** — parallel task execution engine",
            "zh-CN": "**Ultrawork** — 并行任务执行引擎",
        },
        "help": {
            "en": (
                "**Ultrawork** — parallel task execution engine\n\n"
                "Usage: `/ultrawork <task description>`\n\n"
                "Decomposes the task into independent sub-tasks and executes\n"
                "them in parallel via spawn_subagent batch mode."
            ),
        },
    },
    "ralph": {
        "name": {
            "en": "Ralph",
            "zh-CN": "Ralph",
        },
        "description": {
            "en": ("**Ralph** — PRD-driven continuous implementation loop"),
            "zh-CN": "**Ralph** — PRD 驱动的持续实现循环",
        },
        "help": {
            "en": (
                "**Ralph** — PRD-driven continuous implementation loop\n\n"
                "Usage: `/ralph [--no-deslop] "
                "[--critic=architect|critic|codex] <task>`\n\n"
                "Creates a PRD with user stories, implements each one,\n"
                "verifies acceptance criteria, and runs reviewer verification."
            ),
        },
    },
    "autopilot": {
        "name": {
            "en": "Autopilot",
            "zh-CN": "Autopilot",
        },
        "description": {
            "en": "**Autopilot** — full lifecycle pipeline",
            "zh-CN": "**Autopilot** — 全生命周期流水线",
        },
        "help": {
            "en": (
                "**Autopilot** — full lifecycle pipeline\n\n"
                "Usage: `/autopilot [--skip-qa] "
                "[--skip-validation] <task>`\n\n"
                "Phases: expansion -> planning -> execution "
                "-> qa -> validation -> cleanup -> completed\n"
                "Validation uses 3 parallel reviewers "
                "(architect + security + code)."
            ),
        },
    },
    "ultraqa": {
        "name": {
            "en": "UltraQA",
            "zh-CN": "UltraQA",
        },
        "description": {
            "en": "**UltraQA** — automated QA cycle engine",
            "zh-CN": "**UltraQA** — 自动化 QA 循环引擎",
        },
        "help": {
            "en": (
                "**UltraQA** — automated QA cycle engine\n\n"
                "Usage:\n"
                "  `/ultraqa [--tests|--build|--lint|"
                '--typecheck|--custom "cmd"]'
                " [--interactive]`\n\n"
                "Runs repeated QA cycles: check → diagnose → fix → re-check.\n"
                "Stops when all checks pass or max cycles reached."
            ),
        },
    },
    "team": {
        "name": {
            "en": "Team",
            "zh-CN": "Team",
        },
        "description": {
            "en": "**Team** — multi-agent collaboration pipeline",
            "zh-CN": "**Team** — 多智能体协作流水线",
        },
        "help": {
            "en": (
                "**Team** — multi-agent collaboration pipeline\n\n"
                "Usage: `/team [N:role] <task>`\n\n"
                "Examples:\n"
                "  `/team 3:executor Implement authentication`\n"
                "  `/team ralph Build the REST API`\n\n"
                "Phases: plan -> prd -> exec -> verify -> fix (retry)"
            ),
        },
    },
}


def loop_ui(mode_key: str) -> dict[str, Any]:
    """Return the UI copy bundle for one OMP mode."""
    try:
        return LOOP_UI_I18N[mode_key]
    except KeyError as exc:
        raise KeyError(f"Unknown OMP loop UI key: {mode_key}") from exc


def _pick_locale(mapping: dict[str, str], lang: str = "en") -> str:
    if not mapping:
        return ""
    if lang in mapping and mapping[lang]:
        return mapping[lang]
    short = lang.split("-", 1)[0].lower()
    for key, value in mapping.items():
        if key.split("-", 1)[0].lower() == short and value:
            return value
    for key in ("en", "en-US", "zh-CN", "zh"):
        if mapping.get(key):
            return mapping[key]
    for value in mapping.values():
        if value:
            return value
    return ""


def loop_help_text(mode_key: str, lang: str = "en") -> str:
    """Full help text for CommandSpec / slash help handlers."""
    help_map = loop_ui(mode_key).get("help") or {}
    if not isinstance(help_map, dict):
        return ""
    return _pick_locale(help_map, lang)


def loop_command_metadata(mode_key: str) -> dict[str, Any]:
    """Metadata for CommandSpec: loop_name + i18n maps for GET /loops."""
    ui = loop_ui(mode_key)
    name_map = ui.get("name") or {}
    desc_map = ui.get("description") or {}
    return {
        "builtin": True,
        "loop_name": _pick_locale(name_map, "en") or mode_key,
        "name_i18n": dict(name_map) if isinstance(name_map, dict) else {},
        "description_i18n": dict(desc_map)
        if isinstance(desc_map, dict)
        else {},
    }
