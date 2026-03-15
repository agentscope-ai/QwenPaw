# -*- coding: utf-8 -*-
"""Shared data types for ACP runtime integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Literal


ACPEventType = Literal[
    "assistant_chunk",
    "thought_chunk",
    "tool_start",
    "tool_update",
    "tool_end",
    "plan_update",
    "commands_update",
    "usage_update",
    "permission_request",
    "permission_resolved",
    "run_finished",
    "error",
]


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


@dataclass
class ExternalAgentConfig:
    """External ACP agent request config derived from request extras."""

    enabled: bool
    harness: str
    keep_session: bool = False
    cwd: str | None = None
    existing_session_id: str | None = None
    prompt: str | None = None
    keep_session_specified: bool = False


@dataclass
class AcpEvent:
    """Internal ACP event emitted by runtime and consumed by the projector."""

    type: ACPEventType
    chat_id: str
    session_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ACPConversationSession:
    """Runtime state for one chat-bound ACP conversation."""

    chat_id: str
    harness: str
    acp_session_id: str
    cwd: str
    keep_session: bool
    capabilities: dict[str, Any] = field(default_factory=dict)
    active_run_id: str | None = None
    updated_at: datetime = field(default_factory=utc_now)
    runtime: Any | None = None


@dataclass
class ACPRunResult:
    """Summary returned after one ACP turn completes."""

    harness: str
    session_id: str | None
    keep_session: bool
    cwd: str


def normalize_harness_name(raw: str | None) -> str:
    """Normalize external-agent harness names from UI or request payloads."""
    name = (raw or "").strip().lower()
    aliases = {
        "qwen-code": "qwen",
        "qwen code": "qwen",
        "qwencode": "qwen",
        "open-code": "opencode",
        "open code": "opencode",
    }
    return aliases.get(name, name)


def _strip_quotes(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip() or None


def _looks_like_path(raw: str | None) -> bool:
    value = (raw or "").strip()
    return any(token in value for token in ("/", "\\", "~", ".", ":"))


def _pop_option_value(text: str, option_names: tuple[str, ...]) -> tuple[str | None, str]:
    escaped = "|".join(re.escape(name) for name in option_names)
    pattern = re.compile(
        rf"(?<!\S)(?:{escaped})(?:=|\s+)(\"[^\"]+\"|'[^']+'|\S+)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None, text
    value = _strip_quotes(match.group(1))
    updated = (text[:match.start()] + " " + text[match.end():]).strip()
    return value, re.sub(r"\s{2,}", " ", updated)


def _pop_flag(text: str, flag_names: tuple[str, ...]) -> tuple[bool, str]:
    escaped = "|".join(re.escape(name) for name in flag_names)
    pattern = re.compile(rf"(?<!\S)(?:{escaped})(?!\S)", re.IGNORECASE)
    match = pattern.search(text)
    if match is None:
        return False, text
    updated = (text[:match.start()] + " " + text[match.end():]).strip()
    return True, re.sub(r"\s{2,}", " ", updated)


def _pop_leading_harness(text: str) -> tuple[str | None, str]:
    match = re.match(
        r"^(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b\s*(.*)$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None, text
    harness = normalize_harness_name(match.group(1).replace("  ", " "))
    return harness, match.group(2).strip()


def _normalize_prompt(text: str) -> str:
    cleaned = re.sub(r"\s{2,}", " ", text).strip(" \t\r\n,，:：;；。.、")
    return cleaned or "请帮我处理"


def parse_external_agent_text(raw: str | None) -> ExternalAgentConfig | None:
    """Parse ACP intent from command-style or natural-language text."""
    text = (raw or "").strip()
    if not text:
        return None

    harness: str | None = None
    working = text

    if re.match(r"^/acp\b", text, re.IGNORECASE):
        working = re.sub(r"^/acp\b", "", text, count=1, flags=re.IGNORECASE).strip()
        harness, working = _pop_leading_harness(working)
        if harness is None:
            harness, working = _pop_option_value(
                working,
                ("--harness", "--agent"),
            )
            harness = normalize_harness_name(harness)
        if not harness:
            return None
    else:
        slash_match = re.match(
            r"^/(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        cli_match = re.match(
            r"^(?:--harness)(?:=|\s+)(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        zh_match = re.match(
            r"^(?:用|使用|让|通过|调用)\s+(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b(?:\s*(?:来|去|帮忙|帮助))?\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        en_match = re.match(
            r"^(?:use|with|via|call)\s+(opencode|open(?:\s|-)?code|qwen(?:\s*code|-code)?|qwencode)\b(?:\s+to)?\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        match = slash_match or cli_match or zh_match or en_match
        if match is None:
            return None
        harness = normalize_harness_name(match.group(1).replace("  ", " "))
        working = match.group(2).strip()

    keep_session = False
    keep_session_specified = False

    keep_flag, working = _pop_flag(working, ("--keep-session", "--session"))
    if keep_flag:
        keep_session = True
        keep_session_specified = True

    session_id, working = _pop_option_value(
        working,
        ("--session-id", "--resume-session", "--load-session"),
    )

    if session_id is None:
        natural_session = re.search(
            r"(?:继续|复用|加载)\s*(?:session|会话)\s+(\"[^\"]+\"|'[^']+'|\S+)",
            working,
            re.IGNORECASE,
        )
        if natural_session is not None:
            session_id = _strip_quotes(natural_session.group(1))
            working = (
                working[:natural_session.start()] + " " + working[natural_session.end():]
            ).strip()

    cwd, working = _pop_option_value(
        working,
        ("--cwd", "--workdir", "--working-dir", "--work-path"),
    )

    if cwd is None:
        explicit_cwd = re.search(
            r"(?:工作路径|工作目录|workdir|cwd)\s*(?:是|为|=|:|：)?\s*(\"[^\"]+\"|'[^']+'|\S+)",
            working,
            re.IGNORECASE,
        )
        if explicit_cwd is not None:
            cwd = _strip_quotes(explicit_cwd.group(1))
            working = (working[:explicit_cwd.start()] + " " + working[explicit_cwd.end():]).strip()

    if cwd is None:
        natural_cwd = re.search(
            r"在\s+(\"[^\"]+\"|'[^']+'|\S+)\s+(?:下|目录下|工作目录下)",
            working,
            re.IGNORECASE,
        )
        candidate = _strip_quotes(natural_cwd.group(1)) if natural_cwd is not None else None
        if natural_cwd is not None and _looks_like_path(candidate):
            cwd = candidate
            working = (working[:natural_cwd.start()] + " " + working[natural_cwd.end():]).strip()

    if re.search(r"(?:保持会话|keep session)", working, re.IGNORECASE):
        keep_session = True
        keep_session_specified = True
        working = re.sub(r"(?:保持会话|keep session)", " ", working, flags=re.IGNORECASE)

    if re.search(
        r"(?:之前的|上一个|上次的|刚才的|当前的?|现在的?)\s*(?:acp\s*)?(?:session|会话)|(?:previous|last|current)\s+(?:acp\s+)?session",
        working,
        re.IGNORECASE,
    ):
        keep_session = True
        keep_session_specified = True
        working = re.sub(
            r"(?:请)?\s*(?:使用|复用|继续用|沿用|在)?\s*(?:之前的|上一个|上次的|刚才的|当前的?|现在的?)\s*(?:acp\s*)?(?:session|会话)(?:\s*用)?|(?:use|reuse|continue with)\s+(?:the\s+)?(?:previous|last|current)\s+(?:acp\s+)?session",
            " ",
            working,
            flags=re.IGNORECASE,
        )

    if session_id:
        keep_session = True
        keep_session_specified = True

    return ExternalAgentConfig(
        enabled=True,
        harness=harness,
        keep_session=keep_session,
        cwd=cwd,
        existing_session_id=session_id,
        prompt=_normalize_prompt(working),
        keep_session_specified=keep_session_specified,
    )


def merge_external_agent_configs(
    *configs: ExternalAgentConfig | None,
) -> ExternalAgentConfig | None:
    """Merge request/UI config with text-parsed overrides."""
    merged: ExternalAgentConfig | None = None
    for config in configs:
        if config is None:
            continue
        if merged is None:
            merged = ExternalAgentConfig(
                enabled=config.enabled,
                harness=config.harness,
                keep_session=config.keep_session,
                cwd=config.cwd,
                existing_session_id=config.existing_session_id,
                prompt=config.prompt,
                keep_session_specified=config.keep_session_specified,
            )
            continue

        if config.enabled:
            merged.enabled = True
        if config.harness:
            merged.harness = config.harness
        if config.keep_session_specified:
            merged.keep_session = config.keep_session
            merged.keep_session_specified = True
        if config.cwd:
            merged.cwd = config.cwd
        if config.existing_session_id:
            merged.existing_session_id = config.existing_session_id
            merged.keep_session = True
            merged.keep_session_specified = True
        if config.prompt:
            merged.prompt = config.prompt
    return merged


def parse_external_agent_config(request: Any) -> ExternalAgentConfig | None:
    """Extract external agent config from request extras."""
    raw_config = getattr(request, "external_agent", None)

    if raw_config is None:
        biz_params = getattr(request, "biz_params", None)
        if isinstance(biz_params, dict):
            raw_config = biz_params.get("external_agent")

    model_extra = getattr(request, "model_extra", None)
    if raw_config is None and isinstance(model_extra, dict):
        raw_config = model_extra.get("external_agent")
        if raw_config is None:
            biz_params = model_extra.get("biz_params")
            if isinstance(biz_params, dict):
                raw_config = biz_params.get("external_agent")

    if not isinstance(raw_config, dict):
        return None

    enabled = bool(raw_config.get("enabled"))
    harness = normalize_harness_name(raw_config.get("harness"))
    existing_session_id = (
        raw_config.get("existing_session_id")
        or raw_config.get("session_id")
        or raw_config.get("acp_session_id")
    )
    keep_session = bool(raw_config.get("keep_session")) or bool(existing_session_id)
    keep_session_specified = "keep_session" in raw_config or bool(existing_session_id)
    cwd = (
        raw_config.get("cwd")
        or raw_config.get("workdir")
        or raw_config.get("working_dir")
    )

    if not enabled or not harness:
        return None

    return ExternalAgentConfig(
        enabled=enabled,
        harness=harness,
        keep_session=keep_session,
        cwd=_strip_quotes(str(cwd)) if cwd else None,
        existing_session_id=_strip_quotes(str(existing_session_id))
        if existing_session_id
        else None,
        keep_session_specified=keep_session_specified,
    )
