# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-statements,too-many-locals
# pylint: disable=too-many-return-statements,line-too-long
"""VLM-driven motion-graphic design for Timeline edit segments.

``design_motion_overlays`` runs two passes over one Timeline.  Pass A looks
at real frames behind every text Overlay (``pet_os`` / ``interview_summary``)
and designs a fancy generated caption card, stored as ``creation.motion`` on
that same Element; the fixed bubble template stays as the render fallback.
Pass B picks a sparse set of segments worth a decorative sticker through one
coordinated selection call, designs each pick against real keyframes, and
persists accepted designs as ``overlay_kind="motion"`` Elements.  Every
document is validated by actually loading it before one Project commit.

The generated HTML never flows through an agent conversation: the caller only
receives a compact per-segment summary, keeping the collaboration protocol
and context budget unchanged.
"""

from __future__ import annotations

import asyncio
from html import unescape
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from domain.errors import NotFoundError, ValidationError
from models import vlm_model
from models.vlm_model import multimodal_media_part
from services.media_files.keyframe_cache import (
    materialize_keyframe,
    verified_indexed_path,
)
from services.media_files.motion_overlay import probe_motion_document
from services.media_files.motion_templates import (
    MOTION_TEMPLATE_VERSION,
    SUPPORTED_EMOTIONS,
    SUPPORTED_ENTRANCES,
    SUPPORTED_EXITS,
    SUPPORTED_MOTIFS,
    SUPPORTED_THEMES,
    SUPPORTED_VARIANTS,
    render_caption_template,
    render_decoration_template,
)
from services.project_files.models import (
    EditCreation,
    ElementLocation,
    MotionGraphic,
    OverlayCreation,
    Project,
    SourceVersionRenderSource,
    Timeline,
    TimelineElement,
    TimelineSpan,
)
from services.project_files.remote_cache import resolve_remote_cache
from services.project_files.store import ProjectSnapshot
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from utils.logger import setup_logger

logger = setup_logger("services.media_files.motion_design")

_MAX_SEGMENTS = 24
_MAX_CONCURRENT_DESIGNS = 3
_MAX_DESIGN_ATTEMPTS = 2
_TEXT_CARD_DESIGN_ATTEMPTS = 3
_TEXT_CARD_MIN_COVERAGE = 0.3
_TEXT_CARD_MAX_EDGE_CONTACT = 0.02
_DECORATION_MIN_COVERAGE = 0.08
_DECORATION_MAX_EDGE_CONTACT = 0.02
_KEYFRAME_WIDTH = 960
_VLM_MAX_TOKENS = 6000
_MOTION_ELEMENT_SUFFIX = "-motion"
_DEFAULT_DECORATION_BUDGET = 3
_MAX_DECORATION_BUDGET = 8

# Emoji and pictographic glyphs depend on platform color-font rasterization,
# which is unreliable in headless capture (hangs observed on macOS, tofu
# boxes on minimal Linux).  Designs must draw shapes with plain CSS instead.
_EMOJI_PATTERN = re.compile(
    "[\u2600-\u27bf\u2b00-\u2bff\ufe0f\U0001f000-\U0001faff]",
)

_SHARED_CODE_RULES = """代码要求：
- html 是一个完整的独立 HTML 文档，背景完全透明（不要给 html/body 设置任何背景色）。
- 所有运动只允许用 CSS @keyframes 动画实现；文档中不允许出现 <script> 标签，也不允许引用任何外部资源（外链字体、图片、CSS 都不行）。视觉元素只用 CSS 形状、渐变和系统字体的普通文字来构建；不要使用 emoji 字符，渲染环境无法可靠显示 emoji，需要具象图形时请用 CSS 画出来（例如用圆角矩形、border-radius、clip-path、多层渐变组合）。
- 文档会被渲染到一个固定尺寸的透明盒子里，盒子尺寸会在任务里给出；请给 html 和 body 显式设置 width:100% 与 height:100%，用 vw/vh 或百分比布局，让内容撑满该盒子并在盒子内动画。
- location 已经负责把整个透明盒子放到最终画面的正确位置和大小。HTML 内绝对不要再次使用 location 的 x/y/width/height 百分比做二次定位或缩放；根容器应接近 width:100%; height:100%。
- 所有主体、描边、投影、气泡尾巴和装饰粒子在动画的每个关键帧都必须完整留在 HTML 视口内，四周至少保留 5% 安全边距。不要用负 top/right/bottom/left 把任何可见部分伸出视口，也不要依赖 overflow:visible 显示越界内容。"""

_DECOR_SYSTEM_PROMPT = (
    """你是一位视频包装动效设计师。你会看到一个视频片段的真实画面帧和剪辑意图，需要判断这个片段是否值得叠加一个装饰性动效贴纸，并在值得时直接产出动效代码。

判断原则：
- 只有当动效能强化片段的情绪或信息时才生成；画面本身已经很满、很安静唯美、或任何动效都会显得多余时，果断跳过。
- 动效必须贴合画面：配色从画面帧中取，形状与主题呼应，位置和大小必须避开画面主体（人物、动物、关键物体），通常放在角落或留白区域。
- 动效是点缀，不是主角：面积一般不超过画面的四分之一，视觉强度克制。
- 装饰动效不是字幕卡：禁止出现任何可见文字、字母、数字、对话气泡、漫画对白框或标题卡。猫咪台词由独立的 OS Overlay 承担；这里仅使用受控模板制作猫爪印、闪光、叶片、聚焦标记、情绪符号等无文字点缀，并根据不同片段选择不同形式，避免每段重复同一种造型。
- 语义优先于表面配色：任务中如果提供同一时段的 OS 台词与情绪，动效造型必须直接呼应台词含义或当下动作（例如“很乖”可用勾选/认可符号，“发现目标”可用聚焦标记，“紧张对峙”可用闪电/张力线），不能只因为背景有植物就生成与台词无关的叶子。配色再从真实画面取色，让语义与画面同时一致。
- 先识别台词的语用意图，再选图形：寻找/发现可用 focus_target 或 sparkles；真正紧张或惊险才用 alert_mark；猫咪移动可用 paw_trail；明确认同才用 approval_checks。若没有成熟模板贴合语气，应输出 needed=false，宁可不加装饰，也不要用不相关图形代替。
- 克制不等于看不见：颜色要与所在区域的画面有明显对比（避免在亮色背景上用白色半透明这类容易融进画面的设计），并且从第一帧起就要有可见内容（入场运动可用负的 animation-delay 让动画从中段开始）。

"""
    + _SHARED_CODE_RULES
    + """
- 动画应设计成无缝循环（animation-iteration-count 用有限次数定义一个循环周期即可，渲染器会按 loop 处理）。

输出要求：只输出一个 JSON 对象，不要输出任何其他文字或代码围栏。字段：
{
  "needed": true 或 false,
  "skip_reason": "needed=false 时说明原因，否则空字符串",
  "concept": "一句话描述动效创意（needed=true 时必填）",
  "motif": "needed=true 时必须从 paw_trail、alert_mark、approval_checks、focus_target、sparkles、leaf_accent 中选择",
  "primary_color": "从画面取色的 #RRGGBB",
  "secondary_color": "用于描边/对比的 #RRGGBB",
  "theme": "全片统一主题，选 comic_patrol、soft_journal 或 neon_night",
  "variant": "视觉材质，选 sticker、ink 或 neon",
  "emotion": "动画情绪，选 chill、curious、surprise 或 action",
  "entrance": "进场方式，选 pop、stamp、draw_in 或 slide",
  "exit": "退场方式，选 soft_fade、shrink 或 none",
  "intensity": "0 到 1 的动画强度；安静片段低，情绪高点高",
  "html": "固定填空字符串；装饰图形由受控模板渲染",
  "fps": 24,
  "loop": true,
  "location": {"x": 0-1, "y": 0-1, "width": 0-1, "height": 0-1, "anchor_x": 0-1, "anchor_y": 0-1, "opacity": 0-1}
}
location 使用归一化画布坐标：x/y 是锚点在画布上的位置，anchor_x/anchor_y 选择内容盒的哪个点对齐到 x/y，width/height 是盒子相对画布的比例。"""
)

