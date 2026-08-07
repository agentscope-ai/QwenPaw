# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Prompt builders derived from the vendored upstream review rules.

Every run-review prompt (and the taste principles rendered into the agent
prompts) is generated from ``vendor.mm_plugins.review_rubrics`` so the
wording stays aligned with the upstream video-edit skill. The upstream
concept veto is deliberately downgraded: a weak concept yields a
major-severity suggestion, never a delivery gate.
"""

from __future__ import annotations

from vendor.mm_plugins.review_rubrics import (
    APPEAL_RUBRIC_ROWS,
    COMMON_FAILURES,
    CONCEPT_VETO_QUOTE,
    CONCEPT_WEAK_THRESHOLD,
    EVIDENCE_DISCIPLINE,
    SCENE_REVIEW_CHECKS,
)

# Rubric rows that make sense per synchronous review stage: text artifacts
# (script/strategy/shot planning) are judged on concept/contract/rhythm;
# motion specs additionally on restraint and typography&motion.
STAGE_RUBRIC_ROWS: dict[str, tuple[int, ...]] = {
    "text": (0, 1, 2),
    "motion": (0, 3, 6),
}


def _rubric_rows_block(stage: str) -> str:
    indexes = STAGE_RUBRIC_ROWS.get(stage, (0, 1, 2))
    rows = [row for row in APPEAL_RUBRIC_ROWS if row.index in indexes]
    return "\n".join(
        f"- {row.key}（{row.name}，0-10 分）：{row.anchor_questions}"
        for row in rows
    )


def build_appeal_system_prompt(stage: str) -> str:
    """Advisory Appeal-rubric reviewer prompt for text/motion artifacts."""
    rows_block = _rubric_rows_block(stage)
    row_keys = ", ".join(
        row.key
        for row in APPEAL_RUBRIC_ROWS
        if row.index in STAGE_RUBRIC_ROWS.get(stage, (0, 1, 2))
    )
    return f"""你是一名严苛的创作质量审阅顾问，负责在 Creator Agent 运行过程中对刚写入工程的文本产物做证据化的对抗性审阅。
你收到的是本次提交变更的字段指针与内容。审阅采用上游 Appeal rubric 的逐行打分制（每行 0-10 分），行定义如下（保持原义，不得替换维度）：

{rows_block}

判定纪律（{EVIDENCE_DISCIPLINE}）：
1. 每行给出 0-10 分；score <= 5 视为该行不合格（ok=false），必须在 finding 中引用具体字段指针或原文片段作为证据，并在 suggestion 中给出一句可直接执行的修订指令。
2. concept 行 score <= {CONCEPT_WEAK_THRESHOLD} 时，suggestion 必须以 "{CONCEPT_VETO_QUOTE}" 的精神指出概念空洞的具体表现（如素材流水账、换个主体照样成立）。
3. 这是建议不是门禁：不存在否决，你的输出只作为下一回合的修订参考。
4. 无证据不得判不合格；拿不准时从宽给分。
5. 常见需点名的失败模式：{"；".join(COMMON_FAILURES[:6])}。

输出格式（只输出一个 JSON 对象，不要输出任何其他文字或代码块标记）：
{{
  "scores": [
    {{"row_key": "<{row_keys} 各一条>", "score": <0-10>, "ok": true/false, "finding": "<证据引用，合格时可为空>", "suggestion": "<修订指令，合格时可为空>"}}
  ],
  "summary": "<一句话总体评价>"
}}"""


def build_scene_check_system_prompt() -> str:
    """Scene-review reviewer prompt for one generated element video."""
    checks_block = "\n".join(
        f"- {check.key}（{check.title}）：{check.description}"
        for check in SCENE_REVIEW_CHECKS
    )
    check_keys = ", ".join(check.key for check in SCENE_REVIEW_CHECKS)
    return f"""你是一名严苛的场景级视频审阅专家，对一条刚生成的分镜/元素视频按上游 scene-review 六检查做证据化审阅。
你收到的是按时间顺序抽取的证据帧（首尾帧必在其中）、客观门禁证据块（ffprobe/响度/黑帧）与画面统计数值。六检查定义（保持原义）：

{checks_block}

判定纪律（{EVIDENCE_DISCIPLINE}）：
1. 六项各输出恰好一条 finding；passed=false 必须给出 evidence_timestamp_ms（取自证据帧时间戳或门禁证据块），无证据必须判通过。
2. devices 检查对照给出的分镜计划上下文：计划声明的画面要素在帧上找不到即不通过。
3. severity 判据：黑帧/主体错误/首尾帧脏（残留 UI、半截动作）/无法辨认的文字为 major；轻微构图或动感瑕疵为 minor。
4. 门禁证据块中的 FAIL 行必须体现在 technical 检查的 finding 中，不得忽略。
5. 这是建议不是门禁：输出只用于驱动下一轮修订，不阻断交付。

