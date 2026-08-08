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


def _chars(text: str) -> str:
    """Wrap every visible character for per-character staggers."""

    pieces: list[str] = []
    for char in text.strip():
        if char.isspace():
            pieces.append("<i class='sp'>&nbsp;</i>")
        else:
            pieces.append(f"<b class='ch'>{escape(char)}</b>")
    return "".join(pieces)


def _caption_font_css(text: str) -> str:
    """Two-axis font clamp for one caption viewport.

    The document only knows its own viewport, so the size is expressed
    as ``min(vh, vw)``: the vh term keeps line stacks inside flat boxes,
    the vw term keeps the longest line inside narrow boxes. Every
    decorative measure in the blueprints is em-based so the whole card
    scales with this value no matter how extreme the box ratio is.
    """

    length = max(1, len(re.sub(r"\s+", "", text)))
    per_line = length if length <= 12 else math.ceil(length / 2)
    lines = 1 if length <= 12 else 2
    # CJK glyphs are roughly square. Width budget: glyph run plus the
    # widest card chrome (≈1.9em of padding/side accents) inside 80% of
    # the viewport. Height budget: the tallest card stack (line-height
    # plus vertical padding, gap and rule ≈2.4em per line) inside 76%,
    # leaving the root 8% inset and entrance travel untouched.
    vw = 80.0 / (per_line * 1.08 + 1.9)
    vh = 76.0 / (lines * 2.4)
    return f"min({vh:.1f}vh,{vw:.1f}vw)"


def _document(
    css: str,
    body: str,
    script: str,
    duration: float,
    *,
    exit_style: str = "soft_fade",
) -> str:
    register = _HF_REGISTER.replace("%DUR%", f"{duration:.3f}")
    # data-motion-exit hands the ending to the renderer-managed exit (an
    # alpha fade over the last 15% of the output window): cards and
    # decorations leave gracefully instead of hard-cutting, while the
    # timeline itself keeps a fully visible final state for the probes.
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><style>\n'
        f"{_BASE_CSS}\n{css}\n</style></head>"
        f'<body><div id="root" data-motion-exit="{exit_style}">{body}</div>\n'
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
) -> tuple[str, float]:
    """综艺花字：内容包裹式贴纸胶囊 + 逐字弹入 + 强调下划线。"""

    overshoot = 1.3 + intensity * 0.6
    font = _caption_font_css(text)
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


def _caption_ink_reveal(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """电影字幕：大字直压画面 + 细描边投影保可读 + 侧色条 draw-on，
    无满框底板，仅文字底部一条包裹式半透明 scrim 融入画面。"""

    reveal = 0.55 + intensity * 0.25
    font = _caption_font_css(text)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{display:flex;align-items:center;gap:.42em;max-width:96%;font-size:{font};padding:.22em .6em;border-radius:.3em;background:color-mix(in srgb,{palette.ink} 42%,transparent)}}
.bar{{width:.14em;height:1.15em;border-radius:99px;background:{palette.primary};transform-origin:top;flex:none}}
.text{{font-family:"PingFang SC","Songti SC",serif;font-weight:700;font-size:1em;line-height:1.32;letter-spacing:.06em;color:{palette.paper};text-shadow:0 .04em .12em {palette.ink},0 0 .5em {palette.ink}b3}}
"""
    body = f"<div class='wrap'><div class='card'><div class='bar'></div><div class='text'>{escape(text.strip())}</div></div></div>"
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
) -> tuple[str, float]:
    """情绪光晕：无底板，文字发光呼吸直压画面，背后一团包裹式柔光晕，
    两侧星芒点缀随字号缩放。"""

    glow = 0.12 + intensity * 0.14
    font = _caption_font_css(text)
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{position:relative;display:flex;align-items:center;gap:.34em;max-width:96%;font-size:{font};padding:.3em .55em}}
.halo{{position:absolute;inset:-8% -4%;border-radius:50%;background:radial-gradient(closest-side,{palette.ink}80,transparent 78%)}}
.text{{position:relative;text-align:center;font-family:"PingFang SC",sans-serif;font-weight:800;font-size:1em;line-height:1.3;color:{palette.paper};text-shadow:0 0 {glow:.2f}em {palette.primary},0 0 {glow * 2.4:.2f}em {palette.primary}99,0 .05em .14em {palette.ink}}}
.spark{{position:relative;width:.34em;height:.34em;flex:none;background:{palette.primary};clip-path:polygon(50% 0,62% 38%,100% 50%,62% 62%,50% 100%,38% 62%,0 50%,38% 38%)}}
"""
    body = f"<div class='wrap'><div class='card'><i class='halo'></i><i class='spark'></i><div class='text'>{escape(text.strip())}</div><i class='spark'></i></div></div>"
    script = """
tl.fromTo('.card',{autoAlpha:.42,scale:.965},{autoAlpha:1,scale:1,duration:.7,ease:'power2.out'},0);
tl.fromTo('.spark',{autoAlpha:.35,scale:.5,rotate:-40},{autoAlpha:1,scale:1,rotate:0,duration:.6,stagger:.18,ease:'back.out(1.6)'},.1);
tl.to('.text',{scale:1.015,duration:1.1,ease:'sine.inOut'},.8);
tl.to('.text',{scale:1,duration:1.1,ease:'sine.inOut'},1.9);
tl.to('.spark',{rotate:18,duration:2.2,ease:'sine.inOut'},.8);
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


CAPTION_BLUEPRINTS = {
    "stagger_pop": _caption_stagger_pop,
    "ink_reveal": _caption_ink_reveal,
    "glow_breath": _caption_glow_breath,
}
DECORATION_BLUEPRINTS = {
    "wave_flow": _decor_wave_flow,
    "particle_drift": _decor_particle_drift,
    "orbit_rings": _decor_orbit_rings,
}
# Deterministic rotation order for the caption fallback chain.
CAPTION_BLUEPRINT_ORDER = ("stagger_pop", "ink_reveal", "glow_breath")

_BLUEPRINT_HINTS = {
    "stagger_pop": "综艺花字：逐字弹入+强调下划线，适合活泼/惊喜/动作场面",
    "ink_reveal": "电影字幕：横向揭示+侧色条，适合叙事/沉稳/收尾语气",
    "glow_breath": "情绪光晕：发光呼吸+星芒点缀，适合治愈/夜景/抒情",
    "wave_flow": "波浪流动：多层弧带起伏，适合水面/舒缓/自然场景",
    "particle_drift": "微光粒子：光点漂浮呼吸，适合梦幻/温柔/光斑画面",
    "orbit_rings": "几何圆环：双环旋转+光核脉动，适合科技/聚焦/节奏点",
}


def blueprint_catalog_text(kind: str) -> str:
    """Prompt-ready catalog listing for one blueprint family."""

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
    )


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


__all__ = [
    "BLUEPRINT_VERSION",
    "CAPTION_BLUEPRINTS",
    "CAPTION_BLUEPRINT_ORDER",
    "DECORATION_BLUEPRINTS",
    "BlueprintPalette",
    "blueprint_catalog_text",
    "render_caption_blueprint",
    "render_decoration_blueprint",
    "validated_palette",
]
