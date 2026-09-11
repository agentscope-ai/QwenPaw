# -*- coding: utf-8 -*-
"""Materialize the Browser SDK reference into packaged skill marker blocks."""

from pathlib import Path

from qwenpaw.browser.sdk.facade import _build_manual_text


BEGIN = "<!-- BEGIN GENERATED: browser-manual -->"
END = "<!-- END GENERATED: browser-manual -->"
ROOT = Path(__file__).resolve().parents[1]
SKILLS = [
    ROOT / "src/qwenpaw/agents/skills/browser-en/SKILL.md",
    ROOT / "src/qwenpaw/agents/skills/browser-zh/SKILL.md",
]


def inject(path: Path, manual: str) -> None:
    """Replace exactly one generated manual block in a packaged skill."""
    text = path.read_text(encoding="utf-8")
    head, begin, rest = text.partition(BEGIN)
    _old, end, tail = rest.partition(END)
    if not begin or not end:
        raise SystemExit(f"markers missing in {path}")
    block = f"{BEGIN}\n{manual.strip()}\n{END}"
    path.write_text(f"{head}{block}{tail}", encoding="utf-8")


def main() -> None:
    """Write the same generated reference into each browser skill."""
    manual = _build_manual_text()
    for skill in SKILLS:
        inject(skill, manual)
        print(f"updated {skill}")


if __name__ == "__main__":
    main()
