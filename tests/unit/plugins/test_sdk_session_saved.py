# -*- coding: utf-8 -*-
"""SDK persistence signals must describe the durable turn outcome."""

import sqlite3

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin


OBSERVER = """
from qwenpaw.plugins.hooks import HookSpec, HookPhase, HookResult
class Plugin:
    def register(self, ctx):
        events = []
        async def saved(call):
            events.append(['saved', call.session_saved])
            await ctx.storage.awrite_json('saved.json', call.session_saved)
            return HookResult()
        async def finished(call):
            events.append(['finally', call.session_saved])
            await ctx.storage.awrite_json('events.json', events)
            return HookResult()
        ctx.register_hook(HookSpec('saved', HookPhase.POST_RESPONSE, saved))
        ctx.register_hook(HookSpec('finished', HookPhase.FINALLY, finished))
plugin = Plugin()
"""

MODEL = """
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.messages import ContentBlock
class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            yield ModelChunk((ContentBlock(text='Saved turn'),), is_last=True)
        ctx.register_provider(ProviderSpec(
            'save-fixture', 'Save fixture', generate,
            models=(ModelInfo('model', 'Model'),), require_api_key=False))
plugin = Plugin()
"""


@pytest.mark.asyncio
async def test_session_saved_matches_committed_sqlite_turn(
    tmp_path,
    monkeypatch,
):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(
                tmp_path,
                MODEL,
                ["providers"],
                sdk_version="1.2",
            ),
        )
        observer = await host.load(
            make_plugin(
                tmp_path,
                OBSERVER,
                ["hooks", "storage"],
                plugin_id="save-observer",
                sdk_version="1.2",
            ),
        )
        await host.configure_chat_model("save-fixture", "model")
        events = [
            event
            async for event in host.stream_chat(
                "Persist this turn",
                session_id="saved",
                user_id="alice",
            )
        ]
        assert events
        databases = list(
            (host.root / "workspaces/test/transcripts").glob("*.db"),
        )
        assert len(databases) == 1
        with sqlite3.connect(databases[0]) as connection:
            assert (
                connection.execute(
                    "SELECT status FROM transcript_turns",
                ).fetchone()[0]
                == "completed"
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM event_log "
                    "WHERE event_type = 'runtime.committed'",
                ).fetchone()[0]
                == 1
            )
        assert observer.storage.read_json("saved.json") is True
        assert observer.storage.read_json("events.json") == [
            ["saved", True],
            ["finally", True],
        ]
        original = TranscriptStore.commit_turn

        def fail_commit(self, **kwargs):
            raise sqlite3.OperationalError("injected commit failure")

        monkeypatch.setattr(TranscriptStore, "commit_turn", fail_commit)
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            async for _ in host.stream_chat(
                "Fail this save",
                session_id="saved",
                user_id="alice",
            ):
                pass
        assert observer.storage.read_json("saved.json") is False
        monkeypatch.setattr(TranscriptStore, "commit_turn", original)
        async for _ in host.stream_chat(
            "Save again",
            session_id="saved",
            user_id="alice",
        ):
            pass
        assert observer.storage.read_json("saved.json") is True
        assert observer.storage.read_json("events.json") == [
            ["saved", True],
            ["finally", True],
            ["saved", False],
            ["finally", False],
            ["saved", True],
            ["finally", True],
        ]
        with sqlite3.connect(databases[0]) as connection:
            assert [
                row[0]
                for row in connection.execute(
                    "SELECT status FROM transcript_turns ORDER BY turn_seq",
                )
            ] == ["completed", "failed", "completed"]
