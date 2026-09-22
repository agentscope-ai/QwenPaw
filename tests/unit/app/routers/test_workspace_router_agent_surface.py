# -*- coding: utf-8 -*-
"""Workspace-router tests for the agent-facing surface.

The existing modules cover the memory-backend/embedding persistence
machinery (``test_workspace_router.py``), the filesystem helpers
(``test_workspace_router_fs_helpers.py``) and the coded file-tree routes
(``test_workspace_router_file_ops.py``). This one drives the remaining
routes that project *agent* state — markdown files, memory files,
language, system-prompt files, audio mode, transcription provider, the
running-config read, the workspace zip download/upload guards and the
slash-command menu — plus the pure secret-redaction helper.
"""
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
# pylint: disable=unused-argument

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import workspace as ws
from qwenpaw.config.config import AgentsRunningConfig

# Audio-transcription helpers are imported lazily inside the routes, so the
# patch target has to be spelled out in full. Kept as a constant because it
# exceeds the 79-column line limit as a literal.
_AUDIO_MODULE = "qwenpaw.agents.utils.audio_transcription"


def _agent(tmp_path: Path, **extra) -> SimpleNamespace:
    """Workspace stand-in: the routes only read these three attributes."""
    return SimpleNamespace(
        agent_id="agent-x",
        workspace_dir=tmp_path,
        memory_manager=None,
        **extra,
    )


def _agent_resolver(agent) -> AsyncMock:
    """``get_agent_for_request`` stand-in returning *agent*."""
    return AsyncMock(return_value=agent)


def _md_entry(name: str, *, size: int = 3) -> dict:
    """One ``AgentMdManager`` file-info dict as the router validates it."""
    return {
        "filename": name,
        "path": name,
        "size": size,
        "created_time": "2026-09-18T00:00:00",
        "modified_time": "2026-09-18T00:00:01",
    }


