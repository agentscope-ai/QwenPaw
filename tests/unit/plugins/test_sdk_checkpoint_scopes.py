# -*- coding: utf-8 -*-
"""Real Git restores through public SDK HTTP, with explicit memory/file scope."""

import asyncio
import json

import pytest

from qwenpaw.checkpoints.policy import session_file_path
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_checkpoint_fixture import make_checkpoint_plugin

FOCUS = (
    "MEMORY.md",
    "memory/note.md",
    "memory/extra.md",
    "project/a.txt",
    "project/b.txt",
    "scratch.txt",
    "credentials.yaml",
)


def write_fixture(root, session, state):
    session.write_text(
        json.dumps(
            {
                "agent": {
                    "state": {"context": [{"role": "user", "content": state}]},
                },
            },
        ),
    )
    for name in FOCUS:
        if state == "before" and name in {"memory/extra.md", "scratch.txt"}:
            continue
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(state + " " + name)


def contents(root, session):
    return {
        name: (root / name).read_text() if (root / name).exists() else None
        for name in (*FOCUS, str(session.relative_to(root)))
    }


@pytest.mark.parametrize(
    "memory,files",
    [(False, False), (True, False), (False, True), (True, True)],
)
async def test_restore_scope_matches_original_engine(tmp_path, memory, files):
    source = make_checkpoint_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(source)
        workspace = await host._workspace("one")
        root = workspace.workspace_dir
        session = session_file_path(
            root,
            session_id="conversation",
            user_id="alice",
            channel="console",
        )
        session.parent.mkdir(parents=True, exist_ok=True)
        chat = await workspace.chat_manager.get_or_create_chat(
            "conversation",
            "alice",
            "console",
        )
        write_fixture(root, session, "before")
        before = contents(root, session)

        async def request(action, body):
            return await host.request(
                "POST",
                "/api/checkpoint-contract/checkpoints/" + action,
                workspace_id="one",
                user_id="alice",
                headers={"X-Chat-Id": chat.id},
                json=body,
            )

        saved = await request("snapshot", {"name": "scope baseline"})
        assert saved.status == 200, saved.text
        target = saved.json()["id"]
        write_fixture(root, session, "after")
        after = contents(root, session)
        payload = {
            "target": target,
            "include_memory": memory,
            "include_files": files,
        }
        preview = await request("restore/preview", payload)
        assert preview.status == 200, preview.text
        data = preview.json()
        assert (
            data["dry_run"]
            and data["include_memory"] == memory
            and data["include_files"] == files
        )
        assert contents(root, session) == after
        assert "credentials.yaml" not in data["file_paths"]
        if files:
            assert {"project/a.txt", "project/b.txt", "scratch.txt"} <= set(
                data["file_paths"],
            )
            assert (await request("restore", payload)).status == 400
            for selection in (
                ["../outside"],
                ["credentials.yaml"],
                ["memory/note.md"],
                ["missing.txt"],
            ):
                rejected = await request(
                    "restore/preview",
                    {**payload, "files": selection},
                )
                assert rejected.status == 400, rejected.text
                assert contents(root, session) == after
            payload["files"] = ["project/a.txt", "scratch.txt"]
        applying = asyncio.create_task(request("restore", payload))
        try:
            async with asyncio.timeout(5):
                while not (
                    pending := await host.approval_requests("conversation")
                ):
                    await asyncio.sleep(0.01)
            assert contents(root, session) == after
            assert await host.resolve_approval(
                pending[0].request_id,
                approved=True,
            )
            response = await asyncio.wait_for(applying, 10)
            assert response.status == 200, response.text
        finally:
            if not applying.done():
                applying.cancel()
            await asyncio.gather(applying, return_exceptions=True)
        expected = dict(after)
        expected[str(session.relative_to(root))] = before[
            str(session.relative_to(root))
        ]
        if memory:
            expected.update(
                {
                    name: before[name]
                    for name in FOCUS
                    if name == "MEMORY.md" or name.startswith("memory/")
                },
            )
        if files:
            expected.update(
                {
                    name: before[name]
                    for name in ("project/a.txt", "scratch.txt")
                },
            )
        assert contents(root, session) == expected
        assert not await host.approval_requests("conversation")
        (tmp_path / "scope-result.json").write_text(
            json.dumps(
                {
                    "memory": memory,
                    "files": files,
                    "preview": {
                        key: data[key]
                        for key in (
                            "restored_paths",
                            "deleted_paths",
                            "file_paths",
                        )
                    },
                    "contents": contents(root, session),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        assert (await host.uninstall("checkpoint-contract")).clean
