# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,redefined-builtin
"""Trusted deterministic templates for common decorative motion motifs."""

from __future__ import annotations

from html import escape
import math
import re
from collections.abc import Mapping
import unicodedata
from typing import Any

MOTION_TEMPLATE_VERSION = 1
# v3: the plain-subtitle template now honours the chosen style pack
# (weight / letter-spacing / plate / glow / tilt), the user's colour,
# font-size and outline overrides, and the entrance / exit / loop triple.
# v2 hard-coded white glyphs with one fixed shadow and ignored all of it,
# so the live preview and the final cut disagreed with the 动效描述.
CAPTION_TEMPLATE_VERSION = 3
DEFAULT_CAPTION_LOCATION = {
    "x": 0.5,
    "y": 0.86,
    "width": 0.8,
    "height": 0.18,
    "anchor_x": 0.5,
    "anchor_y": 0.5,
}
# Preset locations for each caption_role.  Every entry must clear the
# compose-time validator ``caption_layout_error`` for the text length its own
# role is documented to carry, and must stay inside the 0.04/0.96 safe area on
# landscape and portrait canvases alike.  Compose only logs a rejected caption
# box and then re-renders the whole card in the generic subtitle geometry, so a
# preset that fails here silently throws the role's layout away.
#
# A role that hugs a frame edge pins that edge through ``anchor_y`` rather
# than centering the box: a centered box grows both ways, and the height two
# lines need would push the hugged edge out of the safe area.
CAPTION_ROLE_LOCATIONS: dict[str, dict[str, object]] = {
    # 对白字幕 — 电影标准底部居中（画面 80% 宽，底边距 5%）。钉住底边，与
    # DEFAULT_CAPTION_LOCATION 覆盖同一块画布区域。
    "dialogue": {
        "x": 0.50,
        "y": 0.95,
        "width": 0.8,
        "height": 0.18,
        "anchor_x": 0.5,
        "anchor_y": 1.0,
    },
    # 旁白/内心独白 — 与对白同样贴底边，但宽度更窄（65%）以形成视觉区分；
    # 排版仍是正体，渲染器不区分 caption_role
    "narration": {
        "x": 0.50,
        "y": 0.95,
        "width": 0.65,
        "height": 0.18,
        "anchor_x": 0.5,
        "anchor_y": 1.0,
    },
    # 开场片名 — 黄金比例位置（约 38.2% 处），居中，留给片名呼吸空间
    "opening_title": {
        "x": 0.50,
        "y": 0.33,
        "width": 0.60,
        "height": 0.20,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
    },
    # 开场演职员 — 画面下部居中，小型字体；电影惯例：下三分之一处
    "opening_credit": {
        "x": 0.50,
        "y": 0.80,
        "width": 0.55,
        "height": 0.13,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
    },
    # 片尾致谢 — 钉住底边居中，向上预留滚动空间；电影惯例：从底部向上滚动
    "ending_credit": {
        "x": 0.50,
        "y": 0.95,
        "width": 0.7,
        "height": 0.30,
        "anchor_x": 0.5,
        "anchor_y": 1.0,
    },
    # 地点/时间标注 — 左下角，小字；参考"巴黎，1942"、"三年前"等电影惯用位置
    "location": {
        "x": 0.06,
        "y": 0.88,
        "width": 0.35,
        "height": 0.13,
        "anchor_x": 0.0,
        "anchor_y": 1.0,
    },
    # 章节标题 — 顶部居中，参考电影幕间/段落卡（如《布达佩斯大饭店》章节卡）
    "chapter": {
        "x": 0.50,
        "y": 0.10,
        "width": 0.55,
        "height": 0.13,
        "anchor_x": 0.5,
        "anchor_y": 0.0,
    },
    # 访谈要点摘要 — 顶部区域，纪录片事实卡风格；钉住顶边向下生长
    "interview_summary": {
        "x": 0.50,
        "y": 0.06,
        "width": 0.75,
        "height": 0.13,
        "anchor_x": 0.5,
        "anchor_y": 0.0,
    },
}
# A caption box must also stay inside this normalized safe area.  The
# compose-time validator only checks the width floor, the box aspect ratio and
# the height floor, so a handwritten box such as ``y=0.88, height=0.18`` with a
# centre anchor still passes at 0.97 and burns the last line of the card into
# the frame edge.  The design-time gate and the load-time repair both read
# these numbers, so the preset table and any authored box are judged alike.
CAPTION_SAFE_AREA_EDGES = (0.04, 0.04, 0.96, 0.96)
# Some presets sit exactly on the 0.96 line by construction, so the check needs
# a float tolerance or the guard would reject its own table.
CAPTION_SAFE_AREA_EPSILON = 1e-9


