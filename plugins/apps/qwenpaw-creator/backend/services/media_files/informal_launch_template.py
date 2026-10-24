# -*- coding: utf-8 -*-
"""Optional presets and authored captions for the informal-launch template."""

from __future__ import annotations

from functools import lru_cache
from collections.abc import Mapping
from html import escape, unescape
import json
import math
from pathlib import Path
import re

from domain.errors import ValidationError
from services.external_skills import parse_skill_md
from services.media_files.element_adapter import (
    find_timeline_element,
    selected_element_output,
)
from services.project_files.models import (
    AudioCreation,
    EditCreation,
    ElementLocation,
    ElementOutputRenderSource,
    MotionGraphic,
    OverlayCreation,
    Project,
    R2VCreation,
    SourceVersionRenderSource,
    Timeline,
    TimelineElement,
)

TEMPLATE_MARKER = "【官方固定模板：informal_launch】"


def uses_informal_launch_captions(timeline: Timeline) -> bool:
    return bool(
        timeline.edit_plan
        and TEMPLATE_MARKER in timeline.edit_plan.design_floor.opening,
    )


def informal_launch_uses_uploaded_bgm(
    project: Project,
    timeline: Timeline,
) -> bool:
    """The template's selected source music replaces generated native sound."""
    if not uses_informal_launch_captions(timeline):
        return False
    for element in timeline.elements_by_id.values():
        creation = element.creation
        if not element.enabled or not isinstance(creation, AudioCreation):
            continue
        version = project.assets.source_versions_by_id.get(
            creation.source_asset_version_id or "",
        )
        if (
            creation.role == "bgm"
            and version
            and version.media_kind == "audio"
        ):
            return True
    return False


def informal_launch_caption_skill() -> str:
    """Load the discoverable template skill without changing Agent prompts."""
    path = (
        Path(__file__).resolve().parents[2]
        / "skills/informal-launch-captions/SKILL.md"
    )
    return parse_skill_md(path.read_text(encoding="utf-8"))["body"]


def requests_informal_launch_preset(creation: OverlayCreation) -> bool:
    try:
        options = json.loads(creation.prompt or "{}")
    except ValueError:
        return False
    return bool(
        isinstance(options, dict)
        and options.get("template") == "informal_launch"
        and options.get("mode") != "custom"
        and (options.get("recipe") or options.get("mode") == "preset"),
    )


def informal_launch_frame_windows(
    project: Project,
    timeline: Timeline,
    overlay: TimelineElement,
) -> list[tuple[str, float, float]]:
    """Resolve actual selected footage, including R2V and trimmed Edit cuts."""
    windows = []
    for element in sorted(
        timeline.elements_by_id.values(),
        key=lambda item: (item.span.start_tick, item.element_id),
    ):
        if not element.enabled or not isinstance(
            element.creation,
            (R2VCreation, EditCreation),
        ):
            continue
        start = max(overlay.span.start_tick, element.span.start_tick)
        end = min(
            overlay.span.start_tick + overlay.span.duration_tick,
            element.span.start_tick + element.span.duration_tick,
        )
        if end <= start:
            continue
        source = element.render_source
        if isinstance(source, ElementOutputRenderSource):
            selected = selected_element_output(
                project,
                find_timeline_element(project, source.element_id)[1],
                source.output_name,
            )
            version_id = selected[1] if selected else None
        elif isinstance(source, SourceVersionRenderSource):
            version_id = source.version_id
        else:
            version_id = None
        if version_id is None or source is None:
            raise ValidationError("非正式发布会字幕设计需要对应片段已生成并选中的视频")
        rate = source.playback_rate
        source_start = source.source_in_tick
        first = source_start + (start - element.span.start_tick) * rate
        last = source_start + (end - element.span.start_tick) * rate
        if source.source_out_tick is not None:
            last = min(last, source.source_out_tick)
        if source.loop or last <= first:
            raise ValidationError("非正式发布会字幕设计需要明确且不循环的片内区间")
        windows.append(
            (
                version_id,
                first / timeline.ticks_per_second,
                last / timeline.ticks_per_second,
            ),
        )
    if not windows:
        raise ValidationError("非正式发布会字幕时段没有可观察的底层视频，不能盲选字幕位置")
    return windows


