# -*- coding: utf-8 -*-
"""Durable ledger of accepted (billed) provider task ids.

A model client that submits an asynchronous provider task is billed the
moment the provider accepts it, but the client itself owns no durable
state. Records land in the current Task's own durable scratch directory
(``runtime/task-work/<task_id>/provider-tasks.jsonl``), so an interrupted
poll leaves a retrievable reference instead of a silently lost paid
result: the id survives the process, is scoped to the Task that paid for
it, and is removed with that Task's scratch.

Outside a Task scope (ad-hoc scripts, tests) the note is logged only.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from utils.logger import setup_logger

# pylint: disable=no-name-in-module
from utils.paths import task_work_root

# pylint: enable=no-name-in-module

logger = setup_logger("models.provider_tasks")

PROVIDER_TASK_LEDGER_NAME = "provider-tasks.jsonl"


def note_provider_task(
    *,
    provider_task_id: str,
    model: str,
    kind: str,
) -> None:
    """Append one accepted provider task id to the current Task's ledger."""

    entry = {
        "providerTaskId": provider_task_id,
        "model": model,
        "kind": kind,
        "acceptedAt": datetime.now(UTC).isoformat(),
    }
    logger.info(
        "provider task accepted (billed) | kind=%s model=%s task=%s",
        kind,
        model,
        provider_task_id,
    )
    try:
        ledger = task_work_root() / PROVIDER_TASK_LEDGER_NAME
    except Exception:  # noqa: BLE001 - no Task scope bound (scripts/tests)
        return
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        # O_APPEND keeps concurrent writers from truncating each other, and
        # the ledger must never take precedence over the provider call: a
        # bookkeeping failure is logged, never raised.
        descriptor = os.open(
            ledger,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.write(descriptor, line.encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError as exc:
        logger.warning(
            "could not record provider task %s: %s",
            provider_task_id,
            exc,
        )


def read_provider_tasks(task_id: str, project_id: str) -> list[dict]:
    """Return the accepted provider tasks recorded for one Creator Task."""

    # pylint: disable=no-name-in-module
    from utils.paths import media_task_scope

    # pylint: enable=no-name-in-module
    with media_task_scope(task_id, project_id=project_id):
        ledger = task_work_root() / PROVIDER_TASK_LEDGER_NAME
    if not ledger.is_file():
        return []
    entries: list[dict] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


__all__ = [
    "PROVIDER_TASK_LEDGER_NAME",
    "note_provider_task",
    "read_provider_tasks",
]
