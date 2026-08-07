# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Six-dimension self-review protocol: prompt template and report parsing.

Adapted from the Qwen-MM-Plugins video-edit skill review protocol
(``review/final-review.md``, evidence-based and adversarial): every verdict
must cite frame evidence, and findings without a timestamp cannot fail a
dimension. The verdict is derived deterministically from the findings so the
iteration loop never depends on a free-form model verdict.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from schemas.render_review import (
    AudioProfile,
    RenderReviewReport,
    ReviewDimension,
    ReviewFinding,
    ReviewFrame,
)
from utils.logger import setup_logger

logger = setup_logger("creator.render_review.protocol")

MAX_REVIEW_ROUNDS = 3

_DIMENSION_GUIDES: dict[ReviewDimension, str] = {
    ReviewDimension.VISUAL_QUALITY: (
        "画面质量：逐帧检查是否存在花屏/噪点/伪影、乱码或豆腐块文字、明显残影、"
        "转场闪白或卡死、局部黑块、画面主体被裁切等缺陷。"
        "纯黑帧与黑边归 engineering 维度，不在此重复计。"
    ),
    ReviewDimension.DURATION_MATCH: (
        "时长匹配：对比【工程事实】中的实际时长与计划目标时长，偏差超过 20% 视为不通过；"
        "同时检查末帧是否像被硬切截断（画面/字幕停在半句、动作进行到一半骤停）。"
    ),
    ReviewDimension.PACING: (
        "节奏：相邻多帧几乎完全相同说明镜头拖沓——连续相同帧超过约 5 秒判不"
        "通过（severity=major）；片尾 2-3 秒的定格收尾属正常收束，不判拖沓；"
        "开场 1-2 帧内是否建立主体。以帧序列的变化率为证据，不要凭感觉。"
    ),
    ReviewDimension.VOICEOVER: (
        "配音：先看【计划上下文】的 expects_voiceover：为 false 时，若 project_brief "
        "明确要求旁白/配音而成片自始至终无人声（仅环境音/音乐），判不通过"
        "（severity=major，suggestion 注明需补旁白轨）；否则（例如纯环境音剪辑）"
        "静音段与低响度均属正常，除非出现爆音等硬缺陷否则一律判通过。"
        "为 true 时结合【音频概要】判断：成片整体无声判不通过；对单个超过 3 秒的"
        "静音段，必须对照同时段证据帧：画面中人物口部明显张开在说话才判人声丢失"
        "（major）；人物静坐、沉思、拥抱等无口型画面的安静段落属正常情绪停顿，"
        "判通过；仅当画面无法确认但静音与上下文严重不协调时最多记 minor。"
        "开场或结尾 1 秒以内的短静音属正常淡入淡出，不得判不通过；"
        "若开场静音超过约 1.5 秒而首帧画面已处于说话/对话状态，或人声段与画面"
        "内容段整体错位，判音画错位不通过；配音期间背景音乐是否恰当避让"
        "（ducking——若语音段整体响度反而低于纯音乐段，判为混音失衡）。"
    ),
    ReviewDimension.SUBTITLES: (
        "字幕同步与溢出：帧上字幕是否超出画面安全区或被裁切；同一帧是否出现"
        "重叠/双行叠打字幕；字幕出现的时间段与音频概要中的人声段是否明显错位；"
        "字幕文字是否乱码。【计划上下文】expects_subtitles=false 且帧上确无字幕时"
        "判通过。"
    ),
    ReviewDimension.ENGINEERING: (
        "工程正确性：内容中段出现纯黑帧（片头片尾短暂淡入淡出除外）；"
        "expects_voiceover=true 却整段静音；上下或左右黑边（分辨率/画幅不匹配）；"
        "首帧或末帧为空白/黑帧。这些是客观工程缺陷，一律 severity=major。"
        "注意：expects_voiceover=false 时，低响度或静音段不构成工程缺陷。"
    ),
}

_SYSTEM_PROMPT = """你是一名严苛的成片质量审阅专家，负责在成片交付前做证据化的对抗性审阅。
你收到的是同一条成片按时间顺序均匀抽取的证据帧（首帧与末帧必在其中）、音频响度概要与工程事实。
你必须假设成片有问题并主动找茬，但每一条不通过的结论都必须有帧时间戳证据；反过来，找不到证据就必须判通过——禁止无证据的\"感觉不好\"，也禁止无证据的\"总体看起来不错\"。

判定纪律：
1. 只依据给出的证据帧、音频概要与工程事实判断，不得臆测帧与帧之间未展示的内容；帧间隔内无法确认的问题不计为缺陷。
2. evidence_timestamp_ms 只能取自证据帧时间戳列表或音频概要中的段落边界；没有可引用时间戳的维度不能判不通过。
3. severity 判据：影响观感成立与交付的（黑帧、整段无声、字幕大面积溢出、时长严重不符、画面损坏）为 major；轻微瑕疵（个别帧轻微模糊、节奏略平、字幕轻微贴边）为 minor。
4. 拿不准时：客观工程事实（黑帧/静音/黑边）从严；主观审美（节奏/构图）从宽，只有证据明确才判不通过。
5. suggestion 必须是剪辑专家可直接执行的一句话修订指令（指明大致时间段与操作），不通过的维度必填。

输出格式（只输出一个 JSON 对象，不要输出任何其他文字或代码块标记）：
{
  "findings": [
    {"dimension": "<six dimensions, one entry each>", "passed": true/false, "severity": "minor"/"major", "evidence_timestamp_ms": <int 或 null>, "suggestion": "<修订指令，通过时可为空字符串>"}
  ],
  "verdict": "pass" 或 "revise"
}
六个维度各输出恰好一条 finding，dimension 取值：visual_quality / duration_match / pacing / voiceover / subtitles / engineering。
verdict 规则：任何一条 passed=false 且 severity=major 则为 revise，否则为 pass。"""