def _md_manager(**overrides) -> SimpleNamespace:
    """``AgentMdManager`` stand-in (the real one reads agent config)."""
    base: dict = {
        "list_working_mds": lambda: [],
        "read_working_md": lambda name: "",
        "write_working_md": lambda name, content: None,
        "list_memory_mds": lambda section: [],
        "read_memory_md": lambda path, section: "",
        "write_memory_md": lambda path, content, section: None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _record(sink: list):
    """Return a callable that appends its argument to *sink*."""

    def record(value):
        sink.append(value)

    return record


def _record_pair(sink: list, result):
    """Record the ``(first, second)`` pair of a two-argument stub call."""

    def stub(first, second):
        sink.append((first, second))
        return result

    return stub


def _record_then(sink: list, result):
    """Record the first argument, then hand back *result*.

    Used where a stub has to both capture what the route passed and answer
    with a value; ``sink.append(x) or result`` would depend on ``append``
    returning something, which mypy rightly rejects.
    """

    def stub(value):
        sink.append(value)
        return result

    return stub


def _record_args_then(sink: list, result):
    """Record ``(args, kwargs)`` of a call, then hand back *result*."""

    def stub(*args, **kwargs):
        sink.append((args, kwargs))
        return result

    return stub


def _lookup(table: dict):
    """Return a callable mimicking ``dict.get`` for a resolver stub."""

    def lookup(key):
        return table.get(key)

    return lookup


# --------------------------------------------------------------------- #
# _safe_memory_validation_error — never echoes submitted secrets
# --------------------------------------------------------------------- #


class TestSafeMemoryValidationError:
    def test_scalar_secret_is_redacted(self) -> None:
        detail = ws._safe_memory_validation_error(
            RuntimeError("bad api_key TOPSECRET"),
            {"api_key": "TOPSECRET"},
            ["api_key"],
        )
        assert detail == "bad api_key ***"
        assert "TOPSECRET" not in detail

    def test_nested_mapping_secret_is_redacted(self) -> None:
        submitted = {"config": {"inner": {"token": "S3CR3T"}}}
        detail = ws._safe_memory_validation_error(
            RuntimeError("rejected {'token': 'S3CR3T'}"),
            submitted,
            ["config"],
        )
        assert "S3CR3T" not in detail
        assert "***" in detail

    def test_list_secret_is_redacted(self) -> None:
        detail = ws._safe_memory_validation_error(
            RuntimeError("got ['AAA', 'BBB']"),
            {"keys": ["AAA", "BBB"]},
            ["keys"],
        )
        assert "AAA" not in detail
        assert "BBB" not in detail

    def test_none_secret_contributes_no_fragment(self) -> None:
        detail = ws._safe_memory_validation_error(
            RuntimeError("boom"),
            {"token": None},
            ["token"],
        )
        assert detail == "boom"

    def test_absent_field_leaves_detail_untouched(self) -> None:
        detail = ws._safe_memory_validation_error(
            RuntimeError("boom"),
            {},
            ["token"],
        )
        assert detail == "boom"

    def test_container_form_is_replaced_before_its_member(self) -> None:
        """Longest fragment first: the whole list form goes, not a mangled one.

        Replacing the member ``SECRETVALUE`` first would turn
        ``['SECRETVALUE']`` into ``['***']`` — the container form no longer
        matches, so its quotes and brackets survive into the response.
        Redacting the longer fragment first collapses the whole form.
        """
        detail = ws._safe_memory_validation_error(
            RuntimeError("rejected ['SECRETVALUE']"),
            {"keys": ["SECRETVALUE"]},
            ["keys"],
        )
        assert "SECRETVALUE" not in detail
        assert detail == "rejected ***"


# --------------------------------------------------------------------- #
# Markdown file routes (working dir + memory dir)
# --------------------------------------------------------------------- #


async def test_list_working_files_validates_each_entry(tmp_path) -> None:
    manager = _md_manager(list_working_mds=lambda: [_md_entry("AGENTS.md")])
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        files = await ws.list_working_files(SimpleNamespace())
    assert [f.filename for f in files] == ["AGENTS.md"]
    assert files[0].size == 3


async def test_list_working_files_wraps_failure_as_500(tmp_path) -> None:
    def boom() -> list:
        raise OSError("disk gone")

    manager = _md_manager(list_working_mds=boom)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.list_working_files(SimpleNamespace())
    assert raised.value.status_code == 500
    assert "disk gone" in raised.value.detail


async def test_read_working_file_returns_content(tmp_path) -> None:
    manager = _md_manager(read_working_md=lambda name: f"body of {name}")
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        result = await ws.read_working_file("SOUL.md", SimpleNamespace())
    assert result.content == "body of SOUL.md"


async def test_read_working_file_missing_is_404(tmp_path) -> None:
    def missing(name: str) -> str:
        raise FileNotFoundError(f"No such file: {name}")

    manager = _md_manager(read_working_md=missing)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.read_working_file("gone.md", SimpleNamespace())
    assert raised.value.status_code == 404
    assert "gone.md" in raised.value.detail


async def test_read_working_file_other_failure_is_500(tmp_path) -> None:
    def boom(name: str) -> str:
        raise PermissionError("denied")

    manager = _md_manager(read_working_md=boom)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.read_working_file("SOUL.md", SimpleNamespace())
    assert raised.value.status_code == 500
    assert raised.value.detail == "denied"


async def test_write_working_file_reports_written(tmp_path) -> None:
    calls: list[tuple] = []
    manager = _md_manager(
        write_working_md=lambda name, content: calls.append((name, content)),
    )
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        result = await ws.write_working_file(
            "AGENTS.md",
            ws.MdFileContent(content="new body"),
            SimpleNamespace(),
        )
    assert result == {"written": True}
    assert calls == [("AGENTS.md", "new body")]


async def test_write_working_file_failure_is_500(tmp_path) -> None:
    def boom(name: str, content: str) -> None:
        raise OSError("read-only fs")

    manager = _md_manager(write_working_md=boom)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.write_working_file(
                "AGENTS.md",
                ws.MdFileContent(content="x"),
                SimpleNamespace(),
            )
    assert raised.value.status_code == 500


async def test_list_memory_files_forwards_section(tmp_path) -> None:
    seen: list = []
    manager = _md_manager(
        list_memory_mds=_record_then(
            seen,
            [_md_entry("2026-09-18.md")],
        ),
    )
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        files = await ws.list_memory_files(SimpleNamespace(), section="daily")
    assert seen == ["daily"]
    assert [f.filename for f in files] == ["2026-09-18.md"]


async def test_list_memory_files_failure_is_500(tmp_path) -> None:
    def boom(section):
        raise OSError("nope")

    manager = _md_manager(list_memory_mds=boom)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.list_memory_files(SimpleNamespace(), section=None)
    assert raised.value.status_code == 500


async def test_read_memory_file_forwards_path_and_section(tmp_path) -> None:
    seen: list = []
    manager = _md_manager(
        read_memory_md=_record_pair(seen, "memory body"),
    )
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        result = await ws.read_memory_file(
            "2026-09-18.md",
            SimpleNamespace(),
            section="digest",
        )
    assert seen == [("2026-09-18.md", "digest")]
    assert result.content == "memory body"


async def test_read_memory_file_missing_is_404(tmp_path) -> None:
    def missing(path, section):
        raise FileNotFoundError(path)

    manager = _md_manager(read_memory_md=missing)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.read_memory_file(
                "gone.md",
                SimpleNamespace(),
                section=None,
            )
    assert raised.value.status_code == 404


async def test_read_memory_file_other_failure_is_500(tmp_path) -> None:
    def boom(path, section):
        raise OSError("io")

    manager = _md_manager(read_memory_md=boom)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.read_memory_file("x.md", SimpleNamespace(), section=None)
    assert raised.value.status_code == 500


async def test_write_memory_file_reports_written(tmp_path) -> None:
    seen: list = []
    manager = _md_manager(
        write_memory_md=lambda path, content, section: seen.append(
            (path, content, section),
        ),
    )
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        result = await ws.write_memory_file(
            "note.md",
            ws.MdFileContent(content="hello"),
            SimpleNamespace(),
            section="daily",
        )
    assert result == {"written": True}
    assert seen == [("note.md", "hello", "daily")]


async def test_write_memory_file_failure_is_500(tmp_path) -> None:
    def boom(path, content, section):
        raise OSError("nope")

    manager = _md_manager(write_memory_md=boom)
    with (
        patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ),
        patch.object(ws, "AgentMdManager", return_value=manager),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.write_memory_file(
                "note.md",
                ws.MdFileContent(content="x"),
                SimpleNamespace(),
                section=None,
            )
    assert raised.value.status_code == 500


# --------------------------------------------------------------------- #
# Agent language
# --------------------------------------------------------------------- #


async def test_get_agent_language_reports_config_and_agent(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ws,
        "load_agent_config",
        lambda aid: SimpleNamespace(language="zh"),
    )
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        result = await ws.get_agent_language(SimpleNamespace())
    assert result == {"language": "zh", "agent_id": "agent-x"}


@pytest.mark.parametrize("raw", ["klingon", "", "   ", None])
async def test_put_agent_language_rejects_unsupported(raw) -> None:
    """Rejection happens before any workspace lookup.

    Non-string values are deliberately not covered: the route calls
    ``.strip()`` on them and that raises ``AttributeError`` (a 500), not a
    400. Pinning either outcome here would freeze current behaviour as
    though it were the contract.
    """
    resolver = _agent_resolver(SimpleNamespace())
    with patch.object(ws, "get_agent_for_request", resolver):
        with pytest.raises(HTTPException) as raised:
            await ws.put_agent_language(SimpleNamespace(), {"language": raw})
    assert raised.value.status_code == 400
    assert "Must be one of" in raised.value.detail
    assert "en, id, ru, zh" in raised.value.detail
    resolver.assert_not_awaited()


async def test_put_agent_language_same_value_skips_md_copy(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No language change: config is saved but templates are not re-copied."""
    config = SimpleNamespace(language="en", template_id=None)
    saved: list = []
    copied: list = []
    reloaded: list = []
    monkeypatch.setattr(ws, "load_agent_config", lambda aid: config)
    monkeypatch.setattr(
        ws,
        "save_agent_config",
        lambda aid, cfg: saved.append((aid, cfg)),
    )
    monkeypatch.setattr(
        ws,
        "copy_workspace_md_files",
        _record_args_then(copied, ["AGENTS.md"]),
    )
    monkeypatch.setattr(
        ws,
        "schedule_agent_reload",
        lambda req, aid: reloaded.append(aid),
    )
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        result = await ws.put_agent_language(
            SimpleNamespace(),
            {"language": "EN"},
        )
    assert result == {
        "language": "en",
        "copied_files": [],
        "agent_id": "agent-x",
    }
    assert saved == [("agent-x", config)]
    assert copied == []
    assert reloaded == []


async def test_put_agent_language_copies_templates_on_change(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(language="en", template_id="tpl-1")
    copied: list = []
    reloaded: list = []
    monkeypatch.setattr(ws, "load_agent_config", lambda aid: config)
    monkeypatch.setattr(ws, "save_agent_config", lambda aid, cfg: None)
    monkeypatch.setattr(
        ws,
        "copy_workspace_md_files",
        _record_args_then(copied, ["AGENTS.md", "SOUL.md"]),
    )
    monkeypatch.setattr(
        ws,
        "schedule_agent_reload",
        lambda req, aid: reloaded.append(aid),
    )
    monkeypatch.setattr(
        ws,
        "get_workspace_md_template_id",
        lambda tpl: f"md/{tpl}",
    )
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        result = await ws.put_agent_language(
            SimpleNamespace(),
            {"language": " ru "},
        )
    assert result["language"] == "ru"
    assert result["copied_files"] == ["AGENTS.md", "SOUL.md"]
    assert reloaded == ["agent-x"]
    args, kwargs = copied[0]
    assert args == ("ru", tmp_path)
    assert kwargs["md_template_id"] == "md/tpl-1"
    assert kwargs["only_if_missing"] is False


async def test_put_agent_language_for_qa_agent_uses_qa_template(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An untemplated QA agent falls back to the built-in ``qa`` template."""
    from qwenpaw.constant import BUILTIN_QA_AGENT_ID

    config = SimpleNamespace(language="en", template_id=None)
    seen: list = []
    monkeypatch.setattr(ws, "load_agent_config", lambda aid: config)
    monkeypatch.setattr(ws, "save_agent_config", lambda aid, cfg: None)
    monkeypatch.setattr(ws, "copy_workspace_md_files", lambda *a, **kw: [])
    monkeypatch.setattr(ws, "schedule_agent_reload", lambda req, aid: None)
    monkeypatch.setattr(
        ws,
        "get_workspace_md_template_id",
        _record(seen),
    )
    agent = SimpleNamespace(
        agent_id=BUILTIN_QA_AGENT_ID,
        workspace_dir=tmp_path,
        memory_manager=None,
    )
    with patch.object(ws, "get_agent_for_request", _agent_resolver(agent)):
        await ws.put_agent_language(SimpleNamespace(), {"language": "id"})
    assert seen == ["qa"]


# --------------------------------------------------------------------- #
# System prompt files
# --------------------------------------------------------------------- #


async def test_get_system_prompt_files_returns_configured_list(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ws,
        "load_agent_config",
        lambda aid: SimpleNamespace(
            system_prompt_files=["AGENTS.md", "SOUL.md"],
        ),
    )
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        files = await ws.get_system_prompt_files(SimpleNamespace())
    assert files == ["AGENTS.md", "SOUL.md"]


async def test_get_system_prompt_files_none_becomes_empty_list(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ws,
        "load_agent_config",
        lambda aid: SimpleNamespace(system_prompt_files=None),
    )
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        files = await ws.get_system_prompt_files(SimpleNamespace())
    assert files == []


async def test_put_system_prompt_files_persists_and_reloads(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(system_prompt_files=["OLD.md"])
    saved: list = []
    reloaded: list = []
    monkeypatch.setattr(ws, "load_agent_config", lambda aid: config)
    monkeypatch.setattr(
        ws,
        "save_agent_config",
        lambda aid, cfg: saved.append((aid, cfg.system_prompt_files)),
    )
    monkeypatch.setattr(
        ws,
        "schedule_agent_reload",
        lambda req, aid: reloaded.append(aid),
    )
    request = SimpleNamespace()
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        files = await ws.put_system_prompt_files(["A.md", "B.md"], request)
    assert files == ["A.md", "B.md"]
    assert saved == [("agent-x", ["A.md", "B.md"])]
    assert reloaded == ["agent-x"]


# --------------------------------------------------------------------- #
# Audio mode + transcription provider (all guarded by a value allowlist)
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "route,body,field",
    [
        ("put_audio_mode", {"audio_mode": "shout"}, "audio_mode"),
        ("put_audio_mode", {}, "audio_mode"),
        (
            "put_transcription_provider_type",
            {"transcription_provider_type": "dragon"},
            "transcription_provider_type",
        ),
        ("put_transcription_provider_type", {}, "transcription_provider_type"),
    ],
)
async def test_invalid_enum_like_setting_is_400(route, body, field) -> None:
    handler = getattr(ws, route)
    mutated: list = []
    with patch.object(
        ws,
        "run_sync_io",
        new=AsyncMock(side_effect=lambda *a, **kw: mutated.append(a)),
    ):
        with pytest.raises(HTTPException) as raised:
            await handler(body)
    assert raised.value.status_code == 400
    assert f"Invalid {field}" in raised.value.detail
    assert "Must be one of" in raised.value.detail
    assert mutated == []


async def test_put_audio_mode_persists_via_mutate_config() -> None:
    applied: list = []

    async def fake_run_sync_io(fn, *args, **kwargs):
        applied.append((fn, args))
        return fn(*args) if callable(fn) else None

    config = SimpleNamespace(agents=SimpleNamespace(audio_mode="auto"))
    with patch.object(ws, "run_sync_io", new=fake_run_sync_io):
        with patch.object(
            ws,
            "mutate_config",
            lambda mutator: mutator(config),
        ):
            result = await ws.put_audio_mode({"audio_mode": " NATIVE "})
    assert result == {"audio_mode": "native"}
    assert config.agents.audio_mode == "native"
    assert len(applied) == 1


async def test_put_transcription_provider_type_persists() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(transcription_provider_type="disabled"),
    )

    async def fake_run_sync_io(fn, *args, **kwargs):
        return fn(*args)

    with patch.object(ws, "run_sync_io", new=fake_run_sync_io):
        with patch.object(
            ws,
            "mutate_config",
            lambda mutator: mutator(config),
        ):
            result = await ws.put_transcription_provider_type(
                {"transcription_provider_type": "Local_Whisper"},
            )
    assert result == {"transcription_provider_type": "local_whisper"}
    assert config.agents.transcription_provider_type == "local_whisper"


async def test_put_transcription_provider_trims_and_persists() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(transcription_provider_id="x"),
    )

    async def fake_run_sync_io(fn, *args, **kwargs):
        return fn(*args)

    with patch.object(ws, "run_sync_io", new=fake_run_sync_io):
        with patch.object(
            ws,
            "mutate_config",
            lambda mutator: mutator(config),
        ):
            result = await ws.put_transcription_provider(
                {"provider_id": "  openai  "},
            )
    assert result == {"provider_id": "openai"}
    assert config.agents.transcription_provider_id == "openai"


