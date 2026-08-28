# -*- coding: utf-8 -*-
"""Tests for startup-sensitive provider import boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib import import_module


def test_provider_manager_does_not_import_unused_sdk_modules() -> None:
    code = """
import json
import sys

import qwenpaw.providers.provider_manager

names = ("anthropic", "google.genai", "openai", "agentscope.model")
print(json.dumps([name for name in names if name in sys.modules]))
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def test_package_exports_remain_available_after_lazy_loading() -> None:
    local_models = import_module("qwenpaw.local_models")
    providers = import_module("qwenpaw.providers")

    assert providers.Provider.__name__ == "Provider"
    assert providers.ProviderManager.__name__ == "ProviderManager"
    assert local_models.LocalModelManager.__name__ == "LocalModelManager"
    assert local_models.ModelManager.__name__ == "ModelManager"