def review_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_review_user_text(
    *,
    frames: Sequence[ReviewFrame],
    audio_profile: AudioProfile,
    video_duration_seconds: float | None,
    plan_context: Mapping[str, Any],
) -> str:
    """Compose the user turn text preceding the evidence frame images."""
    frame_lines = [
        f"- 第 {index + 1} 张图 = t={frame.timestamp_ms}ms"
        for index, frame in enumerate(frames)
    ]
    audio_payload = audio_profile.model_dump(mode="json")
    sections = [
        "请按六维协议审阅这条成片。",
        "【工程事实】\n"
        + json.dumps(
            {
                "actual_duration_seconds": video_duration_seconds,
                "frame_count": len(frames),
            },
            ensure_ascii=False,
        ),
        "【计划上下文】\n" + json.dumps(dict(plan_context), ensure_ascii=False),
        "【音频概要（ffmpeg ebur128）】\n"
        + json.dumps(audio_payload, ensure_ascii=False),
        "【证据帧时间戳（与随后附上的图片顺序一一对应）】\n" + "\n".join(frame_lines),
        "【六维检查要点】\n"
        + "\n".join(
            f"- {dimension.value}: {_DIMENSION_GUIDES[dimension]}"
            for dimension in ReviewDimension
        ),
    ]
    return "\n\n".join(sections)


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("review response contains no JSON object")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("review response JSON is not an object")
    return payload


def parse_review_report(
    text: str,
    *,
    video_ref: str,
    round_number: int,
) -> RenderReviewReport:
    """Parse the VLM response and derive the verdict deterministically."""
    payload = _extract_json_object(text)
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list) or not raw_findings:
        raise ValueError("review response has no findings list")
    findings: list[ReviewFinding] = []
    seen: set[ReviewDimension] = set()
    for item in raw_findings:
        if not isinstance(item, Mapping):
            continue
        entry = dict(item)
        severity = entry.get("severity")
        if severity not in ("minor", "major"):
            entry["severity"] = "minor"
        timestamp = entry.get("evidence_timestamp_ms")
        if not isinstance(timestamp, int) or timestamp < 0:
            entry["evidence_timestamp_ms"] = None
        entry.setdefault("suggestion", "")
        if entry.get("suggestion") is None:
            entry["suggestion"] = ""
        finding = ReviewFinding.model_validate(entry)
        if finding.dimension in seen:
            continue
        seen.add(finding.dimension)
        # Evidence discipline: a failure without a citable timestamp cannot
        # stand (upstream review invalidation rule).
        if not finding.passed and finding.evidence_timestamp_ms is None:
            finding = finding.model_copy(
                update={"passed": True, "suggestion": ""},
            )
        findings.append(finding)
    missing = [item for item in ReviewDimension if item not in seen]
    if missing:
        raise ValueError(
            "review response missing dimensions: "
            + ", ".join(item.value for item in missing),
        )
    has_major_failure = any(
        not item.passed and item.severity == "major" for item in findings
    )
    verdict = "revise" if has_major_failure else "pass"
    reported_verdict = payload.get("verdict")
    if reported_verdict in ("pass", "revise") and reported_verdict != verdict:
        logger.info(
            "render review verdict normalized: model=%s derived=%s",
            reported_verdict,
            verdict,
        )
    return RenderReviewReport(
        video_ref=video_ref,
        round=round_number,
        findings=findings,
        verdict=verdict,
        created_at=datetime.now(UTC),
    )


def findings_feedback_payload(report: RenderReviewReport) -> dict[str, Any]:
    """Structured findings payload injected into the next editing run."""
    return {
        "type": "render_review_feedback",
        "video_ref": report.video_ref,
        "round": report.round,
        "max_rounds": MAX_REVIEW_ROUNDS,
        "verdict": report.verdict,
        "findings": [
            item.model_dump(mode="json") for item in report.failed_findings()
        ],
    }


__all__ = [
    "MAX_REVIEW_ROUNDS",
    "build_review_user_text",
    "findings_feedback_payload",
    "parse_review_report",
    "review_system_prompt",
]
