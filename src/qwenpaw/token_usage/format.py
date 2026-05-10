# -*- coding: utf-8 -*-
"""Format token/context usage for chat persistence and SSE (shared)."""

from typing import Any


def fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def _lang(language: str | None) -> str:
    value = (language or "").lower()
    if value.startswith("zh"):
        return "zh"
    if value.startswith("ja"):
        return "ja"
    if value.startswith("ru"):
        return "ru"
    if value.startswith("pt"):
        return "pt"
    return "en"


def _turn_usage_line(
    lang: str,
    tt: int,
    pt: int,
    ct: int,
    estimated: bool,
) -> str:
    pt_s, ct_s, tt_s = fmt_tokens(pt), fmt_tokens(ct), fmt_tokens(tt)
    if lang == "zh":
        prefix = "本轮约" if estimated else "本轮"
        return f"{prefix} **{tt_s}** tok " f"（in {pt_s} · out {ct_s}）"
    if lang == "ja":
        prefix = "このターン約" if estimated else "このターン"
        return f"{prefix} **{tt_s}** tok " f"（入力 {pt_s} · 出力 {ct_s}）"
    if lang == "ru":
        prefix = "Ход примерно" if estimated else "Ход"
        return f"{prefix} **{tt_s}** tok " f"(in {pt_s} · out {ct_s})"
    if lang == "pt":
        prefix = "Turno aprox." if estimated else "Turno"
        return f"{prefix} **{tt_s}** tok " f"(in {pt_s} · out {ct_s})"
    prefix = "~This turn" if estimated else "This turn"
    return f"{prefix} **{tt_s}** tok (in {pt_s} · out {ct_s})"


def _context_usage_line(
    lang: str,
    est: int,
    mx: int,
    ratio: float,
) -> str:
    est_s, mx_s = fmt_tokens(est), fmt_tokens(mx)
    if lang == "zh":
        return f"上下文 **{est_s}** / **{mx_s}** （{ratio:.1f}%）"
    if lang == "ja":
        return f"コンテキスト **{est_s}** / **{mx_s}** （{ratio:.1f}%）"
    if lang == "ru":
        return f"Контекст **{est_s}** / **{mx_s}** ({ratio:.1f}%)"
    if lang == "pt":
        return f"Contexto **{est_s}** / **{mx_s}** ({ratio:.1f}%)"
    return f"Context **{est_s}** / **{mx_s}** ({ratio:.1f}%)"


def format_usage_chat_note(
    turn: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
    language: str | None = "zh",
) -> str:
    lang = _lang(language)
    lines: list[str] = []
    if turn:
        tt = int(turn.get("total_tokens", 0) or 0)
        pt = int(turn.get("prompt_tokens", 0) or 0)
        ct = int(turn.get("completion_tokens", 0) or 0)
        estimated = bool(turn.get("estimated"))
        lines.append(_turn_usage_line(lang, tt, pt, ct, estimated))
    if ctx:
        est = int(ctx.get("estimated_tokens", 0) or 0)
        mx = int(ctx.get("max_input_length", 0) or 0)
        ratio = float(ctx.get("context_usage_ratio", 0) or 0)
        lines.append(_context_usage_line(lang, est, mx, ratio))
    if not lines:
        return ""
    titles = {
        "zh": "用量统计",
        "ja": "使用量統計",
        "ru": "Статистика использования",
        "pt": "Estatísticas de uso",
        "en": "Usage statistics",
    }
    return f"📊 **{titles[lang]}**\n" + "\n".join(lines)