def _location_number(
    location: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    """Read one location field, falling back to the model default."""

    try:
        return float(location.get(key, default))
    except (TypeError, ValueError):
        return default


def caption_box_edges(
    location: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    """Return left, top, right and bottom of a normalized location box.

    ``x``/``y`` is the anchor point and ``anchor_x``/``anchor_y`` select which
    point of the box sits there, so the edges follow the same arithmetic the
    renderer uses.  Missing keys fall back to the ElementLocation defaults.
    """

    width = _location_number(location, "width", 1.0)
    height = _location_number(location, "height", 1.0)
    left = (
        _location_number(location, "x", 0.5)
        - _location_number(
            location,
            "anchor_x",
            0.5,
        )
        * width
    )
    top = (
        _location_number(location, "y", 0.5)
        - _location_number(
            location,
            "anchor_y",
            0.5,
        )
        * height
    )
    return left, top, left + width, top + height


def caption_box_out_of_safe_area(
    location: Mapping[str, Any],
    *,
    epsilon: float = CAPTION_SAFE_AREA_EPSILON,
) -> bool:
    """Whether a caption box reaches outside the caption safe area."""

    safe_left, safe_top, safe_right, safe_bottom = CAPTION_SAFE_AREA_EDGES
    left, top, right, bottom = caption_box_edges(location)
    return (
        left < safe_left - epsilon
        or top < safe_top - epsilon
        or right > safe_right + epsilon
        or bottom > safe_bottom + epsilon
    )


SUPPORTED_MOTIFS = frozenset(
    {
        "paw_trail",
        "alert_mark",
        "approval_checks",
        "focus_target",
        "sparkles",
        "leaf_accent",
    },
)
SUPPORTED_THEMES = frozenset({"comic_patrol", "soft_journal", "neon_night"})
SUPPORTED_VARIANTS = frozenset({"sticker", "ink", "neon"})
SUPPORTED_EMOTIONS = frozenset({"chill", "curious", "surprise", "action"})
SUPPORTED_ENTRANCES = frozenset({"pop", "stamp", "draw_in", "slide"})
SUPPORTED_EXITS = frozenset({"soft_fade", "shrink", "none"})
# Caption-only animation vocabulary.  ``exit`` mirrors the renderer-managed
# ``data-motion-exit`` contract (the compositor owns the fade / shrink, the
# document must not exit by itself); every entrance keeps the first probe
# frame non-empty, which is why none of them starts fully transparent.
CAPTION_ENTRANCES = frozenset({"soft_fade", "pop", "slide", "type_on"})
CAPTION_EXITS = frozenset({"none", "soft_fade", "shrink"})
_LEGACY_CAPTION_FAMILY = (
    '"Noto Sans CJK SC","Noto Sans SC","PingFang SC","Microsoft YaHei",'
    "sans-serif"
)

# Mirrors the front-end preview stacks (OverlayCopyLayer.SUBTITLE_FONT_STACKS)
# and ``overlay._SUBTITLE_FONT_FAMILIES``: one CSS stack per persisted
# ``font_family`` id.  Only an explicit pick overrides the pack's own face;
# ``None`` / "default" / unknown ids keep the pack / legacy family, so an
# untouched project emits exactly the document it used to.
_SUBTITLE_FONT_CSS_STACKS = {
    "song": '"Songti SC","SimSun","Noto Serif CJK SC",serif',
    "hei": (
        '"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",'
        '"Microsoft YaHei",sans-serif'
    ),
    "kai": '"Kaiti SC","KaiTi","STKaiti","Noto Serif CJK SC",serif',
}

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text.lower() if _HEX_COLOR.fullmatch(text) else fallback


def _caption_em_value(value: object) -> float:
    """Read one ``"0.18em"`` typography token as a plain em multiplier."""

    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    try:
        return max(0.0, float(text[:-2] if text.endswith("em") else text))
    except ValueError:
        return 0.0


def _caption_font_css(
    text: str,
    box_width: float | None,
    box_height: float | None,
    *,
    line_height: float = 1.35,
    letter_spacing_em: float = 0.0,
) -> str:
    """Keep normal copy at one canvas-relative size and fit longer lines.

    The 24-character line and the 1.35 leading are the historical assumption,
    which the defaults reproduce byte-for-byte.  A style pack may widen the
    glyphs (letter-spacing) or the leading, so both have to enter the fit
    here: otherwise the browser wraps more rows than the formula reserved and
    the stage's ``overflow:hidden`` silently clips the caption copy.
    """
    per_line_capacity = 24.0 / (1.0 + letter_spacing_em)
    widths = [
        sum(
            1.0 if unicodedata.east_asian_width(char) in "WF" else 0.55
            for char in line
        )
        for line in text.splitlines()
        if line.strip()
    ] or [1.0]
    rows = [max(1, math.ceil(width / per_line_capacity)) for width in widths]
    per_line = max(width / count for width, count in zip(widths, rows))
    width = box_width if box_width and box_width > 0 else 0.8
    height = box_height if box_height and box_height > 0 else 0.18
    return (
        f"min({4 / height:.3f}vh,{4.5 / width:.3f}vw,"
        f"{80 / (sum(rows) * line_height):.3f}vh,{88 / max(1, per_line):.3f}vw)"
    )


def _caption_style_number(
    style: Mapping[str, Any] | None,
    key: str,
    fallback: float,
    low: float,
    high: float,
) -> float:
    """Read one clamped multiplier out of a user subtitle-style mapping."""

    raw = style.get(key) if isinstance(style, Mapping) else None
    if raw is None:
        return fallback
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(value):
        return fallback
    return max(low, min(high, value))


def _caption_em(value: float) -> str:
    """Format an em offset the way the historical template wrote it."""

    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text.startswith("0."):
        text = text[1:]
    return f"{text}em" if text else "0em"


def _caption_shadow_stack(
    stroke_multiplier: float,
    glow: bool,
    colour: str,
) -> str:
    """Text shadow layers for one effective stroke weight.

    ``stroke_multiplier == 1.0`` reproduces the historical two-layer
    shadow byte-for-byte, so nothing changes until a pack or an override
    actually asks for it.  ``0`` drops the outline entirely (the UI's
    "描边关闭"), and neon packs stack coloured glow on top.
    """

    parts: list[str] = []
    if stroke_multiplier > 0:
        parts.append(
            f"0 {_caption_em(0.025 * stroke_multiplier)} "
            f"{_caption_em(0.05 * stroke_multiplier)} #000d",
        )
        parts.append(
            f"0 {_caption_em(0.04 * stroke_multiplier)} "
            f"{_caption_em(0.14 * stroke_multiplier)} #000b",
        )
    if glow:
        halo = colour if colour.startswith("#") else "#ffffff"
        parts.append(f"0 0 .06em {halo}")
        parts.append(f"0 0 .18em {halo}88")
        parts.append(f"0 0 .38em {halo}55")
    return ",".join(parts) if parts else "none"


_PLATE_RGBA = re.compile(r"^rgba\((\d+),(\d+),(\d+),[0-9.]+\)$")
_PLATE_RGB = re.compile(r"^rgb\((\d+),(\d+),(\d+)\)$")


def plate_with_opacity(
    plate: str,
    style: Mapping[str, Any] | None,
) -> str:
    """Re-alpha one pack plate with the user's background-opacity pick.

    ``None`` keeps the pack's own alpha byte-for-byte and a plate-free pack
    stays plate-free whatever the value says: the override reshapes the block
    the pack already draws and never invents one, so no wording can promise a
    background the pixels do not show.  ``0`` drops the plate entirely.
    """

    if not plate:
        return ""
    raw = (
        style.get("background_opacity")
        if isinstance(style, Mapping)
        else None
    )
    # A missing, unreadable or non-finite value all mean the same thing to
    # this function: nothing was picked, so the pack keeps its own alpha.
    try:
        alpha = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        alpha = None
    if alpha is None or not math.isfinite(alpha):
        return plate
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0.0:
        return ""
    text = plate.strip()
    match = _PLATE_RGBA.match(text) or _PLATE_RGB.match(text)
    if match:
        red, green, blue = match.group(1, 2, 3)
    elif _HEX_COLOR.fullmatch(text):
        digits = text.lstrip("#")
        red, green, blue = (str(int(digits[i:i + 2], 16)) for i in (0, 2, 4))
    else:
        # An unparseable colour stays as the pack wrote it rather than being
        # guessed at; the browser reads it either way.
        return plate
    return f"rgba({red},{green},{blue},{alpha:.3f})"


def _caption_entrance_css(
    entrance: str,
) -> tuple[str, str]:
    """``(animation shorthand, keyframes)`` for one caption entrance."""

    if entrance == "pop":
        return (
            "capPop .28s cubic-bezier(.34,1.56,.64,1) both",
            "@keyframes capPop{from{opacity:.6;transform:scale(.88)}"
            "to{opacity:1;transform:scale(1)}}",
        )
    if entrance == "slide":
        return (
            "capSlide .3s ease-out both",
            "@keyframes capSlide{from{opacity:.6;transform:translateY(.45em)}"
            "to{opacity:1;transform:translateY(0)}}",
        )
    if entrance == "type_on":
        return (
            "capType .5s linear both",
            "@keyframes capType{from{opacity:.85;clip-path:inset(0 62% 0 0)}"
            "to{opacity:1;clip-path:inset(0 0 0 0)}}",
        )
    return (
        "appear .14s linear both",
        "@keyframes appear{from{opacity:.72}to{opacity:1}}",
    )


def render_caption_template(
    text: str,
    *,
    theme: str = "comic_patrol",
    emotion: str = "chill",
    box_width: float | None = None,
    box_height: float | None = None,
    style: Mapping[str, Any] | None = None,
    typography: Mapping[str, Any] | None = None,
    entrance: str | None = None,
    exit: str | None = None,
    loop: bool | None = None,
) -> str:
    """Render plain subtitles, also used when an authored design fails.

    Legacy theme/emotion arguments remain accepted without changing the
    typography.  ``typography`` (a resolved style pack), ``style`` (the
    user's colour / font-size / outline overrides) and the ``entrance`` /
    ``exit`` / ``loop`` triple all default to nothing, so a project that
    never picked a style emits exactly the document it used to.
    """

    del theme, emotion
    safe_text = "<br>".join(escape(line) for line in text.strip().splitlines())
    pack = typography if isinstance(typography, Mapping) else None
    # The pack's own leading and tracking are layout facts, so they enter the
    # fit; ``font_scale`` stays a visible multiplier below because a user who
    # picks 大字 expects bigger glyphs even on a long line.
    line_height = float(pack.get("lineHeight", 1.35) or 1.35) if pack else 1.35
    letter_spacing = str(pack.get("letterSpacing") or "") if pack else ""
    font = _caption_font_css(
        text,
        box_width,
        box_height,
        line_height=line_height,
        letter_spacing_em=_caption_em_value(letter_spacing),
    )
    font_scale = _caption_style_number(style, "font_scale", 1.0, 0.6, 1.8)
    if abs(font_scale - 1.0) > 1e-6:
        font = f"calc({font}*{font_scale:.4f})"
    colour = (
        _color(style.get("color"), "#ffffff")
        if isinstance(style, Mapping) and style.get("color")
        else "#fff"
    )
    pack_stroke = (
        float(pack.get("strokeScale", 1.0) or 1.0)
        if pack is not None
        else 1.0
    )
    user_stroke = _caption_style_number(style, "stroke_scale", 1.0, 0.0, 3.0)
    stroke = max(0.0, pack_stroke * user_stroke)
    shadow = _caption_shadow_stack(
        stroke,
        bool(pack and pack.get("glow")),
        colour if colour.startswith("#") else "#ffffff",
    )
    user_family = (
        _SUBTITLE_FONT_CSS_STACKS.get(
            str(style.get("font_family") or "").strip().lower()
        )
        if isinstance(style, Mapping)
        else None
    )
    family = user_family or (
        str(pack.get("fontFamily"))
        if pack and pack.get("fontFamily")
        else _LEGACY_CAPTION_FAMILY
    )
    weight = int(pack.get("fontWeight", 600) or 600) if pack else 600
    plate = str(pack.get("plate") or "") if pack else ""
    plate = plate_with_opacity(plate, style)
    plate_radius = str(pack.get("plateRadius") or "0.28em") if pack else ""
    tilt = float(pack.get("tiltDeg", 0.0) or 0.0) if pack else 0.0

    # The caller resolves the triple (element override -> pack default ->
    # historical default), so anything unrecognised simply stays legacy.
    entrance_key = entrance if entrance in CAPTION_ENTRANCES else "soft_fade"
    exit_key = exit if exit in CAPTION_EXITS else "none"
    is_loop = bool(loop)
    animation, keyframes = _caption_entrance_css(entrance_key)
    if is_loop:
        # One long iteration carrying several breaths: the capture clamps a
        # non-looping document at its detected period, so the ambient motion
        # has to live inside that period and settle back to scale 1.
        animation += ",capBreath 9.6s ease-in-out .45s infinite"
        keyframes += (
            "@keyframes capBreath{0%,100%{transform:scale(1)}"
            "12%{transform:scale(1.022)}25%{transform:scale(1)}"
            "37%{transform:scale(1.018)}50%{transform:scale(1)}"
            "62%{transform:scale(1.022)}75%{transform:scale(1)}"
            "87%{transform:scale(1.014)}}"
        )
    # A plate turns the line box into a pill, so it has to hug the glyphs;
    # without one the text keeps filling the whole placement box as before.
    words_layout = (
        "width:auto;max-width:100%;display:inline-block;"
        f"padding:.28em .6em;background:{plate};border-radius:{plate_radius};"
        if plate
        else "width:100%;"
    )
    # Semicolon-leading so an untilted document keeps the historical byte-for-
    # byte ``.stage`` rule.
    tilt_css = f";transform:rotate({tilt}deg)" if tilt else ""
    # The tilt lives on the stage, never on the glyphs: every entrance and the
    # ambient breath animate ``transform``, which would overwrite a rotate on
    # the same element for the rest of the caption.
    spacing_css = (
        f"letter-spacing:{letter_spacing};"
        if letter_spacing and letter_spacing != "0em"
        else ""
    )
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
html,body{{width:100%;height:100%;margin:0;background:transparent;overflow:hidden}}
*{{box-sizing:border-box}}
.stage{{position:absolute;inset:6%;display:flex;align-items:center;justify-content:center{tilt_css}}}
.words{{{words_layout}margin:0;color:{colour};font-family:{family};font-size:{font};font-weight:{weight};line-height:{line_height};{spacing_css}text-align:center;word-break:normal;overflow-wrap:break-word;line-break:strict;text-shadow:{shadow};animation:{animation}}}
{keyframes}
</style></head><body><div class="stage" data-motion-template-version="{CAPTION_TEMPLATE_VERSION}" data-motion-motif="caption_card" data-caption-style="plain" data-caption-entrance="{entrance_key}" data-motion-exit="{exit_key}" data-caption-loop="{1 if is_loop else 0}"><div class="words">{safe_text}</div></div></body></html>"""


def render_decoration_template(
    motif: str,
    *,
    primary_color: object = None,
    secondary_color: object = None,
    theme: str = "comic_patrol",
    variant: str = "sticker",
    emotion: str = "chill",
    entrance: str = "pop",
    exit: str = "soft_fade",
    intensity: float = 0.6,
) -> str:
    """Render one allowlisted, text-free HTML/CSS decoration."""

    if motif not in SUPPORTED_MOTIFS:
        raise ValueError(f"unsupported motion motif: {motif}")
    primary = _color(primary_color, "#ff9a2f")
    secondary = _color(secondary_color, "#26211d")
    theme = theme if theme in SUPPORTED_THEMES else "comic_patrol"
    variant = variant if variant in SUPPORTED_VARIANTS else "sticker"
    emotion = emotion if emotion in SUPPORTED_EMOTIONS else "chill"
    entrance = entrance if entrance in SUPPORTED_ENTRANCES else "pop"
    exit = exit if exit in SUPPORTED_EXITS else "soft_fade"
    try:
        intensity_value = min(1.0, max(0.0, float(intensity)))
    except (TypeError, ValueError):
        intensity_value = 0.6
    ambient_seconds = 4.2 - intensity_value * 2.2
    entrance_name = f"enter-{entrance}"
    ambient_name = f"ambient-{emotion}"
    motif_css, body = _MOTIFS[motif]
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
html,body{{width:100%;height:100%;margin:0;background:transparent;overflow:hidden}}
:root{{--primary:{primary};--secondary:{secondary};--intensity:{intensity_value:.3f}}}
.stage{{position:absolute;inset:9%;transform-origin:center;animation:{entrance_name} .48s cubic-bezier(.2,.8,.2,1) both,{ambient_name} {ambient_seconds:.2f}s ease-in-out .48s infinite alternate}}
.shape{{position:absolute;display:block;box-sizing:border-box}}
{motif_css}
{_THEME_CSS[theme]}
{_VARIANT_CSS[variant]}
@keyframes enter-pop{{from{{opacity:.25;transform:scale(.68)}}to{{opacity:1;transform:scale(1)}}}}
@keyframes enter-stamp{{0%{{opacity:.25;transform:scale(1.35) rotate(-7deg)}}70%{{opacity:1;transform:scale(.94) rotate(2deg)}}100%{{transform:scale(1)}}}}
@keyframes enter-draw_in{{from{{opacity:.25;clip-path:inset(0 100% 0 0)}}to{{opacity:1;clip-path:inset(0)}}}}
@keyframes enter-slide{{from{{opacity:.25;transform:translateX(-18%)}}to{{opacity:1;transform:translateX(0)}}}}
@keyframes ambient-chill{{to{{transform:translateY(-3px);opacity:.9}}}}
@keyframes ambient-curious{{to{{transform:translateY(-2px) rotate(3deg)}}}}
@keyframes ambient-surprise{{to{{transform:scale(calc(.96 + var(--intensity) * .04))}}}}
@keyframes ambient-action{{0%{{transform:translateX(-2px) rotate(-1deg)}}100%{{transform:translateX(2px) rotate(1deg)}}}}
</style></head><body><div class="stage" data-motion-template-version="1" data-motion-motif="{motif}" data-motion-theme="{theme}" data-motion-variant="{variant}" data-motion-emotion="{emotion}" data-motion-entrance="{entrance}" data-motion-exit="{exit}" data-motion-intensity="{intensity_value:.3f}">{body}</div></body></html>"""


_THEME_CSS = {
    "comic_patrol": ".stage{font-family:Impact,sans-serif}.shape{paint-order:stroke fill}",
    "soft_journal": ".stage{filter:saturate(.82) brightness(1.08)}.shape{opacity:.92}",
    "neon_night": ".stage{filter:saturate(1.25) drop-shadow(0 0 7px var(--primary))}",
}

_VARIANT_CSS = {
    "sticker": ".shape{filter:drop-shadow(3px 3px 0 color-mix(in srgb,var(--secondary) 42%,transparent))}",
    "ink": ".shape{filter:contrast(1.18) drop-shadow(2px 2px 0 var(--secondary))}",
    "neon": ".shape{filter:drop-shadow(0 0 5px var(--primary)) drop-shadow(0 0 10px var(--primary))}",
}


_MOTIFS: dict[str, tuple[str, str]] = {
    "paw_trail": (
        """
.paw{width:23%;aspect-ratio:1;opacity:.25;filter:drop-shadow(3px 3px 0 color-mix(in srgb,var(--secondary) 35%,transparent));animation:paw-appear .36s cubic-bezier(.2,.85,.2,1) forwards}
.pad,.toe{position:absolute;background:var(--primary)}
.pad{left:20%;bottom:4%;width:60%;height:51%;border-radius:52% 52% 44% 44%}
.toe{width:20%;height:20%;border-radius:50%}.t1{left:2%;top:28%}.t2{left:27%;top:7%}.t3{right:27%;top:3%}.t4{right:2%;top:24%}
.p1{left:2%;bottom:2%;transform:rotate(-16deg)}.p2{left:39%;top:31%;transform:rotate(6deg);animation-delay:.38s}.p3{right:1%;top:4%;transform:rotate(20deg);animation-delay:.68s}
@keyframes paw-appear{0%{opacity:.25;scale:.55}72%{opacity:1;scale:1.08}100%{opacity:1;scale:1}}
""",
        """<i class="shape paw p1"><b class="pad"></b><b class="toe t1"></b><b class="toe t2"></b><b class="toe t3"></b><b class="toe t4"></b></i><i class="shape paw p2"><b class="pad"></b><b class="toe t1"></b><b class="toe t2"></b><b class="toe t3"></b><b class="toe t4"></b></i><i class="shape paw p3"><b class="pad"></b><b class="toe t1"></b><b class="toe t2"></b><b class="toe t3"></b><b class="toe t4"></b></i>""",
    ),
    "alert_mark": (
        """
.outer,.inner{inset:0;clip-path:polygon(50% 2%,98% 92%,2% 92%)}.outer{background:var(--secondary)}.inner{inset:9% 8% 12%;background:var(--primary)}
.bar{left:45%;top:29%;width:10%;height:29%;border-radius:99px;background:var(--secondary)}.dot{left:45%;top:62%;width:10%;aspect-ratio:1;border-radius:50%;background:var(--secondary)}
""",
        '<i class="shape outer"></i><i class="shape inner"></i><i class="shape bar"></i><i class="shape dot"></i>',
    ),
    "approval_checks": (
        """
.badge{width:29%;aspect-ratio:1;border-radius:50%;background:var(--primary);border:4px solid var(--secondary);filter:drop-shadow(3px 3px 0 color-mix(in srgb,var(--secondary) 30%,transparent))}
.badge:after{content:"";position:absolute;left:24%;top:20%;width:42%;height:24%;border-left:6px solid white;border-bottom:6px solid white;transform:rotate(-45deg)}
.b1{left:2%;bottom:4%}.b2{left:36%;top:14%}.b3{right:1%;bottom:18%}
""",
        '<i class="shape badge b1"></i><i class="shape badge b2"></i><i class="shape badge b3"></i>',
    ),
    "focus_target": (
        """
.ring{inset:15%;border:6px solid var(--primary);border-radius:50%;filter:drop-shadow(3px 3px 0 var(--secondary))}.ring2{inset:32%;border:3px solid var(--primary);border-radius:50%}
.h{left:4%;right:4%;top:49%;height:4px;background:var(--primary)}.v{top:4%;bottom:4%;left:49%;width:4px;background:var(--primary)}
""",
        '<i class="shape ring"></i><i class="shape ring2"></i><i class="shape h"></i><i class="shape v"></i>',
    ),
    "sparkles": (
        """
.star{aspect-ratio:1;background:var(--primary);clip-path:polygon(50% 0,61% 38%,100% 50%,61% 62%,50% 100%,39% 62%,0 50%,39% 38%)}
.s1{width:40%;left:3%;top:22%}.s2{width:30%;right:3%;top:4%}.s3{width:24%;right:27%;bottom:2%}
""",
        '<i class="shape star s1"></i><i class="shape star s2"></i><i class="shape star s3"></i>',
    ),
    "leaf_accent": (
        """
.leaf{width:38%;height:24%;border-radius:100% 0 100% 0;background:linear-gradient(135deg,var(--primary),var(--secondary));filter:drop-shadow(3px 3px 0 color-mix(in srgb,var(--secondary) 30%,transparent))}
.l1{left:2%;bottom:10%;transform:rotate(-16deg)}.l2{left:32%;top:17%;transform:rotate(18deg) scale(.9)}.l3{right:1%;bottom:20%;transform:rotate(52deg) scale(.75)}
""",
        '<i class="shape leaf l1"></i><i class="shape leaf l2"></i><i class="shape leaf l3"></i>',
    ),
}


__all__ = [
    "CAPTION_ROLE_LOCATIONS",
    "CAPTION_SAFE_AREA_EDGES",
    "MOTION_TEMPLATE_VERSION",
    "SUPPORTED_EMOTIONS",
    "SUPPORTED_ENTRANCES",
    "SUPPORTED_EXITS",
    "SUPPORTED_MOTIFS",
    "SUPPORTED_THEMES",
    "SUPPORTED_VARIANTS",
    "caption_box_edges",
    "caption_box_out_of_safe_area",
    "render_decoration_template",
]
