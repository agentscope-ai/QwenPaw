# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Parameterized GSAP motion blueprints (hyperframes-style catalog blocks).

Free-form VLM documents fail the render truth gates often (empty t=0
frames, loop seams), and the single fixed fallback template made every
caption look identical. Blueprints sit between those extremes: each one
is a hand-verified ``html_js`` skeleton that is seek-safe by
construction (visible at t=0, safe margins, seamless loop period), while
the frame-derived styling — palette, intensity, pacing — arrives as
validated parameters chosen by the design VLM from the real footage.

Every rendered document registers the ``window.__hf`` protocol and only
references the pinned ``vendor/gsap.min.js`` runtime, so it passes
through exactly the same probe/render gates as free-form documents.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from collections.abc import Mapping
import math
import re

BLUEPRINT_VERSION = 1

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

_HF_REGISTER = (
    "window.__hf = { duration: %DUR%, seek: function (t, o) { tl.pause();\n"
    "  tl.totalTime(Math.max(0, t) + 0.001, true);\n"
    "  tl.totalTime(Math.max(0, t), o && o.suppressEvents === true); } };"
)

_BASE_CSS = """html,body{width:100%;height:100%;margin:0;background:transparent;overflow:hidden}
*{box-sizing:border-box}
#root{position:absolute;inset:8%;}"""


@dataclass(frozen=True)
class BlueprintPalette:
    """Frame-derived colors; every field is a validated ``#rrggbb``."""

    primary: str
    secondary: str
    ink: str
    paper: str


