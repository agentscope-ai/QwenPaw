# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Prompt builders derived from the vendored upstream review rules.

Every run-review prompt (and the taste principles rendered into the agent
prompts) is generated from ``vendor.media_toolkit.review_rubrics`` so the
wording stays aligned with the upstream video-edit skill. The upstream
concept veto is deliberately downgraded: a weak concept yields a
major-severity suggestion, never a delivery gate.
"""

from __future__ import annotations

from vendor.media_toolkit.review_rubrics import (
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


def build_scene_check_system_prompt(*, include_probes: bool = False) -> str:
    """Scene-review reviewer prompt for one generated element video.

    ``include_probes`` extends the output contract with the universal
    defect-bank and plan-faithfulness ET/CT/NA arrays (the question
    lists themselves arrive in the user turn).
    """
    checks_block = "\n".join(
        f"- {check.key}（{check.title}）：{check.description}"
        for check in SCENE_REVIEW_CHECKS
    )
    check_keys = ", ".join(check.key for check in SCENE_REVIEW_CHECKS)
    probe_discipline = ""
    probe_format = ""
    if include_probes:
        probe_discipline = """
6. 用户消息中若附有【固定缺陷题清单】与【计划忠实度五要素】，逐题/逐要素给出 ET/CT/NA 判定：ET=确认无此缺陷或方向一致；CT=确认存在（必须给出 evidence_timestamp_ms 与一句可执行的 suggestion）；NA=不适用（reason 必须非空，说明为什么不适用）。拿不准时判 ET，不要猜。
7. 判定中引用的时间戳只能取自证据图列表中存在的时间戳；引用不存在的帧会被程序判为无效。"""
        probe_format = """,
  "defect_findings": [
    {"probe_id": "<题库题目 id>", "verdict": "ET"/"CT"/"NA", "evidence_timestamp_ms": <int 或 null>, "reason": "<NA 必填理由；CT 填「看到了什么」>", "suggestion": "<CT 必填修订指令>"}
  ],
  "faithfulness_findings": [
    {"probe_id": "<要素 key>", "verdict": "ET"/"CT"/"NA", "evidence_timestamp_ms": <int 或 null>, "reason": "<CT 填「计划要求 vs 实际画面」对照；NA 必填理由>", "suggestion": "<CT 必填修订指令>"}
  ]"""
    return f"""你是一名严苛的场景级视频审阅专家，对一条刚生成的分镜/元素视频按上游 scene-review 六检查做证据化审阅。
你收到的是按时间顺序抽取的证据帧（首尾帧必在其中，可能附有程序定位的聚焦帧）、客观门禁证据块（ffprobe/响度/黑帧）、画面统计数值与客观事实提示。六检查定义（保持原义）：

{checks_block}

判定纪律（{EVIDENCE_DISCIPLINE}）：
1. 六项各输出恰好一条 finding；passed=false 必须给出 evidence_timestamp_ms（取自证据帧时间戳或门禁证据块），无证据必须判通过。
2. devices 检查对照计划中持续可见的主体与物件。证据是稀疏采样，不是完整视频；瞬时动作可能发生在两张证据帧之间，未采到不能等同于动作缺失，不得据此判为 major 或要求重做。只描述实际看见的内容，逐张核对证据列表的时间戳，不把相邻图片的动作或时间错配。
3. severity 判据：黑帧/主体错误/首尾帧脏（残留 UI、半截动作）/无法辨认的文字为 major；轻微构图或动感瑕疵为 minor。
4. 门禁证据块中的 FAIL 行必须体现在 technical 检查的 finding 中，不得忽略。
5. 负面约束必须按原句范围判断，不能扩大禁令。例如「不出现纸币特写与可读面额」仍允许桌面远景出现不可读的零钱；只有实际出现特写或可读面额才算违背该约束。计划中明确保留的道具不得仅因出现就要求删除。人物动作归属须沿手臂、袖色与身体逐项核对；遮挡或透视不能确认归属时，不得把猜测当作角色互换或 major。
6. 这是建议不是门禁：输出只用于驱动下一轮修订，不阻断交付。低全帧差异、静态机位或一张姿态静止的图片不能证明视频冻结，人物说话时的嘴型微动可能低于全帧阈值。music_detected 的频谱/节拍投票只是启发式，带音高的人声也会命中，未收到可听音频不能断言添加了背景音乐。句首到切点的距离不是口型同步测量；不得据此断言声画错位。客观提示须结合真实证据，无法确认时不驱动重做。{probe_discipline}