def normalize_informal_launch_html(document: str) -> str:
    """Repair escaped CSS separators without redesigning authored lettering.

    Only repair literal JSON whitespace between HTML tags and CSS rules.
    Quoted CSS strings, comments, escapes inside selectors and visible copy
    remain untouched. Other malformed documents must fail the render gate.
    """

    def stylesheet(match: re.Match[str]) -> str:
        opening, css, closing = match.groups()
        css = re.sub(r"^(?:\\[nrt])+", "\n", css)
        strings = r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' """.rstrip()
        tokens = re.compile(
            strings + r"|/\*.*?\*/|[{};](?:\\[nrt])+",
            re.DOTALL,
        )

        def separator(token: re.Match[str]) -> str:
            value = token.group(0)
            return value[0] + "\n" if value[0] in "{};" else value

        return opening + tokens.sub(separator, css) + closing

    document = re.sub(
        r"(<style\b[^>]*>)(.*?)(</style\s*>)",
        stylesheet,
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(
        r"(<(?:style|script)\b[^>]*>.*?</(?:style|script)\s*>|<!--.*?-->)"
        r"|>(?:\\[nrt])+(?=\s*<)",
        lambda match: match.group(1) or ">\n",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )


def informal_launch_screen_copy(text: str) -> str:
    """Express authored, whitespace-delimited bilingual separators as lines.

    A slash inside a word or value (24/7, AC/DC) is literal copy. Only the
    standalone `` / `` notation used between caption groups is layout.
    """
    return re.sub(r"\s+/\s+", "\n", text)


def informal_launch_copy_matches(document: str, text: str) -> bool:
    """Check every body character, allowing authored layout separators."""
    body = re.sub(
        r"<(head|style|script)\b[^>]*>.*?</\1\s*>|<!--.*?-->",
        "",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    visible = unescape(re.sub(r"<[^>]+>", "", body))
    # Existing documents may show the separator; new designs use separate
    # lines. Permit either only where the author wrote a standalone slash,
    # never by stripping all punctuation or accepting a substring match.
    parts = re.split(r"\s+/\s+", text)
    pattern = "/?".join(re.escape(re.sub(r"\s+", "", part)) for part in parts)
    return re.fullmatch(pattern, re.sub(r"\s+", "", visible)) is not None


def compile_informal_launch_captions(
    timeline: Timeline,
    canvas_size: tuple[int, int],
) -> dict[str, tuple[MotionGraphic, ElementLocation]]:
    """Preserve designs; only fill a missing, explicitly requested preset."""
    if not uses_informal_launch_captions(timeline):
        return {}
    overlays = sorted(
        (
            element
            for element in timeline.elements_by_id.values()
            if element.enabled
            and isinstance(element.creation, OverlayCreation)
            and element.creation.text.strip()
        ),
        key=lambda element: (element.span.start_tick, element.element_id),
    )
    result = {}
    for index, overlay in enumerate(overlays):
        motion = overlay.creation.motion
        if motion is not None:
            if motion.html is not None:
                motion = motion.model_copy(
                    update={
                        "html": normalize_informal_launch_html(motion.html),
                    },
                )
            result[overlay.element_id] = (
                motion,
                overlay.location
                or ElementLocation(x=0.5, y=0.5, width=1, height=1),
            )
        elif requests_informal_launch_preset(overlay.creation):
            result[overlay.element_id] = render_informal_launch_caption(
                overlay,
                ticks_per_second=timeline.ticks_per_second,
                canvas_size=canvas_size,
                card_index=index,
                card_count=len(overlays),
            )
        else:
            raise ValidationError(
                f"非正式发布会字幕 {overlay.element_id} 尚未完成设计；"
                "请调用 design_motion_overlays 按实片生成花字，不会自动改用预设",
            )
    return result


def reject_informal_launch_fallback(
    overlay: Mapping,
    error: str,
) -> None:
    """Keep a failed official template out of the plain-caption fallback."""
    if overlay.get("caption_template") == "informal_launch":
        raise ValidationError(
            f"非正式发布会字幕 {overlay.get('element_id', '')} 渲染失败："
            f"{error}；已中止合成，请修正该字幕设计后重试，未替换为基础字幕",
        )


@lru_cache(maxsize=1)
def _styles() -> dict:
    path = (
        Path(__file__).resolve().parents[3]
        / "templates/cat-launch/caption-styles.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _pairs(text: str) -> list[tuple[str, str]]:
    """Keep authored words and line breaks; never invent a translation."""
    result: list[tuple[str, str]] = []
    chinese: list[str] = []
    english: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.search(r"[\u3400-\u9fff]", line):
            if english:
                result.append(("\n".join(chinese), "\n".join(english)))
                chinese, english = [], []
            chinese.append(line)
        elif chinese:
            english.append(line)
        else:
            raise ValidationError(
                "非正式发布会字幕须按中文、对应英文的顺序填写",
            )
    if not chinese or not english:
        raise ValidationError("非正式发布会字幕缺少中文或对应英文")
    result.append(("\n".join(chinese), "\n".join(english)))
    return result


def _region(value: object, default: list[float]) -> list[float]:
    if value is None:
        return default
    if not isinstance(value, list) or len(value) != 4:
        raise ValidationError("模板 region 须为 [左, 上, 宽, 高] 百分比")
    try:
        box = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValidationError("模板 region 必须是有限数字") from exc
    x, y, width, height = box
    if not all(math.isfinite(v) for v in box) or not (
        x >= 6
        and y >= 6
        and width > 0
        and height > 0
        and x + width <= 94
        and y + height <= 94
    ):
        raise ValidationError("模板文字区须保留6%画布安全边距")
    return box


def _slot_color(options: dict, key: str, default: str) -> str:
    value = str(options.get(key, default))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValidationError("模板强调色须为六位十六进制颜色")
    return value


def _slot_delay(options: dict, key: str, default: float) -> float:
    try:
        value = float(options.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"模板 {key} 须为非负秒数") from exc
    if not math.isfinite(value) or value < 0:
        raise ValidationError(f"模板 {key} 须为非负秒数")
    return value


def _preset_options(creation: OverlayCreation) -> dict:
    try:
        options = json.loads(creation.prompt or "{}")
    except ValueError:
        options = {}
    if (
        not isinstance(options, dict)
        or options.get("template") != "informal_launch"
    ):
        options = {}
    if options.get("mode") == "custom":
        raise ValidationError(
            "非正式发布会自定义字幕缺少 motion 文档；请完成花字设计，不会自动改用预设",
        )
    return options


def render_informal_launch_caption(
    overlay: TimelineElement,
    *,
    ticks_per_second: int,
    canvas_size: tuple[int, int],
    card_index: int,
    card_count: int,
) -> tuple[MotionGraphic, ElementLocation]:
    creation = overlay.creation
    assert isinstance(creation, OverlayCreation)
    options = _preset_options(creation)
    pairs = _pairs(creation.text)
    recipe = options.get("recipe") or (
        "look_labels"
        if len(pairs) >= 3
        else (
            "hero"
            if card_index == 0
            else "closing"
            if card_index == card_count - 1
            else "detail"
        )
    )
    recipes = {item["name"]: item for item in _styles()["recipes"]}
    if not isinstance(recipe, str) or recipe not in recipes:
        raise ValidationError(f"未知的非正式发布会字幕样式: {recipe}")
    portrait = canvas_size[0] < canvas_size[1]
    location = ElementLocation(x=0.5, y=0.5, width=1, height=1)
    reference_width, reference_height = 1280, 720
    if portrait:
        # Size only the transparent text band; keep the video full frame.
        top = bool(overlay.location and overlay.location.y < 0.5)
        location = ElementLocation(
            x=0.5,
            y=0.25 if top else 0.75,
            width=1,
            height=0.36,
        )
        reference_width, reference_height = 720, 1280 * 0.36

    def fill(key: str, **values: object) -> str:
        document = _styles()[key]
        for name, value in values.items():
            document = document.replace("{{" + name + "}}", str(value))
        if "{{" in document:
            raise ValidationError(f"非正式发布会字幕模板槽位未填全: {key}")
        return document

    def group(
        pair: tuple[str, str],
        *,
        kind: str = "",
        motion: str = "fade",
        zh: int = 42,
        en: int = 23,
        delay: float = 0,
        center: bool = False,
        rule: bool = False,
    ) -> str:
        duration = overlay.span.duration_tick / ticks_per_second
        if delay + 0.55 > duration:
            raise ValidationError("字幕入场延迟与动画时长超出当前字幕时段")
        return fill(
            "group_template",
            CLASS=kind,
            MOTION=motion,
            DELAY=delay,
            ZH_SIZE=zh,
            EN_SIZE=en,
            ALIGN="center" if center else "left",
            INK="#20242c",
            MUTED="#454c58",
            SHADOW="none",
            COLOR=_slot_color(options, "accent", "#6142bd"),
            COLOR_END=_slot_color(options, "accent_end", "#277f83"),
            RULE='<div class="rule"></div>' if rule else "",
            ZH=escape(pair[0]).replace("\n", "<br>"),
            EN=escape(pair[1]).replace("\n", "<br>"),
        )

    def region(
        area: list[float],
        items: list[str],
        layout: str = "",
        count: int = 1,
    ) -> str:
        return fill(
            "region_template",
            LEFT=area[0],
            TOP=area[1],
            WIDTH=area[2],
            HEIGHT=area[3],
            ITEMS="".join(items),
            LAYOUT=layout,
            COUNT=count,
        )

    if recipe == "look_labels":
        if not 2 <= len(pairs) <= 6:
            raise ValidationError("造型字幕需要总标题及1–5款完整双语标签")
        header = _region(
            options.get("header_region"),
            [6, 8, 88, 22] if portrait else [6, 6.5, 88, 11],
        )
        labels = _region(
            options.get("label_region"),
            [6, 38, 88, 55] if portrait else [9, 83, 82, 10.5],
        )
        content = region(
            header,
            [
                group(
                    pairs[0],
                    kind="center",
                    zh=28,
                    en=17,
                    center=True,
                    delay=_slot_delay(options, "header_delay", 0),
                ),
            ],
            "top",
        )
        content += region(
            labels,
            [
                group(
                    pair,
                    kind="label center",
                    zh=22,
                    en=17,
                    delay=round(
                        _slot_delay(options, "label_delay", 0.16)
                        + _slot_delay(options, "label_stagger", 0.08) * index,
                        2,
                    ),
                    center=True,
                )
                for index, pair in enumerate(pairs[1:])
            ],
            "row",
            min(2, len(pairs) - 1) if portrait else len(pairs) - 1,
        )
    else:
        if len(pairs) > 2:
            raise ValidationError(
                "普通字幕每个文字区最多两组双语；造型列表请用 look_labels",
            )
        layout = options.get("layout") or (
            "text_right"
            if overlay.location and overlay.location.x > 0.5
            else "text_left"
        )
        layouts = _styles()["overlay_layouts"]
        if layout not in (
            "text_left",
            "text_right",
            "top_left",
            "top_right",
            "top_center",
        ):
            raise ValidationError(f"未知的非正式发布会文字区域: {layout}")
        preset = layouts[layout]["text_region_percent"]
        default = (
            [6, 10, 88, 80]
            if portrait
            else [preset[key] for key in ("LEFT", "TOP", "WIDTH", "HEIGHT")]
        )
        area = _region(options.get("region"), default)
        top = layout.startswith("top_")
        main_size = (
            38
            if portrait or top
            else 50
            if recipe in ("hero", "closing")
            else 42
        )
        content = region(
            area,
            [
                group(
                    pair,
                    kind="small" if index else recipes[recipe]["class"],
                    motion="fade" if index else recipes[recipe]["motion"],
                    zh=30 if index else main_size,
                    en=21 if index else 22 if top else 24,
                    delay=0.18 if index else 0,
                    center=layout == "top_center",
                    rule=recipe == "paired_callout" and index == 0,
                )
                for index, pair in enumerate(pairs)
            ],
            "top" if top else "",
        )
    document = fill(
        "document_template",
        WIDTH=reference_width,
        HEIGHT=reference_height,
        DURATION=overlay.span.duration_tick / ticks_per_second,
        GROUPS=content,
    )
    return (
        MotionGraphic(
            format="html_css",
            html=document,
            template_version=4,
            fps=30,
            loop=False,
            motif="custom",
            design_notes=f"非正式发布会官方固定字幕 · {recipe}",
        ),
        location,
    )