_TEXT_STYLE_SYSTEM_PROMPT = (
    """你是一位视频包装动效设计师。你会看到一个视频片段的真实画面帧和一段必须展示的台词文字，需要为这段文字设计一张精美的动态字幕卡，取代呆板的固定气泡样式。

设计原则：
- 台词文字必须一字不差地完整出现，是这张卡片的绝对主角：字号大、清晰易读，用描边、投影或色块底衬保证在任何画面上都读得清。整句台词必须完整落在视口内，一行放不下就主动换行并适当调小字号，绝不允许文字超出视口边缘被裁掉。卡片上出现的文字只能是台词本身，绝不要把任务说明、Element ID、时长等元数据写进卡片。
- 字效必须克制清楚：文字描边最多 1px，只能使用一层轻微阴影；禁止用四向或多层 text-shadow 模拟粗描边，否则缩小预览时会像多个字重叠。较长台词必须允许换行，不得使用 white-space:nowrap 强塞进一行。
- 视口就是卡片本身：location 已经框定了卡片在画面中的位置和大小，卡片主体必须撑满视口（宽高各占 90% 以上），台词字号用 vh 单位定义（主文字建议 16vh 以上，台词长时可换行）；绝不要在视口里再画一张小卡片或留大片空白。
- 风格精致有趣，漫画/综艺花字的气质：可以有气泡、色块、渐变、描边、装饰线条和小图形点缀；配色从画面帧中取色并拉开对比度，让卡片既融入画面又一眼抢眼。
- 位置和大小要避开画面主体（人物、动物、关键物体），贴近主体但不遮挡，通常在留白区域；卡片面积一般不超过画面的四分之一（通过 location.width/height 控制，不是把卡片画小）。
- 动画节奏：入场干脆有弹性（0.3~0.8 秒），入场后保持稳定可读，可叠加轻微的持续浮动。给所有入场动画设置 animation-fill-mode: forwards；持续浮动用较多的有限迭代次数（例如 animation-iteration-count: 20）覆盖片段时长；loop 字段填 false。

"""
    + _SHARED_CODE_RULES
    + """

输出要求：只输出一个 JSON 对象，不要输出任何其他文字或代码围栏。字段：
{
  "concept": "一句话描述这张字幕卡的设计创意",
  "html": "完整 HTML 文档字符串",
  "fps": 24,
  "loop": false,
  "location": {"x": 0-1, "y": 0-1, "width": 0-1, "height": 0-1, "anchor_x": 0-1, "anchor_y": 0-1, "opacity": 0-1}
}
location 使用归一化画布坐标：x/y 是锚点在画布上的位置，anchor_x/anchor_y 选择内容盒的哪个点对齐到 x/y，width/height 是盒子相对画布的比例。"""
)

_SELECT_SYSTEM_PROMPT = """你是一位视频包装总监。给你一支视频全部片段的剪辑意图清单，你要挑选最值得叠加装饰动效的少数片段。装饰动效是锦上添花：只在情绪高点、转折、开场或收尾这样的关键时刻出现才显得精心；每个片段都有反而廉价。数量不超过给定名额，可以少于名额，也可以是空数组。

输出要求：只输出一个 JSON 对象，格式：{"selected": ["elementId", ...]}。"""


def _target_timeline(project: Project, target_ref: str) -> Timeline:
    prefix = "timeline:"
    if not target_ref.startswith(prefix) or not target_ref[len(prefix) :]:
        raise ValidationError("targetRef 必须是 timeline:<id>")
    timeline_id = target_ref[len(prefix) :]
    timeline = project.timelines.items.get(timeline_id)
    if timeline is None:
        timeline = project.timelines.items.get(target_ref)
    if timeline is None:
        raise NotFoundError("Timeline 不存在")
    return timeline


def _segment_seconds(
    timeline: Timeline,
    element: TimelineElement,
) -> tuple[float, float]:
    render_source = element.render_source
    if not isinstance(render_source, SourceVersionRenderSource) or (
        render_source.source_out_tick is None
    ):
        raise ValidationError(
            f"Edit Element {element.element_id} 缺少完整 source 区间",
        )
    return (
        render_source.source_in_tick / timeline.ticks_per_second,
        render_source.source_out_tick / timeline.ticks_per_second,
    )


def _source_local_path(
    *,
    project: Project,
    project_root: Path,
    version_id: str,
    executions: ProjectExecutionStore,
) -> Path | None:
    """Resolve one source version to an existing local video file.

    Only already-materialized bytes are used: the verified Asset Index copy
    or the remote-ingest cache.  Designing never triggers a new download; a
    segment without local bytes is skipped with a clear reason instead.
    """

    version = project.assets.source_versions_by_id.get(version_id)
    if version is None:
        return None
    if version.file_id is not None:
        indexed = project.assets.files_by_id.get(version.file_id)
        if indexed is not None:
            try:
                return verified_indexed_path(project_root, indexed)
            except Exception:  # pragma: no cover - integrity surface below
                return None
    try:
        tasks = executions.list_tasks(project.project_id)
        cached = resolve_remote_cache(project_root, version, tasks)
    except Exception:  # pragma: no cover - malformed runtime records
        return None
    return cached.path if cached is not None else None