def _color(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if _HEX_COLOR.fullmatch(text) else fallback


def validated_palette(raw: object) -> BlueprintPalette:
    """Clamp one VLM-provided palette mapping to safe hex colors."""

    data = raw if isinstance(raw, dict) else {}
    return BlueprintPalette(
        primary=_color(data.get("primary"), "#ffb35c"),
        secondary=_color(data.get("secondary"), "#2a2622"),
        ink=_color(data.get("ink"), "#241f1b"),
        paper=_color(data.get("paper"), "#fff8ec"),
    )


def _clamped(value: object, fallback: float, low: float, high: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return min(high, max(low, number))


def _escape_text(text: str) -> str:
    """Escape text for HTML, converting newlines to <br> tags."""
    return "<br>".join(escape(line) for line in text.strip().splitlines())


def _chars(text: str) -> str:
    """Wrap every visible character for per-character staggers."""

    lines = text.strip().split("\n")
    groups: list[str] = []
    for line in lines:
        pieces: list[str] = []
        for char in line:
            if char.isspace():
                pieces.append("<i class='sp'>&nbsp;</i>")
            else:
                pieces.append(f"<b class='ch'>{escape(char)}</b>")
        groups.append(f"<div class='line-div'>{''.join(pieces)}</div>")
    return "".join(groups)


def _caption_font_css(
    text: str,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> str:
    """Two-axis font clamp for one caption viewport.

    The document only knows its own viewport, so the size is expressed
    as ``min(vh, vw)``: the vh term keeps line stacks inside flat boxes,
    the vw term keeps the longest line inside narrow boxes. Every
    decorative measure in the blueprints is em-based so the whole card
    scales with this value no matter how extreme the box ratio is.

    When *box_height* is provided (normalised canvas fraction, e.g. 0.25),
    the vh term is scaled inversely so that the apparent font size on the
    canvas stays consistent across overlays with very different box
    heights — a small box (0.18) gets a larger vh value, a tall box
    (0.85) gets a smaller one.

    When *box_width* is provided, the vw term is scaled proportionally
    so the font fits the overlay box width rather than the full viewport.
    """

    raw_lines = text.split("\n")
    line_char_counts = [
        len(re.sub(r"\s+", "", line)) for line in raw_lines if line.strip()
    ]
    if not line_char_counts:
        line_char_counts = [1]
    per_line = max(line_char_counts)
    lines = len(line_char_counts)
    if len(raw_lines) <= 1:
        per_line = per_line if per_line <= 12 else math.ceil(per_line / 2)
        lines = 1 if per_line <= 12 else 2
    # CJK glyphs are roughly square. Width budget: glyph run plus the
    # widest card chrome (≈1.9em of padding/side accents) inside 80% of
    # the box. Height budget: the tallest card stack (line-height plus
    # vertical padding, gap and rule ≈2.4em per line) inside 76%,
    # leaving the root 8% inset and entrance travel untouched.
    vw = 80.0 / (per_line * 1.08 + 1.9)
    vh = 76.0 / (lines * 2.4)
    if box_width is not None and box_width > 0:
        vw *= box_width
    if box_height is not None and box_height > 0:
        vh *= 0.25 / box_height
    return f"min({vh:.1f}vh,{vw:.1f}vw)"


def _document(
    css: str,
    body: str,
    script: str,
    duration: float,
    *,
    exit_style: str = "soft_fade",
    full_bleed: bool = False,
    frame_ring: bool = False,
    frame_window: Mapping[str, float] | None = None,
) -> str:
    register = _HF_REGISTER.replace("%DUR%", f"{duration:.3f}")
    # data-motion-exit hands the ending to the renderer-managed exit (an
    # alpha fade over the last 15% of the output window): cards and
    # decorations leave gracefully instead of hard-cutting, while the
    # timeline itself keeps a fully visible final state for the probes.
    # Caption/decoration cards keep the 8% root inset (entrance travel
    # space inside their overlay box); full-canvas scene documents ARE
    # the picture and must flood the whole viewport instead.
    # data-motion-frame="ring" declares an opaque-border/transparent-
    # window document so the capture gate swaps its edge rule for the
    # transparent-center rule.
    root_css = "#root{position:absolute;inset:0;}" if full_bleed else ""
    ring_attr = ' data-motion-frame="ring"' if frame_ring else ""
    if frame_ring and frame_window is not None:
        ring_attr += (
            ' data-motion-window="'
            f'{frame_window["left"]:.6f},'
            f'{frame_window["top"]:.6f},'
            f'{frame_window["width"]:.6f},'
            f'{frame_window["height"]:.6f}"'
        )
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><style>\n'
        f"{_BASE_CSS}\n{root_css}\n{css}\n</style></head>"
        f'<body><div id="root" data-motion-exit="{exit_style}"{ring_attr}>{body}</div>\n'
        '<script src="vendor/gsap.min.js"></script>\n'
        f"<script>\nvar tl = gsap.timeline({{ paused: true }});\n{script}\n{register}\n</script></body></html>"
    )


# ---------------------------------------------------------------------------
# Caption card blueprints (loop=False, copy must stay readable)
# ---------------------------------------------------------------------------


def _caption_stagger_pop(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """综艺花字：内容包裹式贴纸胶囊 + 逐字弹入 + 强调下划线。"""

    overshoot = 1.3 + intensity * 0.6
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{display:flex;flex-direction:column;align-items:center;gap:.18em;max-width:96%;padding:.34em .85em .3em;font-size:{font};background:{palette.paper}f2;border:.07em solid {palette.ink};border-radius:.55em;box-shadow:.14em .18em 0 {palette.secondary}59}}
.line{{display:flex;flex-wrap:wrap;justify-content:center;font-family:"PingFang SC","Arial Black",sans-serif;font-weight:900;font-size:1em;line-height:1.18;color:{palette.ink}}}
.ch,.sp{{display:inline-block;font-style:normal}}
.rule{{width:52%;height:.11em;border-radius:99px;background:linear-gradient(90deg,{palette.primary},{palette.secondary});transform-origin:center}}
"""
    body = f"<div class='wrap'><div class='card'><div class='line'>{_chars(text)}</div><div class='rule'></div></div></div>"
    script = f"""
tl.fromTo('.card',{{autoAlpha:.45,scale:.96}},{{autoAlpha:1,scale:1,duration:.4,ease:'power2.out'}},0);
tl.fromTo('.ch',{{autoAlpha:.4,y:'16%',scale:.9,rotate:-3}},{{autoAlpha:1,y:'0%',scale:1,rotate:0,duration:.5,stagger:.04,ease:'back.out({overshoot:.2f})'}},.05);
tl.fromTo('.rule',{{scaleX:.3,autoAlpha:.4}},{{scaleX:1,autoAlpha:1,duration:.55,ease:'power3.out'}},.2);
tl.to('.card',{{y:'-3%',duration:1.0,ease:'sine.inOut'}},.9);
tl.to('.card',{{y:'0%',duration:1.0,ease:'sine.inOut'}},1.9);
"""
    return _document(css, body, script, 2.9), 2.9


def _caption_static_capsule(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """静态胶囊：全片像素级一致的解说/教学字幕。

    对齐 hyperframes 的 caption-bar 做法：字号固定（不随文本长度
    缩放，长句靠 max-width 换行），胶囊宽度随内容伸缩，零入场装饰
    ——仅整卡一次短淡入后保持静止，任意时刻采样都是同一幅末态；
    退场硬切（exit none），避免逐句字幕交接处前后两卡淡变叠影。
    """

    del intensity  # 静态模板没有可调幅度，保持签名一致即可
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{width:max-content;max-width:94%;box-sizing:border-box;font-size:{font};padding:.28em .9em;border-radius:.42em;background:{palette.paper}f2;border:.04em solid {palette.ink}26;box-shadow:0 .08em .3em {palette.ink}33}}
.text{{font-family:"PingFang SC","Noto Sans SC",sans-serif;font-weight:600;font-size:1em;line-height:1.35;letter-spacing:.02em;text-align:center;color:{palette.ink}}}
"""
    body = f"<div class='wrap'><div class='card'><div class='text'>{_escape_text(text)}</div></div></div>"
    script = """
tl.fromTo('.card',{autoAlpha:.35},{autoAlpha:1,duration:.3,ease:'power1.out'},0);
tl.to('.card',{autoAlpha:1,duration:.1},.3);
"""
    return _document(css, body, script, 0.4, exit_style="none"), 0.4


def _caption_precision_subtitle(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """现代软件教程字幕：轻量玻璃底、状态点与进度线。

    The card deliberately avoids the thick outline, large rounded capsule and
    bouncing entrance used by entertainment captions. It preserves literal UI
    pixels behind it while still reading as one designed product system.
    """

    del intensity
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;display:grid;grid-template-columns:.28em auto;align-items:center;column-gap:.42em;width:max-content;max-width:96%;padding:.30em .78em .34em;font-size:{font};border:1px solid {palette.paper}26;border-radius:.28em;background:{palette.ink}d9;box-shadow:0 .16em .65em #0000004d;backdrop-filter:blur(.28em)}}
.dot{{width:.24em;height:.24em;border-radius:50%;background:{palette.primary};box-shadow:0 0 .5em {palette.primary}8c}}
.text{{font-family:"PingFang SC","Noto Sans SC",sans-serif;font-size:1em;font-weight:650;line-height:1.30;letter-spacing:.015em;text-align:left;color:{palette.paper};text-wrap:balance}}
.rail{{position:absolute;left:.78em;right:.78em;bottom:.12em;height:.045em;border-radius:99px;background:{palette.paper}1f;overflow:hidden}}
.rail:after{{content:"";position:absolute;inset:0;background:{palette.primary};transform-origin:left center}}
"""
    body = (
        "<div class='wrap'><div class='card'><i class='dot'></i>"
        f"<div class='text'>{escape(text.strip())}</div><i class='rail'></i>"
        "</div></div>"
    )
    script = """
tl.fromTo('.card',{autoAlpha:.35,scale:.985,y:'4%'},{autoAlpha:1,scale:1,y:'0%',duration:.38,ease:'power3.out'},0);
tl.fromTo('.rail',{scaleX:.12},{scaleX:1,duration:.7,ease:'power3.out'},.05);
tl.fromTo('.dot',{scale:.72,autoAlpha:.5},{scale:1,autoAlpha:1,duration:.45,ease:'back.out(1.4)'},.08);
tl.to('.card',{autoAlpha:1,duration:.1},.75);
"""
    return _document(css, body, script, 0.85, exit_style="none"), 0.85


def _caption_editorial_title(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """产品片编辑式标题：左对齐 waterfall 字组、短标尺与轻量景深。"""

    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    overshoot = 1.02 + intensity * 0.08
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:flex-start}}
.block{{position:relative;width:96%;padding:.22em .08em .38em;font-size:{font}}}
.accent{{width:1.4em;height:.08em;border-radius:99px;background:{palette.primary};box-shadow:0 0 .5em {palette.primary}59;transform-origin:left center}}
.line{{display:flex;flex-wrap:wrap;align-items:baseline;margin-top:.28em;font-family:"PingFang SC","Noto Sans SC",sans-serif;font-size:1em;font-weight:760;line-height:1.03;letter-spacing:-.035em;color:{palette.paper};text-shadow:0 .08em .28em #00000073}}
.ch,.sp{{display:inline-block;font-style:normal}}
.meta{{position:absolute;left:.08em;bottom:0;width:62%;height:1px;background:linear-gradient(90deg,{palette.paper}59,transparent)}}
"""
    body = f"<div class='wrap'><div class='block'><i class='accent'></i><div class='line'>{_chars(text)}</div><i class='meta'></i></div></div>"
    script = f"""
tl.fromTo('.accent',{{scaleX:.18,autoAlpha:.45}},{{scaleX:1,autoAlpha:1,duration:.46,ease:'power4.out'}},0);
tl.fromTo('.ch',{{autoAlpha:.3,y:'10%',scale:.97}},{{autoAlpha:1,y:'0%',scale:{overshoot:.2f},duration:.52,stagger:.035,ease:'power4.out'}},.06);
tl.to('.ch',{{scale:1,duration:.24,stagger:.018,ease:'power2.out'}},.52);
tl.fromTo('.meta',{{scaleX:.1,autoAlpha:.35}},{{scaleX:1,autoAlpha:1,duration:.72,ease:'power3.out'}},.18);
tl.to('.block',{{y:'-1.2%',duration:1.25,ease:'sine.inOut'}},.9);
tl.to('.block',{{y:'0%',duration:1.25,ease:'sine.inOut'}},2.15);
"""
    return _document(css, body, script, 3.4), 3.4


def _caption_chapter_label(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """软件教程章节元数据：单行左对齐、窄边和方向性推进。"""

    del intensity
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:flex-start}}
.tag{{position:relative;display:flex;align-items:center;gap:.48em;width:max-content;max-width:96%;padding:.22em .58em .22em .34em;font-size:{font};border-left:.12em solid {palette.primary};border-top:1px solid {palette.paper}26;border-right:1px solid {palette.paper}26;border-bottom:1px solid {palette.paper}26;border-radius:0 .22em .22em 0;background:{palette.ink}d9;box-shadow:0 .12em .45em #00000042}}
.tick{{width:.24em;height:.24em;border-radius:.04em;background:{palette.primary}}}
.text{{font-family:"SFMono-Regular","Menlo","PingFang SC",monospace;font-size:1em;font-weight:650;line-height:1.15;letter-spacing:.025em;color:{palette.paper};white-space:nowrap}}
"""
    body = f"<div class='wrap'><div class='tag'><i class='tick'></i><div class='text'>{escape(text.strip())}</div></div></div>"
    script = """
tl.fromTo('.tag',{autoAlpha:.32,clipPath:'inset(0 72% 0 0)'},{autoAlpha:1,clipPath:'inset(0 0% 0 0)',duration:.48,ease:'power4.out'},0);
tl.fromTo('.tick',{scale:.6,rotate:-20},{scale:1,rotate:0,duration:.42,ease:'back.out(1.6)'},.16);
tl.to('.tag',{x:'1.5%',duration:1.0,ease:'sine.inOut'},.72);
tl.to('.tag',{x:'0%',duration:1.0,ease:'sine.inOut'},1.72);
"""
    return _document(css, body, script, 2.72), 2.72


def _caption_ink_reveal(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """电影字幕：大字直压画面 + 细描边投影保可读 + 侧色条 draw-on，
    无满框底板，仅文字底部一条包裹式半透明 scrim 融入画面。"""

    reveal = 0.55 + intensity * 0.25
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{display:flex;align-items:center;gap:.42em;max-width:96%;font-size:{font};padding:.22em .6em;border-radius:.3em;background:color-mix(in srgb,{palette.ink} 42%,transparent)}}
.bar{{width:.14em;height:1.15em;border-radius:99px;background:{palette.primary};transform-origin:top;flex:none}}
.text{{font-family:"PingFang SC","Songti SC",serif;font-weight:700;font-size:1em;line-height:1.32;letter-spacing:.06em;color:{palette.paper};text-shadow:0 .04em .12em {palette.ink},0 0 .5em {palette.ink}b3}}
"""
    body = f"<div class='wrap'><div class='card'><div class='bar'></div><div class='text'>{_escape_text(text)}</div></div></div>"
    script = f"""
tl.fromTo('.card',{{autoAlpha:.5}},{{autoAlpha:1,duration:.45,ease:'power1.out'}},0);
tl.fromTo('.bar',{{scaleY:.35,autoAlpha:.5}},{{scaleY:1,autoAlpha:1,duration:{reveal:.2f},ease:'power2.out'}},0);
tl.fromTo('.text',{{autoAlpha:.45,letterSpacing:'.28em',x:'2%'}},{{autoAlpha:1,letterSpacing:'.06em',x:'0%',duration:{reveal + 0.2:.2f},ease:'power3.out'}},.05);
tl.to('.bar',{{scaleY:.86,duration:1.1,ease:'sine.inOut'}},1.0);
tl.to('.bar',{{scaleY:1,duration:1.1,ease:'sine.inOut'}},2.1);
"""
    return _document(css, body, script, 3.2), 3.2


def _caption_glow_breath(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """情绪光晕：无底板，文字发光呼吸直压画面，背后一团包裹式柔光晕，
    两侧星芒点缀随字号缩放。"""

    glow = 0.12 + intensity * 0.14
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;display:flex;align-items:center;gap:.34em;max-width:96%;font-size:{font};padding:.3em .55em}}
.halo{{position:absolute;inset:-8% -4%;border-radius:50%;background:radial-gradient(closest-side,{palette.ink}80,transparent 78%)}}
.text{{position:relative;text-align:center;font-family:"PingFang SC",sans-serif;font-weight:800;font-size:1em;line-height:1.3;color:{palette.paper};text-shadow:0 0 {glow:.2f}em {palette.primary},0 0 {glow * 2.4:.2f}em {palette.primary}99,0 .05em .14em {palette.ink}}}
.spark{{position:relative;width:.34em;height:.34em;flex:none;background:{palette.primary};clip-path:polygon(50% 0,62% 38%,100% 50%,62% 62%,50% 100%,38% 62%,0 50%,38% 38%)}}
"""
    body = f"<div class='wrap'><div class='card'><i class='halo'></i><i class='spark'></i><div class='text'>{_escape_text(text)}</div><i class='spark'></i></div></div>"
    script = """
tl.fromTo('.card',{autoAlpha:.42,scale:.965},{autoAlpha:1,scale:1,duration:.7,ease:'power2.out'},0);
tl.fromTo('.spark',{autoAlpha:.35,scale:.5,rotate:-40},{autoAlpha:1,scale:1,rotate:0,duration:.6,stagger:.18,ease:'back.out(1.6)'},.1);
tl.to('.text',{scale:1.015,duration:1.1,ease:'sine.inOut'},.8);
tl.to('.text',{scale:1,duration:1.1,ease:'sine.inOut'},1.9);
tl.to('.spark',{rotate:18,duration:2.2,ease:'sine.inOut'},.8);
"""
    return _document(css, body, script, 3.0), 3.0


def _caption_handwritten_note(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """手写笔记：纸纹底板 + 手写体微倾斜 + 墨水划线动画，适合 Vlog。"""

    tilt = -1.5 - intensity * 1.5
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;max-width:96%;font-size:{font};padding:.4em 1.1em .35em;background:{palette.paper}f0;border-radius:.6em;transform:rotate({tilt:.1f}deg);box-shadow:.2em .25em 0 {palette.secondary}40}}
.tex{{position:absolute;inset:0;border-radius:.6em;background-image:repeating-linear-gradient(0deg,{palette.secondary}12 0,{palette.secondary}12 .4vh,transparent .4vh,transparent 2.8vh);opacity:.7}}
.line{{position:relative;display:flex;flex-wrap:wrap;justify-content:center;font-family:"PingFang SC","Noto Sans SC",sans-serif;font-weight:700;font-style:italic;font-size:1em;line-height:1.3;color:{palette.ink}}}
.ch,.sp{{display:inline-block;font-style:italic}}
.underline{{position:relative;width:60%;height:.12em;border-radius:99px;background:{palette.primary};transform-origin:left center;transform:scaleX(0);margin:.12em auto 0}}
"""
    body = f"<div class='wrap'><div class='card'><i class='tex'></i><div class='line'>{_chars(text)}</div><div class='underline'></div></div></div>"
    script = """
tl.fromTo('.card',{autoAlpha:.3,scale:.95},{autoAlpha:1,scale:1,duration:.45,ease:'power2.out'},0);
tl.fromTo('.ch',{autoAlpha:.3,y:'10%'},{autoAlpha:1,y:'0%',duration:.4,stagger:.035,ease:'power2.out'},.05);
tl.to('.underline',{scaleX:1,duration:.6,ease:'power3.inOut'},.35);
tl.to('.card',{y:'-2%',duration:1.0,ease:'sine.inOut'},1.0);
tl.to('.card',{y:'0%',duration:1.0,ease:'sine.inOut'},2.0);
"""
    return _document(css, body, script, 3.0), 3.0


def _caption_keyword_spotlight(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """关键词聚焦：左对齐，关键词高亮色块滑入，适合教学。"""

    highlight = 0.6 + intensity * 0.4
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;display:flex;flex-direction:column;gap:.15em;max-width:96%;font-size:{font};padding:.3em .7em}}
.line{{position:relative;display:flex;flex-wrap:wrap;align-items:center;font-family:"PingFang SC","Noto Sans SC",sans-serif;font-weight:600;font-size:1em;line-height:1.35;color:{palette.ink}}}
.ch,.sp{{display:inline-block}}
.marker{{position:absolute;left:-.15em;right:-.15em;bottom:.05em;height:.42em;background:{palette.primary};opacity:{highlight:.2f};border-radius:.2em;z-index:-1}}
"""
    words = text.strip().split()
    if len(words) >= 2:
        keyword = max(words, key=len)
        before, _, after = text.partition(keyword)
        line_html = (
            f"{_escape_text(before)}"
            f"<span class='kw' style='position:relative;display:inline-block'>"
            f"<i class='marker'></i>"
            f"<span style='position:relative;z-index:1;font-weight:800;color:{palette.paper}'>"
            f"{escape(keyword)}</span></span>"
            f"{_escape_text(after)}"
        )
    else:
        line_html = f"<span class='kw' style='position:relative;display:inline-block'><i class='marker'></i><span style='position:relative;z-index:1;font-weight:800;color:{palette.paper}'>{_escape_text(text)}</span></span>"
    body = f"<div class='wrap'><div class='card'><div class='line'>{line_html}</div></div></div>"
    script = """
tl.fromTo('.card',{autoAlpha:.35,x:'-3%'},{autoAlpha:1,x:'0%',duration:.4,ease:'power2.out'},0);
tl.fromTo('.marker',{scaleX:0,transformOrigin:'left center'},{scaleX:1,duration:.5,ease:'power3.out'},.2);
tl.fromTo('.kw span',{autoAlpha:.5},{autoAlpha:1,duration:.35,ease:'power1.out'},.25);
"""
    return _document(css, body, script, 2.6), 2.6


def _caption_drama_whisper(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """低语独白：宋体大字宽字距，逐字淡入+垂直模糊，纯文字+横线，适合短剧。"""

    blur = 0.08 + intensity * 0.1
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;display:flex;flex-direction:column;align-items:center;gap:.3em;max-width:96%;font-size:{font}}}
.rule{{width:40%;height:.06em;background:{palette.paper}80;transform-origin:center;transform:scaleX(0)}}
.text{{display:flex;flex-wrap:wrap;justify-content:center;font-family:"Songti SC","STSong",serif;font-weight:400;font-size:1em;line-height:1.5;letter-spacing:.18em;color:{palette.paper};text-shadow:0 0 {blur:.2f}em {palette.ink}}}
.ch,.sp{{display:inline-block}}
"""
    body = f"<div class='wrap'><div class='card'><div class='rule'></div><div class='text'>{_chars(text)}</div><div class='rule'></div></div></div>"
    script = """
tl.fromTo('.rule',{scaleX:0},{scaleX:1,duration:.6,ease:'power2.inOut'},0);
tl.fromTo('.ch',{autoAlpha:.25,filter:'blur(4px)',y:'6%'},{autoAlpha:1,filter:'blur(0px)',y:'0%',duration:.5,stagger:.06,ease:'power1.out'},.15);
tl.to('.text',{letterSpacing:'.22em',duration:1.2,ease:'sine.inOut'},1.0);
tl.to('.text',{letterSpacing:'.18em',duration:1.2,ease:'sine.inOut'},2.2);
"""
    return _document(css, body, script, 3.4), 3.4


def _caption_neon_pulse(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """霓虹脉冲：暗底+亮色文字多层 glow 呼吸+霓虹描边，适合音乐/MV。"""

    glow = 0.15 + intensity * 0.2
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;display:flex;align-items:center;justify-content:center;max-width:96%;font-size:{font};padding:.35em .9em;border:.1em solid {palette.primary}8c;border-radius:.5em;background:{palette.ink}cc;box-shadow:0 0 {glow:.2f}em {palette.primary}66,inset 0 0 {glow * 0.5:.2f}em {palette.primary}33}}
.text{{font-family:"PingFang SC","Arial Black",sans-serif;font-weight:900;font-size:1em;line-height:1.25;color:{palette.primary};text-shadow:0 0 {glow:.2f}em {palette.primary},0 0 {glow * 2:.2f}em {palette.primary}80,0 0 {glow * 4:.2f}em {palette.primary}40}}
"""
    body = f"<div class='wrap'><div class='card'><div class='text'>{_escape_text(text)}</div></div></div>"
    script = f"""
tl.fromTo('.card',{{autoAlpha:.3,scale:.96}},{{autoAlpha:1,scale:1,duration:.4,ease:'power2.out'}},0);
tl.to('.text',{{textShadow:'0 0 {glow * 1.4:.2f}em {palette.primary},0 0 {glow * 2.8:.2f}em {palette.primary}aa,0 0 {glow * 5:.2f}em {palette.primary}66',duration:.8,ease:'sine.inOut'}},.3);
tl.to('.text',{{textShadow:'0 0 {glow:.2f}em {palette.primary},0 0 {glow * 2:.2f}em {palette.primary}80,0 0 {glow * 4:.2f}em {palette.primary}40',duration:.8,ease:'sine.inOut'}},1.1);
tl.to('.card',{{boxShadow:'0 0 {glow * 1.3:.2f}em {palette.primary}80,inset 0 0 {glow * 0.7:.2f}em {palette.primary}4d',duration:.8,ease:'sine.inOut'}},.3);
tl.to('.card',{{boxShadow:'0 0 {glow:.2f}em {palette.primary}66,inset 0 0 {glow * 0.5:.2f}em {palette.primary}33',duration:.8,ease:'sine.inOut'}},1.1);
"""
    return _document(css, body, script, 2.8), 2.8


def _caption_brush_strike(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
    *,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """墨笔横扫：粗体字 clip-path 横扫揭示+对角线扫过，通用动作型。"""

    sweep_dur = 0.4 + intensity * 0.2
    font = _caption_font_css(text, box_width=box_width, box_height=box_height)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;max-width:96%;font-size:{font};padding:.3em .8em;overflow:hidden}}
.accent{{position:absolute;left:-10%;top:-20%;width:30%;height:140%;background:{palette.primary}40;transform:rotate(-18deg) translateX(-120%);z-index:0}}
.text{{position:relative;z-index:1;font-family:"PingFang SC","Arial Black",sans-serif;font-weight:900;font-size:1em;line-height:1.25;color:{palette.paper};text-shadow:0 .06em .15em {palette.ink};clip-path:inset(0 100% 0 0)}}
"""
    body = f"<div class='wrap'><div class='card'><i class='accent'></i><div class='text'>{_escape_text(text)}</div></div></div>"
    script = f"""
tl.to('.text',{{clipPath:'inset(0 0% 0 0)',duration:{sweep_dur:.2f},ease:'power3.inOut'}},.1);
tl.to('.accent',{{x:'420%',duration:{sweep_dur + 0.3:.2f},ease:'power2.inOut'}},.05);
tl.to('.card',{{y:'-2%',duration:1.0,ease:'sine.inOut'}},1.0);
tl.to('.card',{{y:'0%',duration:1.0,ease:'sine.inOut'}},2.0);
"""
    return _document(css, body, script, 3.0), 3.0


# ---------------------------------------------------------------------------
# Text-free decoration blueprints (loop=True, seamless period)
# ---------------------------------------------------------------------------


def _decor_wave_flow(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """波浪流动：三层半透明弧带交错起伏，闭环往返。"""

    lift = 3.0 + intensity * 2.0
    css = f"""
.band{{position:absolute;left:2%;right:2%;height:26%;border-radius:48%;opacity:.85}}
.b1{{bottom:4%;background:linear-gradient(180deg,transparent,{palette.primary}8c)}}
.b2{{bottom:22%;background:linear-gradient(180deg,transparent,{palette.secondary}66);opacity:.62}}
.b3{{bottom:40%;background:linear-gradient(180deg,transparent,{palette.paper}59);opacity:.5}}
"""
    body = (
        "<i class='band b1'></i><i class='band b2'></i><i class='band b3'></i>"
    )
    script = f"""
tl.to('.b1',{{y:'-{lift:.1f}%',duration:1.4,ease:'sine.inOut'}},0);
tl.to('.b1',{{y:'0%',duration:1.4,ease:'sine.inOut'}},1.4);
tl.to('.b2',{{y:'{lift * 0.7:.1f}%',duration:1.4,ease:'sine.inOut'}},0);
tl.to('.b2',{{y:'0%',duration:1.4,ease:'sine.inOut'}},1.4);
tl.to('.b3',{{y:'-{lift * 0.5:.1f}%',duration:1.4,ease:'sine.inOut'}},0);
tl.to('.b3',{{y:'0%',duration:1.4,ease:'sine.inOut'}},1.4);
"""
    return _document(css, body, script, 2.8), 2.8


def _decor_particle_drift(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """微光粒子：错落光点呼吸漂浮，闭环。"""

    drift = 2.5 + intensity * 2.5
    css = f"""
.dot{{position:absolute;border-radius:50%;background:radial-gradient(circle at 35% 35%,{palette.paper},{palette.primary});opacity:.9}}
.d1{{left:8%;top:16%;width:16%;aspect-ratio:1}}
.d2{{left:42%;top:52%;width:12%;aspect-ratio:1;opacity:.7}}
.d3{{left:68%;top:12%;width:20%;aspect-ratio:1;opacity:.8}}
.d4{{left:22%;top:66%;width:10%;aspect-ratio:1;opacity:.6}}
.d5{{left:76%;top:58%;width:14%;aspect-ratio:1;opacity:.75}}
"""
    body = "<i class='dot d1'></i><i class='dot d2'></i><i class='dot d3'></i><i class='dot d4'></i><i class='dot d5'></i>"
    script = f"""
tl.to('.d1,.d3,.d5',{{y:'-{drift:.1f}%',scale:1.1,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.d1,.d3,.d5',{{y:'0%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
tl.to('.d2,.d4',{{y:'{drift * 0.8:.1f}%',scale:.92,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.d2,.d4',{{y:'0%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
"""
    return _document(css, body, script, 3.0), 3.0


def _decor_orbit_rings(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """几何圆环：双环反向往返旋转 + 中心光点脉动，闭环。"""

    sweep = 30 + intensity * 60
    # Rings live in a square stage centred inside the (possibly
    # non-square) viewport: rotating an ellipse would swing its long
    # axis past the box edge and trip the edge-contact gate.
    css = f"""
.stage{{position:absolute;left:50%;top:50%;width:min(76vw,76vh);aspect-ratio:1;transform:translate(-50%,-50%)}}
.halo{{position:absolute;inset:10%;border-radius:50%;background:radial-gradient(circle,{palette.primary}47,{palette.secondary}1f 62%,transparent 76%)}}
.ring{{position:absolute;inset:6%;border-radius:50%;border:1.8vh solid transparent}}
.r1{{border-top-color:{palette.primary};border-right-color:{palette.primary}8c}}
.r2{{inset:24%;border-bottom-color:{palette.paper};border-left-color:{palette.paper}80}}
.core{{position:absolute;left:34%;top:34%;width:32%;aspect-ratio:1;border-radius:50%;background:radial-gradient(circle,{palette.paper},{palette.primary} 46%,{palette.secondary}00 78%)}}
"""
    body = "<div class='stage'><i class='halo'></i><i class='ring r1'></i><i class='ring r2'></i><i class='core'></i></div>"
    script = f"""
tl.to('.r1',{{rotate:{sweep:.0f},duration:1.6,ease:'sine.inOut'}},0);
tl.to('.r1',{{rotate:0,duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.r2',{{rotate:-{sweep * 0.75:.0f},duration:1.6,ease:'sine.inOut'}},0);
tl.to('.r2',{{rotate:0,duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.core',{{scale:1.16,duration:1.6,ease:'sine.inOut'}},0);
tl.to('.core',{{scale:1,duration:1.6,ease:'sine.inOut'}},1.6);
"""
    return _document(css, body, script, 3.2), 3.2


def _decor_cursor_ripple(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """软件教程点击反馈：CSS 光标、触点与两段闭环涟漪。"""

    travel = 1.04 + intensity * 0.05
    css = f"""
.stage{{position:absolute;inset:5%;display:flex;align-items:center;justify-content:center}}
.pulse{{position:absolute;width:56%;aspect-ratio:1;border-radius:50%;border:.045em solid {palette.primary};box-shadow:0 0 .32em {palette.primary}73;opacity:.88}}
.p2{{width:82%;opacity:.42}}
.point{{position:absolute;width:16%;aspect-ratio:1;border-radius:50%;background:{palette.paper};border:.05em solid {palette.ink};box-shadow:0 0 .28em {palette.primary}}}
.cursor{{position:absolute;left:54%;top:53%;width:28%;height:38%;background:{palette.paper};clip-path:polygon(0 0,0 88%,26% 66%,44% 100%,58% 92%,41% 60%,76% 60%);filter:drop-shadow(.06em .08em .08em #00000066);transform-origin:16% 14%}}
"""
    body = "<div class='stage'><i class='pulse p1'></i><i class='pulse p2'></i><i class='point'></i><i class='cursor'></i></div>"
    script = f"""
tl.fromTo('.p1',{{scale:.55,autoAlpha:.82}},{{scale:{travel:.2f},autoAlpha:.22,duration:.72,ease:'power2.out'}},0);
tl.to('.p1',{{scale:.55,autoAlpha:.82,duration:.72,ease:'power2.in'}},.72);
tl.fromTo('.p2',{{scale:.72,autoAlpha:.36}},{{scale:1.02,autoAlpha:.12,duration:.72,ease:'power2.out'}},0);
tl.to('.p2',{{scale:.72,autoAlpha:.36,duration:.72,ease:'power2.in'}},.72);
tl.to('.cursor',{{scale:.88,duration:.16,ease:'power2.in'}},.08);
tl.to('.cursor',{{scale:1,duration:.22,ease:'back.out(1.7)'}},.24);
tl.to('.cursor',{{scale:1,duration:.88,ease:'none'}},.46);
tl.to('.point',{{scale:1.16,duration:.72,ease:'sine.inOut'}},0);
tl.to('.point',{{scale:1,duration:.72,ease:'sine.inOut'}},.72);
"""
    return _document(css, body, script, 1.44, exit_style="soft_fade"), 1.44


def _decor_ambient_halo(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """软件产品镜头的克制景深：径向光晕、网格和扫描线闭环。"""

    alpha = int((0.16 + intensity * 0.10) * 255)
    css = f"""
.stage{{position:absolute;inset:4%;border-radius:18%;overflow:hidden;background:radial-gradient(circle at 50% 50%,{palette.primary}{alpha:02x},transparent 68%)}}
.grid{{position:absolute;inset:8%;background-image:linear-gradient({palette.paper}14 1px,transparent 1px),linear-gradient(90deg,{palette.paper}14 1px,transparent 1px);background-size:12% 12%;mask-image:radial-gradient(circle,#000 12%,transparent 72%)}}
.scan{{position:absolute;left:14%;right:14%;top:48%;height:.04em;background:linear-gradient(90deg,transparent,{palette.primary}8c,transparent);box-shadow:0 0 .35em {palette.primary}66}}
"""
    body = "<div class='stage'><i class='grid'></i><i class='scan'></i></div>"
    script = """
tl.to('.stage',{scale:1.035,opacity:.88,duration:1.6,ease:'sine.inOut'},0);
tl.to('.stage',{scale:1,opacity:1,duration:1.6,ease:'sine.inOut'},1.6);
tl.to('.scan',{y:'34%',opacity:.42,duration:1.6,ease:'sine.inOut'},0);
tl.to('.scan',{y:'0%',opacity:1,duration:1.6,ease:'sine.inOut'},1.6);
"""
    return _document(css, body, script, 3.2, exit_style="none"), 3.2


def _decor_bokeh_float(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """光斑漂浮：大柔和径向渐变圆垂直漂移+缩放呼吸，闭环。"""

    drift = 2.0 + intensity * 2.5
    css = f"""
.blob{{position:absolute;border-radius:50%;filter:blur(1.2vh)}}
.b1{{left:6%;top:10%;width:28%;aspect-ratio:1;background:radial-gradient(closest-side,{palette.primary}55,transparent 72%)}}
.b2{{left:52%;top:8%;width:22%;aspect-ratio:1;background:radial-gradient(closest-side,{palette.paper}44,transparent 70%)}}
.b3{{left:30%;top:50%;width:34%;aspect-ratio:1;background:radial-gradient(closest-side,{palette.secondary}3a,transparent 74%)}}
.b4{{left:68%;top:44%;width:18%;aspect-ratio:1;background:radial-gradient(closest-side,{palette.primary}40,transparent 68%)}}
.b5{{left:12%;top:62%;width:24%;aspect-ratio:1;background:radial-gradient(closest-side,{palette.paper}33,transparent 72%)}}
"""
    body = "<i class='blob b1'></i><i class='blob b2'></i><i class='blob b3'></i><i class='blob b4'></i><i class='blob b5'></i>"
    script = f"""
tl.to('.b1,.b3,.b5',{{y:'-{drift:.1f}%',scale:1.08,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.b1,.b3,.b5',{{y:'0%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
tl.to('.b2,.b4',{{y:'{drift * 0.7:.1f}%',scale:.94,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.b2,.b4',{{y:'0%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
"""
    return _document(css, body, script, 3.0), 3.0


def _decor_grid_pulse(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """网格脉动：细线网格+径向脉动遮罩，格点依次亮起，闭环。"""

    pulse = 0.3 + intensity * 0.4
    css = f"""
.grid{{position:absolute;inset:4%;background:repeating-linear-gradient(0deg,transparent,transparent 9.5%,{palette.primary}33 9.5%,{palette.primary}33 10%),repeating-linear-gradient(90deg,transparent,transparent 9.5%,{palette.primary}33 9.5%,{palette.primary}33 10%)}}
.pulse{{position:absolute;left:50%;top:50%;width:10%;aspect-ratio:1;border-radius:50%;transform:translate(-50%,-50%);background:radial-gradient(circle,{palette.primary}{int(pulse * 255):02x},transparent 72%)}}
"""
    body = "<i class='grid'></i><i class='pulse'></i>"
    script = """
tl.fromTo('.pulse',{scale:.3,autoAlpha:.7},{scale:4.5,autoAlpha:0,duration:1.5,ease:'power2.out'},0);
tl.fromTo('.pulse',{scale:.3,autoAlpha:.7},{scale:4.5,autoAlpha:0,duration:1.5,ease:'power2.out'},1.5);
"""
    return _document(css, body, script, 3.0), 3.0


def _decor_ink_splash(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """墨迹晕染：不规则色块缓慢变形+blur，有机感，闭环。"""

    morph = 10 + intensity * 15
    css = f"""
.blob{{position:absolute;filter:blur(1.5vh);opacity:.75}}
.b1{{left:8%;top:14%;width:30%;aspect-ratio:1;background:{palette.primary};border-radius:42% 58% 54% 46% / 48% 44% 56% 52%}}
.b2{{left:48%;top:10%;width:26%;aspect-ratio:1;background:{palette.secondary};border-radius:56% 44% 48% 52% / 42% 58% 42% 58%}}
.b3{{left:24%;top:52%;width:34%;aspect-ratio:1;background:{palette.paper};border-radius:48% 52% 58% 42% / 56% 46% 54% 44%;opacity:.5}}
"""
    body = (
        "<i class='blob b1'></i><i class='blob b2'></i><i class='blob b3'></i>"
    )
    script = f"""
tl.to('.b1',{{borderRadius:'{58 - morph * 0.3:.0f}% {42 + morph * 0.3:.0f}% {46 + morph * 0.2:.0f}% {54 - morph * 0.2:.0f}% / {52 - morph * 0.2:.0f}% {48 + morph * 0.2:.0f}% {44 + morph * 0.3:.0f}% {56 - morph * 0.3:.0f}%',scale:1.06,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.b1',{{borderRadius:'42% 58% 54% 46% / 48% 44% 56% 52%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
tl.to('.b2',{{borderRadius:'{44 + morph * 0.3:.0f}% {56 - morph * 0.3:.0f}% {52 + morph * 0.2:.0f}% {48 - morph * 0.2:.0f}% / {58 - morph * 0.2:.0f}% {42 + morph * 0.2:.0f}% {58 - morph * 0.3:.0f}% {42 + morph * 0.3:.0f}%',scale:.95,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.b2',{{borderRadius:'56% 44% 48% 52% / 42% 58% 42% 58%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
tl.to('.b3',{{borderRadius:'{52 - morph * 0.2:.0f}% {48 + morph * 0.2:.0f}% {42 + morph * 0.3:.0f}% {58 - morph * 0.3:.0f}% / {44 + morph * 0.3:.0f}% {56 - morph * 0.3:.0f}% {46 + morph * 0.2:.0f}% {54 - morph * 0.2:.0f}%',scale:1.04,duration:1.5,ease:'sine.inOut'}},0);
tl.to('.b3',{{borderRadius:'48% 52% 58% 42% / 56% 46% 54% 44%',scale:1,duration:1.5,ease:'sine.inOut'}},1.5);
"""
    return _document(css, body, script, 3.0), 3.0


def _decor_eq_bars(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """均衡律动：竖条不同高度 scaleY 振荡，音频可视化风格，闭环。"""

    peak = 0.5 + intensity * 0.5
    css = f"""
.bar{{position:absolute;bottom:6%;border-radius:.6vh .6vh 0 0;transform-origin:bottom center}}
.b1{{left:10%;width:6%;height:28%;background:{palette.primary}b3}}
.b2{{left:22%;width:6%;height:40%;background:{palette.primary}99}}
.b3{{left:34%;width:6%;height:22%;background:{palette.secondary}8c}}
.b4{{left:46%;width:6%;height:50%;background:{palette.primary}cc}}
.b5{{left:58%;width:6%;height:32%;background:{palette.secondary}99}}
.b6{{left:70%;width:6%;height:44%;background:{palette.primary}b3}}
.b7{{left:82%;width:6%;height:26%;background:{palette.secondary}80}}
"""
    body = (
        "<i class='bar b1'></i><i class='bar b2'></i><i class='bar b3'></i>"
        "<i class='bar b4'></i><i class='bar b5'></i><i class='bar b6'></i>"
        "<i class='bar b7'></i>"
    )
    script = f"""
tl.to('.b1',{{scaleY:{1 + peak * 0.6:.2f},duration:.38,ease:'sine.inOut'}},0);
tl.to('.b1',{{scaleY:1,duration:.38,ease:'sine.inOut'}},.38);
tl.to('.b1',{{scaleY:{1 + peak * 0.3:.2f},duration:.38,ease:'sine.inOut'}},.76);
tl.to('.b1',{{scaleY:1,duration:.38,ease:'sine.inOut'}},1.14);
tl.to('.b2',{{scaleY:{1 + peak * 0.8:.2f},duration:.32,ease:'sine.inOut'}},.1);
tl.to('.b2',{{scaleY:1,duration:.32,ease:'sine.inOut'}},.42);
tl.to('.b2',{{scaleY:{1 + peak * 0.5:.2f},duration:.32,ease:'sine.inOut'}},.74);
tl.to('.b2',{{scaleY:1,duration:.32,ease:'sine.inOut'}},1.06);
tl.to('.b3',{{scaleY:{1 + peak * 0.5:.2f},duration:.42,ease:'sine.inOut'}},.05);
tl.to('.b3',{{scaleY:1,duration:.42,ease:'sine.inOut'}},.47);
tl.to('.b3',{{scaleY:{1 + peak * 0.7:.2f},duration:.42,ease:'sine.inOut'}},.89);
tl.to('.b3',{{scaleY:1,duration:.42,ease:'sine.inOut'}},1.31);
tl.to('.b4',{{scaleY:{1 + peak:.2f},duration:.28,ease:'sine.inOut'}},.15);
tl.to('.b4',{{scaleY:1,duration:.28,ease:'sine.inOut'}},.43);
tl.to('.b4',{{scaleY:{1 + peak * 0.6:.2f},duration:.28,ease:'sine.inOut'}},.71);
tl.to('.b4',{{scaleY:1,duration:.28,ease:'sine.inOut'}},.99);
tl.to('.b5',{{scaleY:{1 + peak * 0.7:.2f},duration:.36,ease:'sine.inOut'}},.08);
tl.to('.b5',{{scaleY:1,duration:.36,ease:'sine.inOut'}},.44);
tl.to('.b5',{{scaleY:{1 + peak * 0.4:.2f},duration:.36,ease:'sine.inOut'}},.8);
tl.to('.b5',{{scaleY:1,duration:.36,ease:'sine.inOut'}},1.16);
tl.to('.b6',{{scaleY:{1 + peak * 0.9:.2f},duration:.3,ease:'sine.inOut'}},.12);
tl.to('.b6',{{scaleY:1,duration:.3,ease:'sine.inOut'}},.42);
tl.to('.b6',{{scaleY:{1 + peak * 0.5:.2f},duration:.3,ease:'sine.inOut'}},.72);
tl.to('.b6',{{scaleY:1,duration:.3,ease:'sine.inOut'}},1.02);
tl.to('.b7',{{scaleY:{1 + peak * 0.55:.2f},duration:.4,ease:'sine.inOut'}},.06);
tl.to('.b7',{{scaleY:1,duration:.4,ease:'sine.inOut'}},.46);
tl.to('.b7',{{scaleY:{1 + peak * 0.35:.2f},duration:.4,ease:'sine.inOut'}},.86);
tl.to('.b7',{{scaleY:1,duration:.4,ease:'sine.inOut'}},1.26);
"""
    return _document(css, body, script, 3.0), 3.0


def _decor_confetti_drift(
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """彩纸飘落：小型旋转矩形向下飘落+旋转，循环重置，闭环。"""

    fall = 30 + intensity * 30
    css = f"""
.bit{{position:absolute;width:3.2vh;height:1.4vh;border-radius:.3vh}}
.c1{{left:8%;top:-6%;background:{palette.primary};transform:rotate(18deg)}}
.c2{{left:24%;top:-10%;background:{palette.secondary};transform:rotate(-25deg)}}
.c3{{left:42%;top:-4%;background:{palette.paper};transform:rotate(35deg)}}
.c4{{left:58%;top:-12%;background:{palette.primary};transform:rotate(-12deg)}}
.c5{{left:72%;top:-8%;background:{palette.secondary};transform:rotate(42deg)}}
.c6{{left:86%;top:-5%;background:{palette.paper};transform:rotate(-30deg)}}
"""
    body = (
        "<i class='bit c1'></i><i class='bit c2'></i><i class='bit c3'></i>"
        "<i class='bit c4'></i><i class='bit c5'></i><i class='bit c6'></i>"
    )
    script = f"""
tl.to('.c1,.c3,.c5',{{y:'{fall:.0f}vh',rotate:'+=180',duration:1.5,ease:'none'}},0);
tl.set('.c1,.c3,.c5',{{y:'-{fall * 0.3:.0f}vh',rotate:'-=180'}},1.5);
tl.to('.c1,.c3,.c5',{{y:'0%',duration:0.01,ease:'none'}},1.5);
tl.to('.c2,.c4,.c6',{{y:'{fall:.0f}vh',rotate:'-=180',duration:1.5,ease:'none'}},0);
tl.set('.c2,.c4,.c6',{{y:'-{fall * 0.3:.0f}vh',rotate:'+=180'}},1.5);
tl.to('.c2,.c4,.c6',{{y:'0%',duration:0.01,ease:'none'}},1.5);
"""
    return _document(css, body, script, 3.0), 3.0


# ---------------------------------------------------------------------------
# Variety frame blueprints (loop=True, opaque border + transparent window)
# ---------------------------------------------------------------------------


def validated_frame_window(raw: object) -> dict[str, float]:
    """Clamp one normalized window rect for a frame blueprint.

    The window is the transparent hole the wrapped footage shows
    through, expressed as left/top/width/height fractions of the
    canvas. Borders thinner than ~2% would render sub-pixel at 720p,
    so the window is clamped to leave a real border on every side.
    """

    data = raw if isinstance(raw, Mapping) else {}
    width = _clamped(data.get("width"), 0.86, 0.40, 0.94)
    height = _clamped(data.get("height"), 0.80, 0.40, 0.94)
    left = _clamped(data.get("left"), (1.0 - width) / 2, 0.02, 0.56)
    top = _clamped(data.get("top"), (1.0 - height) / 2, 0.02, 0.56)
    width = min(width, 0.98 - left - 0.02)
    height = min(height, 0.98 - top - 0.02)
    return {"left": left, "top": top, "width": width, "height": height}


def _frame_geometry(window: Mapping[str, float]) -> str:
    """Shared strip/ring/corner CSS for one frame window rect.

    Four opaque strips tile everything outside the window; a rounded
    ring sits on the window edge and four small corner patches (in the
    strip base color, painted before the ring) fill the notches between
    the square strips and the ring's rounded corners.
    """

    left = window["left"] * 100
    top = window["top"] * 100
    width = window["width"] * 100
    height = window["height"] * 100
    right = 100 - left - width
    bottom = 100 - top - height
    return f"""
.strip{{position:absolute;overflow:hidden}}
.st{{left:0;right:0;top:0;height:{top:.2f}%}}
.sb{{left:0;right:0;bottom:0;height:{bottom:.2f}%}}
.sl{{left:0;top:{top:.2f}%;bottom:{bottom:.2f}%;width:{left:.2f}%}}
.sr{{right:0;top:{top:.2f}%;bottom:{bottom:.2f}%;width:{right:.2f}%}}
.patch{{position:absolute;width:3.2vh;height:3.2vh}}
.p1{{left:{left:.2f}%;top:{top:.2f}%}}
.p2{{right:{right:.2f}%;top:{top:.2f}%}}
.p3{{left:{left:.2f}%;bottom:{bottom:.2f}%}}
.p4{{right:{right:.2f}%;bottom:{bottom:.2f}%}}
.ring{{position:absolute;left:{left:.2f}%;top:{top:.2f}%;width:{width:.2f}%;height:{height:.2f}%;border-radius:2.6vh;box-sizing:border-box}}
.c{{position:absolute;width:4.6vh;height:4.6vh}}
.c1{{left:{left:.2f}%;top:{top:.2f}%;transform:translate(-46%,-46%)}}
.c2{{left:{left + width:.2f}%;top:{top:.2f}%;transform:translate(-54%,-46%)}}
.c3{{left:{left:.2f}%;top:{top + height:.2f}%;transform:translate(-46%,-54%)}}
.c4{{left:{left + width:.2f}%;top:{top + height:.2f}%;transform:translate(-54%,-54%)}}
"""


_FRAME_BODY = (
    "<i class='strip st'><i class='tex'></i></i>"
    "<i class='strip sb'><i class='tex'></i></i>"
    "<i class='strip sl'><i class='tex'></i></i>"
    "<i class='strip sr'><i class='tex'></i></i>"
    "<i class='patch p1'></i><i class='patch p2'></i>"
    "<i class='patch p3'></i><i class='patch p4'></i>"
    "<i class='ring'></i>"
    "<i class='c c1'></i><i class='c c2'></i>"
    "<i class='c c3'></i><i class='c c4'></i>"
)


def _frame_pop_variety(
    palette: BlueprintPalette,
    intensity: float,
    window: Mapping[str, float],
) -> tuple[str, float]:
    """综艺贴纸框：撞色渐变边框 + 波点纹理流动 + 四角星星贴纸律动，闭环。"""

    wiggle = 8 + intensity * 8
    css = (
        _frame_geometry(window)
        + f"""
.strip,.patch{{background:linear-gradient(135deg,{palette.primary},{palette.secondary})}}
.tex{{position:absolute;inset:-8vh;background-image:radial-gradient(circle,{palette.paper}59 1vh,transparent 1.15vh);background-size:4vh 4vh}}
.ring{{border:1.3vh solid {palette.paper};box-shadow:0 0 0 .5vh {palette.ink}33 inset}}
.c{{background:{palette.paper};clip-path:polygon(50% 0,62% 38%,100% 50%,62% 62%,50% 100%,38% 62%,0 50%,38% 38%);filter:drop-shadow(.3vh .4vh 0 {palette.ink}4d)}}
"""
    )
    script = f"""
tl.fromTo('.tex',{{x:'0vh',y:'0vh'}},{{x:'4vh',y:'4vh',duration:3.2,ease:'none'}},0);
tl.to('.c1,.c4',{{rotate:{wiggle:.0f},scale:1.12,duration:1.6,ease:'sine.inOut'}},0);
tl.to('.c1,.c4',{{rotate:0,scale:1,duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.c2,.c3',{{rotate:-{wiggle:.0f},scale:.92,duration:1.6,ease:'sine.inOut'}},0);
tl.to('.c2,.c3',{{rotate:0,scale:1,duration:1.6,ease:'sine.inOut'}},1.6);
"""
    return (
        _document(
            css,
            _FRAME_BODY,
            script,
            3.2,
            exit_style="none",
            full_bleed=True,
            frame_ring=True,
            frame_window=window,
        ),
        3.2,
    )


def _frame_warm_journal(
    palette: BlueprintPalette,
    intensity: float,
    window: Mapping[str, float],
) -> tuple[str, float]:
    """手账拍立得框：奶油纸边框 + 细纹纸理 + 角上胶带与光点呼吸，闭环。"""

    breath = 0.06 + intensity * 0.08
    css = (
        _frame_geometry(window)
        + f"""
.strip,.patch{{background:{palette.paper}}}
.tex{{position:absolute;inset:-8vh;background-image:repeating-linear-gradient(45deg,{palette.secondary}1f 0,{palette.secondary}1f .5vh,transparent .5vh,transparent 3vh)}}
.ring{{border:1.1vh solid #ffffff;box-shadow:0 .5vh 2.2vh {palette.ink}40,0 0 0 .35vh {palette.primary}59 inset}}
.c{{border-radius:50%;background:radial-gradient(circle at 35% 35%,#ffffff,{palette.primary})}}
.c2,.c3{{border-radius:.7vh;background:{palette.primary}b3;width:7vh;height:2.6vh}}
.c2{{transform:translate(-54%,-46%) rotate(-38deg)}}
.c3{{transform:translate(-46%,-54%) rotate(-38deg)}}
"""
    )
    script = f"""
tl.fromTo('.tex',{{x:'0vh',y:'0vh'}},{{x:'4.24vh',y:'4.24vh',duration:3.2,ease:'none'}},0);
tl.to('.c1,.c4',{{scale:{1 + breath:.2f},duration:1.6,ease:'sine.inOut'}},0);
tl.to('.c1,.c4',{{scale:1,duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.ring',{{boxShadow:'0 .7vh 2.6vh {palette.ink}4d,0 0 0 .35vh {palette.primary}73 inset',duration:1.6,ease:'sine.inOut'}},0);
tl.to('.ring',{{boxShadow:'0 .5vh 2.2vh {palette.ink}40,0 0 0 .35vh {palette.primary}59 inset',duration:1.6,ease:'sine.inOut'}},1.6);
"""
    return (
        _document(
            css,
            _FRAME_BODY,
            script,
            3.2,
            exit_style="none",
            full_bleed=True,
            frame_ring=True,
            frame_window=window,
        ),
        3.2,
    )


def _frame_kraft_paper(
    palette: BlueprintPalette,
    intensity: float,
    window: Mapping[str, float],
) -> tuple[str, float]:
    """牛皮纸框：棕色纸纹边框 + 遮盖胶带圆环 + 折角贴片，闭环。"""

    breath = 0.04 + intensity * 0.06
    css = (
        _frame_geometry(window)
        + f"""
.strip,.patch{{background:linear-gradient(180deg,#c8a882,#b8956a)}}
.tex{{position:absolute;inset:-8vh;background-image:repeating-linear-gradient(0deg,#a07850 0,#a07850 .3vh,transparent .3vh,transparent 2.2vh);opacity:.18}}
.ring{{border:1.4vh solid #d4b896;box-shadow:0 .4vh 1.6vh {palette.ink}33,inset 0 0 0 .3vh #c8a88266}}
.c{{background:#d4b896;border-radius:.6vh;width:5.4vh;height:2.2vh;box-shadow:0 .2vh .8vh {palette.ink}26}}
.c1{{transform:translate(-46%,-46%) rotate(-8deg)}}
.c2{{transform:translate(-54%,-46%) rotate(6deg)}}
.c3{{transform:translate(-46%,-54%) rotate(5deg)}}
.c4{{transform:translate(-54%,-54%) rotate(-7deg)}}
"""
    )
    script = f"""
tl.fromTo('.tex',{{x:'0vh',y:'0vh'}},{{x:'2.2vh',y:'0vh',duration:3.2,ease:'none'}},0);
tl.to('.c1,.c4',{{scale:{1 + breath:.2f},duration:1.6,ease:'sine.inOut'}},0);
tl.to('.c1,.c4',{{scale:1,duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.c2,.c3',{{scale:{1 + breath:.2f},duration:1.6,ease:'sine.inOut'}},.8);
tl.to('.c2,.c3',{{scale:1,duration:1.6,ease:'sine.inOut'}},2.4);
"""
    return (
        _document(
            css,
            _FRAME_BODY,
            script,
            3.2,
            exit_style="none",
            full_bleed=True,
            frame_ring=True,
            frame_window=window,
        ),
        3.2,
    )


def _frame_chalk_board(
    palette: BlueprintPalette,  # pylint: disable=unused-argument
    intensity: float,
    window: Mapping[str, float],
) -> tuple[str, float]:
    """黑板粉笔框：深炭色条 + 白色粉笔灰尘虚线环 + 粉笔痕角标，闭环。"""

    dust = 0.4 + intensity * 0.4
    css = (
        _frame_geometry(window)
        + f"""
.strip,.patch{{background:#2d3436}}
.tex{{position:absolute;inset:-8vh;background-image:radial-gradient(circle,#ffffff{int(dust * 30):02x} .4vh,transparent .5vh);background-size:3vh 3vh;opacity:.5}}
.ring{{border:.4vh dashed #ffffffcc;box-shadow:0 0 1.2vh #ffffff22 inset}}
.c{{background:transparent;border:.35vh solid #ffffffaa;width:3vh;height:3vh;border-radius:50%}}
.c2,.c3,.c4{{border-radius:.4vh;width:3.6vh;height:1.4vh;border:none;background:#ffffffaa}}
.c2{{transform:translate(-54%,-46%) rotate(-12deg)}}
.c3{{transform:translate(-46%,-54%) rotate(8deg)}}
.c4{{transform:translate(-54%,-54%) rotate(-5deg)}}
"""
    )
    script = """
tl.fromTo('.tex',{x:'0vh',y:'0vh'},{x:'3vh',y:'3vh',duration:3.2,ease:'none'},0);
tl.to('.ring',{opacity:.7,duration:1.6,ease:'sine.inOut'},0);
tl.to('.ring',{opacity:1,duration:1.6,ease:'sine.inOut'},1.6);
tl.to('.c1',{rotate:12,scale:1.1,duration:1.6,ease:'sine.inOut'},0);
tl.to('.c1',{rotate:0,scale:1,duration:1.6,ease:'sine.inOut'},1.6);
"""
    return (
        _document(
            css,
            _FRAME_BODY,
            script,
            3.2,
            exit_style="none",
            full_bleed=True,
            frame_ring=True,
            frame_window=window,
        ),
        3.2,
    )


def _frame_neon_glow(
    palette: BlueprintPalette,
    intensity: float,
    window: Mapping[str, float],
) -> tuple[str, float]:
    """霓虹灯框：暗底条 + primary 色霓虹发光环 + 发光角点，闭环。"""

    glow = 0.8 + intensity * 1.2
    css = (
        _frame_geometry(window)
        + f"""
.strip,.patch{{background:#0d0d1a}}
.tex{{position:absolute;inset:0;background:transparent}}
.ring{{border:.5vh solid {palette.primary};box-shadow:0 0 {glow:.1f}vh {palette.primary}88,0 0 {glow * 2:.1f}vh {palette.primary}44,inset 0 0 {glow * 0.6:.1f}vh {palette.primary}66}}
.c{{background:{palette.primary};border-radius:50%;width:2.4vh;height:2.4vh;box-shadow:0 0 {glow:.1f}vh {palette.primary},0 0 {glow * 2:.1f}vh {palette.primary}88}}
"""
    )
    script = f"""
tl.to('.ring',{{boxShadow:'0 0 {glow * 1.3:.1f}vh {palette.primary}aa,0 0 {glow * 2.6:.1f}vh {palette.primary}66,inset 0 0 {glow * 0.8:.1f}vh {palette.primary}88',duration:1.6,ease:'sine.inOut'}},0);
tl.to('.ring',{{boxShadow:'0 0 {glow:.1f}vh {palette.primary}88,0 0 {glow * 2:.1f}vh {palette.primary}44,inset 0 0 {glow * 0.6:.1f}vh {palette.primary}66',duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.c',{{scale:1.2,autoAlpha:.7,duration:1.6,ease:'sine.inOut'}},0);
tl.to('.c',{{scale:1,autoAlpha:1,duration:1.6,ease:'sine.inOut'}},1.6);
"""
    return (
        _document(
            css,
            _FRAME_BODY,
            script,
            3.2,
            exit_style="none",
            full_bleed=True,
            frame_ring=True,
            frame_window=window,
        ),
        3.2,
    )


def _frame_product_ui(
    palette: BlueprintPalette,
    intensity: float,
    window: Mapping[str, float],
) -> tuple[str, float]:
    """高端软件演示框：石墨舞台、浏览器状态点与克制环境光。"""

    glow = 0.12 + intensity * 0.12
    css = (
        _frame_geometry(window)
        + f"""
.strip,.patch{{background:#0b0f14}}
.tex{{position:absolute;inset:0;background:radial-gradient(circle at 25% 25%,{palette.primary}24,transparent 42%),radial-gradient(circle at 82% 74%,{palette.secondary}2b,transparent 38%)}}
.ring{{border:.22vh solid {palette.paper}38;box-shadow:0 1.4vh 5vh #00000073,0 0 {glow:.2f}em {palette.primary}24}}
.c{{width:1.5vh;height:1.5vh;border-radius:50%;background:{palette.paper}59}}
.c1{{background:#ff6b6b;transform:translate(-20%,-185%)}}
.c2{{background:#ffd166;transform:translate(-210%,-185%)}}
.c3{{background:{palette.primary};transform:translate(170%,-185%)}}
.c4{{width:7vh;height:.62vh;border-radius:99px;background:linear-gradient(90deg,{palette.primary},transparent);transform:translate(-70%,175%)}}
"""
    )
    script = f"""
tl.to('.tex',{{opacity:{0.78 + intensity * 0.12:.2f},duration:1.6,ease:'sine.inOut'}},0);
tl.to('.tex',{{opacity:1,duration:1.6,ease:'sine.inOut'}},1.6);
tl.to('.c3',{{boxShadow:'0 0 1.4vh {palette.primary}',scale:1.12,duration:1.6,ease:'sine.inOut'}},0);
tl.to('.c3',{{boxShadow:'0 0 0 {palette.primary}',scale:1,duration:1.6,ease:'sine.inOut'}},1.6);
"""
    return (
        _document(
            css,
            _FRAME_BODY,
            script,
            3.2,
            exit_style="none",
            full_bleed=True,
            frame_ring=True,
            frame_window=window,
        ),
        3.2,
    )


FRAME_BLUEPRINTS = {
    "pop_variety": _frame_pop_variety,
    "warm_journal": _frame_warm_journal,
    "kraft_paper": _frame_kraft_paper,
    "chalk_board": _frame_chalk_board,
    "neon_glow": _frame_neon_glow,
    "product_ui": _frame_product_ui,
}


def render_frame_blueprint(
    blueprint: str,
    *,
    palette: object = None,
    intensity: object = None,
    window: object = None,
) -> tuple[str, float]:
    """Render one variety frame blueprint; ``(html, period seconds)``.

    The frame is an opaque decorated border with a transparent window:
    burned over a footage segment (usually shrunk to the window rect via
    its Element location) it produces the variety-show "wrapped picture"
    composition without any pipeline change.
    """

    if blueprint not in FRAME_BLUEPRINTS:
        raise ValueError(f"unknown frame blueprint: {blueprint!r}")
    return FRAME_BLUEPRINTS[blueprint](
        validated_palette(palette),
        _clamped(intensity, 0.55, 0.0, 1.0),
        validated_frame_window(window),
    )


CAPTION_BLUEPRINTS = {
    "stagger_pop": _caption_stagger_pop,
    "ink_reveal": _caption_ink_reveal,
    "glow_breath": _caption_glow_breath,
    "static_capsule": _caption_static_capsule,
    "precision_subtitle": _caption_precision_subtitle,
    "editorial_title": _caption_editorial_title,
    "chapter_label": _caption_chapter_label,
    "handwritten_note": _caption_handwritten_note,
    "keyword_spotlight": _caption_keyword_spotlight,
    "drama_whisper": _caption_drama_whisper,
    "neon_pulse": _caption_neon_pulse,
    "brush_strike": _caption_brush_strike,
}
DECORATION_BLUEPRINTS = {
    "wave_flow": _decor_wave_flow,
    "particle_drift": _decor_particle_drift,
    "orbit_rings": _decor_orbit_rings,
    "cursor_ripple": _decor_cursor_ripple,
    "ambient_halo": _decor_ambient_halo,
    "bokeh_float": _decor_bokeh_float,
    "grid_pulse": _decor_grid_pulse,
    "ink_splash": _decor_ink_splash,
    "eq_bars": _decor_eq_bars,
    "confetti_drift": _decor_confetti_drift,
}
# Deterministic rotation order for the caption fallback chain.
CAPTION_BLUEPRINT_ORDER = ("stagger_pop", "ink_reveal", "glow_breath")

_BLUEPRINT_HINTS = {
    "stagger_pop": "综艺花字：逐字弹入+强调下划线，适合活泼/惊喜/动作场面",
    "ink_reveal": "电影字幕：横向揭示+侧色条，适合叙事/沉稳/收尾语气",
    "glow_breath": "情绪光晕：发光呼吸+星芒点缀，适合治愈/夜景/抒情",
    "static_capsule": "静态胶囊：固定字号白底深字零动画，适合解说/教学/纪录片逐句字幕",
    "precision_subtitle": "精密字幕：玻璃石墨底+状态点+进度线，适合软件教程/产品演示",
    "editorial_title": "编辑标题：左对齐 waterfall 字组+短标尺，适合产品片开场/收束",
    "chapter_label": "章节元数据：单行窄边标签+方向性推进，适合软件教程步骤编号",
    "handwritten_note": "手写笔记：纸纹底板+手写体微倾斜+墨水划线，适合Vlog/日常/手账",
    "keyword_spotlight": "关键词聚焦：左对齐+关键词高亮色块滑入，适合教学/知识/重点强调",
    "drama_whisper": "低语独白：宋体大字宽字距+逐字淡入模糊，适合短剧/情感/文艺",
    "neon_pulse": "霓虹脉冲：暗底+亮色文字多层glow呼吸+霓虹描边，适合音乐/MV/夜间",
    "brush_strike": "墨笔横扫：粗体字clip-path横扫揭示+对角线扫过，适合动作/高燃/通用",
    "wave_flow": "波浪流动：多层弧带起伏，适合水面/舒缓/自然场景",
    "particle_drift": "微光粒子：光点漂浮呼吸，适合梦幻/温柔/光斑画面",
    "orbit_rings": "几何圆环：双环旋转+光核脉动，适合科技/聚焦/节奏点",
    "cursor_ripple": "光标点击：CSS 光标+触点+闭环涟漪，适合软件教程真实动作",
    "ambient_halo": "环境光晕：径向柔光+细网格+扫描线，适合产品镜头景深",
    "bokeh_float": "光斑漂浮：大柔和径向渐变圆漂移+缩放呼吸，适合Vlog/日常/唯美",
    "grid_pulse": "网格脉动：细线网格+径向脉动遮罩，适合教学/科技/结构化",
    "ink_splash": "墨迹晕染：不规则色块缓慢变形+blur，适合短剧/情感/艺术",
    "eq_bars": "均衡律动：竖条不同高度scaleY振荡，适合音乐/MV/节奏",
    "confetti_drift": "彩纸飘落：小型旋转矩形向下飘落+旋转，适合庆祝/欢快/通用",
    "pop_variety": "综艺贴纸框：撞色波点边框+四角星星贴纸，适合活泼/高光/搞笑时刻",
    "warm_journal": "手账拍立得框：奶油纸边框+胶带贴角，适合温馨/家庭/治愈时刻",
    "kraft_paper": "牛皮纸框：棕色纸纹边框+遮盖胶带圆环，适合Vlog/日常/复古",
    "chalk_board": "黑板粉笔框：深炭色条+白色粉笔灰尘虚线环，适合教学/知识/校园",
    "neon_glow": "霓虹灯框：暗底条+霓虹发光环+发光角点，适合音乐/MV/夜间",
    "product_ui": "产品界面框：石墨舞台+浏览器状态点+克制环境光，适合软件教程",
}


def blueprint_catalog_text(
    kind: str,
    *,
    content_type: str | None = None,
) -> str:
    """Prompt-ready catalog listing for one blueprint family.

    When *content_type* is given the listing is filtered to the preferred
    subset for that type (4-6 entries); otherwise every registered
    blueprint is listed (backward-compatible).
    """

    if content_type and content_type in _CONTENT_TYPE_PALETTES:
        prefs = _CONTENT_TYPE_PALETTES[content_type]
        if kind == "caption":
            names = prefs["caption_order"]
        else:
            names = prefs["decoration_catalog"]
    else:
        names = (
            CAPTION_BLUEPRINT_ORDER
            if kind == "caption"
            else tuple(DECORATION_BLUEPRINTS)
        )
    return "\n".join(f"- {name}: {_BLUEPRINT_HINTS[name]}" for name in names)


def render_caption_blueprint(
    blueprint: str,
    text: str,
    *,
    palette: object = None,
    intensity: object = None,
    box_width: float | None = None,
    box_height: float | None = None,
) -> tuple[str, float]:
    """Render one caption card blueprint; returns ``(html, hf duration)``."""

    if blueprint not in CAPTION_BLUEPRINTS:
        raise ValueError(f"unknown caption blueprint: {blueprint!r}")
    if not text.strip():
        raise ValueError("caption blueprint requires non-empty text")
    return CAPTION_BLUEPRINTS[blueprint](
        text,
        validated_palette(palette),
        _clamped(intensity, 0.55, 0.0, 1.0),
        box_width=box_width,
        box_height=box_height,
    )


# Latin runs allowed inside otherwise-Chinese teaching copy: standard
# math function names that legitimately appear in derivations.
_MATH_LATIN_TOKENS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "log",
        "ln",
        "lim",
        "exp",
        "sqrt",
        "abs",
        "max",
        "min",
        "mod",
    },
)
_LATIN_RUN = re.compile(r"[A-Za-z]{3,}")


def require_chinese_copy(value: str, slot: str) -> str:
    """Reject teaching copy that drifted into English.

    Single-letter variables (x, y) and math function names pass; any
    other run of 3+ latin letters ("PREVIOUS", "Step") is a language
    drift and fails closed so it can never reach the final cut.
    """

    for run in _LATIN_RUN.findall(value):
        if run.lower() not in _MATH_LATIN_TOKENS:
            raise ValueError(
                f"教学卡文案必须使用中文：{slot} 中出现了英文词「{run}」",
            )
    return value.strip()


def _scene_edu_step_card(
    content: Mapping[str, object],
    palette: BlueprintPalette,
) -> tuple[str, float]:
    """教学推导卡：确定性全屏场景骨架，内容只填槽位。

    蒸馏自 edu-agent 的 Aurora Scholar 设计系统：满屏淡雅渐变背景（无
    外边距，天然满足 coverage 守卫）+ 实心白板 + 步骤徽章 + 上一步
    回顾条 + 推导行 + 结果高亮框；所有固定标签（“上一步”“得到”）写死
    在模板里，VLM 只产内容文案，英文漂移在槽位校验处 fail-closed。
    底部 18% 为字幕保留区。
    """

    del palette  # Aurora Scholar 自带固定配色，不随主题漂移
    badge = require_chinese_copy(str(content.get("badge") or ""), "badge")
    title = require_chinese_copy(str(content.get("title") or ""), "title")
    previous = require_chinese_copy(
        str(content.get("previous") or ""),
        "previous",
    )
    operation = require_chinese_copy(
        str(content.get("operation") or ""),
        "operation",
    )
    raw_lines = content.get("lines") or []
    if not isinstance(raw_lines, (list, tuple)):
        raise ValueError("lines 必须是字符串列表")
    lines = [
        require_chinese_copy(str(line), f"lines[{index}]")
        for index, line in enumerate(raw_lines)
        if str(line).strip()
    ]
    result = require_chinese_copy(str(content.get("result") or ""), "result")
    if not (title or lines or result):
        raise ValueError("教学卡至少需要 title、lines 或 result 之一")

    parts: list[str] = []
    if badge:
        parts.append(f"<div class='badge'>{escape(badge)}</div>")
    if title:
        parts.append(f"<div class='title'>{escape(title)}</div>")
    if previous:
        parts.append(
            "<div class='prev'><span class='prev-tag'>上一步</span>"
            f"<span class='prev-math math'>{escape(previous)}</span></div>",
        )
    if operation:
        parts.append(f"<div class='op'>{escape(operation)}</div>")
    if lines:
        rows = "".join(
            f"<div class='row'><i class='dot'>{index + 1}</i>"
            f"<span class='math'>{escape(line)}</span></div>"
            for index, line in enumerate(lines)
        )
        parts.append(f"<div class='rows'>{rows}</div>")
    if result:
        parts.append(
            "<div class='result'><span class='result-tag'>得到</span>"
            f"<span class='result-math math'>{escape(result)}</span></div>",
        )
    css = """
html,body{width:100%;height:100%;margin:0;overflow:hidden}
.stage{position:absolute;inset:0;background:linear-gradient(160deg,#f8fafc 0%,#eef2ff 55%,#e0e7ff 100%);font-family:"PingFang SC","Noto Sans SC",sans-serif}
.aurora{position:absolute;border-radius:50%;filter:blur(2vh)}
.a1{left:-6%;top:-10%;width:44%;height:44%;background:radial-gradient(closest-side,rgba(99,102,241,.18),transparent 72%)}
.a2{right:-8%;bottom:6%;width:52%;height:52%;background:radial-gradient(closest-side,rgba(6,182,212,.14),transparent 74%)}
.panel{position:absolute;left:8%;right:8%;top:7%;bottom:20%;background:#ffffff;border:.35vh solid rgba(99,102,241,.28);border-top:.55vh solid rgba(99,102,241,.24);border-radius:2.6vh;box-shadow:0 .6vh 2.4vh rgba(99,102,241,.08),0 2.4vh 7vh rgba(99,102,241,.12);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2.6vh;padding:3.5vh 5vw}
.badge{padding:1.1vh 3.2vh;border-radius:99px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-weight:700;font-size:3.4vh;letter-spacing:.08em}
.title{font-weight:700;font-size:6.4vh;color:#0f172a}
.prev{display:flex;align-items:center;gap:1.6vh;padding:1.2vh 2.6vh;border-radius:1.6vh;background:#f1f5f9;color:#64748b;font-size:3.4vh}
.prev-tag{font-size:2.6vh;color:#94a3b8}
.op{padding:1.2vh 2.8vh;border-radius:1.6vh;border:.25vh solid rgba(99,102,241,.35);color:#6366f1;font-weight:600;font-size:3.2vh}
.rows{display:flex;flex-direction:column;gap:1.8vh;align-items:flex-start}
.row{display:flex;align-items:center;gap:1.8vh}
.dot{width:4.6vh;height:4.6vh;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-style:normal;font-weight:700;font-size:2.6vh;display:flex;align-items:center;justify-content:center;flex:none}
.math{font-family:Georgia,"Times New Roman","Songti SC",serif;font-size:5vh;color:#0f172a;letter-spacing:.04em}
.result{display:flex;align-items:center;gap:1.8vh;padding:1.6vh 3.2vh;border-radius:1.8vh;background:#ecfdf5;border:.3vh solid rgba(16,185,129,.5)}
.result-tag{font-size:2.8vh;color:#059669;font-weight:600}
.result-math{font-size:6vh;color:#047857;font-weight:700}
"""
    body = (
        "<div class='stage'><i class='aurora a1'></i><i class='aurora a2'></i>"
        f"<div class='panel'>{''.join(parts)}</div></div>"
    )
    script = """
tl.fromTo('.stage',{autoAlpha:.6},{autoAlpha:1,duration:.4,ease:'power1.out'},0);
tl.fromTo('.panel',{autoAlpha:.4,y:'2.4%'},{autoAlpha:1,y:'0%',duration:.6,ease:'power3.out'},0);
tl.fromTo('.badge',{autoAlpha:.4,scale:.85},{autoAlpha:1,scale:1,duration:.5,ease:'back.out(1.4)'},.15);
tl.fromTo('.prev,.op,.title',{autoAlpha:.35,y:'12%'},{autoAlpha:1,y:'0%',duration:.5,stagger:.12,ease:'power3.out'},.25);
tl.fromTo('.row',{autoAlpha:.3,x:'-2%'},{autoAlpha:1,x:'0%',duration:.5,stagger:.18,ease:'power3.out'},.45);
tl.fromTo('.result',{autoAlpha:.35,scale:.94},{autoAlpha:1,scale:1,duration:.6,ease:'back.out(1.4)'},1.0);
"""
    return (
        _document(css, body, script, 2.2, exit_style="none", full_bleed=True),
        2.2,
    )


def _scene_lyric_card(
    content: Mapping[str, object],
    palette: BlueprintPalette,
) -> tuple[str, float]:
    """歌词卡：暗色渐变全屏+大字歌词+发光+歌曲标题角标，适合 MV 间奏。"""

    lyric = require_chinese_copy(str(content.get("lyric") or ""), "lyric")
    title = require_chinese_copy(str(content.get("title") or ""), "title")
    if not lyric:
        raise ValueError("歌词卡至少需要 lyric 文案")

    parts = [f"<div class='lyric'>{escape(lyric)}</div>"]
    if title:
        parts.insert(0, f"<div class='badge'>{escape(title)}</div>")

    css = f"""
html,body{{width:100%;height:100%;margin:0;overflow:hidden}}
.stage{{position:absolute;inset:0;background:linear-gradient(160deg,{palette.secondary},{palette.ink});font-family:"PingFang SC","Songti SC",serif;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3vh}}
.glow{{position:absolute;left:30%;top:20%;width:40%;aspect-ratio:1;border-radius:50%;background:radial-gradient(closest-side,{palette.primary}33,transparent 72%);filter:blur(2vh)}}
.badge{{padding:1vh 2.8vh;border-radius:99px;border:.2vh solid {palette.primary}8c;color:{palette.primary};font-size:2.8vh;font-weight:600;letter-spacing:.06em}}
.lyric{{position:relative;text-align:center;font-size:7vh;font-weight:700;color:{palette.paper};text-shadow:0 0 .3em {palette.primary}88,0 0 .8em {palette.primary}44;line-height:1.4;padding:0 8%;max-width:90%}}
"""
    body = "<div class='stage'><i class='glow'></i>" f"{''.join(parts)}</div>"
    script = f"""
tl.fromTo('.stage',{{autoAlpha:.5}},{{autoAlpha:1,duration:.5,ease:'power1.out'}},0);
tl.fromTo('.lyric',{{autoAlpha:.3,y:'4%',scale:.97}},{{autoAlpha:1,y:'0%',scale:1,duration:.7,ease:'power2.out'}},.1);
tl.fromTo('.badge',{{autoAlpha:.3,scale:.9}},{{autoAlpha:1,scale:1,duration:.5,ease:'back.out(1.3)'}},.2);
tl.to('.lyric',{{textShadow:'0 0 .4em {palette.primary}aa,0 0 1.2em {palette.primary}66',duration:1.0,ease:'sine.inOut'}},.8);
tl.to('.lyric',{{textShadow:'0 0 .3em {palette.primary}88,0 0 .8em {palette.primary}44',duration:1.0,ease:'sine.inOut'}},1.8);
"""
    return (
        _document(
            css,
            body,
            script,
            2.8,
            exit_style="soft_fade",
            full_bleed=True,
        ),
        2.8,
    )


def _scene_comparison_card(
    content: Mapping[str, object],
    palette: BlueprintPalette,  # pylint: disable=unused-argument
) -> tuple[str, float]:
    """对比推导卡：左右分栏+标签+箭头+底部结果高亮，适合教学对比。"""

    left_label = require_chinese_copy(
        str(content.get("left_label") or ""),
        "left_label",
    )
    right_label = require_chinese_copy(
        str(content.get("right_label") or ""),
        "right_label",
    )
    left_text = require_chinese_copy(
        str(content.get("left_text") or ""),
        "left_text",
    )
    right_text = require_chinese_copy(
        str(content.get("right_text") or ""),
        "right_text",
    )
    result = require_chinese_copy(str(content.get("result") or ""), "result")
    if not (left_text and right_text):
        raise ValueError("对比卡需要 left_text 和 right_text")

    css = """
html,body{width:100%;height:100%;margin:0;overflow:hidden}
.stage{position:absolute;inset:0;background:linear-gradient(160deg,#f8fafc 0%,#eef2ff 55%,#e0e7ff 100%);font-family:"PingFang SC","Noto Sans SC",sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2.4vh}
.row{display:flex;align-items:stretch;gap:3vw;width:86%}
.panel{flex:1;display:flex;flex-direction:column;align-items:center;gap:1.4vh;padding:3vh 3vw;background:#ffffff;border-radius:2vh;border:.3vh solid rgba(99,102,241,.2);box-shadow:0 .4vh 1.6vh rgba(99,102,241,.08)}
.label{padding:.8vh 2.4vh;border-radius:99px;font-size:2.8vh;font-weight:700;letter-spacing:.04em}
.l-label{background:#fee2e2;color:#dc2626}
.r-label{background:#dcfce7;color:#16a34a}
.body{font-family:Georgia,"Times New Roman","Songti SC",serif;font-size:5vh;color:#0f172a;text-align:center;line-height:1.4}
.arrow{font-size:5vh;color:#6366f1;flex:none;display:flex;align-items:center}
.result{padding:1.4vh 3vh;border-radius:1.6vh;background:#ecfdf5;border:.3vh solid rgba(16,185,129,.5);font-size:4.4vh;color:#047857;font-weight:700}
"""
    body = (
        "<div class='stage'>"
        "<div class='row'>"
        f"<div class='panel'><div class='label l-label'>{escape(left_label or '前')}</div>"
        f"<div class='body'>{escape(left_text)}</div></div>"
        "<div class='arrow'>→</div>"
        f"<div class='panel'><div class='label r-label'>{escape(right_label or '后')}</div>"
        f"<div class='body'>{escape(right_text)}</div></div>"
        "</div>"
    )
    if result:
        body += f"<div class='result'>{escape(result)}</div>"
    body += "</div>"

    script = """
tl.fromTo('.stage',{autoAlpha:.5},{autoAlpha:1,duration:.4,ease:'power1.out'},0);
tl.fromTo('.panel',{autoAlpha:.3,y:'3%'},{autoAlpha:1,y:'0%',duration:.5,stagger:.15,ease:'power3.out'},.1);
tl.fromTo('.arrow',{autoAlpha:.3,scale:.7},{autoAlpha:1,scale:1,duration:.4,ease:'back.out(1.4)'},.3);
tl.fromTo('.result',{autoAlpha:.35,scale:.94},{autoAlpha:1,scale:1,duration:.5,ease:'back.out(1.4)'},.8);
"""
    return (
        _document(css, body, script, 2.2, exit_style="none", full_bleed=True),
        2.2,
    )


SCENE_BLUEPRINTS = {
    "edu_step_card": _scene_edu_step_card,
    "lyric_card": _scene_lyric_card,
    "comparison_card": _scene_comparison_card,
}


def render_scene_blueprint(
    blueprint: str,
    content: Mapping[str, object],
    *,
    palette: object = None,
) -> tuple[str, float]:
    """Render one full-canvas scene blueprint; ``(html, hf duration)``.

    Scene blueprints are the caption-blueprint philosophy applied to the
    segment picture itself: the skeleton (layout, colors, fixed Chinese
    labels, choreography) is deterministic code and the model only
    supplies content slots, so styling can never drift per segment.
    """

    if blueprint not in SCENE_BLUEPRINTS:
        raise ValueError(f"unknown scene blueprint: {blueprint!r}")
    return SCENE_BLUEPRINTS[blueprint](content, validated_palette(palette))


def render_decoration_blueprint(
    blueprint: str,
    *,
    palette: object = None,
    intensity: object = None,
) -> tuple[str, float]:
    """Render one looping decoration blueprint; ``(html, period seconds)``."""

    if blueprint not in DECORATION_BLUEPRINTS:
        raise ValueError(f"unknown decoration blueprint: {blueprint!r}")
    return DECORATION_BLUEPRINTS[blueprint](
        validated_palette(palette),
        _clamped(intensity, 0.55, 0.0, 1.0),
    )


# ---------------------------------------------------------------------------
# Content-type aware effect matching
# ---------------------------------------------------------------------------

CONTENT_TYPES = (
    "tutorial",
    "short_drama",
    "interview",
    "pets",
    "gaming",
    "sports",
    "travel",
    "general",
)

_CONTENT_TYPE_PALETTES: dict[str, dict[str, object]] = {
    "tutorial": {
        "caption_order": (
            "precision_subtitle",
            "editorial_title",
            "chapter_label",
            "keyword_spotlight",
            "ink_reveal",
        ),
        "decoration_catalog": (
            "cursor_ripple",
            "ambient_halo",
            "grid_pulse",
        ),
        "frame": "product_ui",
        "transitions": ("slideleft", "slideright", "zoomin", "fade"),
        # Literal UI colors must remain exact; polish belongs outside the
        # captured pixels, not in a global grade.
        "color_grade": "",
        "palette": {
            "primary": "#3fb950",
            "secondary": "#2f81f7",
            "ink": "#0b0f14",
            "paper": "#f0f6fc",
        },
    },
    "short_drama": {
        "caption_order": (
            "ink_reveal",
            "drama_whisper",
            "glow_breath",
            "brush_strike",
        ),
        "decoration_catalog": ("ink_splash", "particle_drift", "bokeh_float"),
        "frame": "warm_journal",
        "transitions": ("fade", "fadeblack", "fadewhite", "dissolve"),
        "color_grade": "ink_wash",
        "palette": {
            "primary": "#e99e88",
            "secondary": "#8a6f60",
            "ink": "#55473d",
            "paper": "#fffaf2",
        },
    },
    "interview": {
        "caption_order": ("static_capsule", "keyword_spotlight", "ink_reveal"),
        "decoration_catalog": ("particle_drift", "grid_pulse", "wave_flow"),
        "frame": "chalk_board",
        "transitions": ("fade", "fadeblack", "slideleft", "horzopen"),
        "color_grade": "clean_cool",
        "palette": {
            "primary": "#4a90d9",
            "secondary": "#2c3e50",
            "ink": "#1a1a2e",
            "paper": "#f5f7fa",
        },
    },
    "pets": {
        "caption_order": ("handwritten_note", "stagger_pop", "glow_breath"),
        "decoration_catalog": (
            "bokeh_float",
            "confetti_drift",
            "particle_drift",
            "wave_flow",
        ),
        "frame": "kraft_paper",
        "transitions": ("fade", "wipeleft", "wiperight", "circleopen"),
        "color_grade": "vlog_fresh",
        "palette": {
            "primary": "#ff9a2f",
            "secondary": "#5a3d1f",
            "ink": "#231f1a",
            "paper": "#fff8df",
        },
    },
    "gaming": {
        "caption_order": ("neon_pulse", "brush_strike", "stagger_pop"),
        "decoration_catalog": (
            "eq_bars",
            "orbit_rings",
            "grid_pulse",
            "confetti_drift",
        ),
        "frame": "neon_glow",
        "transitions": ("fade", "pixelize", "circleclose", "radial", "zoomin"),
        "color_grade": "neon_vivid",
        "palette": {
            "primary": "#70f0dc",
            "secondary": "#3a3560",
            "ink": "#171527",
            "paper": "#f8f5ff",
        },
    },
    "sports": {
        "caption_order": ("brush_strike", "stagger_pop", "keyword_spotlight"),
        "decoration_catalog": ("orbit_rings", "eq_bars", "confetti_drift"),
        "frame": "pop_variety",
        "transitions": (
            "fade",
            "wipeleft",
            "slideright",
            "circleopen",
            "zoomin",
        ),
        "color_grade": "warm_bright",
        "palette": {
            "primary": "#e63946",
            "secondary": "#1d3557",
            "ink": "#0d1b2a",
            "paper": "#f1faee",
        },
    },
    "travel": {
        "caption_order": ("handwritten_note", "glow_breath", "stagger_pop"),
        "decoration_catalog": (
            "bokeh_float",
            "wave_flow",
            "particle_drift",
            "confetti_drift",
        ),
        "frame": "kraft_paper",
        "transitions": (
            "fade",
            "wipeleft",
            "wiperight",
            "dissolve",
            "circleopen",
        ),
        "color_grade": "vlog_fresh",
        "palette": {
            "primary": "#2ec4b6",
            "secondary": "#cbf3f0",
            "ink": "#1a535c",
            "paper": "#ffefe8",
        },
    },
    "general": {
        "caption_order": (
            "stagger_pop",
            "ink_reveal",
            "glow_breath",
            "static_capsule",
        ),
        "decoration_catalog": (
            "particle_drift",
            "wave_flow",
            "orbit_rings",
            "bokeh_float",
        ),
        "frame": "pop_variety",
        "transitions": ("fade", "fadeblack", "dissolve", "wipeleft"),
        "color_grade": "warm_bright",
        "palette": {
            "primary": "#ffb35c",
            "secondary": "#2a2622",
            "ink": "#241f1b",
            "paper": "#fff8ec",
        },
    },
}


def suggested_transitions_for_content(content_type: str) -> tuple[str, ...]:
    """Preferred transition palette for a content type."""

    prefs = _CONTENT_TYPE_PALETTES.get(content_type)
    if prefs:
        return tuple(prefs["transitions"])  # type: ignore[arg-type]
    return ("fade", "fadeblack", "dissolve")


def suggested_color_grade(content_type: str) -> str:
    """Default color grade preset for a content type."""

    prefs = _CONTENT_TYPE_PALETTES.get(content_type)
    if prefs:
        return str(prefs["color_grade"])
    return ""


def content_type_palette(content_type: str) -> BlueprintPalette | None:
    """Default palette for a content type, or None if unknown."""

    prefs = _CONTENT_TYPE_PALETTES.get(content_type)
    if not prefs:
        return None
    raw = prefs["palette"]
    if not isinstance(raw, dict):
        return None
    return BlueprintPalette(
        primary=_color(raw.get("primary"), "#ffb35c"),
        secondary=_color(raw.get("secondary"), "#2a2622"),
        ink=_color(raw.get("ink"), "#241f1b"),
        paper=_color(raw.get("paper"), "#fff8ec"),
    )


def content_type_frame(content_type: str) -> str:
    """Default frame blueprint for a content type."""

    prefs = _CONTENT_TYPE_PALETTES.get(content_type)
    if prefs:
        return str(prefs["frame"])
    return "pop_variety"


def content_type_caption_order(content_type: str) -> tuple[str, ...]:
    """Caption blueprint fallback rotation for a content type."""

    prefs = _CONTENT_TYPE_PALETTES.get(content_type)
    if prefs:
        return tuple(prefs["caption_order"])  # type: ignore[arg-type]
    return CAPTION_BLUEPRINT_ORDER


__all__ = [
    "BLUEPRINT_VERSION",
    "CAPTION_BLUEPRINTS",
    "CAPTION_BLUEPRINT_ORDER",
    "CONTENT_TYPES",
    "DECORATION_BLUEPRINTS",
    "FRAME_BLUEPRINTS",
    "SCENE_BLUEPRINTS",
    "BlueprintPalette",
    "blueprint_catalog_text",
    "content_type_caption_order",
    "content_type_frame",
    "content_type_palette",
    "render_caption_blueprint",
    "render_decoration_blueprint",
    "render_frame_blueprint",
    "render_scene_blueprint",
    "require_chinese_copy",
    "suggested_color_grade",
    "suggested_transitions_for_content",
    "validated_frame_window",
    "validated_palette",
]
