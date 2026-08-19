# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-many-branches,too-many-return-statements
# pylint: disable=too-many-statements
"""File-native Project snapshot, patch, block, and Review endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator

from domain.errors import (
    CasConflictError,
    ConflictError,
    CreatorError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from schemas.common import StrictModel
from services.file_agent_runtime import notify_creator_agent_runtime
from services.project_files.commit import (
    ActiveReviewConflictError,
    CommitJournalState,
    ProjectCommitJournal,
    ProtectedFieldError,
    is_protected_pointer,
)
from services.project_files.edit_impact import (
    apply_frontend_edit_impacts,
    summarize_committed_edit_impact,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.json_pointer import (
    MISSING,
    JsonCasConflict,
    JsonChange,
    JsonPointerError,
    apply_changes,
    hash_json_value,
    pointers_overlap,
    value_at,
)
from services.project_files.review import (
    ReviewDecisionConflict,
    ReviewDecisionError,
    ReviewDecisionItem,
    ReviewRejectionFeedback,
    ReviewNotFound,
)
from services.project_files.models import Project
from services.project_files.serialization import project_etag
from services.project_files.store import (
    BUILTIN_EXAMPLE_MARKER,
    ProjectConflict,
    ProjectIntegrityError,
    ProjectNotFound,
    ProjectStoreError,
)
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.errors import (
    FieldBlockBaseConflictError,
    FieldBlockConflictError,
    FieldBlockTokenError,
    IdempotencyConflictError,
    RuntimeFileError,
)
from services.runtime_files.idempotency_store import IdempotencyRecordStore
from services.runtime_files.models import (
    IdempotencyRecord,
    IdempotencyStatus,
    RuntimeChangeSet,
)

from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
)


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["project-files"],
    route_class=CreatorErrorRoute,
)

logger = logging.getLogger("qwenpaw.creator.api.project_file_routes")

_PATCH_IDEMPOTENCY_SCOPE = "PATCH /projects/{projectId}/project"


class ProjectPatchOperation(StrictModel):
    op: Literal["add", "replace", "remove"]
    path: str = Field(min_length=1)
    value: Any = None
    expected_value_hash: str = Field(alias="expectedValueHash", min_length=1)

    @model_validator(mode="after")
    def validate_value_presence(self) -> ProjectPatchOperation:
        if self.op != "remove" and "value" not in self.model_fields_set:
            raise ValueError("add/replace operation requires value")
        return self


class ProjectPatchRequest(StrictModel):
    client_command_id: str = Field(alias="clientCommandId", min_length=1)
    edit_session_id: str = Field(alias="editSessionId", min_length=1)
    base_generation: int = Field(alias="baseGeneration", ge=0)
    base_etag: str = Field(alias="baseEtag", min_length=1)
    block_token: str | None = Field(default=None, alias="blockToken")
    operations: list[ProjectPatchOperation] = Field(min_length=1)


class FieldBlockAcquireRequest(StrictModel):
    json_pointer: str = Field(alias="jsonPointer", min_length=1)
    owner_kind: Literal["user", "agent", "runtime"] = Field(alias="ownerKind")
    owner_id: str = Field(alias="ownerId", min_length=1)
    base_field_hash: str = Field(alias="baseFieldHash", min_length=1)
    ttl_seconds: float = Field(15.0, alias="ttlSeconds", gt=0, le=300)


class FieldBlockRenewRequest(StrictModel):
    token: str = Field(min_length=1)
    ttl_seconds: float = Field(15.0, alias="ttlSeconds", gt=0, le=300)


class FieldBlockReleaseRequest(StrictModel):
    token: str = Field(min_length=1)


class ReviewDecisionRequest(StrictModel):
    decision_id: str = Field(alias="decisionId", min_length=1, max_length=192)
    decision_token: str = Field(alias="decisionToken", min_length=1)
    decisions: list[ReviewDecisionItem] = Field(min_length=1)
    rejection_feedback: ReviewRejectionFeedback | None = Field(
        default=None,
        alias="rejectionFeedback",
    )

    @model_validator(mode="after")
    def validate_rejection_feedback(self) -> ReviewDecisionRequest:
        if self.rejection_feedback is not None and not any(
            item.decision == "REJECT" for item in self.decisions
        ):
            raise ValueError(
                "rejectionFeedback requires at least one REJECT decision",
            )
        return self


def _etag_header(etag: str) -> str:
    return f'"{etag}"'


def _semantic_etag(value: str) -> str:
    """Reduce HTTP entity-tag forms (weak prefix, quotes) to the raw tag."""

    return value.strip().removeprefix("W/").strip().strip('"')


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return any(_semantic_etag(item) == etag for item in header.split(","))


def _project_headers(
    *,
    etag: str,
    generation: int,
    sync_status: str,
) -> dict[str, str]:
    return {
        "ETag": _etag_header(etag),
        "X-Project-Generation": str(generation),
        "X-Project-Sync-Status": sync_status,
        "Cache-Control": "no-cache",
    }


def _as_creator_error(error: BaseException) -> CreatorError:
    if isinstance(error, CreatorError):
        return error
    if isinstance(error, ProjectNotFound):
        return NotFoundError("Project 不存在")
    if isinstance(error, (JsonCasConflict, ProjectConflict)):
        details = (
            {"conflicts": error.conflicts}
            if isinstance(error, JsonCasConflict)
            else {}
        )
        return CasConflictError("Project 字段已被其他写者修改", details=details)
    if isinstance(error, IdempotencyConflictError):
        return ConflictError("Idempotency-Key 已用于不同请求")
    if isinstance(error, FieldBlockBaseConflictError):
        return CasConflictError(
            "Field Block 的字段基线已变化",
            details={"expected": error.expected, "actual": error.actual},
        )
    if isinstance(error, FieldBlockConflictError):
        return ConflictError(
            "目标字段正被其他写者编辑",
            details={
                "pointer": error.block.json_pointer,
                "blockId": error.block.block_id,
            },
        )
    if isinstance(error, ActiveReviewConflictError):
        return ConflictError(str(error))
    if isinstance(error, ProtectedFieldError):
        return ValidationError(
            "请求不能修改 Runtime protected fields",
            details={"pointers": error.pointers},
        )
    if isinstance(error, ReviewNotFound):
        return NotFoundError("Review 不存在")
    if isinstance(error, ReviewDecisionConflict):
        return CasConflictError(str(error))
    if isinstance(error, ReviewDecisionError):
        return ValidationError(str(error))
    if isinstance(error, (JsonPointerError, ValueError)):
        return ValidationError(str(error))
    if isinstance(
        error,
        (ProjectIntegrityError, ProjectStoreError, RuntimeFileError),
    ):
        return StorageIntegrityError(str(error))
    return StorageIntegrityError("Project 文件操作失败")


def _translate_storage_error(error: BaseException) -> None:
    mapped = _as_creator_error(error)
    if mapped is error:
        raise mapped
    raise mapped from error


def _creator_error_body(error: CreatorError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
        "details": error.details,
    }


def _replay_failed_idempotency(record: IdempotencyRecord) -> None:
    body = record.error
    response_status = record.response_status
    if not isinstance(body, dict) or not isinstance(response_status, int):
        raise StorageIntegrityError("Idempotency failure 快照损坏")
    code = body.get("code")
    message = body.get("message")
    retryable = body.get("retryable")
    details = body.get("details")
    if (
        not isinstance(code, str)
        or not isinstance(message, str)
        or not isinstance(retryable, bool)
        or not isinstance(details, dict)
    ):
        raise StorageIntegrityError("Idempotency failure 快照损坏")
    error = CreatorError(message, details=details)
    error.status_code = response_status
    error.code = code
    error.retryable = retryable
    raise error


def _completed_idempotency_body(record: IdempotencyRecord) -> dict[str, Any]:
    if not isinstance(record.response, dict) or not isinstance(
        record.response_status,
        int,
    ):
        raise StorageIntegrityError("Idempotency response 快照损坏")
    return record.response


def _patch_response_headers(response: Response, body: dict[str, Any]) -> None:
    etag = body.get("etag")
    generation = body.get("generation")
    if not isinstance(etag, str) or not isinstance(generation, int):
        raise StorageIntegrityError("Project Patch replay 快照损坏")
    response.headers.update(
        _project_headers(
            etag=etag,
            generation=generation,
            sync_status="healthy",
        ),
    )


def _recover_patch_response(
    services: CreatorFileServices,
    *,
    project_id: str,
    transaction_id: str,
    lifecycle_lock_held: bool = False,
) -> dict[str, Any] | None:
    """Recover/reconstruct a durable Patch result for an IN_PROGRESS record.

    ``project.json`` publication and Runtime finalization precede the HTTP
    idempotency result.  The deterministic transaction therefore acts as the
    durable witness when a worker dies in that narrow gap.  An unpublished or
    explicitly aborted transaction returns ``None`` and may be executed again;
    an ambiguous transaction fails closed.
    """

    runtime_root = services.projects.project_root(project_id) / "runtime"
    transaction_root = runtime_root / "transactions" / transaction_id
    journal_store = AtomicJsonRecordStore(
        transaction_root / "journal.json",
        ProjectCommitJournal,
    )
    journal = journal_store.read_or_none()
    if journal is None:
        return None
    if (
        journal.project_id != project_id
        or journal.transaction_id != transaction_id
    ):
        raise StorageIntegrityError("Project Patch transaction identity 损坏")

    if journal.state not in {
        CommitJournalState.ABORTED,
        CommitJournalState.RUNTIME_FINALIZED,
    }:
        services.recover_project(
            project_id,
            _lifecycle_lock_held=lifecycle_lock_held,
        )
        journal = journal_store.read()

    if journal.state is CommitJournalState.ABORTED:
        return None
    if journal.state is not CommitJournalState.RUNTIME_FINALIZED:
        raise StorageIntegrityError(
            "Project Patch transaction 尚未安全完成，不能猜测重放结果",
        )
    if journal.final_etag is None or journal.round_id is None:
        raise StorageIntegrityError("Project Patch finalized journal 损坏")

    # A changed transaction stores its exact published snapshot.  A no-change
    # transaction may omit final.json, in which case only an authority snapshot
    # with the journal's exact ETag is a valid reconstruction source.
    project = AtomicJsonRecordStore(
        transaction_root / "final.json",
        Project,
    ).read_or_none()
    if project is None:
        current = services.projects.read(project_id)
        if current.etag != journal.final_etag:
            raise StorageIntegrityError(
                "Project Patch no-change response snapshot 已不可重建",
            )
        project = current.project
    if (
        project.project_id != project_id
        or project_etag(project) != journal.final_etag
    ):
        raise StorageIntegrityError(
            "Project Patch final snapshot 与 journal 不一致",
        )

    transaction_changeset_path = transaction_root / "changeset.json"
    aggregate_changeset_path = (
        runtime_root / "change-rounds" / journal.round_id / "changeset.json"
    )
    changeset = AtomicJsonRecordStore(
        (
            transaction_changeset_path
            if transaction_changeset_path.is_file()
            else aggregate_changeset_path
        ),
        RuntimeChangeSet,
    ).read_or_none()
    if changeset is None:
        raise StorageIntegrityError("Project Patch ChangeSet 缺失")
    if (
        changeset.project_id != project_id
        or changeset.round_id != journal.round_id
        or changeset.final_etag != journal.final_etag
        or changeset.final_generation != project.generation
    ):
        raise StorageIntegrityError(
            "Project Patch ChangeSet 与 transaction 不一致",
        )

    project_data = project.model_dump(mode="json")
    changed_pointers = [
        item.json_pointer
        for item in changeset.changes
        if item.json_pointer is not None
    ]
    return {
        "projectId": project_id,
        "generation": project.generation,
        "etag": journal.final_etag,
        "changedPointers": changed_pointers,
        "project": project_data,
        "editImpact": summarize_committed_edit_impact(
            project_data,
            changed_pointers,
        ).response(),
    }


async def _require_existing_project(
    services: CreatorFileServices,
    project_id: str,
) -> None:
    await asyncio.to_thread(services.projects.read, project_id)


async def _acquire_existing_project_lifecycle(
    services: CreatorFileServices,
    project_id: str,
):
    """Enter lifecycle admission and revalidate the Project authority.

    Project-local stores create parent directories for durable locks and
    journals.  The authority check therefore has to happen *after* lifecycle
    admission; a check performed before the lock can race deletion and leave a
    phantom directory without ``project.json``.
    """

    lifecycle_lock = services.projects.lifecycle_lock(project_id)
    await asyncio.to_thread(lifecycle_lock.acquire)
    try:
        await _require_existing_project(services, project_id)
    except BaseException:
        lifecycle_lock.release()
        raise
    return lifecycle_lock


async def _persist_idempotent_failure(
    idempotency: IdempotencyRecordStore,
    *,
    project_id: str,
    scope: str,
    key: str,
    request_hash: str,
    error: CreatorError,
) -> None:
    await asyncio.to_thread(
        idempotency.fail_if_in_progress,
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
        error=_creator_error_body(error),
        response_status=error.status_code,
    )


@router.get("/project")
async def get_project_snapshot(
    project_id: str,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    try:
        entry = await services.snapshot(project_id)
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    snapshot = entry.snapshot
    if entry.sync_status == "invalid" or snapshot is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "PROJECT_INVALID",
                "syncStatus": entry.sync_status,
                "lastGoodGeneration": entry.generation,
                "message": entry.last_error or "project.json 未通过校验",
            },
            headers={"X-Project-Sync-Status": entry.sync_status},
        )
    headers = _project_headers(
        etag=snapshot.etag,
        generation=snapshot.generation,
        sync_status=entry.sync_status,
    )
    if _etag_matches(if_none_match, snapshot.etag):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )
    # Bundled example Projects carry a marker file; the frontend uses the
    # flag to gate flows that need the remote original source footage.
    builtin_example = (
        services.projects.project_root(project_id) / BUILTIN_EXAMPLE_MARKER
    ).exists()
    return JSONResponse(
        content={
            "projectId": project_id,
            "generation": snapshot.generation,
            "etag": snapshot.etag,
            "syncStatus": entry.sync_status,
            "builtinExample": builtin_example,
            "project": snapshot.project.model_dump(mode="json"),
        },
        headers=headers,
    )


def _build_patch_candidate(
    services: CreatorFileServices,
    project_id: str,
    request: ProjectPatchRequest,
):
    current = services.projects.read(project_id)
    if request.base_generation > current.generation:
        raise CasConflictError("baseGeneration 超前于当前 Project")
    if (
        request.base_generation == current.generation
        # The frontend echoes the HTTP ETag header, so accept the quoted
        # entity-tag form alongside the raw semantic tag.
        and _semantic_etag(request.base_etag) != current.etag
    ):
        raise CasConflictError("相同 generation 的 Project ETag 不匹配")
    active_blocks = services.blocks(project_id).list_active(
        project_id=project_id,
    )
    changes: list[JsonChange] = []
    document = current.project.model_dump(mode="json")
    for operation in request.operations:
        if is_protected_pointer(operation.path):
            raise ProtectedFieldError([operation.path])
        for block in active_blocks:
            if (
                pointers_overlap(operation.path, block.json_pointer)
                and request.block_token != block.token
            ):
                raise ConflictError(
                    "目标字段正被其他写者编辑",
                    details={
                        "pointer": operation.path,
                        "blockId": block.block_id,
                    },
                )
        before = value_at(document, operation.path)
        if hash_json_value(before) != operation.expected_value_hash:
            raise JsonCasConflict(
                [
                    {
                        "pointer": operation.path,
                        "expected": operation.expected_value_hash,
                        "actual": hash_json_value(before),
                    },
                ],
            )
        if operation.op == "add":
            if before is not MISSING:
                raise JsonPointerError(
                    f"add target already exists: {operation.path}",
                )
            change = JsonChange(
                "create",
                operation.path,
                MISSING,
                operation.value,
            )
        elif operation.op == "remove":
            if before is MISSING:
                raise JsonPointerError(
                    f"remove target does not exist: {operation.path}",
                )
            change = JsonChange("delete", operation.path, before, MISSING)
        else:
            if before is MISSING:
                raise JsonPointerError(
                    f"replace target does not exist: {operation.path}",
                )
            kind = "reorder" if operation.path.endswith("/order") else "update"
            change = JsonChange(kind, operation.path, before, operation.value)
        # Apply each operation in request order, matching JSON Patch semantics.
        document = apply_changes(document, [change])
        changes.append(change)
    return current, document


@router.patch("/project")
async def patch_project(
    project_id: str,
    request: ProjectPatchRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    key = resolve_idempotency_key(
        idempotency_key,
        stable_client_id=request.client_command_id,
    )
    try:
        await _require_existing_project(services, project_id)
    except Exception as exc:
        _translate_storage_error(exc)
        raise

    scope = _PATCH_IDEMPOTENCY_SCOPE
    payload = request.model_dump(mode="json", by_alias=True)
    idempotency = IdempotencyRecordStore(
        services.projects.project_root(project_id)
        / "runtime"
        / "commands"
        / "idempotency",
    )
    request_hash = idempotency.request_hash(payload)
    operation_id = idempotency.operation_id(
        namespace="project-patch",
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
    )
    lifecycle_lock = services.projects.lifecycle_lock(project_id)
    try:
        await asyncio.to_thread(lifecycle_lock.acquire)
        # Close the read/delete window before any idempotency or operation lock
        # is allowed to materialize a path below the Project directory.
        await _require_existing_project(services, project_id)
    except Exception as exc:
        lifecycle_lock.release()
        _translate_storage_error(exc)
        raise
    try:
        reservation = await asyncio.to_thread(
            idempotency.reserve,
            owner_id=project_id,
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
            record_id=operation_id,
        )
    except Exception as exc:
        lifecycle_lock.release()
        _translate_storage_error(exc)
        raise

    operation_lock = idempotency.operation_lock(
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
    )
    try:
        await asyncio.to_thread(operation_lock.acquire)
    except Exception as exc:
        lifecycle_lock.release()
        _translate_storage_error(exc)
        raise

    try:
        record = await asyncio.to_thread(
            idempotency.get,
            owner_id=project_id,
            scope=scope,
            idempotency_key=key,
        )
        if record is None:
            raise StorageIntegrityError(
                "Project Patch idempotency reservation 丢失",
            )
        if record.status is IdempotencyStatus.COMPLETED:
            body = _completed_idempotency_body(record)
            _patch_response_headers(response, body)
            response.headers["X-Idempotent-Replay"] = "true"
            return body
        if record.status is IdempotencyStatus.FAILED:
            _replay_failed_idempotency(record)
        if record.record_id != operation_id:
            raise StorageIntegrityError(
                "Project Patch IN_PROGRESS reservation 未关联确定性 transaction",
            )

        try:
            body = await asyncio.to_thread(
                _recover_patch_response,
                services,
                project_id=project_id,
                transaction_id=operation_id,
                lifecycle_lock_held=True,
            )
            recovered = body is not None
            if body is None:
                base, candidate = await asyncio.to_thread(
                    _build_patch_candidate,
                    services,
                    project_id,
                    request,
                )
                candidate, _ = apply_frontend_edit_impacts(
                    candidate,
                    [operation.path for operation in request.operations],
                    base=base.project.model_dump(mode="json"),
                )
                result = await services.commit_candidate(
                    base=base,
                    candidate=candidate,
                    origin="frontend_edit",
                    review_policy="auto_fix",
                    caused_by_request_id=request.client_command_id,
                    round_id=operation_id,
                    transaction_id=operation_id,
                    block_token=request.block_token,
                    _lifecycle_lock_held=True,
                )
                project_data = result.snapshot.project.model_dump(mode="json")
                changed_pointers = [
                    item.json_pointer
                    for item in result.changeset.changes
                    if item.json_pointer is not None
                ]
                body = {
                    "projectId": project_id,
                    "generation": result.snapshot.generation,
                    "etag": result.snapshot.etag,
                    "changedPointers": changed_pointers,
                    "project": project_data,
                    "editImpact": summarize_committed_edit_impact(
                        project_data,
                        changed_pointers,
                    ).response(),
                }
        except Exception as exc:
            # A storage failure can be raised after project.json was already
            # published.  Reconcile the deterministic transaction before
            # deciding that the business operation failed; otherwise a true
            # success could be frozen as a terminal FAILED idempotency record.
            try:
                recovered_body = await asyncio.to_thread(
                    _recover_patch_response,
                    services,
                    project_id=project_id,
                    transaction_id=operation_id,
                    lifecycle_lock_held=True,
                )
            except Exception as recovery_exc:
                # Ambiguous durable evidence must remain IN_PROGRESS for
                # operator/startup recovery; never rewrite it as a known
                # mutation failure.
                _translate_storage_error(recovery_exc)
                raise
            if recovered_body is not None:
                body = recovered_body
                recovered = True
            else:
                mapped = _as_creator_error(exc)
                try:
                    await _persist_idempotent_failure(
                        idempotency,
                        project_id=project_id,
                        scope=scope,
                        key=key,
                        request_hash=request_hash,
                        error=mapped,
                    )
                except Exception as persist_exc:
                    _translate_storage_error(persist_exc)
                    raise
                if mapped is exc:
                    raise
                raise mapped from exc

        # Completion persistence is not part of the Project mutation itself.
        # If this write fails, retaining IN_PROGRESS is essential: the next
        # request can prove the deterministic transaction and finish it.  It
        # must never be rewritten as a terminal mutation failure.
        try:
            await asyncio.to_thread(
                idempotency.complete,
                owner_id=project_id,
                scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                response=body,
                response_status=200,
            )
        except Exception as exc:
            _translate_storage_error(exc)
            raise
        _patch_response_headers(response, body)
        if recovered or not reservation.created:
            response.headers["X-Idempotent-Replay"] = "true"
        return body
    finally:
        operation_lock.release()
        lifecycle_lock.release()


@router.post("/runtime/blocks", status_code=status.HTTP_201_CREATED)
async def acquire_field_block(
    project_id: str,
    request: FieldBlockAcquireRequest,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    lifecycle_lock = None
    try:
        lifecycle_lock = await _acquire_existing_project_lifecycle(
            services,
            project_id,
        )
        block = await asyncio.to_thread(
            services.blocks(project_id).acquire,
            project_id=project_id,
            json_pointer=request.json_pointer,
            owner_kind=request.owner_kind,
            owner_id=request.owner_id,
            base_field_hash=request.base_field_hash,
            ttl_seconds=request.ttl_seconds,
            current_field_hash=lambda: hash_json_value(
                value_at(
                    services.projects.read(project_id).project.model_dump(
                        mode="json",
                    ),
                    request.json_pointer,
                ),
            ),
        )
        return block.model_dump(mode="json", by_alias=True)
    except FieldBlockConflictError as exc:
        raise ConflictError(
            "目标字段已有 Block",
            details={"blockId": exc.block.block_id},
        ) from exc
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    finally:
        if lifecycle_lock is not None:
            lifecycle_lock.release()


@router.patch("/runtime/blocks/{block_id}")
async def renew_field_block(
    project_id: str,
    block_id: str,
    request: FieldBlockRenewRequest,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    lifecycle_lock = None
    try:
        lifecycle_lock = await _acquire_existing_project_lifecycle(
            services,
            project_id,
        )
        block = await asyncio.to_thread(
            services.blocks(project_id).renew,
            block_id,
            token=request.token,
            ttl_seconds=request.ttl_seconds,
        )
        return block.model_dump(mode="json", by_alias=True)
    except FieldBlockTokenError as exc:
        raise ConflictError("Field Block token 不匹配") from exc
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    finally:
        if lifecycle_lock is not None:
            lifecycle_lock.release()


@router.delete(
    "/runtime/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release_field_block(
    project_id: str,
    block_id: str,
    request: FieldBlockReleaseRequest,
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    lifecycle_lock = None
    try:
        lifecycle_lock = await _acquire_existing_project_lifecycle(
            services,
            project_id,
        )
        await asyncio.to_thread(
            services.blocks(project_id).release,
            block_id,
            token=request.token,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except FieldBlockTokenError as exc:
        raise ConflictError("Field Block token 不匹配") from exc
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    finally:
        if lifecycle_lock is not None:
            lifecycle_lock.release()


@router.get("/runtime/reviews/active")
async def active_project_reviews(
    project_id: str,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    lifecycle_lock = None
    try:
        lifecycle_lock = await _acquire_existing_project_lifecycle(
            services,
            project_id,
        )
        reviews = await services.active_reviews(project_id)
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    finally:
        if lifecycle_lock is not None:
            lifecycle_lock.release()
    if not reviews:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    composite_token = "|".join(r.decision_token for r in reviews)
    if _etag_matches(if_none_match, composite_token):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": _etag_header(composite_token)},
        )
    return JSONResponse(
        content=[r.model_dump(mode="json") for r in reviews],
        headers={
            "ETag": _etag_header(composite_token),
            "Cache-Control": "no-cache",
        },
    )


@router.post("/runtime/reviews/{review_id}/decisions")
async def decide_project_review(
    project_id: str,
    review_id: str,
    request: ReviewDecisionRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    decisions_summary = ",".join(
        f"{item.operation_id}={item.decision}" for item in request.decisions
    )
    logger.info(
        "review decided: project=%s review=%s decisions=%s feedback=%s",
        project_id,
        review_id,
        decisions_summary,
        "yes" if request.rejection_feedback is not None else "no",
    )
    key = resolve_idempotency_key(
        idempotency_key,
        stable_client_id=request.decision_id,
    )
    scope = (
        f"POST /projects/{{projectId}}/runtime/reviews/{review_id}/decisions"
    )
    payload = {
        "reviewId": review_id,
        **request.model_dump(mode="json", by_alias=True),
    }
    idempotency = IdempotencyRecordStore(
        services.projects.project_root(project_id)
        / "runtime"
        / "commands"
        / "idempotency",
    )
    request_hash = idempotency.request_hash(payload)
    operation_id = idempotency.operation_id(
        namespace="review-decision",
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
    )
    try:
        lifecycle_lock = await _acquire_existing_project_lifecycle(
            services,
            project_id,
        )
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    try:
        reservation = await asyncio.to_thread(
            idempotency.reserve,
            owner_id=project_id,
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
            record_id=operation_id,
        )
    except Exception as exc:
        lifecycle_lock.release()
        _translate_storage_error(exc)
        raise

    operation_lock = idempotency.operation_lock(
        owner_id=project_id,
        scope=scope,
        idempotency_key=key,
    )
    try:
        await asyncio.to_thread(operation_lock.acquire)
    except Exception as exc:
        lifecycle_lock.release()
        _translate_storage_error(exc)
        raise

    try:
        record = await asyncio.to_thread(
            idempotency.get,
            owner_id=project_id,
            scope=scope,
            idempotency_key=key,
        )
        if record is None:
            raise StorageIntegrityError(
                "Review decision idempotency reservation 丢失",
            )
        if record.status is IdempotencyStatus.COMPLETED:
            response.headers["X-Idempotent-Replay"] = "true"
            body = _completed_idempotency_body(record)
        else:
            if record.status is IdempotencyStatus.FAILED:
                _replay_failed_idempotency(record)
            if record.record_id != operation_id:
                raise StorageIntegrityError(
                    "Review decision IN_PROGRESS reservation 未关联确定性 operation",
                )

            recovered = False
            try:
                # The Review service journals by decision_id. Re-entering with
                # the identical request resumes the same semantic operation.
                review = await services.decide_review(
                    project_id=project_id,
                    review_id=review_id,
                    decision_token=request.decision_token,
                    decisions=request.decisions,
                    rejection_feedback=request.rejection_feedback,
                    decision_id=request.decision_id,
                    _lifecycle_lock_held=True,
                )
                body = review.model_dump(mode="json")
            except Exception as exc:
                try:
                    # The service-level decision journal makes this an exact
                    # resume, not a second semantic operation.
                    resumed_review = await services.decide_review(
                        project_id=project_id,
                        review_id=review_id,
                        decision_token=request.decision_token,
                        decisions=request.decisions,
                        rejection_feedback=request.rejection_feedback,
                        decision_id=request.decision_id,
                        _lifecycle_lock_held=True,
                    )
                    body = resumed_review.model_dump(mode="json")
                    recovered = True
                except Exception as resume_exc:
                    journal = await asyncio.to_thread(
                        services.reviews._decision_journal_store(
                            runtime_root=services.projects.project_root(
                                project_id,
                            )
                            / "runtime",
                            review_id=review_id,
                            decision_id=request.decision_id,
                        ).read_or_none,
                    )
                    if journal is not None:
                        mapped_resume = _as_creator_error(resume_exc)
                        if mapped_resume is resume_exc:
                            raise
                        raise mapped_resume from resume_exc
                    mapped = _as_creator_error(exc)
                    try:
                        await _persist_idempotent_failure(
                            idempotency,
                            project_id=project_id,
                            scope=scope,
                            key=key,
                            request_hash=request_hash,
                            error=mapped,
                        )
                    except Exception as persist_exc:
                        _translate_storage_error(persist_exc)
                        raise
                    if mapped is exc:
                        raise
                    raise mapped from exc

            # As with Project Patch, a response-record write failure leaves
            # the reservation recoverable. It is not a Review decision failure.
            try:
                await asyncio.to_thread(
                    idempotency.complete,
                    owner_id=project_id,
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    response=body,
                    response_status=200,
                )
            except Exception as exc:
                _translate_storage_error(exc)
                raise
            if recovered or not reservation.created:
                response.headers["X-Idempotent-Replay"] = "true"
    finally:
        operation_lock.release()
        lifecycle_lock.release()

    # Session messages use the same Project lock as lifecycle operations, so
    # publish only after the decision boundary has released it. The journal
    # plus deterministic clientMessageId make this safe to retry.
    try:
        await services.publish_review_followup(
            project_id=project_id,
            review_id=review_id,
            decision_id=request.decision_id,
        )
    except Exception as exc:
        _translate_storage_error(exc)
        raise
    # The driver converges the resolved Review projection and consumes an
    # executable continuation only for ACCEPT or UNDO_AND_REGENERATE.
    # UNDO_ONLY is stored as system context and cannot start a run.
    notify_creator_agent_runtime(project_id)
    return body