def _parse_design_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.match(
        r"^```[A-Za-z0-9_-]*\s*(.*?)\s*```$",
        cleaned,
        re.DOTALL,
    )
    if fenced:
        cleaned = fenced.group(1).strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValidationError("VLM 输出中不包含 JSON 对象")
        cleaned = cleaned[start : end + 1]
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"VLM 输出不是合法 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("VLM 输出 JSON 不是对象")
    return value


def _validated_location(raw: Any) -> ElementLocation:
    if not isinstance(raw, Mapping):
        raise ValidationError("design location 必须是对象")
    allowed = {
        "x",
        "y",
        "width",
        "height",
        "anchor_x",
        "anchor_y",
        "rotation_degrees",
        "opacity",
    }
    payload = {
        key: value for key, value in dict(raw).items() if key in allowed
    }
    location = ElementLocation.model_validate(payload)
    if not 0.01 <= location.width <= 1.0 or not 0.01 <= location.height <= 1.0:
        raise ValidationError("动效盒子必须在画布尺寸的 1% 到 100% 之间")
    left = location.x - location.anchor_x * location.width
    top = location.y - location.anchor_y * location.height
    right = left + location.width
    bottom = top + location.height
    if left < 0.0 or top < 0.0 or right > 1.0 or bottom > 1.0:
        raise ValidationError(
            "动效 location 盒子超出画布边界；调整 x/y、width/height 或 anchor，确保完整落在 0..1 画布内",
        )
    return location


def _locations_overlap(
    left: ElementLocation,
    right: ElementLocation,
    *,
    gap: float = 0.01,
) -> bool:
    """Return whether two normalized boxes overlap or violate a small gap."""

    left_x = left.x - left.anchor_x * left.width
    left_y = left.y - left.anchor_y * left.height
    right_x = right.x - right.anchor_x * right.width
    right_y = right.y - right.anchor_y * right.height
    return not (
        left_x + left.width + gap <= right_x
        or right_x + right.width + gap <= left_x
        or left_y + left.height + gap <= right_y
        or right_y + right.height + gap <= left_y
    )


