# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for seed-file distribution in create_mail_monitor_service.

Old workspaces created before 0.2.0 never went through the agent CRUD
APIs again, so MAIL_TRIAGE.md / CONTACTS.md were missing while the wake
prompt requires reading them.  The monitor factory must ensure both
files exist before starting the monitor.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.app.workspace.service_factories import (
    create_mail_monitor_service,
)
from qwenpaw.config.config import (
    AgentMailConfig,
    AgentMailCredential,
    AgentMailPushConfig,
)

_SEED_ROOT = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "qwenpaw"
    / "agents"
    / "md_files"
)


def _mail_config() -> AgentMailConfig:
    return AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="tester",
            domain="163.com",
            auth_code="a" * 16,
            password="pw",
            phone_number="13800000000",
        ),
        push=AgentMailPushConfig(mode="agent_all"),
    )


def _fake_workspace(
    backend: str,
    tmp_path,
    language: str = "zh",
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="agent-1",
        workspace_dir=str(tmp_path),
        _config=SimpleNamespace(
            backend=backend,
            mail=_mail_config(),
            language=language,
        ),
        _service_manager=SimpleNamespace(services={}),
    )


def _create_monitor(ws):
    published = []
    monitor = asyncio.run(
        create_mail_monitor_service(ws, None, published.append),
    )
    return monitor, published


def test_monitor_start_seeds_missing_mail_files(tmp_path):
    ws = _fake_workspace("qwenpaw", tmp_path)
    monitor, published = _create_monitor(ws)
    assert monitor is not None
    assert published == [monitor]
    triage = tmp_path / "MAIL_TRIAGE.md"
    contacts = tmp_path / "CONTACTS.md"
    assert triage.is_file()
    assert contacts.is_file()
    seed = _SEED_ROOT / "zh" / "MAIL_TRIAGE.md"
    assert triage.read_text(encoding="utf-8") == seed.read_text(
        encoding="utf-8",
    )


def test_monitor_start_keeps_existing_files(tmp_path):
    existing = tmp_path / "MAIL_TRIAGE.md"
    existing.write_text("user edited triage tree", encoding="utf-8")
    ws = _fake_workspace("qwenpaw", tmp_path)
    monitor, _published = _create_monitor(ws)
    assert monitor is not None
    assert existing.read_text(encoding="utf-8") == "user edited triage tree"


def test_monitor_start_falls_back_to_en_for_unknown_language(tmp_path):
    ws = _fake_workspace("qwenpaw", tmp_path, language="fr")
    monitor, _published = _create_monitor(ws)
    assert monitor is not None
    triage = tmp_path / "MAIL_TRIAGE.md"
    assert triage.is_file()
    seed = _SEED_ROOT / "en" / "MAIL_TRIAGE.md"
    assert triage.read_text(encoding="utf-8") == seed.read_text(
        encoding="utf-8",
    )


def test_guarded_backend_does_not_seed_files(tmp_path):
    ws = _fake_workspace("claude_code", tmp_path)
    monitor, published = _create_monitor(ws)
    assert monitor is None
    assert not published
    assert not (tmp_path / "MAIL_TRIAGE.md").exists()
    assert not (tmp_path / "CONTACTS.md").exists()