async def test_put_transcription_provider_accepts_empty_unset() -> None:
    """``""`` unsets the provider and is not rejected."""
    config = SimpleNamespace(
        agents=SimpleNamespace(transcription_provider_id="openai"),
    )

    async def fake_run_sync_io(fn, *args, **kwargs):
        return fn(*args)

    with patch.object(ws, "run_sync_io", new=fake_run_sync_io):
        with patch.object(
            ws,
            "mutate_config",
            lambda mutator: mutator(config),
        ):
            result = await ws.put_transcription_provider({"provider_id": ""})
    assert result == {"provider_id": ""}
    assert config.agents.transcription_provider_id == ""


async def test_get_audio_mode_reads_global_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ws,
        "load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(audio_mode="native")),
    )
    assert await ws.get_audio_mode() == {"audio_mode": "native"}


async def test_get_transcription_provider_type_reads_global_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ws,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(transcription_provider_type="whisper_api"),
        ),
    )
    assert await ws.get_transcription_provider_type() == {
        "transcription_provider_type": "whisper_api",
    }


async def test_get_local_whisper_status_delegates_to_probe() -> None:
    probe = {"ffmpeg": True, "whisper": False}
    with patch(
        f"{_AUDIO_MODULE}.check_local_whisper_available",
        return_value=probe,
    ):
        assert await ws.get_local_whisper_status() == probe


