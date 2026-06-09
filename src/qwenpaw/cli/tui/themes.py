# -*- coding: utf-8 -*-
"""Fun terminal theme gallery for QwenPaw."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeInfo:
    id: str
    name: str
    emoji: str
    prompt: str
    screen: str
    prompt_bg: str
    chrome: str
    accent: str
    text: str = "#f4fff8"

    @property
    def palette(self) -> tuple[str, str, str]:
        return self.screen, self.prompt_bg, self.chrome


THEME_GALLERY: tuple[ThemeInfo, ...] = (
    ThemeInfo(
        "original",
        "Original",
        "🐾",
        "original",
        # Warm, dark take on QwenPaw's console palette (brand orange #ff7f16).
        "#1d1308",
        "#2c1d0e",
        "#5a3614",
        "#ff7f16",
    ),
    ThemeInfo(
        "funky",
        "Funky Paw Rave",
        "🪩",
        "funky neon paw party",
        "#23153d",
        "#351f57",
        "#53218a",
        "#ff7ad9",
    ),
    ThemeInfo(
        "cyberpunk",
        "Cyberpunk Alley",
        "⚡",
        "cyberpunk tiger-paw alley with laser rain",
        "#071b2c",
        "#101f3c",
        "#163857",
        "#00f5ff",
    ),
    ThemeInfo(
        "greek",
        "Oracle Marble",
        "🏛️",
        "greek roman marble oracle courtyard",
        "#1f2330",
        "#2b3140",
        "#3d4660",
        "#f4d58d",
    ),
    ThemeInfo(
        "zen",
        "Zen Matcha",
        "🍵",
        "quiet zen garden with matcha glow",
        "#14251d",
        "#1c3428",
        "#274a37",
        "#a9f0b6",
    ),
    ThemeInfo(
        "medieval",
        "Medieval Quest",
        "🛡️",
        "middle age quest tavern with warm torchlight",
        "#281b19",
        "#38261f",
        "#563722",
        "#ffb86b",
    ),
    ThemeInfo(
        "jurassic",
        "Jurassic Ferns",
        "🦖",
        "jurassic park rainforest terminal",
        "#10261f",
        "#17382c",
        "#1d523d",
        "#7cff6b",
    ),
    ThemeInfo(
        "space",
        "Space Alien",
        "👽",
        "space alien mothership with cute paw console",
        "#081525",
        "#121a39",
        "#1f295a",
        "#9d8cff",
    ),
    ThemeInfo(
        "mars",
        "Mars Invader",
        "🛸",
        "mars invader arcade red planet",
        "#251111",
        "#3a1818",
        "#5c241e",
        "#ff6d4d",
    ),
    ThemeInfo(
        "ocean",
        "Deep Sea Synth",
        "🐚",
        "deep sea synthwave coral reef",
        "#071e24",
        "#0d2e36",
        "#134751",
        "#55e6c1",
    ),
)


def find_theme(value: str) -> ThemeInfo | None:
    needle = value.strip().casefold()
    if not needle:
        return None
    for theme in THEME_GALLERY:
        if needle in {theme.id.casefold(), theme.name.casefold()}:
            return theme
    return None


def _resolve_theme(prompt: str) -> ThemeInfo:
    """Map any prompt to a theme: an exact match, else a stable hash pick."""
    theme = find_theme(prompt)
    if theme is not None:
        return theme
    index = sum(ord(ch) for ch in prompt) % len(THEME_GALLERY)
    return THEME_GALLERY[index]


def palette_for_prompt(prompt: str) -> tuple[str, str, str]:
    return _resolve_theme(prompt).palette


def accent_for_prompt(prompt: str) -> str:
    """The theme's bright accent — used to colour the welcome logo."""
    return _resolve_theme(prompt).accent


def mix_hex(left: str, right: str, amount: float) -> str:
    """Blend two ``#rrggbb`` colours; ``amount`` is the weight of ``right``."""

    def channels(value: str) -> tuple[int, int, int]:
        cleaned = value.removeprefix("#")
        return (
            int(cleaned[0:2], 16),
            int(cleaned[2:4], 16),
            int(cleaned[4:6], 16),
        )

    left_rgb = channels(left)
    right_rgb = channels(right)
    mixed = tuple(
        round(a + (b - a) * amount) for a, b in zip(left_rgb, right_rgb)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed)
