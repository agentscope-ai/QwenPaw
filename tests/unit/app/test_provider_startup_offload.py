# -*- coding: utf-8 -*-
"""Tests for provider initialization during application startup."""

import importlib
import threading
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

import qwenpaw.backup._utils.safe_swap as safe_swap_module


@pytest.mark.asyncio
async def test_lifespan_initializes_provider_manager_in_worker_thread(
    monkeypatch,
) -> None:
    """Provider scanning must not run on the event-loop thread."""
    monkeypatch.setattr(safe_swap_module, "restore_process_lock", _nullcontext)
    app_module_name = "qwenpaw.app._app"
    previous_app_module = __import__("sys").modules.get(app_module_name)
    app_module = importlib.import_module(app_module_name)
    caller_thread = threading.get_ident()
    initialization_threads = []

    def get_instance():
        initialization_threads.append(threading.get_ident())
        raise RuntimeError("provider initialized")

    monkeypatch.setattr(
        app_module.ProviderManager,
        "get_instance",
        get_instance,
    )
    monkeypatch.setattr(
        app_module,
        "add_project_file_handler",
        lambda _path: None,
    )
    monkeypatch.setattr(
        app_module,
        "cleanup_startup_restore_artifacts",
        lambda: None,
    )
    monkeypatch.setattr(app_module, "auto_register_from_env", lambda: None)
    monkeypatch.setattr(
        app_module,
        "check_proxy_config_sanity",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "migrate_legacy_workspace_to_default_agent",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "ensure_default_agent_exists",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "migrate_legacy_skills_to_skill_pool",
        lambda: None,
        monkeypatch.setattr(
            app_module,
            "_sync_scroll_history_on_startup",
            AsyncMock(),
        ),
    )
    monkeypatch.setattr(app_module, "ensure_qa_agent_exists", lambda: None)

    try:
        with pytest.raises(RuntimeError, match="provider initialized"):
            async with app_module.lifespan(FastAPI()):
                pass
    finally:
        modules = __import__("sys").modules
        if previous_app_module is None:
            modules.pop(app_module_name, None)
        else:
            modules[app_module_name] = previous_app_module

    assert len(initialization_threads) == 1
    assert initialization_threads[0] != caller_thread


@pytest.mark.asyncio
async def test_lifespan_initializes_local_model_manager_in_worker_thread(
    monkeypatch,
) -> None:
    """Local model config loading must not run on the event-loop thread."""
    monkeypatch.setattr(safe_swap_module, "restore_process_lock", _nullcontext)
    app_module_name = "qwenpaw.app._app"
    previous_app_module = __import__("sys").modules.get(app_module_name)
    app_module = importlib.import_module(app_module_name)
    caller_thread = threading.get_ident()
    initialization_threads = []

    def get_provider_instance():
        return object()

    def get_local_instance():
        initialization_threads.append(threading.get_ident())
        raise RuntimeError("local model initialized")

    monkeypatch.setattr(
        app_module.ProviderManager,
        "get_instance",
        get_provider_instance,
    )
    monkeypatch.setattr(
        app_module.LocalModelManager,
        "get_instance",
        get_local_instance,
    )
    monkeypatch.setattr(
        app_module,
        "add_project_file_handler",
        lambda _path: None,
    )
    monkeypatch.setattr(
        app_module,
        "cleanup_startup_restore_artifacts",
        lambda: None,
    )
    monkeypatch.setattr(app_module, "auto_register_from_env", lambda: None)
    monkeypatch.setattr(
        app_module,
        "check_proxy_config_sanity",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "migrate_legacy_workspace_to_default_agent",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "ensure_default_agent_exists",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "migrate_legacy_skills_to_skill_pool",
        lambda: None,
    )
    monkeypatch.setattr(
        app_module,
        "_sync_scroll_history_on_startup",
        AsyncMock(),
    )
    monkeypatch.setattr(app_module, "ensure_qa_agent_exists", lambda: None)

    try:
        with pytest.raises(RuntimeError, match="local model initialized"):
            async with app_module.lifespan(FastAPI()):
                pass
    finally:
        modules = __import__("sys").modules
        if previous_app_module is None:
            modules.pop(app_module_name, None)
        else:
            modules[app_module_name] = previous_app_module

    assert len(initialization_threads) == 1
    assert initialization_threads[0] != caller_thread


class _nullcontext:
    """Minimal context manager for isolating import-time restore locking."""

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False
