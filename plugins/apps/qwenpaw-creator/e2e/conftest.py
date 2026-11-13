# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-outer-name,use-sequence-for-iteration
# pylint: disable=wrong-import-position

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest


E2E_DIR = Path(__file__).resolve().parent
if str(E2E_DIR) not in sys.path:
    sys.path.insert(0, str(E2E_DIR))

import config as e2e_config  # noqa: E402
from utils.api_client import CreatorApiClient  # noqa: E402


@pytest.fixture(scope="session")
def base_url() -> str:
    return e2e_config.BASE_URL


@pytest.fixture(scope="session")
def api(base_url: str) -> CreatorApiClient:
    return CreatorApiClient(base_url)


@pytest.fixture(scope="session", autouse=True)
def require_services(api: CreatorApiClient):
    if not api.health_ok(timeout=30):
        message = (
            f"Creator 服务未就绪：{e2e_config.BASE_URL}{e2e_config.API_PREFIX}/health。"
            "请先启动当前 backend 与 Vite UI。"
        )
        if e2e_config.STRICT:
            pytest.fail(message)
        pytest.skip(message, allow_module_level=True)
    yield


@pytest.fixture()
def project(api: CreatorApiClient):
    created = api.create_project(f"Timeline Element E2E {uuid4().hex[:8]}")
    try:
        yield created
    finally:
        api.delete_project(created["projectId"])


@pytest.fixture()
def browser_context_args(browser_context_args, base_url):
    # Mark every onboarding tour as done: the tour mask intercepts pointer
    # events and would break real interaction-driven assertions.
    onboarding = (
        '{"homeTourDone":true,"projectTourDone":true,'
        '"assetsTourDone":true,"hints":{}}'
    )
    return {
        **browser_context_args,
        "viewport": {"width": 1440, "height": 1000},
        "base_url": base_url,
        "storage_state": {
            "cookies": [],
            "origins": [
                {
                    "origin": base_url,
                    "localStorage": [
                        {
                            "name": "qwenpaw-creator:onboarding:v2",
                            "value": onboarding,
                        },
                    ],
                },
            ],
        },
    }
