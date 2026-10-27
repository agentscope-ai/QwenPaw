# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,redefined-builtin
"""Trusted deterministic templates for common decorative motion motifs."""

from __future__ import annotations

from html import escape
import math
import re
import unicodedata

MOTION_TEMPLATE_VERSION = 1
CAPTION_TEMPLATE_VERSION = 2
DEFAULT_CAPTION_LOCATION = {
    "x": 0.5,
    "y": 0.86,
    "width": 0.8,
    "height": 0.18,
    "anchor_x": 0.5,
    "anchor_y": 0.5,
}
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

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text.lower() if _HEX_COLOR.fullmatch(text) else fallback


def _caption_font_css(
    text: str,
    box_width: float | None,
    box_height: float | None,
) -> str:
    """Keep normal copy at one canvas-relative size and fit longer lines."""
    widths = [
        sum(
            1.0 if unicodedata.east_asian_width(char) in "WF" else 0.55
            for char in line
        )
        for line in text.splitlines()
        if line.strip()
    ] or [1.0]
    rows = [max(1, math.ceil(width / 24)) for width in widths]
    per_line = max(width / count for width, count in zip(widths, rows))
    width = box_width if box_width and box_width > 0 else 0.8
    height = box_height if box_height and box_height > 0 else 0.18
    return (
        f"min({4 / height:.3f}vh,{4.5 / width:.3f}vw,"
        f"{80 / (sum(rows) * 1.35):.3f}vh,{88 / max(1, per_line):.3f}vw)"
    )


def render_caption_template(
    text: str,
    *,
    theme: str = "comic_patrol",
    emotion: str = "chill",
    box_width: float | None = None,
    box_height: float | None = None,
) -> str:
    """Render plain subtitles, also used when an authored design fails.

    Legacy theme/emotion arguments remain accepted without changing the
    typography. The only motion is a brief opacity fade; glyphs stay still.
    """
    del theme, emotion
    safe_text = "<br>".join(escape(line) for line in text.strip().splitlines())
    font = _caption_font_css(text, box_width, box_height)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
html,body{{width:100%;height:100%;margin:0;background:transparent;overflow:hidden}}
*{{box-sizing:border-box}}
.stage{{position:absolute;inset:6%;display:flex;align-items:center;justify-content:center}}
.words{{width:100%;margin:0;color:#fff;font-family:"Noto Sans CJK SC","Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;font-size:{font};font-weight:600;line-height:1.35;text-align:center;word-break:normal;overflow-wrap:break-word;text-wrap:balance;text-shadow:0 .025em .05em #000d,0 .04em .14em #000b;animation:appear .14s linear both}}
@keyframes appear{{from{{opacity:.72}}to{{opacity:1}}}}
</style></head><body><div class="stage" data-motion-template-version="{CAPTION_TEMPLATE_VERSION}" data-motion-motif="caption_card" data-caption-style="plain" data-motion-exit="none"><div class="words">{safe_text}</div></div></body></html>"""


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
    "MOTION_TEMPLATE_VERSION",
    "SUPPORTED_EMOTIONS",
    "SUPPORTED_ENTRANCES",
    "SUPPORTED_EXITS",
    "SUPPORTED_MOTIFS",
    "SUPPORTED_THEMES",
    "SUPPORTED_VARIANTS",
    "render_decoration_template",
]
