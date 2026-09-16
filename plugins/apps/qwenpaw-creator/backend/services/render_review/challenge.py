# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Per-case near-miss challenge questions for the render review (tier-3).

Ported from APE-benchmark's challenge pass (``gen_challenge_vqa`` +
``challenge_postprocess``): instead of the open-ended "find problems",
each question hypothesizes ONE specific, plausible defect derived from
the actual plan and asks the VLM to falsify it — near-miss questions hit
far more reliably because they collapse the search space to a checkable
assertion.

The upstream disciplines ship together (they are what keeps the false
alarm rate survivable):

- straw-man filter — a question may only challenge something the plan
  actually asked for; the program drops questions whose anchor text is
  not found in the plan.
- anchor enforcement — every question must reference a concrete
  shot/element; anchor-less questions are dropped.
- question cap (6) and near-duplicate pruning.
- verdict anti-hallucination — an NA needs a reason, a CT needs a frame
  timestamp inside the shown evidence set; a violating verdict is
  downgraded to ET so it can never force a revision on invented
  evidence.

Switchable as the ``challenge`` review operator (auto-on; an explicitly
set ``CREATOR_RENDER_CHALLENGE_ENABLED`` still overrides it). Question
drafting is cached by canonical plan fingerprint and overlaps the main
review. All accepted hypotheses are judged in one multimodal batch: the VLM
already evaluates them together, avoiding six copies of the same frame set.
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import re
import threading
from typing import Any, Mapping, Sequence

from schemas.render_review import ChallengeFinding, ReviewFrame
from utils.logger import setup_logger

logger = setup_logger("creator.render_review.challenge")

_MAX_QUESTIONS = 6
_TEXT_LIMIT = 240
# Real-model observation (2026-08-20): question generation through the
# DogFooding proxy exceeded 60s while the agent's own turn ran
# concurrently; keep parity with the tier-1 text review timeout.
_TEXT_MODEL_TIMEOUT_SECONDS = 120.0
_FRAME_REF_TOLERANCE_MS = 500
_QUESTION_CACHE_LIMIT = 64
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
# Near-miss polarity marker: the question must contain an actual negative
# assertion. ``确认`` alone is not polarity — otherwise an unrelated positive
# question can pass merely by starting with "please confirm".
_POLARITY_PATTERN = re.compile(r"没有|未(?:出现|保持|达到|包含|呈现)|不存在|不应|不该|不再|保持不")

_QUESTION_CACHE: "OrderedDict[str, tuple[dict[str, str], ...]]" = OrderedDict()
_QUESTION_CACHE_LOCK = threading.Lock()

_GENERATION_SYSTEM_PROMPT = """你是一名视频审阅出题人，负责根据剪辑计划为一条成片生成「近失误挑错题」：每题假设一个具体的、似是而非的缺陷，让审阅者去证伪。

出题纪律：
1. 只能挑计划确实要求过的东西：每题必须带 anchor 字段，anchor 必须是计划文本中的原文片段（逐字），挑计划没要求的错（straw-man）会被程序丢弃。
2. 每题必须绑定具体对象（某一镜/某个元素/某段文字），提问形如「请确认X没有Y」；anchor 原文必须逐字出现在 question 中。
3. 缺陷假设要具体可验证（颜色变了、元素缺了、顺序反了、文字错了），不要出「整体质量如何」这类开放题。
4. 最多 6 题，优先出最可能真实发生的缺陷。
5. severity：影响内容成立的（主体错误/元素缺失/顺序错乱/文字错误）为 major；观感瑕疵为 minor。

输出格式（只输出一个 JSON 对象）：
{
  "questions": [
    {"question_id": "cq1", "question": "<请确认…没有…>", "anchor": "<计划原文片段>", "severity": "major"/"minor"}
  ]
}"""

