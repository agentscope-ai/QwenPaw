# -*- coding: utf-8 -*-
"""Selected history uses authenticated HTTP identity and persisted host state."""

from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.app import auth
from qwenpaw.plugins.apps import PawApp, ChatRequest
from qwenpaw.plugins.errors import StaleContextError
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.shell import ShellBackendSpec, ShellResult


async def test_selected_history_scope_projection_and_lifetime(
    sdk_component,
    tmp_path,
):
    retained = []

    def declare(ctx):
        app = PawApp(app_id="history-sample")

        @app.route("/history")
        async def history(call, request):
            retained.append(call.conversations)
            return {
                "messages": [
                    asdict(item)
                    for item in await call.conversations.history(limit=2)
                ],
                "projects": [
                    str(path)
                    for path in await call.workspace_ops.project_directories()
                ],
            }

        ctx.register_app(app)

    async with sdk_component(declare, capabilities=("apps",)) as (host, _):
        workspace = await host._workspace("one")
        other = await host._workspace("two")
        project = tmp_path / "selected-project"
        project.mkdir()
        own = await workspace.chat_manager.get_or_create_chat(
            "main",
            "default",
            "console",
        )
        await workspace.chat_manager.set_session_project_dirs(
            own.id,
            [{"path": str(project)}],
        )
        raw = [
            {"role": "user", "content": "old"},
            {"role": "system", "content": "secret system"},
            {
                "role": "user",
                "content": "question",
                "metadata": {"private": "hidden"},
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "secret reasoning"},
                    {"type": "tool_use", "input": {"secret": "secret tool"}},
                    {"type": "text", "text": "answer"},
                ],
            },
        ]
        await workspace.session.save_session_state(
            "main",
            "default",
            "console",
            agent=SimpleNamespace(
                state_dict=lambda: {"state": {"context": raw}},
            ),
        )
        response = await host.request(
            "GET",
            "/api/history-sample/history?agent_id=one",
            headers={"X-Chat-Id": own.id},
            user_id="default",
            workspace_id="one",
        )
        assert response.status == 200
        assert response.json() == {
            "messages": [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "answer"},
            ],
            "projects": [str(project)],
        }
        with pytest.raises(StaleContextError):
            await retained[-1].history()
        forbidden = ["missing", ""]
        for owner, channel, sid, ws in (
            ("bob", "console", "main", workspace),
            ("default", "email", "main", workspace),
            ("default", "console", "pawapp:other", workspace),
            ("default", "console", "main", other),
        ):
            chat = await ws.chat_manager.get_or_create_chat(
                sid,
                owner,
                channel,
            )
            forbidden.append(chat.id)
        for selected in forbidden:
            response = await host.request(
                "GET",
                "/api/history-sample/history?agent_id=one",
                headers={"X-Chat-Id": selected},
                user_id="default",
                workspace_id="one",
            )
            assert response.status == 403, (selected, response.text)


async def test_login_can_use_the_selected_default_console_chat(
    sdk_component,
    tmp_path,
    monkeypatch,
):
    def declare(ctx):
        async def execute(call, request):
            return ShellResult(0)

        ctx.register_shell_backend(
            ShellBackendSpec("remote", lambda identity: True, execute),
        )
        app = PawApp(app_id="login-sample")
        app.enable_standard_capabilities()

        @app.route("/selected", methods=("POST",))
        async def select(call, request):
            history = await call.conversations.history()
            await call.select_shell_backend("remote")
            return {
                "user": call.user_id,
                "history": list(map(asdict, history)),
            }

        ctx.register_app(app)

    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    token = auth.register_user("operator", "temporary-test-passphrase")
    assert token
    async with sdk_component(declare, capabilities=("apps", "shell")) as (
        host,
        _,
    ):
        workspace = await host._workspace("one")
        other_workspace = await host._workspace("two")
        chats = workspace.chat_manager
        own = await chats.get_or_create_chat("main", "default", "console")
        await workspace.session.save_session_state(
            "main",
            "default",
            "console",
            agent=SimpleNamespace(
                state_dict=lambda: {
                    "state": {
                        "context": [{"role": "user", "content": "hello"}],
                    },
                },
            ),
        )
        forbidden = [
            await chats.get_or_create_chat("main", "bob", "console"),
            await chats.get_or_create_chat("main", "default", "email"),
            await chats.get_or_create_chat(
                "pawapp:other",
                "default",
                "console",
            ),
            await other_workspace.chat_manager.get_or_create_chat(
                "main",
                "default",
                "console",
            ),
        ]
        host._http_app.add_middleware(auth.AuthMiddleware)
        transport = httpx.ASGITransport(
            app=host._http_app,
            client=("192.0.2.10", 12345),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://qwenpaw.test/api/login-sample/",
        ) as client:
            headers = {"X-Chat-Id": own.id}
            assert (
                await client.post("selected?agent_id=one", headers=headers)
            ).status_code == 401
            client.headers["Authorization"] = f"Bearer {token}"
            response = await client.post(
                "selected?agent_id=one",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "user": "operator",
                "history": [{"role": "user", "content": "hello"}],
            }
            timeline = await client.get(
                "checkpoints/timeline?agent_id=one",
                headers=headers,
            )
            assert timeline.status_code == 200, timeline.text
            assert timeline.json() == []
            for chat in forbidden:
                response = await client.post(
                    "selected?agent_id=one",
                    headers={"X-Chat-Id": chat.id},
                )
                assert response.status_code == 403, response.text
        assert await chats.shell_backend_for("main", "default", "console") == (
            "resource-contract:remote"
        )
        assert (
            await chats.shell_backend_for("main", "operator", "console")
            is None
        )


async def test_history_reads_actual_runtime_saved_turn(sdk_component):
    def declare(ctx):
        async def generate(call, request):
            yield ModelChunk(
                (ContentBlock(text="saved answer"),),
                is_last=True,
            )

        ctx.register_provider(
            ProviderSpec(
                "history",
                "History",
                generate,
                models=(ModelInfo("model", "Model"),),
                require_api_key=False,
            ),
        )
        app = PawApp(app_id="saved-history")

        @app.route("/history")
        async def history(call, request):
            return [
                asdict(item) for item in await call.conversations.history()
            ]

        ctx.register_app(app)

    async with sdk_component(declare, capabilities=("apps", "providers")) as (
        host,
        _,
    ):
        await host.configure_chat_model("history", "model", workspace_id="one")
        workspace = await host._workspace("one")
        chat = await workspace.chat_manager.get_or_create_chat(
            "actual",
            "default",
            "console",
        )
        events = [
            event
            async for event in host.stream_chat(
                ChatRequest("saved question", session_id="actual"),
                workspace_id="one",
                user_id="default",
            )
        ]
        assert events
        response = await host.request(
            "GET",
            "/api/saved-history/history?agent_id=one",
            headers={"X-Chat-Id": chat.id},
            user_id="default",
            workspace_id="one",
        )
        assert response.status == 200
        assert response.json()[-2:] == [
            {"role": "user", "content": "saved question"},
            {"role": "assistant", "content": "saved answer"},
        ]
