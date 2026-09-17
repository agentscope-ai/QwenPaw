# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_sensitive_and_generated_paths_are_excluded_from_image_context():
    rules = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required = {
        "tmp",
        "data",
        "logs",
        "*.dump",
        "*.bak",
        "playwright-report",
        "test-results",
        "docs/superpowers",
    }
    assert required.issubset(rules)


def test_production_environment_file_is_ignored_by_git():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/deploy/.env" in rules


def test_public_deployment_guide_uses_external_brand_only():
    guide = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    assert "WeldonAgent" in guide
    assert "QwenPaw" not in guide
    assert "CoPaw" not in guide