async def test_get_transcription_providers_reports_selection() -> None:
    with patch(
        f"{_AUDIO_MODULE}.list_transcription_providers",
        return_value=[{"id": "openai"}],
    ):
        with patch(
            f"{_AUDIO_MODULE}.get_configured_transcription_provider_id",
            return_value="openai",
        ):
            result = await ws.get_transcription_providers()
    assert result == {
        "providers": [{"id": "openai"}],
        "configured_provider_id": "openai",
    }


# --------------------------------------------------------------------- #
# Running config read
# --------------------------------------------------------------------- #


async def test_get_running_config_offloads_read_and_injects_approval(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route reads the profile off the loop and adds ``approval_level``.

    Secret masking itself is pinned by ``test_workspace_router.py``; what
    belongs to the route is the thread offload, the profile-derived
    approval level, and handing back a config detached from the profile.
    """
    running = AgentsRunningConfig()
    profile = SimpleNamespace(running=running, approval_level="STRICT")
    calls: list = []

    async def fake_run_sync_io(fn, *args, **kwargs):
        calls.append((fn, args))
        return fn(*args)

    monkeypatch.setattr(ws, "load_agent_config", lambda aid: profile)
    with patch.object(ws, "run_sync_io", new=fake_run_sync_io):
        with patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ):
            result = await ws.get_agents_running_config(SimpleNamespace())

    assert calls == [(ws.load_agent_config, ("agent-x",))]
    assert result.approval_level == "STRICT"
    # Detached: mutating the API payload must not reach the profile config.
    result.approval_level = "OFF"
    assert profile.running.approval_level != "OFF"


async def test_get_running_config_defaults_when_profile_has_none(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile without ``running`` still answers, and without approval
    level the documented ``AUTO`` default is surfaced."""
    profile = SimpleNamespace(running=None)

    async def fake_run_sync_io(fn, *args, **kwargs):
        return fn(*args)

    monkeypatch.setattr(ws, "load_agent_config", lambda aid: profile)
    with patch.object(ws, "run_sync_io", new=fake_run_sync_io):
        with patch.object(
            ws,
            "get_agent_for_request",
            _agent_resolver(_agent(tmp_path)),
        ):
            result = await ws.get_agents_running_config(SimpleNamespace())

    assert isinstance(result, AgentsRunningConfig)
    assert result.approval_level == "AUTO"


async def test_mask_memory_backend_drops_unregistered_backend_entry() -> None:
    """An unavailable plugin's opaque payload is removed, not leaked.

    Core cannot tell which keys inside an unknown plugin payload are
    secrets, so the whole entry goes: masking it would imply the rest of
    the payload is safe to display.
    """
    running = AgentsRunningConfig(
        memory_manager_backend="ghost-plugin",
        memory_backend_configs={
            "ghost-plugin": {"api_key": "TOPSECRET", "endpoint": "http://h"},
        },
    )
    masked = ws._mask_memory_backend_secrets(running)
    assert masked.memory_backend_configs == {}
    assert (
        running.memory_backend_configs["ghost-plugin"]["api_key"]
        == "TOPSECRET"
    )


# --------------------------------------------------------------------- #
# Workspace zip download / upload guards
# --------------------------------------------------------------------- #


async def test_download_workspace_streams_named_zip(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("# hi\n", encoding="utf-8")
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        response = await ws.download_workspace(SimpleNamespace())
    assert response.media_type == "application/zip"
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith('attachment; filename="qwenpaw_workspace_')
    assert "agent-x" in disposition
    assert disposition.endswith('.zip"')


async def test_download_workspace_missing_dir_is_404(tmp_path) -> None:
    absent = tmp_path / "nope"
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(absent)),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.download_workspace(SimpleNamespace())
    assert raised.value.status_code == 404
    assert str(absent) in raised.value.detail


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/json", "image/png"],
)
async def test_upload_workspace_rejects_non_zip_content_type(
    tmp_path,
    content_type,
) -> None:
    """The guard runs before the workspace is resolved or the body read."""
    resolver = _agent_resolver(_agent(tmp_path))
    reads: list = []

    async def read_body() -> bytes:
        reads.append(1)
        return b""

    upload = SimpleNamespace(content_type=content_type, read=read_body)
    with patch.object(ws, "get_agent_for_request", resolver):
        with pytest.raises(HTTPException) as raised:
            await ws.upload_workspace(SimpleNamespace(), upload)
    assert raised.value.status_code == 400
    assert content_type in raised.value.detail
    resolver.assert_not_awaited()
    assert reads == []


