# -*- coding: utf-8 -*-
"""Reliability adapters for ReMe's Auto-Dream integration steps.

ReMe owns the generic dream workflow, while QwenPaw owns the embedded
execution boundary.  These adapters keep the dependency pinned and make the
boundary resilient to transient structured-output failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reme.components import R
from reme.enumeration import DreamBucketEnum
from reme.schema import IntegrateOutcome
from reme.steps.evolve.dream.finish import DreamFinishStep
from reme.steps.evolve.dream.integrate import DreamIntegrateStep
from reme.steps.evolve.dream.utils import (
    pack_paths,
    parse_structured_reply,
    state_from_context,
    store_state,
)
from reme.steps.evolve._evolve import agent_reply_result_text


_TOOLS = (
    "node_search",
    "read",
    "frontmatter_read",
    "write",
    "edit",
    "frontmatter_update",
)
_READ_ONLY_TOOLS = ("node_search", "read", "frontmatter_read")
_MAX_RETRY_CONTEXT_CHARS = 4000
_registered = False


class _StructuredReplyError(ValueError):
    """Carry the malformed response into the single retry prompt."""

    def __init__(self, message: str, raw_result: str):
        super().__init__(message)
        self.raw_result = raw_result


def classify_dream_status(state: Any) -> str:
    """Return the user-visible status for an Auto-Dream run."""
    if not state.failed_units and not state.errors:
        return "success"
    if state.integrate_results:
        return "partial"
    return "error"


def _normalize_bucket(raw_bucket: Any) -> str:
    try:
        return DreamBucketEnum(str(raw_bucket or "")).value
    except ValueError:
        return DreamBucketEnum.WIKI.value


def _unit_key(unit: dict[str, Any], bucket: str, paths: list[str]) -> tuple:
    """Build a stable identity for idempotent unit handling."""
    return (
        str(unit.get("name") or "").strip(),
        bucket,
        tuple(dict.fromkeys(paths)),
    )


def _result_key(result: dict[str, Any]) -> tuple:
    return (
        str(result.get("unit") or "").strip(),
        str(result.get("bucket") or "").strip(),
        tuple(dict.fromkeys(str(p) for p in result.get("paths") or [])),
    )


def _snapshot_digest(
    workspace: Path,
    digest_dir: str,
) -> dict[str, tuple[int, int]]:
    """Capture digest file metadata to detect writes made by an LLM attempt."""
    root = workspace / digest_dir
    if not root.is_dir():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path.relative_to(workspace).as_posix()] = (
            stat.st_mtime_ns,
            stat.st_size,
        )
    return snapshot


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".strip()


class QwenPawDreamIntegrateStep(DreamIntegrateStep):
    """Retry malformed unit metadata without repeating completed writes."""

    async def _integrate_one(
        self,
        state,
        unit: dict,
        index: int,
        workspace: Path,
        digest_dir: str,
    ) -> None:
        bucket = _normalize_bucket(unit.get("bucket"))
        paths = [str(p) for p in unit.get("paths", [])]
        key = _unit_key(unit, bucket, paths)

        if any(
            _result_key(result) == key for result in state.integrate_results
        ):
            self.logger.info(
                f"[{self.name}] unit {index}/{len(state.units)} "
                "already integrated; skip",
            )
            return

        self.logger.info(
            f"[{self.name}] unit {index}/{len(state.units)} start "
            f"name={unit.get('name', '')!r} bucket={bucket} "
            f"paths={len(paths)}",
        )
        user_message = self.prompt_format(
            "integrate_user_message",
            hint=state.hint or "(none)",
            unit_name=unit.get("name", ""),
            unit_bucket=bucket,
            unit_summary=unit.get("summary", ""),
            unit_paths_json=json.dumps(paths, ensure_ascii=False, indent=2),
            material_blob=pack_paths(workspace, paths),
        )
        system_prompt = self.prompt_format(
            f"integrate_system_prompt_{bucket}",
            workspace_dir=str(workspace),
            digest_dir=digest_dir,
            bucket=bucket,
        )

        before = _snapshot_digest(workspace, digest_dir)
        errors: list[str] = []
        raw_result = ""
        try:
            raw_result, outcome = await self._reply_and_validate(
                user_message,
                system_prompt,
                list(_TOOLS),
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, _StructuredReplyError):
                raw_result = exc.raw_result
            errors.append(_error_text(exc))

        if not errors:
            self._record_success(state, unit, bucket, paths, outcome)
            self.logger.info(
                f"[{self.name}] unit {index}/{len(state.units)} done "
                f"action={outcome.action} target_path={outcome.target_path}",
            )
            return

        after = _snapshot_digest(workspace, digest_dir)
        write_detected = before != after
        retry_tools = _READ_ONLY_TOOLS if write_detected else _TOOLS
        retry_context = (
            "\n\nAutomatic recovery attempt (1 of 1): "
            "the previous response failed "
            "structured validation. Return only a complete JSON object with "
            "action, target_path, and optional note."
        )
        if raw_result:
            retry_context += (
                " The previous raw response was:\n"
                f"{raw_result[:_MAX_RETRY_CONTEXT_CHARS]}"
            )
        retry_context += "\nPrevious validation error: " + errors[-1] + "."
        if write_detected:
            retry_context += (
                " The previous attempt changed a digest file. Inspect the "
                "existing file and do not call write, edit, or "
                "frontmatter_update again."
            )
        try:
            retry_raw, outcome = await self._reply_and_validate(
                user_message + retry_context,
                system_prompt,
                list(retry_tools),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(_error_text(exc))
            retry_raw = ""
        if errors and retry_raw:
            raw_result = retry_raw

        if len(errors) >= 2:
            error = f"retry exhausted: first={errors[0]}; retry={errors[-1]}"
            self._record_failure(state, unit, bucket, paths, error)
            self.logger.error(
                f"[{self.name}] unit {index}/{len(state.units)} "
                f"failed: {error}",
            )
            return

        self._record_success(state, unit, bucket, paths, outcome)
        self.logger.info(
            f"[{self.name}] unit {index}/{len(state.units)} "
            "recovered on retry "
            f"action={outcome.action} target_path={outcome.target_path}",
        )

    async def _reply_and_validate(
        self,
        user_message: str,
        system_prompt: str,
        job_tools: list[str],
    ) -> tuple[str, IntegrateOutcome]:
        result = await self.agent_wrapper.reply(
            user_message,
            system_prompt=system_prompt,
            job_tools=job_tools,
        )
        raw_result = agent_reply_result_text(result)
        try:
            outcome = IntegrateOutcome.model_validate(
                parse_structured_reply(raw_result),
            )
        except Exception as exc:  # noqa: BLE001
            raise _StructuredReplyError(_error_text(exc), raw_result) from exc
        return raw_result, outcome

    @staticmethod
    def _record_failure(
        state,
        unit: dict,
        bucket: str,
        paths: list[str],
        error: str,
    ) -> None:
        key = _unit_key(unit, bucket, paths)
        state.failed_units[:] = [
            failed
            for failed in state.failed_units
            if _unit_key(
                failed,
                _normalize_bucket(failed.get("bucket")),
                [str(p) for p in failed.get("paths") or []],
            )
            != key
        ]
        state.failed_units.append({**unit, "error": error})
        for path in paths:
            if path not in state.failed_paths:
                state.failed_paths.append(path)

    @staticmethod
    def _record_success(
        state,
        unit: dict,
        bucket: str,
        paths: list[str],
        outcome: IntegrateOutcome,
    ) -> None:
        key = _unit_key(unit, bucket, paths)
        state.failed_units[:] = [
            failed
            for failed in state.failed_units
            if _unit_key(
                failed,
                _normalize_bucket(failed.get("bucket")),
                [str(p) for p in failed.get("paths") or []],
            )
            != key
        ]
        result = {
            "unit": unit.get("name", ""),
            "bucket": bucket,
            "paths": paths,
            "action": outcome.action,
            "target_path": outcome.target_path,
            "note": outcome.note,
        }
        if not any(
            _result_key(existing) == key
            for existing in state.integrate_results
        ):
            state.integrate_results.append(result)
        target = outcome.target_path
        targets = (
            state.nodes_created
            if outcome.action == "CREATE"
            else state.nodes_updated
        )
        if target not in targets:
            targets.append(target)
        failed_paths = {
            path
            for failed in state.failed_units
            for path in failed.get("paths") or []
        }
        state.failed_paths[:] = [
            path for path in state.failed_paths if path in failed_paths
        ]


class QwenPawDreamFinishStep(DreamFinishStep):
    """Expose success/partial/error without changing ReMe's catalog logic."""

    async def execute(self):
        result = await super().execute()
        assert self.context is not None
        state = state_from_context(self)
        status = classify_dream_status(state)
        metadata = self.context.response.metadata
        metadata["dream_status"] = status
        metadata["status"] = status
        answer = str(self.context.response.answer or "")
        if not answer.startswith("Status: "):
            answer = f"Status: {status}\n{answer}".strip()
        state.summary = answer
        store_state(self, state)
        self.context.response.answer = answer
        self.context.response.success = status == "success"
        return result


def register_reme_dream_resilience_steps() -> None:
    """Register QwenPaw's adapters after ReMe has loaded its built-ins."""
    global _registered
    if _registered:
        return
    R.register(QwenPawDreamIntegrateStep, "qwenpaw_dream_integrate_step")
    R.register(QwenPawDreamFinishStep, "qwenpaw_dream_finish_step")
    _registered = True


__all__ = [
    "QwenPawDreamFinishStep",
    "QwenPawDreamIntegrateStep",
    "classify_dream_status",
    "register_reme_dream_resilience_steps",
]
