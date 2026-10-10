# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Eight-row self-review protocol: prompt template and report parsing.

The seven Appeal rubric rows come verbatim from the vendored
``review_rubrics.APPEAL_RUBRIC_ROWS`` (Qwen-MM-Plugins video-edit skill,
``review/final-review.md`` §D) so self-review and the bypass run_review
share one fact source; a Creator ``engineering`` row keeps the objective
defect checks of the original six-dimension protocol. Every verdict must
cite frame evidence, findings without a timestamp cannot fail a row, and
the verdict is derived deterministically — a concept score at or below the
upstream veto threshold forces ``revise``.
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
from vendor.media_toolkit.review_rubrics import (
    APPEAL_RUBRIC_ROWS,
    CONCEPT_VETO_QUOTE,
    CONCEPT_WEAK_THRESHOLD,
)

logger = setup_logger("creator.render_review.protocol")

MAX_REVIEW_ROUNDS = 3

_RUBRIC_BY_KEY = {row.key: row for row in APPEAL_RUBRIC_ROWS}

# Creator-side evidence discipline appended to the verbatim rubric rows:
# the anchor questions stay upstream-verbatim, the guides tell the VLM how
# to ground each row in the extracted frames/audio profile (folding in the
# objective checks of the retired six-dimension protocol).
_DIMENSION_GUIDES: dict[ReviewDimension, str] = {
    ReviewDimension.CONCEPT: (
        f"{_RUBRIC_BY_KEY['concept'].anchor_questions} "
        "给出 score（0-10）；素材流水账不是概念。score ≤ "
        f"{CONCEPT_WEAK_THRESHOLD} 时必须 passed=false、severity=major。"
    ),
    ReviewDimension.CONTRACT: (
        f"{_RUBRIC_BY_KEY['contract'].anchor_questions} "
        "对照物是【剪辑契约】（edit_plan）；契约为 null 或未声明时本行判 "
        "passed=true 并在 suggestion 注明无契约可对照。证据帧是稀疏抽样且"
        "设计元素带入场动画：判定 opening/ending 等短时窗设计缺失前，必须有"
        "落在该时窗中段的证据帧支撑；若该时窗内只有起点帧（t=0 或时窗边界），"
        "不得据此判缺失，应视为证据不足按通过处理并在 suggestion 注明。"
    ),
    ReviewDimension.RHYTHM: (
        f"{_RUBRIC_BY_KEY['rhythm'].anchor_questions} "
        "以帧序列的变化率为证据：相邻多帧几乎完全相同说明镜头拖沓——连续相同"
        "帧超过约 5 秒判不通过（severity=major）；片尾 2-3 秒定格收尾属正常收束，"
        "不判拖沓；开场 1-2 帧内是否建立主体。"
    ),
    ReviewDimension.RESTRAINT: (
        f"{_RUBRIC_BY_KEY['restraint'].anchor_questions} "
        "以证据帧中的装饰/特效出现次数为准；同一装饰手法泛滥或逐卡重复判不通过。"
    ),
    ReviewDimension.CRAFT: (
        f"{_RUBRIC_BY_KEY['craft'].anchor_questions} "
        "逐帧检查花屏/噪点/伪影、乱码或豆腐块文字、明显残影、转场闪白或卡死、"
        "局部黑块、画面主体被裁切等缺陷；纯黑帧与黑边归 engineering 行，不在此重复计。"
    ),
    ReviewDimension.SOUND: (
        f"{_RUBRIC_BY_KEY['sound'].anchor_questions} "
        "先看【计划上下文】的 expects_voiceover：为 false 时，若 project_brief "
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
    ReviewDimension.TYPOGRAPHY_MOTION: (
        f"{_RUBRIC_BY_KEY['typography_motion'].anchor_questions} "
        "帧上字幕是否超出画面安全区或被裁切；同一帧是否出现重叠/双行叠打字幕；"
        "字幕出现的时间段与音频概要中的人声段是否明显错位；字幕文字是否乱码。"
        "【计划上下文】expects_subtitles=false 且帧上确无字幕时本部分判通过。"
    ),
    ReviewDimension.ENGINEERING: (
        "工程正确性：内容中段出现纯黑帧（片头片尾短暂淡入淡出除外）；"
        "expects_voiceover=true 却整段静音；上下或左右黑边（分辨率/画幅不匹配）；"
        "首帧或末帧为空白/黑帧。对比【工程事实】中的实际时长与计划目标时长，"
        "偏差超过 20% 视为不通过；同时检查末帧是否像被硬切截断（画面/字幕停在"
        "半句、动作进行到一半骤停）。这些是客观工程缺陷，一律 severity=major。"
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
    {"dimension": "<eight rows, one entry each>", "passed": true/false, "severity": "minor"/"major", "score": <0-10 整数，仅 concept 行必填，其他行可为 null>, "evidence_timestamp_ms": <int 或 null>, "suggestion": "<修订指令，通过时可为空字符串>"}
  ],
  "verdict": "pass" 或 "revise"
}
八个检查行各输出恰好一条 finding，dimension 取值：concept / contract / rhythm / restraint / craft / sound / typography_motion / engineering。
verdict 规则：任何一条 passed=false 且 severity=major，或 concept 的 score ≤ 5，则为 revise，否则为 pass。"""


def review_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_review_user_text(
    *,
    frames: Sequence[ReviewFrame],
    audio_profile: AudioProfile,
    video_duration_seconds: float | None,
    plan_context: Mapping[str, Any],
    objective_facts: Mapping[str, Any] | None = None,
) -> str:
    """Compose the user turn text preceding the evidence frame images."""
    frame_lines = [
        f"- 第 {index + 1} 张图 = t={frame.timestamp_ms}ms"
        for index, frame in enumerate(frames)
    ]
    audio_payload = audio_profile.model_dump(mode="json")
    edit_plan = plan_context.get("edit_plan") if plan_context else None
    sections = [
        "请按八行协议审阅这条成片。",
        "【工程事实】\n"
        + json.dumps(
            {
                "actual_duration_seconds": video_duration_seconds,
                "frame_count": len(frames),
            },
            ensure_ascii=False,
        ),
        "【计划上下文】\n"
        + json.dumps(
            {
                key: value
                for key, value in dict(plan_context).items()
                if key != "edit_plan"
            },
            ensure_ascii=False,
        ),
        "【剪辑契约（edit_plan，contract 行的对照物）】\n"
        + json.dumps(edit_plan, ensure_ascii=False),
        "【音频概要（ffmpeg ebur128）】\n"
        + json.dumps(audio_payload, ensure_ascii=False),
    ]
    if objective_facts:
        # Tier-0 objective operators (APE-benchmark port): facts only —
        # the preamble inside the block repeats the "hints, not verdicts"
        # framing so the VLM folds them into row reasoning instead of
        # copying them as findings.
        from services.run_review.objective import render_facts_block

        sections.append(render_facts_block(objective_facts))
    sections += [
        "【证据帧时间戳（与随后附上的图片顺序一一对应）】\n" + "\n".join(frame_lines),
        "【八行检查要点】\n"
        + "\n".join(
            f"- {dimension.value}: {_DIMENSION_GUIDES[dimension]}"
            for dimension in ReviewDimension
        ),
    ]
    if plan_context.get("live_operation_tutorial"):
        sections.append(
            "【真实操作教程专项验收】\n"
            "- 关键步骤必须出现可辨识的真实动作与结果态，不能只有旁白、标题或静态页面。\n"
            "- 动作前有总览定位，动作时有同步聚焦，动作后保留足够时间证明结果；"
            "连续长录屏、无焦点滚动或没有结果证明属于节奏/概念缺陷。\n"
            "- 标注、字幕和装饰不得覆盖被点击、输入或需要阅读的目标；"
            "同一时刻只保留一个主焦点，字幕样式应全片统一。\n"
            "- 聚焦裁切必须保持满画布、无意外黑边；章节变化清楚，开场先给具体收益，"
            "结尾给出明确收束而不是原始录屏硬停。\n"
            "- 不能只靠原始录屏、底部黑框字幕、圆环和全片交叉淡化通过审美验收；"
            "画面应存在背景舞台、真实界面、前景标注三层深度，至少两个场景有非对称构图或产品界面框，"
            "章节运动方向一致且点击反馈像真实光标动作。\n"
            "- 超过 10 秒的解说成片应检查音乐床/环境声的明确取舍；有旁白时音乐不能争抢语音，"
            "只有零散 click/whoosh 不等于完整声音设计。",
        )
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
        score = entry.get("score")
        if not isinstance(score, int) or not 0 <= score <= 10:
            entry["score"] = None
        entry.setdefault("suggestion", "")
        if entry.get("suggestion") is None:
            entry["suggestion"] = ""
        finding = ReviewFinding.model_validate(entry)
        if finding.dimension in seen:
            continue
        seen.add(finding.dimension)
        # Evidence discipline: a failure without a citable timestamp cannot
        # stand (upstream review invalidation rule). The concept row is
        # score-driven and exempt: its evidence is the whole piece.
        if (
            not finding.passed
            and finding.evidence_timestamp_ms is None
            and finding.dimension is not ReviewDimension.CONCEPT
        ):
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
    concept = next(
        item for item in findings if item.dimension is ReviewDimension.CONCEPT
    )
    concept_veto = (
        concept.score is not None and concept.score <= CONCEPT_WEAK_THRESHOLD
    )
    if concept_veto and concept.passed:
        # Upstream veto rule: "execution polish cannot rescue an empty
        # concept" — normalize the row so the feedback loop sees it.
        suggestion = concept.suggestion or (
            f"concept score {concept.score} ≤ {CONCEPT_WEAK_THRESHOLD}："
            f"{CONCEPT_VETO_QUOTE}；重写 edit_plan.concept 并按新概念重剪。"
        )
        concept = concept.model_copy(
            update={
                "passed": False,
                "severity": "major",
                "suggestion": suggestion,
            },
        )
        findings = [
            concept if item.dimension is ReviewDimension.CONCEPT else item
            for item in findings
        ]
    has_major_failure = any(
        not item.passed and item.severity == "major" for item in findings
    )
    verdict = "revise" if has_major_failure or concept_veto else "pass"
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
    """Structured findings payload injected into the next editing run.

    Severity-weighted ordering (APE: major=2.0 / minor=1.0) is an
    internal mechanism: the agent receives the reasoning entries
    (evidence + suggestion) sorted most-damaging-first, never a score.
    Confirmed near-miss challenges ride along; the eight-row findings
    are always fully preserved (cap, don't erase).
    """
    ordered = sorted(
        report.failed_findings(),
        key=lambda item: 0 if item.severity == "major" else 1,
    )
    payload = {
        "type": "render_review_feedback",
        "video_ref": report.video_ref,
        "round": report.round,
        "max_rounds": MAX_REVIEW_ROUNDS,
        "verdict": report.verdict,
        "findings": [item.model_dump(mode="json") for item in ordered],
    }
    confirmed = sorted(
        report.confirmed_challenges(),
        key=lambda item: 0 if item.severity == "major" else 1,
    )
    if confirmed:
        payload["challenge_findings"] = [
            item.model_dump(mode="json") for item in confirmed
        ]
    return payload


__all__ = [
    "MAX_REVIEW_ROUNDS",
    "build_review_user_text",
    "findings_feedback_payload",
    "parse_review_report",
    "review_system_prompt",
]