输出格式（只输出一个 JSON 对象）：
{{
  "findings": [
    {{"check_key": "<{check_keys} 各一条>", "passed": true/false, "severity": "minor"/"major", "evidence_timestamp_ms": <int 或 null>, "suggestion": "<修订指令，通过时可为空>"}}
  ]
}}"""


def build_image_check_system_prompt() -> str:
    """Reviewer prompt for one generated still image artifact.

    Derived from the scene-review rows that exist at image level
    (type_fonts, composition_safety) plus the craft rubric row.
    """
    relevant = [
        check
        for check in SCENE_REVIEW_CHECKS
        if check.key in {"devices", "type_fonts", "composition_safety"}
    ]
    checks_block = "\n".join(
        f"- {check.key}（{check.title}）：{check.description}"
        for check in relevant
    )
    craft = next(row for row in APPEAL_RUBRIC_ROWS if row.key == "craft")
    check_keys = ", ".join(check.key for check in relevant) + ", craft"
    return f"""你是一名严苛的视觉产物审阅专家，对一张刚生成的图像（角色图/场景图/分镜图）做证据化审阅。
适用的上游检查行（保持原义，按图像语境理解：devices=计划上下文声明的主体/场景/道具是否真的在画面中）：

{checks_block}
- craft（{craft.name}）：{craft.anchor_questions}；另检查肢体/手指畸变、乱码或豆腐块文字、主体被裁切。

判定纪律（{EVIDENCE_DISCIPLINE}，图像以字段指针/画面区域描述代替时间戳）：
1. 各检查行输出恰好一条 finding；passed=false 必须在 suggestion 中描述画面中的具体证据位置。
2. 与计划上下文（分镜描述/角色引用）不一致（如角色不符、场景不符）为 major；轻微风格偏差为 minor。
3. 画面统计（欠曝/发灰/低饱和）仅在肉眼可见劣化时才计为 finding。
4. 这是建议不是门禁。

输出格式（只输出一个 JSON 对象）：
{{
  "findings": [
    {{"check_key": "<{check_keys} 各一条>", "passed": true/false, "severity": "minor"/"major", "evidence_timestamp_ms": null, "suggestion": "<修订指令，通过时可为空>"}}
  ]
}}"""


def render_taste_principles(role: str) -> str:
    """Role-scoped taste principles for the static agent prompt sections.

    Rendered once and pasted into the ``prompts/*.system.txt`` files; kept
    here so tests can assert the prompt files stay derived from the vendored
    rubric (see ``tests/run_review/test_rubric_prompts.py``).
    """
    concept = APPEAL_RUBRIC_ROWS[0]
    rhythm = APPEAL_RUBRIC_ROWS[2]
    restraint = APPEAL_RUBRIC_ROWS[3]
    lines: list[str] = [
        "以下创作品味准则源自 vendored review_rubrics（Qwen-MM-Plugins "
        "video-edit skill），应当遵循（建议性准则，不是门禁）：",
    ]
    if role in {"creator_agent", "ai_editing_director"}:
        lines += [
            f"- 概念先行：{concept.anchor_questions}（素材流水账不是概念）。",
            f"- 节奏：{rhythm.anchor_questions}",
            f"- 克制：{restraint.anchor_questions}",
            (
                "- 设计底线：有开场处理、每个场景至少一个设计化节拍、有收束式结尾；"
                "避免：" + "；".join(COMMON_FAILURES[:5]) + "。"
            ),
        ]
    if role == "r2v_generation_director":
        motion = next(
            check
            for check in SCENE_REVIEW_CHECKS
            if check.key == "motion_quality"
        )
        lines += [
            f"- 概念先行：{concept.anchor_questions}",
            f"- 镜头与首尾帧：{motion.description}",
            "- 主体一致：分镜计划声明的主体/场景/道具必须真的出现在画面中，声明而未落地即失败。",
        ]
    if role == "visual_development_agent":
        composition = next(
            check
            for check in SCENE_REVIEW_CHECKS
            if check.key == "composition_safety"
        )
        lines += [
            f"- 构图安全：{composition.description}",
            "- 一致性：角色/场景设计图之间保持造型、配色与光线的一致性；文字元素不得乱码或使用占位字形。",
        ]
    return "\n".join(lines)


__all__ = [
    "STAGE_RUBRIC_ROWS",
    "build_appeal_system_prompt",
    "build_image_check_system_prompt",
    "build_scene_check_system_prompt",
    "render_taste_principles",
]
