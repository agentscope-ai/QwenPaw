# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""DELETE must drop the per-project log handle before renaming the tree.

On Windows an open ``creator.log`` inside the project directory makes
``os.replace`` fail with ``PermissionError`` (WinError 5). The route has to
close that handle before ``ProjectStore.delete``.
"""

from __future__ import annotations

import sys

from services.observability.tracing import bind_trace_context
from services.project_files import store as project_store


def test_delete_closes_logging_before_rename(
    app,
    api_runtime_root,
    run_scenario,
    monkeypatch,
):
    # ``utils/__init__.py`` binds ``utils.logger`` to a Logger instance, so the
    # real module is only reachable through ``sys.modules``.
    logger_mod = sys.modules["utils.logger"]
    order: list[str] = []

    async def scenario(client):
        created = await client.post(
            "/projects",
            json={
                "clientRequestId": "delete-closes-log-before-rename",
                "name": "Close log before rename",
                "scenario": "general",
                "aspectRatio": "16:9",
                "resolution": "720P",
            },
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["projectId"]

        logger_mod.configure_creator_file_logging(api_runtime_root)
        with bind_trace_context(projectId=project_id):
            logger_mod.logger.info("holding per-project creator.log open")

        log_path = logger_mod.creator_log_path(
            api_runtime_root,
            project_id=project_id,
        )
        handler = logger_mod._FILE_HANDLER
        assert handler is not None and log_path in handler._targets, (
            log_path,
            None if handler is None else list(handler._targets),
        )

        real_replace = project_store.atomic_replace_path
        real_close = logger_mod.close_creator_project_logging

        def close_logging(target_project_id: str) -> None:
            order.append("close_logging")
            real_close(target_project_id)

        def replace(source, target) -> None:
            order.append("replace")
            current = logger_mod._FILE_HANDLER
            targets = {} if current is None else current._targets
            if log_path in targets:
                raise PermissionError(5, "Access is denied")
            real_replace(source, target)

        monkeypatch.setattr(
            project_store,
            "atomic_replace_path",
            replace,
        )
        monkeypatch.setattr(
            logger_mod,
            "close_creator_project_logging",
            close_logging,
        )

        return await client.delete(
            f"/projects/{project_id}",
            headers={"Idempotency-Key": "delete-closes-log-before-rename"},
        )

    try:
        deleted = run_scenario(app, scenario)
    finally:
        logger_mod.shutdown_creator_file_logging()

    assert deleted.status_code == 204, deleted.text
    assert order.index("close_logging") < order.index("replace")
    # Post-delete close must remain: a worker can reopen the project log
    # between the pre-delete close and rename.
    assert order.count("close_logging") >= 2
    assert order.index("replace") < (
        len(order) - 1 - order[::-1].index("close_logging")
    )