@pytest.mark.parametrize(
    "content_type",
    [
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
        None,
    ],
)
async def test_upload_workspace_accepts_zip_content_types(
    tmp_path,
    content_type,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted: list = []

    def fake_extract(data: bytes, workspace_dir: Path) -> None:
        extracted.append((data, workspace_dir))

    async def read_body() -> bytes:
        return b"ZIPBYTES"

    upload = SimpleNamespace(content_type=content_type, read=read_body)
    monkeypatch.setattr(ws, "_validate_and_extract_zip", fake_extract)
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        result = await ws.upload_workspace(SimpleNamespace(), upload)
    assert result == {"success": True}
    assert extracted == [(b"ZIPBYTES", tmp_path)]


async def test_upload_workspace_propagates_validation_http_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 from the zip validator must not be rewrapped into a 500."""

    def fake_extract(data: bytes, workspace_dir: Path) -> None:
        raise HTTPException(
            status_code=400,
            detail="Zip contains unsafe path: ../escape",
        )

    async def read_body() -> bytes:
        return b"ZIPBYTES"

    upload = SimpleNamespace(content_type="application/zip", read=read_body)
    monkeypatch.setattr(ws, "_validate_and_extract_zip", fake_extract)
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.upload_workspace(SimpleNamespace(), upload)
    assert raised.value.status_code == 400
    assert "unsafe path" in raised.value.detail


async def test_upload_workspace_wraps_unexpected_failure_as_500(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_extract(data: bytes, workspace_dir: Path) -> None:
        raise OSError("disk full")

    async def read_body() -> bytes:
        return b"ZIPBYTES"

    upload = SimpleNamespace(content_type="application/zip", read=read_body)
    monkeypatch.setattr(ws, "_validate_and_extract_zip", fake_extract)
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        with pytest.raises(HTTPException) as raised:
            await ws.upload_workspace(SimpleNamespace(), upload)
    assert raised.value.status_code == 500
    assert "Failed to merge workspace: disk full" == raised.value.detail


# --------------------------------------------------------------------- #
# Slash-command menu
# --------------------------------------------------------------------- #


async def test_available_commands_without_plugin_registry_is_empty(
    tmp_path,
) -> None:
    """No plugin surface at all: the menu is empty, not an error."""
    with patch.object(
        ws,
        "get_agent_for_request",
        _agent_resolver(_agent(tmp_path)),
    ):
        response = await ws.get_available_commands(SimpleNamespace())
    assert json.loads(response.body) == {"commands": []}


async def test_available_commands_lists_resolved_specs(tmp_path) -> None:
    spec_ok = SimpleNamespace(help_text="do it", category="tools")
    spec_blank = SimpleNamespace(help_text=None, category=None)
    registry = SimpleNamespace(
        names=lambda: ["alpha", "beta"],
        resolve=_lookup(
            {
                "/alpha": (spec_ok, "extra"),
                "/beta": (spec_blank, "extra"),
            },
        ),
    )
    agent = _agent(
        tmp_path,
        plugins=SimpleNamespace(slash_command_registry=registry),
    )
    with patch.object(ws, "get_agent_for_request", _agent_resolver(agent)):
        response = await ws.get_available_commands(SimpleNamespace())
    payload = json.loads(response.body)
    assert payload["commands"] == [
        {"name": "alpha", "description": "do it", "category": "tools"},
        {"name": "beta", "description": "", "category": ""},
    ]


async def test_available_commands_tolerates_unresolvable_name(
    tmp_path,
) -> None:
    """A registered name whose spec vanished yields an entry, not a crash."""
    registry = SimpleNamespace(names=lambda: ["ghost"], resolve=lambda t: None)
    agent = _agent(
        tmp_path,
        plugins=SimpleNamespace(slash_command_registry=registry),
    )
    with patch.object(ws, "get_agent_for_request", _agent_resolver(agent)):
        response = await ws.get_available_commands(SimpleNamespace())
    assert json.loads(response.body) == {
        "commands": [{"name": "ghost", "description": "", "category": ""}],
    }
