# -*- coding: utf-8 -*-
"""Protocol-1 Engine adapter for independent analysis tasks."""

from __future__ import annotations

import re
from typing import Any, AsyncGenerator, Callable

import httpx

from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    CommandLookup,
    ExecutorEvent,
    ExecutorRunRef,
    LocalizedText,
    SubmissionLookup,
    TaskExperienceContextItem,
    TaskExperienceDefinition,
    TaskExperienceStepDefinition,
    TaskExperienceStepState,
    TaskExperienceUpdate,
    TaskExperienceViewDefinition,
    TaskScope,
    TaskCommand,
    TaskStoreError,
    TaskSubmission,
)
from qwenpaw.pawapp.tasks.contracts import ArtifactPresentation, content_digest

from .events import TextProjection, read_frames

_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")


def data_action_descriptor() -> ActionDescriptor:
    """Server-owned contract; registration does not grant these permissions."""
    return ActionDescriptor(
        app_id="qwenpaw-data",
        action_id="analyze",
        summary=(
            "Analyze a selected datasource "
            "using the Data App's domain runtime."
        ),
        engagements=("delegated", "direct"),
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "datasource_id": {"type": "string", "minLength": 1},
            },
            "required": ["text", "datasource_id"],
            "additionalProperties": False,
        },
        output_types=("text/plain", "qwenpaw:file"),
        permissions=("data.analysis.execute", "data.datasource.read"),
        effects=("model_usage", "datasource_query"),
        adapter_ref="qwenpaw-data.analysis.v1",
    )


def data_session_action_descriptor() -> ActionDescriptor:
    """Native Console turns keep the selected session and its input context."""
    base = data_action_descriptor()
    schema = base.model_dump(mode="json")["input_schema"]
    schema["properties"].update(
        {
            "session_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "attachment_ids": {
                "type": "array",
                "maxItems": 32,
                "items": {"type": "string"},
            },
            "artifact_comments": {
                "type": "array",
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string"},
                        "line_start": {"type": "integer"},
                        "line_end": {"type": "integer"},
                        "comment": {"type": "string"},
                    },
                    "required": ["path", "line_start", "line_end", "comment"],
                },
            },
        }
    )
    schema["required"].append("session_id")
    return base.model_copy(
        update={
            "action_id": "analyze-session",
            "engagements": ("direct",),
            "summary": "Analyze data in an existing Data session, retaining its files and history.",
            "input_schema": schema,
        }
    )


def data_task_experience(
    action_id: str = "analyze",
) -> TaskExperienceDefinition:
    """Describe Data's business-facing task experience for Main Chat."""

    def text(default: str, zh: str) -> LocalizedText:
        return LocalizedText(default=default, translations={"zh-CN": zh})

    return TaskExperienceDefinition(
        action_id=action_id,
        title=text("Data analysis", "数据分析"),
        steps=tuple(
            TaskExperienceStepDefinition(id=step_id, label=text(en, zh))
            for step_id, en, zh in (
                ("read_data", "Read data", "读取数据"),
                ("confirm_scope", "Confirm scope", "确认口径"),
                ("analyze", "Analyze", "分析归因"),
                ("publish_report", "Publish report", "发布报告"),
            )
        ),
        views=(
            TaskExperienceViewDefinition(
                id="summary",
                label=text("Summary", "结论"),
                open_label=text("Open analysis", "打开分析"),
            ),
            TaskExperienceViewDefinition(
                id="evidence",
                label=text("Evidence", "证据"),
                open_label=text("Review evidence", "查看证据"),
            ),
            TaskExperienceViewDefinition(
                id="diagnostics",
                label=text("Diagnostics", "诊断"),
                open_label=text("Open diagnostics", "打开诊断"),
            ),
        ),
        default_view_id="summary",
    )


