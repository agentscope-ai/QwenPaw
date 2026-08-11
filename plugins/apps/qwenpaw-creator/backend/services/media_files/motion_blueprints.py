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
    full_bleed: bool = False,
    frame_ring: bool = False,
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


def _caption_static_capsule(
    text: str,
    palette: BlueprintPalette,
    intensity: float,
) -> tuple[str, float]:
    """静态胶囊：全片像素级一致的解说/教学字幕。

    对齐 hyperframes 的 caption-bar 做法：字号固定（不随文本长度
    缩放，长句靠 max-width 换行），胶囊宽度随内容伸缩，零入场装饰
    ——仅整卡一次短淡入后保持静止，任意时刻采样都是同一幅末态；
    退场硬切（exit none），避免逐句字幕交接处前后两卡淡变叠影。
    """

    del intensity  # 静态模板没有可调幅度，保持签名一致即可
    css = f"""
.wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.card{{width:max-content;max-width:94%;box-sizing:border-box;font-size:24vh;padding:.28em .9em;border-radius:.42em;background:{palette.paper}f2;border:.04em solid {palette.ink}26;box-shadow:0 .08em .3em {palette.ink}33}}
.text{{font-family:"PingFang SC","Noto Sans SC",sans-serif;font-weight:600;font-size:1em;line-height:1.35;letter-spacing:.02em;text-align:center;color:{palette.ink}}}
"""
    body = f"<div class='wrap'><div class='card'><div class='text'>{escape(text.strip())}</div></div></div>"
    script = """
tl.fromTo('.card',{autoAlpha:.35},{autoAlpha:1,duration:.3,ease:'power1.out'},0);
tl.to('.card',{autoAlpha:1,duration:.1},.3);
"""
    return _document(css, body, script, 0.4, exit_style="none"), 0.4


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
        ),
        3.2,
    )


FRAME_BLUEPRINTS = {
    "pop_variety": _frame_pop_variety,
    "warm_journal": _frame_warm_journal,
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
    "static_capsule": "静态胶囊：固定字号白底深字零动画，适合解说/教学/纪录片逐句字幕",
    "wave_flow": "波浪流动：多层弧带起伏，适合水面/舒缓/自然场景",
    "particle_drift": "微光粒子：光点漂浮呼吸，适合梦幻/温柔/光斑画面",
    "orbit_rings": "几何圆环：双环旋转+光核脉动，适合科技/聚焦/节奏点",
    "pop_variety": "综艺贴纸框：撞色波点边框+四角星星贴纸，适合活泼/高光/搞笑时刻",
    "warm_journal": "手账拍立得框：奶油纸边框+胶带贴角，适合温馨/家庭/治愈时刻",
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


SCENE_BLUEPRINTS = {
    "edu_step_card": _scene_edu_step_card,
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


__all__ = [
    "BLUEPRINT_VERSION",
    "CAPTION_BLUEPRINTS",
    "CAPTION_BLUEPRINT_ORDER",
    "DECORATION_BLUEPRINTS",
    "FRAME_BLUEPRINTS",
    "SCENE_BLUEPRINTS",
    "BlueprintPalette",
    "blueprint_catalog_text",
    "render_caption_blueprint",
    "render_decoration_blueprint",
    "render_frame_blueprint",
    "render_scene_blueprint",
    "require_chinese_copy",
    "validated_frame_window",
    "validated_palette",
]
