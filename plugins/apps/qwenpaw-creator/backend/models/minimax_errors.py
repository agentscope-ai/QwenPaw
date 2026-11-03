# -*- coding: utf-8 -*-
"""Shared MiniMax ``base_resp`` error decoding.

MiniMax wraps every failure - bad key, empty balance, rate limit, content
safety - in an HTTP 200 with a ``base_resp`` envelope, so the status code alone
cannot tell a success from a rejection. This module is the single source of the
official error-code meanings (platform.minimaxi.com/docs error-code table) so
the connection probe and the real image/video generation paths all surface the
same human-readable message instead of three drifting copies.
"""

from __future__ import annotations

# Official MiniMax error-code table.
MINIMAX_BASE_RESP_HINTS: dict[int, str] = {
    1000: "未知错误/系统默认错误，请稍后再试",
    1001: "请求超时，请稍后再试",
    1002: "请求频率超限，请稍后再试",
    1004: "未授权/Token 不匹配，请检查 API Key",
    1008: "余额不足，请检查账户余额",
    1024: "内部错误，请稍后再试",
    1026: "输入内容涉敏，请调整输入",
    1027: "输出内容涉敏，请调整输入",
    1033: "系统错误/下游服务错误，请稍后再试",
    1039: "Token 限制，请调整 max_tokens",
    1041: "连接数限制，请联系 MiniMax",
    1042: "不可见字符/非法字符比例超限，请检查输入",
    1043: "ASR 相似度检查失败，请核对 file_id 与文本",
    1044: "克隆提示词相似度检查失败，请检查提示音频与文本",
    2013: "参数错误，请检查请求参数",
    20132: "语音克隆样本或 voice_id 参数错误",
    2037: "语音时长不符合要求（10 秒–5 分钟）",
    2038: "用户语音克隆功能被禁用，需完成实名认证",
    2039: "语音克隆 voice_id 重复",
    2042: "无权访问该 voice_id",
    2045: "请求频率增长超限，请避免骤增骤减",
    2048: "语音克隆提示音频太长（需 < 8s）",
    2049: "无效的 API Key，请检查 API Key",
    2056: "超出 M Plan 资源限制，请稍后再试",
}


def minimax_base_resp_message(code: object, status_msg: object = "") -> str:
    """Build the human-readable line for one non-zero ``base_resp`` code."""
    label = (
        MINIMAX_BASE_RESP_HINTS.get(code, "") if isinstance(code, int) else ""
    )
    detail = str(status_msg or "")
    return (
        f"MiniMax 返回错误 {code}"
        + (f"（{label}）" if label else "")
        + (f"：{detail}" if detail else "")
    )


def minimax_base_resp_error(payload: object) -> str | None:
    """Message when a parsed MiniMax body carries a non-zero ``base_resp``.

    Returns ``None`` when the body is not a MiniMax error envelope (a success,
    or a non-MiniMax shape such as the self-hosted SGLang ``/health``).
    """
    if not isinstance(payload, dict):
        return None
    base_resp = payload.get("base_resp")
    if not isinstance(base_resp, dict):
        return None
    code = base_resp.get("status_code")
    if code in (None, 0):
        return None
    return minimax_base_resp_message(code, base_resp.get("status_msg"))


# Codes that mean the saved configuration itself is unusable: a wrong/expired
# key or no balance. A connection probe sends a throwaway ``task_id``, so every
# other non-zero base_resp (notably "task not found") proves the request
# reached and authenticated at MiniMax and must NOT fail the probe. Real
# generation still treats any non-zero base_resp as a failure via
# :func:`minimax_base_resp_error`.
MINIMAX_PROBE_FATAL_CODES = frozenset({1004, 2049, 1008})


def minimax_probe_base_resp_error(payload: object) -> str | None:
    """Failure message for a probe body, limited to config-level codes."""
    if not isinstance(payload, dict):
        return None
    base_resp = payload.get("base_resp")
    if not isinstance(base_resp, dict):
        return None
    code = base_resp.get("status_code")
    if code in MINIMAX_PROBE_FATAL_CODES:
        return minimax_base_resp_message(code, base_resp.get("status_msg"))
    return None