def _data_experience_update(
    submission: TaskSubmission,
    event: ExecutorEvent,
) -> TaskExperienceUpdate:
    step_ids = ("read_data", "confirm_scope", "analyze", "publish_report")
    if event.status == "waiting_for_input":
        active = "confirm_scope"
    elif event.status == "succeeded":
        active = "publish_report"
    else:
        active = event.detail.get("analysis_stage", "read_data")
    active_index = step_ids.index(active)
    failed = event.status in {"failed", "cancelled", "interrupted"}
    succeeded = event.status == "succeeded"
    waiting = event.status == "waiting_for_input"
    states = []
    for index, step_id in enumerate(step_ids):
        if succeeded or index < active_index:
            status = "complete"
        elif index > active_index:
            status = "pending"
        elif failed:
            status = "failed"
        elif waiting:
            status = "waiting"
        else:
            status = "running"
        states.append(TaskExperienceStepState(step_id=step_id, status=status))
    return TaskExperienceUpdate(
        step_states=tuple(states),
        active_step_id=active,
        context_items=(
            TaskExperienceContextItem(
                id="datasource",
                label=LocalizedText(
                    default="Data source",
                    translations={"zh-CN": "数据源"},
                ),
                value=submission.inputs["datasource_id"],
            ),
        ),
        view_id="summary",
    )


