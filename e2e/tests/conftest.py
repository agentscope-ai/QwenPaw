# -*- coding: utf-8 -*-
"""
Tests-level conftest: session-scoped seed data for E2E tests.

Ensures a test skill exists before any skill-related test runs.
This is necessary because a clean (isolated) backend starts with
no skills in the workspace directory.
"""
from __future__ import annotations

import logging
import pytest

logger = logging.getLogger(__name__)

_SEED_SKILL_NAME = "_e2e_seed_skill"
_SEED_SKILL_CONTENT = """\
---
name: E2E Seed Skill
description: Auto-created by E2E framework for testing.
---

Placeholder skill for E2E tests.
"""


@pytest.fixture(scope="session", autouse=True)
def seed_test_skill(api_context):
    """Ensure at least one skill exists so list/filter/toggle tests pass."""
    try:
        resp = api_context.get("/api/skills")
        if resp.ok and len(resp.json()) > 0:
            logger.info("Skills already present, skipping seed")
            yield
            return
    except Exception as exc:
        logger.warning(f"Skills list check failed ({exc}), attempting seed anyway")

    created = False
    try:
        resp = api_context.post(
            "/api/skills",
            data={"name": _SEED_SKILL_NAME, "content": _SEED_SKILL_CONTENT, "enable": True},
        )
        if resp.ok:
            logger.info(f"Seed skill '{_SEED_SKILL_NAME}' created")
            created = True
        else:
            logger.warning(f"Seed skill creation returned {resp.status}")
    except Exception as exc:
        logger.warning(f"Seed skill creation failed: {exc}")

    yield

    if created:
        try:
            api_context.delete(f"/api/skills/{_SEED_SKILL_NAME}")
            logger.info(f"Seed skill '{_SEED_SKILL_NAME}' cleaned up")
        except Exception:
            pass
