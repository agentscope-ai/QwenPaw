#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2: Validate a skill directory's SKILL.md against the required schema.

Usage:
    python validate_skill.py <skill_dir>
    python validate_skill.py /path/to/active_skills/xlsx

Exit codes:
    0 — valid
    1 — validation failed
    2 — file not found or parse error
"""
import json
import re
import sys
from pathlib import Path

# Required frontmatter fields and their basic types
# Based on universal skill standard: name + description required
# CoPaw extensions (triggers, metadata) are optional
REQUIRED_FIELDS = {
    "name": str,
    "description": str,
}

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def parse_frontmatter(skill_md: Path) -> dict | None:
    """Extract YAML-like frontmatter from SKILL.md between --- delimiters."""
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return None

    try:
        import yaml
        fm_text = "\n".join(lines[1:end])
        return yaml.safe_load(fm_text) or {}
    except Exception:
        pass

    # Fallback: naive key: value parser (no nested)
    result = {}
    for line in lines[1:end]:
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def validate(skill_dir: Path) -> list[str]:
    """Return list of error strings. Empty list = valid."""
    errors = []
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        return [f"SKILL.md not found in {skill_dir}"]

    fm = parse_frontmatter(skill_md)
    if fm is None:
        return ["SKILL.md has no valid frontmatter (missing --- delimiters)"]

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in fm:
            errors.append(f"Missing required field: '{field}'")
        elif not isinstance(fm[field], expected_type):
            errors.append(
                f"Field '{field}' should be {expected_type.__name__}, "
                f"got {type(fm[field]).__name__}"
            )

    # Optional field format checks
    if "metadata" in fm and isinstance(fm.get("metadata"), dict):
        copaw = fm["metadata"].get("copaw", {})
        version = fm["metadata"].get("builtin_skill_version", "")
        if version and not re.match(r"^\d+\.\d+", str(version)):
            errors.append(f"metadata.builtin_skill_version format invalid: '{version}'")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_skill.py <skill_dir>", file=sys.stderr)
        sys.exit(2)

    skill_dir = Path(sys.argv[1]).resolve()
    if not skill_dir.is_dir():
        print(f"Error: '{skill_dir}' is not a directory", file=sys.stderr)
        sys.exit(2)

    errors = validate(skill_dir)
    if errors:
        print(f"[FAIL] {skill_dir.name}:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"[OK] {skill_dir.name}: SKILL.md is valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
