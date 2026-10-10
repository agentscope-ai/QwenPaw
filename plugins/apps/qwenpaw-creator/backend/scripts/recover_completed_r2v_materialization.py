# -*- coding: utf-8 -*-
"""Adopt a billed, provider-succeeded R2V result after download failure.

This repair path never calls the video provider's submit endpoint.  It is for
the narrow case where the durable R2V state already contains a successful
provider result URL but the local Task failed while materializing that URL.
The signed result is downloaded through the same SSRF-safe materializer,
published under the Task's pre-admitted stable IDs, and committed to Project.
"""

# This narrowly scoped recovery utility deliberately resumes the owning
# service's durable internal state machine instead of submitting a new job.
# pylint: disable=protected-access

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "validate recoverability without mutating Runtime or Project "
            "state"
        ),
    )
    return parser.parse_args()


def _reopen_materialization_state(
    current: Any,
    *,
    provider_task_id: str,
    provider_result: dict[str, Any],
) -> dict[str, Any]:
    """Return a claim-free provider-success state safe for another attempt.

    A previous recovery can fail after reopening ``FAILED`` to
    ``PROVIDER_SUCCEEDED``.  Accept both phases so the operator can rerun this
    script without hand-editing the durable state; ownership and provider
    result must still match exactly.
    """

    if (
        current.phase not in {"FAILED", "PROVIDER_SUCCEEDED"}
        or current.provider_task_id != provider_task_id
        or current.provider_result != provider_result
    ):
        raise RuntimeError("R2V state changed before repair")
    dumped = current.model_dump(mode="python")
    dumped.update(
        {
            "phase": "PROVIDER_SUCCEEDED",
            "last_error": None,
            "materialize_owner": None,
            "materialize_claim_token": None,
            "materialize_claimed_at_epoch": None,
            "materialize_heartbeat_at_epoch": None,
            "materialize_claim_expires_at_epoch": None,
        },
    )
    return dumped


async def _recover(args: argparse.Namespace) -> dict[str, Any]:
    from services.media_files.r2v_execution import (
        FileR2VExecutionService,
        _ids,
    )
    from services.project_files.facade import CreatorFileServices
    from services.runtime_files.execution_models import TaskStatus
    from services.runtime_files.models import ChangeOrigin, ReviewPolicy

    data_root = args.data_root.expanduser().resolve()
    os.environ["CREATOR_DATA_ROOT"] = str(data_root)
    config_path = data_root / "config" / "model_config.json"
    if config_path.is_file():
        os.environ["CREATOR_MODEL_CONFIG_PATH"] = str(config_path)

    services = CreatorFileServices.create(data_root)
    worker = FileR2VExecutionService(
        services,
        materialize_retry_delays=(1.0, 2.0, 5.0, 10.0),
    )
    try:
        task = worker.executions.get_task(args.project_id, args.task_id)
        state = worker._read_state_sync(args.project_id, args.task_id)
        result = state.provider_result
        if task.status is not TaskStatus.FAILED:
            raise RuntimeError("repair requires a FAILED R2V Task")
        if not isinstance(result, dict) or result.get("status") != "SUCCEEDED":
            raise RuntimeError(
                "repair requires a durable SUCCEEDED provider result",
            )
        if not state.provider_task_id:
            raise RuntimeError("repair refuses state without provider task id")
        _reopen_materialization_state(
            state,
            provider_task_id=state.provider_task_id,
            provider_result=result,
        )
        if args.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "project_id": args.project_id,
                "task_id": args.task_id,
                "provider_task_id": state.provider_task_id,
                "recoverable_phase": state.phase,
                "provider_resubmitted": False,
            }

        worker._update_state_sync(
            args.project_id,
            args.task_id,
            lambda current: _reopen_materialization_state(
                current,
                provider_task_id=state.provider_task_id,
                provider_result=result,
            ),
        )
        claim = await worker._claim_materialize(task)
        if claim is None:
            raise RuntimeError(
                "could not claim provider result materialization",
            )
        stable = _ids(
            task.project_id,
            str(task.idempotency_key or task.task_id),
        )
        published = await worker._materialize_and_publish_owned(
            task,
            claim,
            stable=stable,
        )

        current = services.projects.read(args.project_id)
        candidate = current.project.model_dump(mode="json")
        worker._apply_result(candidate, published)
        commit = services.commits.commit(
            base=current,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id=task.caused_by_request_id,
            round_id=stable["round_id"],
            transaction_id=stable["transaction_id"],
            advance_accepted_baseline=True,
        )
        services.poller.note_commit(commit.snapshot)

        success = {
            **published,
            "projectEtag": commit.snapshot.etag,
            "projectGeneration": commit.snapshot.generation,
            "materializationRecovery": {
                "reusedProviderTask": True,
                "providerTaskId": state.provider_task_id,
                "providerResubmitted": False,
            },
        }
        # Preserve the failed Attempt event as audit evidence while making the
        # durable Task reflect the successfully adopted result.  No provider
        # attempt is appended because this recovery performs no new submit.
        reopened = worker.executions.transition_task(
            args.project_id,
            args.task_id,
            expected_status=TaskStatus.FAILED,
            status=TaskStatus.QUEUED,
            updates={"error": None},
        )
        running = worker.executions.transition_task(
            args.project_id,
            args.task_id,
            expected_status=reopened.status,
            status=TaskStatus.RUNNING,
            updates={"progress": 0.95},
        )
        worker.executions.transition_task(
            args.project_id,
            args.task_id,
            expected_status=running.status,
            status=TaskStatus.SUCCEEDED,
            updates={
                "progress": 1.0,
                "result": success,
                "output_refs": [str(success["outputRef"])],
                "metadata": {
                    **dict(task.metadata),
                    "materializationRecovery": success[
                        "materializationRecovery"
                    ],
                },
            },
        )

        def finish(current_state):
            dumped = current_state.model_dump(mode="python")
            dumped.update(
                {
                    "phase": "SUCCEEDED",
                    "published_result": success,
                    "last_error": None,
                },
            )
            return dumped

        worker._update_state_sync(
            args.project_id,
            args.task_id,
            finish,
        )
        return {
            "ok": True,
            "project_id": args.project_id,
            "task_id": args.task_id,
            "provider_task_id": state.provider_task_id,
            "provider_resubmitted": False,
            "output_ref": success["outputRef"],
        }
    finally:
        await worker.shutdown()


def main() -> None:
    result = asyncio.run(_recover(_arguments()))
    print(result)


if __name__ == "__main__":
    main()
