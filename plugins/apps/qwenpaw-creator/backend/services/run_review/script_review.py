# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Script-to-shots coverage / hallucination / shootability check (tier-1).

Method borrowed from APE-benchmark Layer A (coverage entailment over
atomized requirements, near-miss hallucination probing, and the
specificity/executability reads of its script-quality dimension), with
the comparison pair swapped for Creator's own chain: the project's
creative strategy (剧本源头) versus the freshly committed shot list
(分镜文本). It runs alongside the Appeal taste scoring on the same
``/creation/shots`` commits and reviews a DIFFERENT judgement surface:
Appeal asks "is it tasteful", this asks "does it match the script".

Output contract (Creator review doctrine): a reasoning list — what is
missing (quoting the script), what was invented (pointing at the shot),
what cannot be filmed (naming the vague passage) — never a score. Every
entry must carry its quote/reference; entries without evidence are
dropped by the parser.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from utils.logger import setup_logger

logger = setup_logger("creator.run_review.script")

_TEXT_MODEL_TIMEOUT_SECONDS = 120.0
_MAX_ENTRIES_PER_LIST = 6
_ENTRY_TEXT_LIMIT = 200
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

_SYSTEM_PROMPT = """你是一名剧本-分镜对齐审阅顾问，负责在 Creator Agent 刚提交分镜文本时，对照创作策略（剧本源头）做三类证据化检查。这是建议不是门禁，输出只作为下一回合的修订参考。

三类检查（每一条发现都必须引用具体证据，无证据的发现会被程序丢弃）：
1. coverage_missing（覆盖缺失）：把剧本源头拆成关键要素（角色/道具/场景、情节节拍、明确约束），逐条检查分镜是否承接。只报告确实缺失的要素，source_quote 必须引用剧本原文片段。
2. hallucinated（无源设定）：反向检查分镜中哪些设定在剧本源头找不到依据（新增角色、改变的地点、与约束冲突的情节）。shot_ref 指明分镜编号，claim 引用分镜原文。注意：合理的视觉化展开（把"清晨"具体化为"阳光透过窗帘"）不算幻觉，只报告改变事实/新增设定的条目。
3. unshootable（不可拍）：哪一镜的描述空泛到无法生成画面（只有情绪词没有画面主体、缺少场景/人物指向）。shot_ref 指明分镜编号，issue 说明缺什么。

判定纪律：
- 拿不准时不报告：三个列表都允许为空，空列表代表该项检查通过。
- 每个列表最多报告最重要的 6 条。
- 这不是打分：不要输出任何分数或等级，只输出逐条 reasoning。

输出格式（只输出一个 JSON 对象，不要输出任何其他文字或代码块标记）：
{
  "coverage_missing": [{"source_quote": "<剧本原文片段>", "note": "<缺失说明与建议落到哪一镜>"}],
  "hallucinated": [{"shot_ref": "<分镜编号或指针>", "claim": "<分镜原文片段>", "note": "<为何无源及处理建议>"}],
  "unshootable": [{"shot_ref": "<分镜编号或指针>", "issue": "<缺少什么画面要素>"}],
  "summary": "<一句话总体评价>"
}"""


def build_script_check_system_prompt() -> str:
    return _SYSTEM_PROMPT


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("script check response contains no JSON object")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("script check response JSON is not an object")
    return payload


def _clean_entries(
    raw: Any,
    *,
    evidence_keys: tuple[str, ...],
) -> list[dict[str, str]]:
    """Keep entries that carry every required evidence field."""
    entries: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return entries
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        entry = {
            key: str(item.get(key) or "").strip()[:_ENTRY_TEXT_LIMIT]
            for key in (*evidence_keys, "note", "issue")
            if str(item.get(key) or "").strip()
        }
        # Evidence discipline: an entry without its quote/reference
        # cannot stand (Layer A: no evidence-free failures).
        if all(entry.get(key) for key in evidence_keys):
            entries.append(entry)
        if len(entries) >= _MAX_ENTRIES_PER_LIST:
            break
    return entries


def parse_script_check(text: str) -> dict[str, Any]:
    """Normalize the model output into the reasoning-list contract."""
    payload = _extract_json_object(text)
    return {
        "coverage_missing": _clean_entries(
            payload.get("coverage_missing"),
            evidence_keys=("source_quote",),
        ),
        "hallucinated": _clean_entries(
            payload.get("hallucinated"),
            evidence_keys=("shot_ref", "claim"),
        ),
        "unshootable": _clean_entries(
            payload.get("unshootable"),
            evidence_keys=("shot_ref",),
        ),
        "summary": str(payload.get("summary") or "")[:_ENTRY_TEXT_LIMIT],
    }


def script_check_has_findings(check: Mapping[str, Any] | None) -> bool:
    if not check:
        return False
    return any(
        check.get(key)
        for key in ("coverage_missing", "hallucinated", "unshootable")
    )


async def run_script_check(
    *,
    strategy_payload: str,
    shots_payload: str,
) -> dict[str, Any] | None:
    """One script-to-shots check round; fail-open (None on any failure)."""
    try:
        from models.text_model import chat_completion

        user_text = (
            "【剧本源头（creative strategy）】\n"
            + strategy_payload
            + "\n\n【本次提交的分镜文本】\n"
            + shots_payload
        )
        response = await chat_completion(
            user_text,
            system_prompt=build_script_check_system_prompt(),
            temperature=0.2,
            max_tokens=1800,
            timeout=_TEXT_MODEL_TIMEOUT_SECONDS,
        )
        return parse_script_check(response)
    except Exception:  # noqa: BLE001 - advisory-only
        logger.exception("script-to-shots check failed")
        return None


__all__ = [
    "build_script_check_system_prompt",
    "parse_script_check",
    "run_script_check",
    "script_check_has_findings",
]
