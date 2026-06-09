# -*- coding: utf-8 -*-
"""
Tests-level conftest: session-scoped seed data for E2E tests.

Ensures a test skill exists before any skill-related test runs.
This is necessary because a clean (isolated) backend starts with
no skills in the workspace directory.
"""
from __future__ import annotations

import logging
import os
import pytest

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = os.getenv("QWENPAW_MODEL_PROVIDER", "dashscope")
_DEFAULT_MODEL = os.getenv("QWENPAW_DEFAULT_MODEL", "qwen3.6-plus")

_SEED_FILE_NAME = "_e2e_test_note.md"
_SEED_FILE_CONTENT = "# E2E Test Note\n\nThis file was created by the E2E test framework.\n"

_SEED_SKILL_NAME = "_e2e_seed_skill"
_SEED_SKILL_CONTENT = """\
---
name: E2E Seed Skill
description: Auto-created by E2E framework for testing.
---

Placeholder skill for E2E tests.
"""


@pytest.fixture(scope="session", autouse=True)
def setup_default_model(api_context):
    """Configure provider API key and set a global default model when QWENPAW_DASHSCOPE_API_KEY is set."""
    model_key = os.getenv("QWENPAW_DASHSCOPE_API_KEY")
    if not model_key:
        logger.info("QWENPAW_DASHSCOPE_API_KEY not set, skipping model setup")
        yield
        return

    provider = _DEFAULT_PROVIDER
    model = _DEFAULT_MODEL

    try:
        resp = api_context.put(
            f"/api/models/{provider}/config",
            data={"api_key": model_key},
        )
        if resp.ok:
            logger.info(f"Provider '{provider}' configured with API key")
        else:
            logger.warning(f"Provider config returned {resp.status}: {resp.text()}")
    except Exception as exc:
        logger.warning(f"Provider config failed: {exc}")

    try:
        resp = api_context.put(
            "/api/models/active",
            data={"provider_id": provider, "model": model, "scope": "global"},
        )
        if resp.ok:
            logger.info(f"Global model set to {provider}/{model}")
        elif resp.status == 400 and "MODEL_NOT_FOUND" in resp.text():
            logger.info(f"Model '{model}' not in built-in list, adding as extra model")
            add_resp = api_context.post(
                f"/api/models/{provider}/models",
                data={"id": model, "name": model},
            )
            if add_resp.ok:
                logger.info(f"Extra model '{model}' added to {provider}")
                resp = api_context.put(
                    "/api/models/active",
                    data={"provider_id": provider, "model": model, "scope": "global"},
                )
                if resp.ok:
                    logger.info(f"Global model set to {provider}/{model}")
                else:
                    logger.warning(f"Set active model returned {resp.status}: {resp.text()}")
            else:
                logger.warning(f"Add extra model returned {add_resp.status}: {add_resp.text()}")
        else:
            logger.warning(f"Set active model returned {resp.status}: {resp.text()}")
    except Exception as exc:
        logger.warning(f"Set active model failed: {exc}")

    yield


@pytest.fixture(scope="session", autouse=True)
def seed_workspace_file(api_context):
    """Ensure at least one workspace file exists so file list/edit/toggle tests pass."""
    try:
        resp = api_context.get("/api/workspace/files")
        if resp.ok and len(resp.json()) > 0:
            logger.info("Workspace files already present, skipping seed")
            yield
            return
    except Exception as exc:
        logger.warning(f"Workspace files check failed ({exc}), attempting seed anyway")

    created = False
    try:
        resp = api_context.put(
            f"/api/workspace/files/{_SEED_FILE_NAME}",
            data={"content": _SEED_FILE_CONTENT},
        )
        if resp.ok:
            logger.info(f"Seed workspace file '{_SEED_FILE_NAME}' created")
            created = True
        else:
            logger.warning(f"Seed file creation returned {resp.status}: {resp.text()}")
    except Exception as exc:
        logger.warning(f"Seed file creation failed: {exc}")

    yield


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