def _artifact_presentation(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("presentation") is not None:
        return ArtifactPresentation.model_validate(
            source["presentation"]
        ).model_dump(mode="json")
    # Compatibility only: new Engines explicitly classify every artifact.
    name = str(source.get("name", "")).casefold()
    path = str(source.get("path", "")).casefold()
    media_type = str(source.get("media_type", "")).casefold()
    business_report = any(
        token in f"{name} {path}"
        for token in ("report", "analysis", "summary", "insight")
    )
    if media_type.startswith("image/"):
        role, kind, visibility, preview, rank = (
            "supporting",
            "data/chart",
            "chat",
            "inline",
            20,
        )
    elif business_report and media_type in {
        "text/html",
        "text/markdown",
        "application/pdf",
        "text/plain",
    }:
        role, kind, visibility, preview, rank = (
            "primary",
            "data/report",
            "chat",
            "inline" if media_type != "application/pdf" else "link",
            0,
        )
    elif media_type in {"text/csv", "application/csv"}:
        role, kind, visibility, preview, rank = (
            "source",
            "data/dataset",
            "app_only",
            "none",
            200,
        )
    else:
        role, kind, visibility, preview, rank = (
            "diagnostic",
            "data/diagnostic",
            "app_only",
            "none",
            300,
        )
    return {
        "schema_version": 1,
        "role": role,
        "kind": kind,
        "visibility": visibility,
        "preview": preview,
        "rank": rank,
    }


class DataTaskAdapter:
    """Bind one stable Engine identity to a trusted endpoint resolver.

    Ports and credentials may change at restart; executor_id must remain tied
    to the same persistent Engine database. Never derive the endpoint or token
    from action inputs. This client owns its HTTP connection pool.
    """

    submission_protocol_version = 1

    def __init__(
        self,
        endpoint: Callable[[], tuple[str, str]],
        *,
        executor_id: str,
        capability_bridge: (
            Callable[[TaskSubmission], dict[str, Any]] | None
        ) = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not executor_id or len(executor_id) > 256:
            raise ValueError("executor_id is required")
        self._endpoint = endpoint
        self._executor_id = executor_id
        self._capability_bridge = capability_bridge
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(60.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def identity_namespace(scope: TaskScope) -> str:
        """Stable business stamp, not an Engine-side authentication claim."""
        return "pawapp_" + content_digest(scope.model_dump(mode="json"))

    def _connection(self, scope: TaskScope) -> tuple[str, dict[str, str]]:
        if scope.app_id != "qwenpaw-data":
            raise TaskStoreError("data_action_scope_mismatch")
        try:
            base, token = self._endpoint()
            url = httpx.URL(base)
        except (RuntimeError, ValueError, TypeError, httpx.InvalidURL):
            raise TaskStoreError("engine_unavailable") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise TaskStoreError("invalid_engine_endpoint")
        headers = {"X-User-Id": self.identity_namespace(scope)}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return str(url).rstrip("/"), headers

    async def _json(
        self,
        connection: tuple[str, dict[str, str]],
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict:
        base, headers = connection
        try:
            response = await self._client.request(
                method,
                base + path,
                headers=headers,
                **kwargs,
            )
        except httpx.TransportError:
            raise TaskStoreError("engine_unavailable") from None
        if not response.is_success:
            raise TaskStoreError(f"engine_http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise TaskStoreError("invalid_engine_response") from None
        if not isinstance(payload, dict):
            raise TaskStoreError("invalid_engine_response")
        return payload

    async def _check_protocol(self, connection) -> dict:
        try:
            caps = await self._json(
                connection,
                "GET",
                "/api/v1/capabilities/submissions",
            )
        except TaskStoreError as exc:
            if exc.code in {"engine_http_404", "engine_http_501"}:
                raise TaskStoreError("unsupported_engine_protocol") from None
            raise
        if (
            type(caps.get("protocol_version")) is not int
            or caps["protocol_version"] != 1
            or caps.get("durable_submissions") is not True
            or caps.get("event_replay") is not True
            or caps.get("artifact_handoff") is not True
            or (
                self._capability_bridge is not None
                and caps.get("scoped_host_capabilities") is not True
            )
        ):
            raise TaskStoreError("unsupported_engine_protocol")
        return caps

    async def check_compatibility(self, scope: TaskScope) -> None:
        """Read-only durable submission protocol probe."""
        await self._check_protocol(self._connection(scope))

    async def readiness(self, scope: TaskScope, inputs: dict):
        """Check analysis model configuration and DataBridge source presence.

        A configured model/source is not a successful connectivity or SQL
        probe. Provider calls and SQL execute only after explicit dispatch.
        """
        from qwenpaw.pawapp.tasks.binding import Readiness

        try:
            connection = self._connection(scope)
            caps = await self._check_protocol(connection)
            if (
                "session_id" in inputs
                and caps.get("session_submissions") is not True
            ):
                return Readiness(
                    state="blocked", reason="unsupported_session_submissions"
                )
            if "session_id" in inputs:
                session_id = inputs["session_id"]
                if not isinstance(session_id, str) or not _ID.fullmatch(
                    session_id
                ):
                    return Readiness(
                        state="blocked", reason="session_unavailable"
                    )
                try:
                    session = await self._json(
                        connection,
                        "GET",
                        f"/api/v1/sessions/{session_id}/submission-readiness",
                    )
                except TaskStoreError as exc:
                    if exc.code == "engine_http_404":
                        return Readiness(
                            state="blocked", reason="session_unavailable"
                        )
                    raise
                if session.get("ready") is not True:
                    return Readiness(state="blocked", reason="session_busy")
            model = await self._json(
                connection,
                "GET",
                "/api/v1/capabilities/analysis",
            )
            if (
                type(model.get("readiness_version")) is not int
                or model["readiness_version"] != 1
                or type(model.get("model_configured")) is not bool
            ):
                return Readiness(
                    state="blocked",
                    reason="readiness_unsupported",
                )
            if not model["model_configured"]:
                return Readiness(
                    state="blocked",
                    reason="analysis_model_missing",
                )
            sources = await self._json(
                connection,
                "GET",
                "/api/v1/datasources",
            )
            items = sources.get("items")
            if not isinstance(items, list):
                return Readiness(
                    state="blocked",
                    reason="datasource_unavailable",
                )
            found = any(
                isinstance(item, dict)
                and item.get("id") == inputs.get("datasource_id")
                and item.get("status") == "ready"
                for item in items
            )
            return (
                Readiness(state="ready")
                if found
                else Readiness(
                    state="blocked",
                    reason="datasource_missing",
                )
            )
        except TaskStoreError as exc:
            reason = (
                "readiness_unsupported"
                if exc.code == "engine_http_404"
                else exc.code
            )
            return Readiness(state="blocked", reason=reason)

    def _lookup(self, payload: dict, submission_id: str) -> SubmissionLookup:
        if (
            type(payload.get("protocol_version")) is not int
            or payload["protocol_version"] != 1
            or payload.get("submission_id") != submission_id
        ):
            raise TaskStoreError("invalid_engine_response")
        state, run = payload.get("state"), payload.get("run")
        if state == "not_found" and run is None:
            return SubmissionLookup(state="not_found")
        if state != "accepted" or not isinstance(run, dict):
            raise TaskStoreError("invalid_engine_response")
        if any(
            not isinstance(run.get(key), str) or not _ID.fullmatch(run[key])
            for key in ("session_id", "run_id")
        ):
            raise TaskStoreError("invalid_engine_response")
        return SubmissionLookup(
            state="accepted",
            run_ref=ExecutorRunRef(
                executor_id=self._executor_id,
                session_id=run["session_id"],
                run_id=run["run_id"],
            ),
        )

    @staticmethod
    def _submission_id(submission: TaskSubmission) -> str:
        submission_id = submission.handle.submission_id
        if not _ID.fullmatch(submission_id) or len(submission_id) > 128:
            raise TaskStoreError("invalid_submission_id")
        return submission_id

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        descriptor = (
            data_session_action_descriptor()
            if submission.action.action_id == "analyze-session"
            else data_action_descriptor()
        )
        if submission.action.descriptor_digest != descriptor.descriptor_digest:
            raise TaskStoreError("data_action_mismatch")
        descriptor.validate_inputs(submission.inputs)
        if any(
            not value.strip()
            for value in submission.inputs.values()
            if isinstance(value, str)
        ):
            raise TaskStoreError("invalid_data_action_input")
        submission_id = self._submission_id(submission)
        connection = self._connection(submission.handle.scope)
        caps = await self._check_protocol(connection)
        if (
            "session_id" in submission.inputs
            and caps.get("session_submissions") is not True
        ):
            raise TaskStoreError("unsupported_session_submissions")
        body = {
            "protocol_version": 1,
            "submission_id": submission_id,
            "agent_id": "default",
            **submission.inputs,
        }
        if self._capability_bridge is not None:
            body["capability_bridge"] = self._capability_bridge(submission)
        payload = await self._json(
            connection,
            "POST",
            "/api/v1/submissions",
            json=body,
        )
        lookup = self._lookup(payload, submission_id)
        if lookup.run_ref is None:
            raise TaskStoreError("invalid_engine_acceptance")
        return lookup.run_ref

    @staticmethod
    def _command_lookup(payload: dict, command: TaskCommand) -> CommandLookup:
        if (
            payload.get("protocol_version") != 1
            or payload.get("submission_id") is None
            or payload.get("command_id") != command.command_id
            or payload.get("kind") not in {command.kind, None}
        ):
            raise TaskStoreError("invalid_engine_response")
        state = payload.get("state")
        if state not in {"accepted", "rejected", "not_found", "unknown"}:
            raise TaskStoreError("invalid_engine_response")
        reason = payload.get("reason")
        if reason is not None and (
            not isinstance(reason, str) or not 1 <= len(reason) <= 256
        ):
            raise TaskStoreError("invalid_engine_response")
        return CommandLookup(state=state, reason=reason)

    async def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        connection = self._connection(submission.handle.scope)
        caps = await self._check_protocol(connection)
        if caps.get("durable_commands") is not True:
            raise TaskStoreError("unsupported_engine_commands")
        body: dict[str, Any] = {
            "protocol_version": 1,
            "command_id": command.command_id,
            "kind": command.kind,
        }
        if command.kind == "answer":
            body.update(
                {
                    "request_id": command.request_id,
                    "answers": command.payload["answers"],
                },
            )
        elif command.payload.get("reason"):
            body["reason"] = command.payload["reason"]
        submission_id = self._submission_id(submission)
        payload = await self._json(
            connection,
            "POST",
            f"/api/v1/submissions/{submission_id}/commands",
            json=body,
        )
        if payload.get("submission_id") != submission_id:
            raise TaskStoreError("invalid_engine_response")
        return self._command_lookup(payload, command)

    async def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        connection = self._connection(submission.handle.scope)
        caps = await self._check_protocol(connection)
        if caps.get("durable_commands") is not True:
            raise TaskStoreError("unsupported_engine_commands")
        submission_id = self._submission_id(submission)
        payload = await self._json(
            connection,
            "GET",
            "/api/v1/submissions/"
            f"{submission_id}/commands/{command.command_id}",
        )
        if payload.get("submission_id") != submission_id:
            raise TaskStoreError("invalid_engine_response")
        return self._command_lookup(payload, command)

    async def query(self, submission: TaskSubmission) -> SubmissionLookup:
        submission_id = self._submission_id(submission)
        connection = self._connection(submission.handle.scope)
        try:
            await self._check_protocol(connection)
            payload = await self._json(
                connection,
                "GET",
                f"/api/v1/submissions/{submission_id}",
            )
            return self._lookup(payload, submission_id)
        except TaskStoreError:
            # Only the explicit, validated not_found response permits a retry.
            return SubmissionLookup(state="unknown")

    async def _download_artifact(
        self,
        submission: TaskSubmission,
        artifact: dict[str, Any],
    ) -> bytes:
        connection = self._connection(submission.handle.scope)
        base, headers = connection
        run = submission.handle.executor_run_ref
        if run is None:
            raise TaskStoreError("artifact_run_missing")
        try:
            response = await self._client.get(
                f"{base}/api/v1/sessions/{run.session_id}/artifacts/file",
                headers=headers,
                params={
                    "path": artifact["path"],
                    "digest": artifact["digest"],
                },
            )
        except httpx.TransportError:
            raise TaskStoreError("engine_unavailable") from None
        if not response.is_success:
            raise TaskStoreError(
                f"engine_artifact_http_{response.status_code}",
            )
        content = response.content
        if len(content) > 64 * 1024 * 1024:
            raise TaskStoreError("artifact_too_large")
        return content

    async def materialize_event(self, submission, event, artifacts):
        """Copy executor files into immutable Host storage before commit."""
        detail = dict(event.detail)
        run = submission.handle.executor_run_ref
        if event.sequence == 0 and run is not None:
            detail["project_ref"] = {
                "schema_version": 1,
                "app_id": submission.handle.scope.app_id,
                "project_id": run.session_id,
                "kind": "analysis-session",
                "revision": 1,
            }
        source = event.detail.get("artifact")
        if source is None:
            return event.model_copy(update={"detail": detail})
        source = {
            **source,
            "presentation": _artifact_presentation(source),
        }
        content = await self._download_artifact(submission, source)
        ref = await artifacts.publish(submission, source, content)
        detail.pop("artifact", None)
        detail["artifact_ref"] = ref.model_dump(mode="json")
        return event.model_copy(update={"detail": detail})

    async def attach(
        self,
        submission: TaskSubmission,
    ) -> AsyncGenerator[ExecutorEvent, None]:
        handle = submission.handle
        ref = handle.executor_run_ref
        if ref is None or ref.executor_id != self._executor_id:
            raise TaskStoreError("run_conflict")
        cursor = handle.replay_cursor
        if cursor is not None and (
            not cursor.isascii()
            or not cursor.isdecimal()
            or str(int(cursor)) != cursor
            or handle.executor_sequence != int(cursor)
        ):
            raise TaskStoreError("invalid_engine_cursor")
        after = -1 if cursor is None else int(cursor)
        connection = self._connection(handle.scope)
        submission_id = self._submission_id(submission)
        await self._check_protocol(connection)
        lookup = self._lookup(
            await self._json(
                connection,
                "GET",
                f"/api/v1/submissions/{submission_id}",
            ),
            submission_id,
        )
        if lookup.run_ref != ref:
            raise TaskStoreError("run_conflict")
        base, headers = connection
        projection = TextProjection(ref)
        replayed_text = None
        try:
            async with self._client.stream(
                "GET",
                f"{base}/api/v1/submissions/{submission_id}/events",
                headers=headers,
                # Rebuild projection state before emitting new full snapshots.
                params={"after_sequence_number": -1},
            ) as response:
                if response.status_code != 200:
                    raise TaskStoreError(f"engine_http_{response.status_code}")
                if not response.headers.get("content-type", "").startswith(
                    "text/event-stream",
                ):
                    raise TaskStoreError("invalid_engine_stream")
                async for frame in read_frames(response.aiter_lines()):
                    event = projection.apply(frame)
                    if event.text_result is not None:
                        replayed_text = event.text_result
                    if submission.handle.experience is not None:
                        detail = dict(event.detail)
                        detail["experience_update"] = _data_experience_update(
                            submission,
                            event,
                        ).model_dump(mode="json")
                        event = event.model_copy(update={"detail": detail})
                    if event.sequence == after and (
                        handle.text_result is not None
                        and replayed_text != handle.text_result
                    ):
                        raise TaskStoreError("engine_replay_conflict")
                    if event.sequence > after:
                        yield event
                        if event.status == "waiting_for_input":
                            return
                    if projection.terminal:
                        if event.sequence <= after:
                            raise TaskStoreError("engine_replay_conflict")
                        return
        except httpx.TransportError:
            raise TaskStoreError("engine_unavailable") from None
        if projection.sequence < after:
            raise TaskStoreError("engine_replay_incomplete")