_JUDGE_SYSTEM_PROMPT = """你是一名严苛的成片审阅专家，对一组「近失误挑错题」逐题判定。每题假设了一个具体缺陷，你的任务是证实或证伪它。

判定纪律：
1. ET=确认该缺陷不存在（默认答案，拿不准判 ET）；CT=确认该缺陷存在，必须给出 evidence_timestamp_ms（只能取自证据帧时间戳列表）、reason（看到了什么）与一句可执行的 suggestion；NA=该题不适用（reason 必须非空）。
2. 引用不存在的帧时间戳会被程序判为无效。
3. 这是建议不是门禁。

输出格式（只输出一个 JSON 对象）：
{
  "verdicts": [
    {"question_id": "<题目 id>", "verdict": "ET"/"CT"/"NA", "evidence_timestamp_ms": <int 或 null>, "reason": "<...>", "suggestion": "<CT 必填>"}
  ]
}"""


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("challenge response contains no JSON object")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("challenge response JSON is not an object")
    return payload


def _plan_corpus(plan_context: Mapping[str, Any]) -> str:
    """Flattened plan text used by the straw-man anchor check."""
    return json.dumps(dict(plan_context), ensure_ascii=False)


def filter_questions(
    raw_questions: Any,
    *,
    plan_context: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Program-side challenge hygiene: anchors, polarity, dedupe, cap."""
    corpus = _plan_corpus(plan_context)
    accepted: list[dict[str, str]] = []
    seen_texts: list[str] = []
    if not isinstance(raw_questions, list):
        return accepted
    for index, item in enumerate(raw_questions):
        if not isinstance(item, Mapping):
            continue
        question = str(item.get("question") or "").strip()[:_TEXT_LIMIT]
        anchor = str(item.get("anchor") or "").strip()[:_TEXT_LIMIT]
        if not question or not anchor:
            continue
        # Straw-man filter: the anchor must literally exist in the plan and
        # in the question. Merely borrowing an unrelated plan substring does
        # not make the proposed defect traceable to the plan.
        if anchor not in corpus:
            logger.info("challenge question dropped (straw-man): %s", anchor)
            continue
        normalized_anchor = re.sub(r"\s+", "", anchor).casefold()
        normalized_question = re.sub(r"\s+", "", question).casefold()
        if normalized_anchor not in normalized_question:
            logger.info(
                "challenge question dropped (anchor not in question): %s",
                anchor,
            )
            continue
        if not _POLARITY_PATTERN.search(question):
            continue
        # Near-duplicate pruning (cheap containment check).
        normalized = question.replace(" ", "")
        if any(normalized[:40] == other[:40] for other in seen_texts):
            continue
        seen_texts.append(normalized)
        severity = str(item.get("severity") or "major")
        accepted.append(
            {
                "question_id": f"cq{index + 1}",
                "question": question,
                "anchor": anchor,
                "severity": severity
                if severity in ("minor", "major")
                else "major",
            },
        )
        if len(accepted) >= _MAX_QUESTIONS:
            break
    return accepted


async def generate_challenge_questions(
    plan_context: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Generate questions once per canonical plan, then reuse across renders."""

    canonical = json.dumps(
        dict(plan_context),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with _QUESTION_CACHE_LOCK:
        cached = _QUESTION_CACHE.get(cache_key)
        if cached is not None:
            _QUESTION_CACHE.move_to_end(cache_key)
            return [dict(item) for item in cached]
    try:
        from models.text_model import chat_completion

        response = await chat_completion(
            "【剪辑计划（挑错对照物）】\n"
            + json.dumps(dict(plan_context), ensure_ascii=False),
            system_prompt=_GENERATION_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=1500,
            timeout=_TEXT_MODEL_TIMEOUT_SECONDS,
        )
        payload = _extract_json_object(response)
        questions = filter_questions(
            payload.get("questions"),
            plan_context=plan_context,
        )
        if questions:
            with _QUESTION_CACHE_LOCK:
                _QUESTION_CACHE[cache_key] = tuple(
                    dict(item) for item in questions
                )
                _QUESTION_CACHE.move_to_end(cache_key)
                while len(_QUESTION_CACHE) > _QUESTION_CACHE_LIMIT:
                    _QUESTION_CACHE.popitem(last=False)
        return questions
    except Exception:  # noqa: BLE001 - advisory-only
        logger.exception("challenge question generation failed")
        return []


def clear_question_cache() -> None:
    """Clear the bounded process cache (tests/config reloads)."""

    with _QUESTION_CACHE_LOCK:
        _QUESTION_CACHE.clear()


def parse_challenge_verdicts(
    text: str,
    *,
    questions: Sequence[Mapping[str, str]],
    valid_timestamps: Sequence[int],
) -> list[ChallengeFinding]:
    """Normalize verdicts with the anti-hallucination checks applied.

    A suspect verdict is kept but excluded from the verdict derivation
    via ``needs_review`` semantics: here that means demoting the CT to
    an ET-with-note, mirroring the run_review probe treatment.
    """
    payload = _extract_json_object(text)
    by_id = {item["question_id"]: item for item in questions}
    findings: list[ChallengeFinding] = []
    seen: set[str] = set()
    for item in payload.get("verdicts") or []:
        if not isinstance(item, Mapping):
            continue
        question_id = str(item.get("question_id") or "")
        source = by_id.get(question_id)
        if source is None or question_id in seen:
            continue
        seen.add(question_id)
        verdict = str(item.get("verdict") or "").strip().upper()
        if verdict not in ("ET", "CT", "NA"):
            continue
        timestamp = item.get("evidence_timestamp_ms")
        if not isinstance(timestamp, int) or timestamp < 0:
            timestamp = None
        reason = str(item.get("reason") or "").strip()[:_TEXT_LIMIT]
        suggestion = str(item.get("suggestion") or "").strip()[:_TEXT_LIMIT]
        if verdict == "NA" and not reason:
            verdict = "ET"
            reason = "（NA 未附理由，按未确认处理）"
        if verdict == "CT":
            in_bounds = timestamp is not None and any(
                abs(timestamp - valid) <= _FRAME_REF_TOLERANCE_MS
                for valid in valid_timestamps
            )
            evidence_complete = in_bounds and bool(reason) and bool(suggestion)
            if not evidence_complete:
                verdict = "ET"
                missing: list[str] = []
                if not in_bounds:
                    missing.append("证据帧无效")
                if not reason:
                    missing.append("未附具体理由")
                if not suggestion:
                    missing.append("未附修复建议")
                original_reason = reason[:120]
                reason = "（CT 证据不完整：" + "、".join(missing)
                if original_reason:
                    reason += "；原理由：" + original_reason
                reason += "，按未确认处理）"
                suggestion = ""
        findings.append(
            ChallengeFinding(
                question_id=question_id,
                question=source["question"],
                verdict=verdict,  # type: ignore[arg-type]
                severity=source["severity"],  # type: ignore[arg-type]
                evidence_timestamp_ms=timestamp,
                reason=reason,
                suggestion=suggestion,
            ),
        )
    return findings


async def judge_challenges(
    questions: Sequence[Mapping[str, str]],
    *,
    frames: Sequence[ReviewFrame],
) -> list[ChallengeFinding]:
    """One batched VLM verdict round over the extracted evidence frames."""

    if not questions:
        return []
    try:
        from pathlib import Path

        from models.vlm_model import chat_completion, multimodal_media_part

        question_lines = "\n".join(
            f"- {item['question_id']}（{item['severity']}）：{item['question']}"
            for item in questions
        )
        frame_lines = "\n".join(
            f"- 第 {index + 1} 张图 = t={frame.timestamp_ms}ms"
            for index, frame in enumerate(frames)
        )
        user_text = (
            "【挑错题清单】\n"
            + question_lines
            + "\n\n【证据帧时间戳（与随后附上的图片顺序一一对应）】\n"
            + frame_lines
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for frame in frames:
            content.append(
                multimodal_media_part(
                    Path(frame.image_path).as_uri(),
                    "image",
                ),
            )
        response = await chat_completion(
            content,
            system_prompt=_JUDGE_SYSTEM_PROMPT,
            max_tokens=1600,
        )
        return parse_challenge_verdicts(
            response,
            questions=questions,
            valid_timestamps=[frame.timestamp_ms for frame in frames],
        )
    except Exception:  # noqa: BLE001 - advisory-only
        logger.exception("challenge judging failed")
        return []


__all__ = [
    "filter_questions",
    "clear_question_cache",
    "generate_challenge_questions",
    "judge_challenges",
    "parse_challenge_verdicts",
]