def _validated_design(
    raw: Mapping[str, Any],
    *,
    required_text: str | None = None,
    default_loop: bool = True,
) -> tuple[MotionGraphic, ElementLocation, str] | str:
    """Return ``(motion, location, concept)`` or a skip reason string.

    ``required_text`` switches to text-card mode: the design is always
    needed and the given text must appear verbatim in the document.
    """

    if required_text is None:
        needed = raw.get("needed")
        if needed is not True:
            reason = str(raw.get("skip_reason") or "").strip()
            return reason or "设计模型判断此片段无需动效"
    motif = str(raw.get("motif") or "custom").strip()
    theme = str(raw.get("theme") or "comic_patrol").strip()
    variant = str(raw.get("variant") or "sticker").strip()
    emotion = str(raw.get("emotion") or "chill").strip()
    entrance = str(raw.get("entrance") or "pop").strip()
    exit_style = str(raw.get("exit") or "soft_fade").strip()
    theme = theme if theme in SUPPORTED_THEMES else "comic_patrol"
    variant = variant if variant in SUPPORTED_VARIANTS else "sticker"
    emotion = emotion if emotion in SUPPORTED_EMOTIONS else "chill"
    entrance = entrance if entrance in SUPPORTED_ENTRANCES else "pop"
    exit_style = exit_style if exit_style in SUPPORTED_EXITS else "soft_fade"
    try:
        intensity = min(1.0, max(0.0, float(raw.get("intensity", 0.6))))
    except (TypeError, ValueError):
        intensity = 0.6
    uses_template = required_text is None and motif in SUPPORTED_MOTIFS
    html = (
        render_decoration_template(
            motif,
            primary_color=raw.get("primary_color"),
            secondary_color=raw.get("secondary_color"),
            theme=theme,
            variant=variant,
            emotion=emotion,
            entrance=entrance,
            exit=exit_style,
            intensity=intensity,
        )
        if uses_template
        else raw.get("html")
    )
    if not isinstance(html, str) or len(html.strip()) < 32:
        raise ValidationError("design html 缺失或过短")
    html = html.strip()
    if len(html) > 200_000:
        raise ValidationError("design html 超过 200000 字符上限")
    if re.search(r"<\s*script\b", html, re.IGNORECASE):
        raise ValidationError("design html 不允许包含 <script> 标签")
    if re.search(
        r"<\s*(?:iframe|object|embed|applet|base|form|input|button|textarea|select)\b",
        html,
        re.IGNORECASE,
    ):
        raise ValidationError("design html 包含不允许的交互、嵌入或导航标签")
    if re.search(
        r"<\s*meta\b[^>]*http-equiv\s*=\s*(['\"]?)refresh\1",
        html,
        re.IGNORECASE,
    ):
        raise ValidationError("design html 不允许使用 meta refresh 导航")
    if re.search(r"\son[a-z0-9_-]+\s*=", html, re.IGNORECASE):
        raise ValidationError("design html 不允许包含事件处理属性")
    if re.search(
        r"(?:javascript|file|data\s*:\s*text/html)\s*:",
        html,
        re.IGNORECASE,
    ):
        raise ValidationError("design html 不允许包含脚本、本机文件或嵌入网页 URL")
    if re.search(
        r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""",
        html,
        re.IGNORECASE,
    ) or re.search(r"url\(\s*['\"]?\s*(?:https?:)?//", html, re.IGNORECASE):
        raise ValidationError("design html 不允许引用外部网络资源")
    if _EMOJI_PATTERN.search(html):
        raise ValidationError(
            "design html 包含 emoji 字符，渲染环境无法可靠显示，请改用纯 CSS 形状、渐变来构建视觉元素",
        )
    body = re.sub(
        r"<\s*(style|head)\b.*?<\s*/\s*\1\s*>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)
    visible = unescape(
        re.sub(r"\s+", "", re.sub(r"<[^>]+>", " ", body)),
    )
    if required_text is None and visible:
        raise ValidationError(
            "装饰动效不允许包含任何可见文字；请改用纯 CSS 图形表达，不要生成对话气泡或标题卡",
        )
    if required_text is None and re.search(
        r"\bcontent\s*:\s*(['\"])(?!\s*\1).+?\1",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        raise ValidationError(
            "装饰动效不允许通过 CSS content 生成可见文字或符号；请用 CSS 几何图形表达",
        )
    if required_text is not None:
        wanted = re.sub(r"\s+", "", required_text)
        if wanted and wanted not in visible:
            raise ValidationError(
                "design html 没有完整包含给定的台词文字，台词必须一字不差地出现（可以换行，但不能改写或省略）",
            )
        extra = visible.replace(wanted, "", 1) if wanted else visible
        if len(extra) > 6:
            raise ValidationError(
                "卡片上的可见文字只能是台词本身，不要把任务说明、Element ID 等其他文字画进卡片",
            )
    elif motif not in SUPPORTED_MOTIFS:
        raise ValidationError(
            "装饰动效必须使用受控 motif 模板，不允许自由生成 custom HTML",
        )
    concept = str(raw.get("concept") or "").strip()
    if not concept:
        raise ValidationError("design concept 不能为空")
    fps_raw = raw.get("fps", 24)
    try:
        fps = int(fps_raw)
    except (TypeError, ValueError):
        fps = 24
    fps = min(max(fps, 8), 60)
    loop = raw.get("loop")
    motion = MotionGraphic(
        html=html,
        fps=fps,
        loop=default_loop if loop is None else bool(loop),
        design_notes=concept,
        motif=motif if required_text is None else "caption_card",
        template_version=MOTION_TEMPLATE_VERSION if uses_template else None,
        theme=theme,
        variant=variant,
        emotion=emotion,
        entrance=entrance,
        exit=exit_style,
        intensity=intensity,
    )
    location = _validated_location(raw.get("location"))
    return motion, location, concept


def _design_task_text(
    *,
    element: TimelineElement,
    duration_seconds: float,
    canvas_size: tuple[int, int],
    brief: str,
    avoid_locations: list[tuple[str, ElementLocation]] | None = None,
    os_context: list[str] | None = None,
    theme: str = "comic_patrol",
    used_motifs: set[str] | None = None,
    story_role: str | None = None,
    story_motif: str | None = None,
) -> str:
    creation = element.creation
    assert isinstance(creation, EditCreation)
    lines = [
        "请为下面这个视频片段做动效决策与设计。",
        f"片段标签: {element.label or element.element_id}",
        f"片段时长: {duration_seconds:.1f} 秒",
        f"剪辑意图: {creation.intent or '（未提供）'}",
        f"选择理由: {creation.reason or '（未提供）'}",
        f"画布尺寸: {canvas_size[0]}x{canvas_size[1]} 像素。"
        "动效盒子的像素尺寸 = location.width/height 乘以画布尺寸，请据此设计布局。",
        f"全片统一视觉主题: {theme}。所有片段必须沿用该主题，不得自行切换。",
    ]
    if brief:
        lines.append(f"整体包装要求: {brief}")
    if story_role and story_motif:
        lines.append(
            f"本段在全片动效叙事中的角色是「{story_role}」，"
            f"故事规划建议 {story_motif} 造型，但这只是建议。必须先判断同一时段 OS 台词的语用意图；"
            "若建议造型与台词不吻合，请从允许的 motif 中换成更直接的视觉表达。",
        )
    if used_motifs:
        lines.append(
            "全片前面已使用这些装饰造型: "
            + "、".join(sorted(used_motifs))
            + "。若剧情语义允许，请换一种造型，形成有变化但统一的视觉节奏。",
        )
    if os_context:
        lines.append("同一时段的猫咪 OS 语义如下；装饰造型必须呼应这些台词/情绪，但不得重复显示文字：")
        lines.extend(f"- {context}" for context in os_context)
    if avoid_locations:
        lines.append("以下猫咪 OS/字幕卡会在同一时段出现，装饰动效的 location 盒子不得与它们重叠：")
        lines.extend(
            f"- {label}: {location.model_dump(mode='json')}"
            for label, location in avoid_locations
        )
    lines.append(
        "附图是该片段内按时间顺序抽取的真实画面帧，请从中判断主体位置、留白区域和配色。严格按系统要求只输出一个 JSON 对象。",
    )
    return "\n".join(lines)


def _text_style_task_text(
    *,
    overlay: TimelineElement,
    edit_element: TimelineElement | None,
    duration_seconds: float,
    canvas_size: tuple[int, int],
    brief: str,
    theme: str = "comic_patrol",
) -> str:
    creation = overlay.creation
    assert isinstance(creation, OverlayCreation)
    lines = [
        "请为下面这段台词设计动态字幕卡。",
        f"台词文字: {creation.text}",
        f"情绪基调: {creation.vibe}",
        f"展示时长: {duration_seconds:.1f} 秒",
        f"全片统一视觉主题: {theme}。字幕卡需与该主题保持一致。",
    ]
    if edit_element is not None and isinstance(
        edit_element.creation,
        EditCreation,
    ):
        lines.append(
            f"片段剪辑意图: {edit_element.creation.intent or '（未提供）'}",
        )
    lines.append(
        f"画布尺寸: {canvas_size[0]}x{canvas_size[1]} 像素。"
        "字幕卡盒子的像素尺寸 = location.width/height 乘以画布尺寸，请据此设计字号与布局。",
    )
    if brief:
        lines.append(f"整体包装要求: {brief}")
    lines.append(
        "附图是该时段内按时间顺序抽取的真实画面帧，请从中判断主体位置、留白区域和配色。严格按系统要求只输出一个 JSON 对象。",
    )
    return "\n".join(lines)


async def _design_document(
    *,
    system_prompt: str,
    task_text: str,
    frame_paths: list[Path],
    canvas_size: tuple[int, int],
    required_text: str | None = None,
    default_loop: bool = True,
    min_coverage: float = 0.0,
    max_edge_contact: float = 1.0,
    forbidden_locations: tuple[ElementLocation, ...] = (),
    max_attempts: int = _MAX_DESIGN_ATTEMPTS,
    ffmpeg_path: str | None = None,
    forced_theme: str | None = None,
    forced_fields: Mapping[str, Any] | None = None,
) -> tuple[MotionGraphic, ElementLocation, str] | str:
    """Design one document with bounded retries; returns design or skip reason."""

    base_content: list[dict[str, Any]] = [
        multimodal_media_part(path.resolve().as_uri(), "image")
        for path in frame_paths
    ]
    feedback = ""
    last_error = "动效设计失败"
    for attempt in range(max_attempts):
        content = [
            *base_content,
            {"type": "text", "text": task_text + feedback},
        ]
        try:
            answer = await vlm_model.chat_completion(
                content,
                system_prompt=system_prompt,
                temperature=0.6 if attempt == 0 else 0.4,
                max_tokens=_VLM_MAX_TOKENS,
            )
            parsed = _parse_design_json(answer)
            if forced_theme is not None:
                parsed["theme"] = forced_theme
            if forced_fields:
                parsed.update(forced_fields)
            design = _validated_design(
                parsed,
                required_text=required_text,
                default_loop=default_loop,
            )
        except ValidationError as exc:
            last_error = str(exc)
            feedback = f"\n上一次输出被拒绝，原因：{last_error}。" "请修正后重新只输出一个 JSON 对象。"
            continue
        if isinstance(design, str):
            return design
        motion, location, concept = design
        if any(
            _locations_overlap(location, forbidden)
            for forbidden in forbidden_locations
        ):
            last_error = "装饰动效位置与同一时段的猫咪 OS/字幕卡重叠"
            feedback = (
                f"\n上一次输出被拒绝，原因：{last_error}。"
                "请在真实画面的其他留白区域重新选择 location，"
                "两个盒子之间至少保留 1% 画布间距。请重新只输出一个 JSON 对象。"
            )
            continue
        probe = await asyncio.to_thread(
            probe_motion_document,
            motion.html,
            box_width=max(
                160,
                round(canvas_size[0] * location.width) // 2 * 2,
            ),
            box_height=max(
                90,
                round(canvas_size[1] * location.height) // 2 * 2,
            ),
            ffmpeg_path=ffmpeg_path,
        )
        if not probe.ok:
            last_error = probe.error
            feedback = (
                f"\n上一次输出的 HTML 加载校验失败，原因：{last_error}。" "请修正后重新只输出一个 JSON 对象。"
            )
            continue
        if 0.0 <= probe.visible_coverage < min_coverage:
            last_error = f"卡片内容只覆盖盒子面积的 {probe.visible_coverage:.0%}，太小了"
            feedback = (
                f"\n上一次输出被拒绝，原因：{last_error}。"
                "html 视口本身就是这张卡片，卡片主体必须撑满视口"
                "（宽高各占 90% 以上），台词字号用 vh 单位放大（主文字 16vh 以上），"
                "不要在视口里画小卡片。请修正后重新只输出一个 JSON 对象。"
            )
            continue
        if probe.edge_contact > max_edge_contact:
            last_error = f"卡片内容溢出了视口边缘被裁掉" f"（边缘接触率 {probe.edge_contact:.0%}）"
            feedback = (
                f"\n上一次输出被拒绝，原因：{last_error}。"
                "整句台词和卡片装饰必须完整落在视口内、四周留出边距："
                "一行放不下就换行并适当调小字号，绝不要让内容贴到或超出视口边缘。"
                "请修正后重新只输出一个 JSON 对象。"
            )
            continue
        return motion, location, concept
    raise ValidationError(last_error)


async def _select_decoration_ids(
    *,
    edit_elements: list[TimelineElement],
    timeline: Timeline,
    budget: int,
    brief: str,
) -> set[str]:
    """Pick at most ``budget`` segments that deserve a decoration.

    One text-only coordinated pass sees the whole cut, so sparsity is a
    property of the video instead of independent per-segment decisions.
    Falls back to evenly spaced picks if the model answer is unusable.
    """

    if budget <= 0:
        return set()
    if len(edit_elements) <= budget:
        return {element.element_id for element in edit_elements}
    lines = [
        f"全片共 {len(edit_elements)} 个片段，装饰动效名额最多 {budget} 个。",
    ]
    if brief:
        lines.append(f"整体包装要求: {brief}")
    for index, element in enumerate(edit_elements, 1):
        creation = element.creation
        intent = (
            creation.intent
            if isinstance(creation, EditCreation) and creation.intent
            else "（未提供）"
        )
        seconds = element.span.duration_tick / timeline.ticks_per_second
        lines.append(
            f"{index}. elementId={element.element_id} 时长{seconds:.1f}秒 "
            f"标签：{element.label or '（无）'} 意图：{intent}",
        )
    lines.append('只输出 {"selected": [elementId, ...]} 形式的 JSON 对象。')
    known = {element.element_id for element in edit_elements}
    try:
        answer = await vlm_model.chat_completion(
            [{"type": "text", "text": "\n".join(lines)}],
            system_prompt=_SELECT_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=1000,
        )
        raw = _parse_design_json(answer).get("selected")
        if isinstance(raw, list):
            picked = [
                item for item in raw if isinstance(item, str) and item in known
            ]
            return set(picked[:budget])
    except Exception:  # pragma: no cover - selection falls back below
        pass
    step = len(edit_elements) / budget
    return {
        edit_elements[
            min(len(edit_elements) - 1, round(index * step))
        ].element_id
        for index in range(budget)
    }


def _motion_element(
    *,
    edit_element: TimelineElement,
    motion: MotionGraphic,
    location: ElementLocation,
    concept: str,
) -> TimelineElement:
    return TimelineElement(
        element_id=f"{edit_element.element_id}{_MOTION_ELEMENT_SUFFIX}",
        label=f"动效: {concept[:40]}",
        span=TimelineSpan(
            start_tick=edit_element.span.start_tick,
            duration_tick=edit_element.span.duration_tick,
        ),
        location=location,
        z_index=edit_element.z_index + 10,
        creation=OverlayCreation(
            overlay_kind="motion",
            prompt=concept,
            motion=motion,
        ),
        provenance_refs=[f"element:{edit_element.element_id}"],
    )


def _story_arc_motifs(
    ordered_element_ids: list[str],
    planned_beats: list[tuple[str, str, Mapping[str, Any]]] | None = None,
) -> dict[str, tuple[str, str, Mapping[str, Any]]]:
    """Map a free-form beginning-turn-resolution plan onto the timeline."""

    if not ordered_element_ids:
        return {}
    beats = planned_beats or [
        (
            "开场引导：建立故事起点",
            "focus_target",
            {
                "emotion": "curious",
                "entrance": "draw_in",
                "exit": "soft_fade",
                "intensity": 0.5,
            },
        ),
        (
            "中段变化：提示重要转折",
            "sparkles",
            {
                "emotion": "surprise",
                "entrance": "pop",
                "exit": "shrink",
                "intensity": 0.6,
            },
        ),
        (
            "结尾收束：完成视觉句点",
            "approval_checks",
            {
                "emotion": "chill",
                "entrance": "pop",
                "exit": "soft_fade",
                "intensity": 0.5,
            },
        ),
    ]
    opening, turn, ending = beats
    if len(ordered_element_ids) == 1:
        return {ordered_element_ids[0]: ending}
    arc = {
        ordered_element_ids[0]: opening,
        ordered_element_ids[-1]: ending,
    }
    if len(ordered_element_ids) >= 3:
        arc[ordered_element_ids[len(ordered_element_ids) // 2]] = turn
    return arc


def _validated_story_beats(
    raw: Any,
) -> list[tuple[str, str, Mapping[str, Any]]] | None:
    if not isinstance(raw, list) or len(raw) != 3:
        return None
    result: list[tuple[str, str, Mapping[str, Any]]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return None
        role = str(item.get("role") or "").strip()
        motif = str(item.get("motif") or "").strip()
        emotion = str(item.get("emotion") or "").strip()
        entrance = str(item.get("entrance") or "").strip()
        exit_style = str(item.get("exit") or "soft_fade").strip()
        if (
            not role
            or motif not in SUPPORTED_MOTIFS
            or emotion not in SUPPORTED_EMOTIONS
            or entrance not in SUPPORTED_ENTRANCES
            or exit_style not in SUPPORTED_EXITS
        ):
            return None
        try:
            intensity = min(1.0, max(0.0, float(item.get("intensity", 0.6))))
        except (TypeError, ValueError):
            return None
        result.append(
            (
                role,
                motif,
                {
                    "emotion": emotion,
                    "entrance": entrance,
                    "exit": exit_style,
                    "intensity": intensity,
                },
            ),
        )
    return result


async def _plan_story_beats(
    *,
    edit_elements: list[TimelineElement],
    text_overlays: list[TimelineElement],
    brief: str,
) -> tuple[str, list[tuple[str, str, Mapping[str, Any]]] | None]:
    """Understand this particular cut and freely plan three visual beats."""

    lines = [f"整体要求：{brief or '（未提供）'}", "按时间顺序的内容："]
    for element in edit_elements:
        creation = element.creation
        assert isinstance(creation, EditCreation)
        lines.append(
            f"- 片段：{element.label or '（无标签）'}；"
            f"意图：{creation.intent or '（无）'}；理由：{creation.reason or '（无）'}",
        )
    for overlay in text_overlays:
        creation = overlay.creation
        assert isinstance(creation, OverlayCreation)
        lines.append(f"- 台词：{creation.text}；情绪：{creation.vibe}")
    try:
        answer = await vlm_model.chat_completion(
            [{"type": "text", "text": "\n".join(lines)}],
            system_prompt=(
                "你是短视频故事与动效导演。不要套用预设故事类型，直接理解这支影片实际发生的事件，"
                "为开场、关键转折、结尾各设计一个有前后关系的无文字动效。只输出 JSON："
                '{"storySummary":"一句话描述实际叙事", "beats":['
                '{"role":"该节点在故事中的具体作用","motif":"造型","emotion":"情绪",'
                '"entrance":"进场","exit":"退场","intensity":0.0}]}. '
                "beats 必须正好三个并按时间排序。motif 从 paw_trail、alert_mark、approval_checks、"
                "focus_target、sparkles、leaf_accent 中自由选择；若没有真正贴合语义的成熟模板，"
                "该节点可以不生成装饰，不要为了凑满三个而使用不相关造型。"
                "emotion 从 chill、curious、surprise、action 选择；entrance 从 pop、stamp、draw_in、slide 选择；"
                "exit 从 soft_fade、shrink、none 选择。"
            ),
            temperature=0.35,
            max_tokens=900,
        )
        parsed = _parse_design_json(answer)
        summary = str(parsed.get("storySummary") or "").strip()
        beats = _validated_story_beats(parsed.get("beats"))
        if summary and beats is not None:
            return summary, beats
    except Exception:  # pragma: no cover - neutral fallback below
        pass
    return "根据时间线建立开场、变化与收束", None


async def design_motion_overlays(
    services: Any,
    *,
    project_id: str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    """Style text Overlays and add sparse decorations for one Timeline."""

    brief = str(arguments.get("brief") or "").strip()
    theme = str(arguments.get("theme") or "comic_patrol").strip()
    if theme not in SUPPORTED_THEMES:
        raise ValidationError(
            "theme 必须是 comic_patrol、soft_journal 或 neon_night",
        )
    requested_ids = arguments.get("elementIds")
    if requested_ids is not None and (
        not isinstance(requested_ids, list)
        or any(not isinstance(item, str) for item in requested_ids)
    ):
        raise ValidationError("elementIds 必须是字符串数组")
    requested = (
        {item.strip() for item in requested_ids if item.strip()}
        if isinstance(requested_ids, list)
        else None
    )
    budget_raw = arguments.get("maxDecorations")
    if budget_raw is None:
        budget = _DEFAULT_DECORATION_BUDGET
    else:
        try:
            budget = int(budget_raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError("maxDecorations 必须是整数") from exc
        budget = min(max(budget, 0), _MAX_DECORATION_BUDGET)

    snapshot: ProjectSnapshot = await asyncio.to_thread(
        services.projects.read,
        project_id,
    )
    project = snapshot.project
    timeline = _target_timeline(project, target_ref)
    project_root = services.projects.project_root(project_id)
    executions = ProjectExecutionStore(services.root)
    ffmpeg_path = resolve_ffmpeg() or "ffmpeg"
    canvas_size = _design_canvas_size(project)

    edit_elements = sorted(
        (
            element
            for element in timeline.elements_by_id.values()
            if element.enabled and isinstance(element.creation, EditCreation)
        ),
        key=lambda element: (element.span.start_tick, element.element_id),
    )[:_MAX_SEGMENTS]
    text_overlays = sorted(
        (
            element
            for element in timeline.elements_by_id.values()
            if element.enabled
            and isinstance(element.creation, OverlayCreation)
            and element.creation.overlay_kind
            in {"pet_os", "interview_summary"}
        ),
        key=lambda element: (element.span.start_tick, element.element_id),
    )[:_MAX_SEGMENTS]
    if not edit_elements and not text_overlays:
        raise ValidationError(
            "Timeline 没有可设计的 Edit Element 或文字 Overlay Element",
        )

    designed: list[TimelineElement] = []
    styled: dict[str, tuple[MotionGraphic, ElementLocation]] = {}
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_DESIGNS)

    def fallback_text_style(
        overlay: TimelineElement,
        *,
        reason: str,
    ) -> dict[str, Any]:
        creation = overlay.creation
        assert isinstance(creation, OverlayCreation)
        emotion = (
            creation.vibe if creation.vibe in SUPPORTED_EMOTIONS else "chill"
        )
        concept = f"可靠动态 OS 字幕卡（生成样式回退：{reason}）"
        location = ElementLocation(
            x=0.50,
            y=0.88,
            width=0.80,
            height=0.18,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        if overlay.location:
            location = overlay.location
        motion = MotionGraphic(
            html=render_caption_template(
                creation.text,
                theme=theme,
                emotion=emotion,
                box_width=location.width,
                box_height=location.height,
            ),
            fps=24,
            loop=False,
            design_notes=concept,
            motif="caption_card",
            template_version=MOTION_TEMPLATE_VERSION,
            theme=theme,
            variant="sticker",
            emotion=emotion,
            entrance="pop",
            exit="soft_fade",
            intensity=0.6,
        )
        styled[overlay.element_id] = (motion, location)
        return {
            "elementId": overlay.element_id,
            "overlayKind": creation.overlay_kind,
            "status": "styled_fallback",
            "concept": concept,
            "fallbackReason": reason,
        }

    async def window_frames(
        render_source: SourceVersionRenderSource,
        window_start: float,
        window_end: float,
    ) -> list[Path] | dict[str, Any]:
        """Return two frame paths inside the window, or a status fragment."""

        source_path = await asyncio.to_thread(
            _source_local_path,
            project=project,
            project_root=project_root,
            version_id=render_source.version_id,
            executions=executions,
        )
        if source_path is None:
            return {
                "status": "skipped",
                "skipReason": "片段源视频没有可用的本地字节，无法观察画面",
            }
        span_seconds = max(0.1, window_end - window_start)
        version = project.assets.source_versions_by_id.get(
            render_source.version_id,
        )
        identity = (
            f"{render_source.version_id}:{version.checksum}"
            if version is not None
            else render_source.version_id
        )
        try:
            return [
                (
                    await asyncio.to_thread(
                        materialize_keyframe,
                        project_root,
                        source_path=source_path,
                        source_identity=identity,
                        timestamp_seconds=window_start
                        + span_seconds * fraction,
                        width=_KEYFRAME_WIDTH,
                        ffmpeg_path=ffmpeg_path,
                    )
                ).path
                for fraction in (0.25, 0.75)
            ]
        except Exception as exc:
            return {"status": "failed", "error": f"抽帧失败: {exc}"}

    def best_covering_edit(
        overlay: TimelineElement,
    ) -> TimelineElement | None:
        overlay_start = overlay.span.start_tick
        overlay_end = overlay_start + overlay.span.duration_tick
        best: TimelineElement | None = None
        best_overlap = 0
        for edit in edit_elements:
            edit_start = edit.span.start_tick
            edit_end = edit_start + edit.span.duration_tick
            overlap = min(overlay_end, edit_end) - max(
                overlay_start,
                edit_start,
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best = edit
        return best

    async def style_text_overlay(
        overlay: TimelineElement,
    ) -> dict[str, Any]:
        creation = overlay.creation
        assert isinstance(creation, OverlayCreation)
        entry: dict[str, Any] = {
            "elementId": overlay.element_id,
            "overlayKind": creation.overlay_kind,
        }
        if requested is not None and overlay.element_id not in requested:
            return {**entry, "status": "not_requested"}
        if creation.motion is not None:
            return {**entry, "status": "already_styled"}
        edit = best_covering_edit(overlay)
        if edit is None:
            return fallback_text_style(
                overlay,
                reason="没有相交的剪辑画面",
            )
        try:
            source_start, source_end = _segment_seconds(timeline, edit)
        except ValidationError as exc:
            return fallback_text_style(overlay, reason=str(exc))
        edit_start = edit.span.start_tick
        edit_duration = max(1, edit.span.duration_tick)
        overlay_start = overlay.span.start_tick
        overlay_end = overlay_start + overlay.span.duration_tick
        rel_start = (
            max(overlay_start, edit_start) - edit_start
        ) / edit_duration
        rel_end = (
            min(overlay_end, edit_start + edit.span.duration_tick) - edit_start
        ) / edit_duration
        source_span = source_end - source_start
        frames = await window_frames(
            edit.render_source,  # type: ignore[arg-type]
            source_start + source_span * rel_start,
            source_start + source_span * rel_end,
        )
        if isinstance(frames, dict):
            return fallback_text_style(
                overlay,
                reason=str(
                    frames.get("error") or frames.get("skipReason") or "抽帧失败",
                ),
            )
        duration_seconds = (
            overlay.span.duration_tick / timeline.ticks_per_second
        )
        async with semaphore:
            try:
                design = await _design_document(
                    system_prompt=_TEXT_STYLE_SYSTEM_PROMPT,
                    task_text=_text_style_task_text(
                        overlay=overlay,
                        edit_element=edit,
                        duration_seconds=duration_seconds,
                        canvas_size=canvas_size,
                        brief=brief,
                        theme=theme,
                    ),
                    frame_paths=frames,
                    canvas_size=canvas_size,
                    required_text=creation.text,
                    default_loop=False,
                    min_coverage=_TEXT_CARD_MIN_COVERAGE,
                    max_edge_contact=_TEXT_CARD_MAX_EDGE_CONTACT,
                    max_attempts=_TEXT_CARD_DESIGN_ATTEMPTS,
                    ffmpeg_path=ffmpeg_path,
                    forced_theme=theme,
                )
            except Exception as exc:
                return fallback_text_style(overlay, reason=str(exc))
        if isinstance(design, str):
            return fallback_text_style(overlay, reason=design)
        motion, location, concept = design
        styled[overlay.element_id] = (motion, location)
        return {**entry, "status": "styled", "concept": concept}

    async def decorate_segment(
        element: TimelineElement,
        selected: set[str],
        used_motifs: set[str],
        story_beat: tuple[str, str, Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        motion_id = f"{element.element_id}{_MOTION_ELEMENT_SUFFIX}"
        entry: dict[str, Any] = {
            "elementId": element.element_id,
            "motionElementId": motion_id,
        }
        if requested is not None and element.element_id not in requested:
            return {**entry, "status": "not_requested"}
        if requested is None and element.element_id not in selected:
            return {**entry, "status": "not_selected"}
        if motion_id in timeline.elements_by_id:
            return {**entry, "status": "already_exists"}
        try:
            start_seconds, end_seconds = _segment_seconds(timeline, element)
        except ValidationError as exc:
            return {**entry, "status": "failed", "error": str(exc)}
        frames = await window_frames(
            element.render_source,  # type: ignore[arg-type]
            start_seconds,
            end_seconds,
        )
        if isinstance(frames, dict):
            return {**entry, **frames}
        segment_duration = (
            element.span.duration_tick / timeline.ticks_per_second
        )
        element_end = element.span.start_tick + element.span.duration_tick
        avoid_locations: list[tuple[str, ElementLocation]] = []
        os_context: list[str] = []
        for overlay in text_overlays:
            overlay_end = overlay.span.start_tick + overlay.span.duration_tick
            if (
                overlay.span.start_tick >= element_end
                or overlay_end <= element.span.start_tick
            ):
                continue
            styled_item = styled.get(overlay.element_id)
            location = styled_item[1] if styled_item else overlay.location
            if location is not None:
                avoid_locations.append(
                    (overlay.label or overlay.element_id, location),
                )
            creation = overlay.creation
            if isinstance(creation, OverlayCreation):
                os_context.append(
                    f"台词「{creation.text}」，情绪「{creation.vibe}」",
                )
        async with semaphore:
            try:
                story_role = story_beat[0] if story_beat else None
                story_motif = story_beat[1] if story_beat else None
                forced_fields = (
                    {
                        **story_beat[2],
                    }
                    if story_beat
                    else None
                )
                design = await _design_document(
                    system_prompt=_DECOR_SYSTEM_PROMPT,
                    task_text=_design_task_text(
                        element=element,
                        duration_seconds=segment_duration,
                        canvas_size=canvas_size,
                        brief=brief,
                        avoid_locations=avoid_locations,
                        os_context=os_context,
                        theme=theme,
                        used_motifs=used_motifs,
                        story_role=story_role,
                        story_motif=story_motif,
                    ),
                    frame_paths=frames,
                    canvas_size=canvas_size,
                    min_coverage=_DECORATION_MIN_COVERAGE,
                    max_edge_contact=_DECORATION_MAX_EDGE_CONTACT,
                    max_attempts=_TEXT_CARD_DESIGN_ATTEMPTS,
                    forbidden_locations=tuple(
                        location for _, location in avoid_locations
                    ),
                    ffmpeg_path=ffmpeg_path,
                    forced_theme=theme,
                    forced_fields=forced_fields,
                )
            except Exception as exc:
                return {**entry, "status": "failed", "error": str(exc)}
        if isinstance(design, str):
            return {**entry, "status": "skipped", "skipReason": design}
        motion, location, concept = design
        if motion.motif != "custom":
            used_motifs.add(motion.motif)
        designed.append(
            _motion_element(
                edit_element=element,
                motion=motion,
                location=location,
                concept=concept,
            ),
        )
        return {**entry, "status": "designed", "concept": concept}

    if requested is not None:
        selected = requested
    else:
        selectable = [
            element
            for element in edit_elements
            if f"{element.element_id}{_MOTION_ELEMENT_SUFFIX}"
            not in timeline.elements_by_id
        ]
        selected = await _select_decoration_ids(
            edit_elements=selectable,
            timeline=timeline,
            budget=budget,
            brief=brief,
        )
    selected_in_story_order = [
        element.element_id
        for element in sorted(
            edit_elements,
            key=lambda item: (item.span.start_tick, item.element_id),
        )
        if element.element_id in selected
    ]
    story_summary, planned_beats = (
        await _plan_story_beats(
            edit_elements=edit_elements,
            text_overlays=text_overlays,
            brief=brief,
        )
        if selected_in_story_order
        else ("没有选中的装饰节点", None)
    )
    story_arc = _story_arc_motifs(selected_in_story_order, planned_beats)

    # Text cards choose their final locations first. Decorations then receive
    # those committed-in-memory boxes as hard collision constraints.
    text_results = list(
        await asyncio.gather(
            *(style_text_overlay(overlay) for overlay in text_overlays),
        ),
    )
    # Design decorations in timeline order so each decision can see motifs
    # already used earlier in the story and avoid accidental repetition.
    segment_results: list[dict[str, Any]] = []
    used_motifs: set[str] = set()
    for element in edit_elements:
        segment_results.append(
            await decorate_segment(
                element,
                selected,
                used_motifs,
                story_arc.get(element.element_id),
            ),
        )

    if not designed and not styled:
        return {
            "ok": True,
            "designedCount": 0,
            "storySummary": story_summary,
            "textOverlays": text_results,
            "segments": segment_results,
            "generation": snapshot.generation,
            "etag": snapshot.etag,
        }

    def commit_sync() -> ProjectSnapshot:
        current = services.projects.read(project_id)
        candidate = current.project.model_dump(mode="json")
        timelines = candidate["timelines"]["items"]
        timeline_key = (
            timeline.timeline_id
            if timeline.timeline_id in timelines
            else target_ref
        )
        elements = timelines[timeline_key]["elements_by_id"]
        for item in designed:
            if item.element_id in elements:
                continue
            elements[item.element_id] = item.model_dump(mode="json")
        for overlay_id, (motion, location) in styled.items():
            raw = elements.get(overlay_id)
            if not isinstance(raw, dict):
                continue
            raw["creation"]["motion"] = motion.model_dump(mode="json")
            raw["location"] = location.model_dump(mode="json")
        commit = services.commits.commit(
            base=current,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id=idempotency_key,
        )
        return commit.snapshot

    committed = await asyncio.to_thread(commit_sync)
    await asyncio.to_thread(services.poller.note_commit, committed)
    logger.info(
        "motion design committed: project=%s decorations=%d styled=%d "
        "segments=%s overlays=%s",
        project_id,
        len(designed),
        len(styled),
        [(item["elementId"], item["status"]) for item in segment_results],
        [(item["elementId"], item["status"]) for item in text_results],
    )
    return {
        "ok": True,
        "designedCount": len(designed) + len(styled),
        "storySummary": story_summary,
        "textOverlays": text_results,
        "segments": segment_results,
        "generation": committed.generation,
        "etag": committed.etag,
    }


def _design_canvas_size(project: Project) -> tuple[int, int]:
    try:
        width_part, height_part = project.settings.aspect_ratio.split(":", 1)
        ratio = float(width_part) / float(height_part)
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        ratio = 16 / 9
    base = (
        1080 if "1080" in str(project.settings.resolution).casefold() else 720
    )
    if ratio >= 1:
        height = base
        width = round(height * ratio)
    else:
        width = base
        height = round(width / ratio)
    return (max(2, width // 2 * 2), max(2, height // 2 * 2))


__all__ = ["design_motion_overlays"]
