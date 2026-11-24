# -*- coding: utf-8 -*-
"""Real workspace/chat metadata, filesystem links and stale call ownership."""

from dataclasses import replace

import pytest

from qwenpaw.plugins.context import RequestContext
from qwenpaw.plugins.errors import SDKAccessError, StaleContextError


async def test_workspace_paths_follow_exact_session_owner_and_reject_escapes(
    sdk_component,
    tmp_path,
):
    alice, bob, extra, outside = (
        tmp_path / name for name in ("alice", "bob", "extra", "outside")
    )
    for path in (alice, bob, extra, outside):
        path.mkdir()
    (alice / "escape").symlink_to(outside, target_is_directory=True)
    (alice / "allowed").symlink_to(extra, target_is_directory=True)
    async with sdk_component() as (host, ctx):
        workspace = await host._workspace("one")
        other = await host._workspace("two")
        for user, paths in (("alice", (alice, extra)), ("bob", (bob,))):
            chat = await workspace.chat_manager.get_or_create_chat(
                session_id="shared",
                user_id=user,
                channel="console",
            )
            await workspace.chat_manager.set_session_project_dirs(
                chat.id,
                [{"path": str(path)} for path in paths],
            )

        async with ctx._invocation(
            workspace_id="one",
            session_id="shared",
            identity=RequestContext("one", "shared", "console", "alice"),
        ) as call:
            service = call.workspace_ops
            assert service.directory == workspace.workspace_dir.resolve()
            assert await service.project_directories() == (alice, extra)
            assert await service.resolve_path("new.txt") == alice / "new.txt"
            assert (
                await service.resolve_path("allowed/new.txt")
                == extra / "new.txt"
            )
            for path in (
                "escape/secret",
                "../../escape",
                other.workspace_dir / "secret",
                outside,
            ):
                with pytest.raises(SDKAccessError):
                    await service.resolve_path(path)
            bob_call = replace(
                call,
                identity=RequestContext("one", "shared", "console", "bob"),
            )
            assert await bob_call.workspace_ops.project_directories() == (bob,)
            foreign = replace(
                call,
                identity=RequestContext("one", "shared", "email", "alice"),
            )
            assert await foreign.workspace_ops.project_directories() == ()

        with pytest.raises(StaleContextError):
            await service.resolve_path("late")


async def test_pinned_turn_projects_and_other_workspace_do_not_mix(
    sdk_component,
    tmp_path,
):
    from qwenpaw.config.context import (
        current_project_dirs,
        current_session_id,
        current_workspace_dir,
    )
    from qwenpaw.services.project_directory import (
        resolve_effective_project_dirs,
    )
    from qwenpaw.app.agent_context import _current_user_id, _current_channel

    async with sdk_component() as (host, ctx):
        one = await host._workspace("one")
        two = await host._workspace("two")
        project = tmp_path / "pinned"
        project.mkdir()
        pinned = resolve_effective_project_dirs(
            one.workspace_dir,
            request_override=str(project),
        ).dirs
        tokens = (
            (_current_user_id, _current_user_id.set("alice")),
            (_current_channel, _current_channel.set("console")),
            (current_project_dirs, current_project_dirs.set(pinned)),
            (current_session_id, current_session_id.set("same")),
            (
                current_workspace_dir,
                current_workspace_dir.set(one.workspace_dir),
            ),
        )
        try:
            for wid, root, expected in (
                ("one", one.workspace_dir, (project,)),
                ("two", two.workspace_dir, ()),
            ):
                async with ctx._invocation(
                    workspace_id=wid,
                    session_id="same",
                    identity=RequestContext(wid, "same", "console", "alice"),
                ) as call:
                    assert (
                        await call.workspace_ops.project_directories()
                        == expected
                    )
                    assert (
                        await call.workspace_ops.resolve_path("file")
                        == (project if expected else root) / "file"
                    )
                    other_user = replace(
                        call,
                        identity=RequestContext(wid, "same", "console", "bob"),
                    )
                    assert (
                        await other_user.workspace_ops.project_directories()
                        == ()
                    )
        finally:
            for variable, token in reversed(tokens):
                variable.reset(token)