输出格式（只输出一个 JSON 对象）：
{{
  "findings": [
    {{"check_key": "<{check_keys} 各一条>", "passed": true/false, "severity": "minor"/"major", "evidence_timestamp_ms": <int 或 null>, "suggestion": "<修订指令，通过时可为空>"}}
  ]{probe_format}
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
3. 先按 artifact_purpose、variant_requirements 和 generation_prompt 判断当前图的用途；project_brief 是全片目标，不能要求单张人物身份板同时出现剧情场景、对白或电影画面。身份板中的独立姿态、轮廓、表情、细节和留白按参考用途评价，不按连续剧情动作评价。
4. 画面统计是全图指标，不是主体颜色诊断。米白/白色背景、留白、黑白服装会显著拉低均值；不得仅因 sat_mean 或全图均值低而认定人物或服装发灰、欠饱和。只有具体主体区域肉眼可见且违背该图生成要求的色彩损失才可提出建议，轻微风格偏差为 minor。不要无依据要求提高饱和度来否定刻意的自然低饱和风格。
5. 道具上的背景纹理文字与剧情必须读清的文字分开：只在用途明确要求可读、且确实影响身份或叙事时，才将不可读文字列为 major；仍要报告可见的真实结构、主体或空间矛盾。
6. 阵容参考图（cast_lineup_reference）须按 expected_character_count 逐人计数、核对身份与道具归属。每个角色只能出现一次；不能把多角度身份板允许的重复视图套用到同框阵容。实际多出人物、复制同一人、胡须或服装身份混淆、关键道具交给错误人物，均须指出具体画面区域并报告。
7. 负面约束按原句范围判断，不扩大禁令；「不出现纸币特写与可读面额」不等于「不得出现任何零钱」。人物动作归属须沿手臂、袖色与身体核对，不得因遮挡或透视把猜测当作人物互换。要求重做前，复核所指画面区域确实与计划冲突。
8. 这是建议不是门禁。

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
    rubric (see ``tests/run_review/test_vendored_rules.py``).
    """
    concept = APPEAL_RUBRIC_ROWS[0]
    rhythm = APPEAL_RUBRIC_ROWS[2]
    restraint = APPEAL_RUBRIC_ROWS[3]
    if role == "ai_editing_director":
        # The editing director carries the edit_plan taste contract (WT-B1):
        # the principles land in that object and the plan advisory nudges
        # the model when it skips the contract.
        lines: list[str] = [
            "以下创作品味准则源自 vendored review_rubrics（Qwen-MM-Plugins "
            "video-edit skill）。`edit_plan` 是它们的落地载体：先写契约是"
            "标准流程，跳过会在提交结果收到 `planAdvisory` 提示（不阻断），"
            "成片审查也会以契约为对照物评分：",
        ]
    else:
        lines = [
            "以下创作品味准则源自 vendored review_rubrics（Qwen-MM-Plugins "
            "video-edit skill），应当遵循（建议性准则，不是门禁）：",
        ]
    if role in {"creator_agent", "ai_editing_director"}:
        rhythm_principle = (
            "开场是否尽快建立关注点？能量是否有快慢变化？需要停留的时刻是否"
            "真正停住？长镜头只在叙事和可执行动作支持时使用，不设统一的 7 秒"
            "镜头上限。"
            if role == "creator_agent"
            else rhythm.anchor_questions
        )
        lines += [
            f"- 概念先行：{concept.anchor_questions}（素材流水账不是概念）。",
            f"- 节奏：{rhythm_principle}",
            f"- 克制：{restraint.anchor_questions}",
            (
                "- 设计底线：有开场处理、每个场景至少一个设计化节拍、有收束式结尾；"
                "避免：" + "；".join(COMMON_FAILURES[:5]) + "。"
            ),
        ]
    return "\n".join(lines)


__all__ = [
    "STAGE_RUBRIC_ROWS",
    "build_appeal_system_prompt",
    "build_image_check_system_prompt",
    "build_scene_check_system_prompt",
    "render_taste_principles",
]
