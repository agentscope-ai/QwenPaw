# -*- coding: utf-8 -*-
"""剧本直登：把写好的剧本正文直接落成 timeline_script 版本，不经素材理解。

用户自带的剧本此前只被当作普通 Source：文档要逐页 VLM 观察，正文还要模型
把整份剧本重新抄进工具参数，一次导入能耗到小时级。本模块提供一条一等通
道——正文按 UTF-8 读取、归一化到约定块格式、以内容寻址写入该 Timeline 的
``timeline_script`` ArtifactVersion。两个入口共用同一实现：

- :func:`publish_script_import`：HTTP 直登（前端剧本页导入）；
- ``AgentProjectTools.import_script_asset``：主 Agent 把本轮已入库的文本
  或 DOCX/PDF 文档素材直接登记为剧本，不创建 ProjectSource，因此不会
  触发 ``source_intelligence_agent`` 委派。

DOCX/PDF 的正文抽取在 :mod:`services.project_files.script_document_text`：
复用文档渲染链路的文字层（不渲染页图），抽不到就显式失败，不静默登记
半份剧本。

直登写入走既有提交边界（``ProjectCommitBoundary``），因此剧本变更仍会按
``production_stage`` 的既有派生规则重新要求用户确认剧本，审阅策略也不会
被绕过。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict

from services.runtime_files.atomic_store import AtomicJsonRecordStore

from .assets import AssetAlreadyExists, AssetFileStore
from .commit import (
    CommitJournalState,
    ProjectCommitBoundary,
    ProjectCommitError,
    ProjectCommitJournal,
)
from .models import ArtifactVersion, IndexedFile
from .script_artifacts import (
    add_script_version,
    script_file_relative_uri,
    script_version_id,
    timeline_script_slot_id,
)
from .script_markdown import (
    parse_script_markdown,
    serialize_script_blocks,
)
from .store import ProjectSnapshot, ProjectStore

IMPORT_SCRIPT_TOOL_NAME = "import_script_asset"

# A hand-written script is text: 2 MiB of UTF-8 already exceeds any realistic
# feature-length draft, and the cap keeps a mis-uploaded blob out of the index.
SCRIPT_IMPORT_MAX_BYTES = 2 * 1024 * 1024

TEXT_MEDIA_KINDS = frozenset({"text"})
TEXT_MEDIA_TYPE_PREFIXES = ("text/",)
JSON_MEDIA_TYPES = frozenset({"application/json"})

_SOURCE_KIND = "script_import"
# ``auto_snapshot._SNAPSHOT_PREFIX``: rolled-back copies live in the same
# ``timelines.items`` map but never enter the work graph, so landing a script
# version on one would be invisible to the user.
_SNAPSHOT_TIMELINE_PREFIX = "snapshot:"


class ScriptImportError(RuntimeError):
    """A script import that must surface a readable reason to the caller."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "SCRIPT_IMPORT_INVALID",
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = dict(details or {})


@dataclass(slots=True)
class ScriptImportOutcome:
    """One landed script version, plus the Project state it produced."""

    project_id: str
    timeline_id: str
    slot_id: str
    artifact_version_id: str
    file_id: str
    checksum: str
    block_count: int
    character_count: int
    generation: int
    etag: str
    replayed: bool
    review_id: str | None = None
    changed_pointers: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Camel-case payload shared by the tool result and the HTTP route."""

        return {
            "resultKind": "script_import",
            "projectId": self.project_id,
            "timelineId": self.timeline_id,
            "slotId": self.slot_id,
            "artifactVersionId": self.artifact_version_id,
            "fileId": self.file_id,
            "checksum": self.checksum,
            "blockCount": self.block_count,
            "characterCount": self.character_count,
            "generation": self.generation,
            "etag": self.etag,
            "replayed": self.replayed,
            "reviewId": self.review_id,
            "changedPointers": list(self.changed_pointers),
            "summary": self.summary_text(),
        }

    def summary_text(self) -> str:
        if self.replayed:
            return (
                f"该正文与当前已登记剧本内容一致，未产生新版本"
                f"（{self.block_count} 块 / {self.character_count} 字）。"
            )
        if self.review_id is not None:
            return (
                f"剧本正文（{self.block_count} 块 / {self.character_count} 字）"
                f"已提交待审阅，通过后成为该集剧本版本。"
            )
        return (
            f"剧本正文（{self.block_count} 块 / {self.character_count} 字）"
            f"已直接登记为该集剧本版本，未经过素材理解。"
        )


def normalize_script_text(raw_text: str) -> tuple[str, int]:
    """归一化到约定块格式并返回 ``(markdown, block_count)``。

    解析/序列化双向无损，所以前端块级渲染与块级 diff 得到与模型起草
    同一套基线；不做任何内容改写。
    """

    if not raw_text.strip():
        raise ScriptImportError(
            "剧本正文为空，无法登记为剧本版本。",
            code="SCRIPT_IMPORT_EMPTY",
        )
    markdown_text = serialize_script_blocks(parse_script_markdown(raw_text))
    if not markdown_text.strip():
        raise ScriptImportError(
            "剧本正文没有可解析的内容，无法登记为剧本版本。",
            code="SCRIPT_IMPORT_EMPTY",
        )
    blocks = parse_script_markdown(markdown_text)
    return markdown_text, len(blocks)


def script_import_file_id(project_id: str, checksum: str) -> str:
    """内容寻址的剧本文件 ID：同一内容重复导入不会新增文件。"""

    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:script-import:{project_id}:{checksum}",
    ).hex
    return f"file-script-{digest}"


def is_importable_script_text(
    *,
    media_kind: str | None,
    media_type: str | None,
) -> bool:
    """Only readable UTF-8 text may land a script directly."""

    if media_kind in TEXT_MEDIA_KINDS:
        return True
    normalized = (media_type or "").split(";", 1)[0].strip().casefold()
    if not normalized:
        return False
    if normalized in JSON_MEDIA_TYPES:
        return False
    return normalized.startswith(TEXT_MEDIA_TYPE_PREFIXES)


def _script_import_identity(
    project_id: str,
    timeline_id: str,
    idempotency_key: str,
) -> str:
    """Deterministic edit-transaction identity for one explicit request key.

    Keyed on the caller-supplied idempotency key -- never on the script
    checksum -- so re-selecting previously imported content (A -> B -> A) is a
    *new* edit transaction, while a network retry carrying the same key maps
    back to the same transaction and deduplicates.
    """

    return uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:script-import-transaction:"
        f"{project_id}:{timeline_id}:{idempotency_key}",
    ).hex


_IDEMPOTENCY_DIR = "script-import-idempotency"


class ScriptImportIdempotencyRecord(BaseModel):
    """Durable replay record for one explicit script-import request key.

    Stored under ``runtime/script-import-idempotency/{operation_id}.json`` --
    a sibling of ``runtime/transactions`` that startup recovery never scans --
    and keyed on the deterministic operation id derived from the caller's
    ``Idempotency-Key``.  It remembers the request digest, so a reused key
    carrying a different payload is rejected as a conflict, and the completed
    outcome, so a delayed retry of an already-committed request replays that
    result verbatim instead of re-committing the same transaction id (which
    the boundary rejects as a duplicate) or rewinding whatever edit has since
    become current.
    """

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    request_digest: str
    outcome: dict[str, Any]
    created_at: datetime


def _script_import_request_digest(
    project_id: str,
    timeline_id: str,
    checksum: str,
    source_name: str,
) -> str:
    """Stable digest of the payload an idempotency key was first used for."""

    payload = json.dumps(
        {
            "projectId": project_id,
            "timelineId": timeline_id,
            "checksum": checksum,
            "sourceName": source_name,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _idempotency_store(
    store: ProjectStore,
    project_id: str,
    operation_id: str,
) -> AtomicJsonRecordStore[ScriptImportIdempotencyRecord]:
    path = (
        store.project_root(project_id)
        / "runtime"
        / _IDEMPOTENCY_DIR
        / f"{operation_id}.json"
    )
    # The caller already holds the per-project lifecycle lock, which
    # serializes every writer of this record, so the inner per-record lock
    # would only add a second file open and timeout source.
    return AtomicJsonRecordStore(
        path,
        ScriptImportIdempotencyRecord,
        locked=False,
    )


def _replay_idempotent_request(
    store: ProjectStore,
    project_id: str,
    operation_id: str | None,
    request_digest: str | None,
) -> ScriptImportOutcome | None:
    """Replay a completed keyed request, or ``None`` when there is none.

    ``None`` when the request carried no explicit key or the key is new.
    Raises ``SCRIPT_IMPORT_IDEMPOTENCY_CONFLICT`` when the same key arrives
    with a different payload (a different body or a different timeline).
    """

    if operation_id is None or request_digest is None:
        return None
    record = _idempotency_store(
        store,
        project_id,
        operation_id,
    ).read_or_none()
    if record is None:
        return None
    if record.request_digest != request_digest:
        raise ScriptImportError(
            "同一个 Idempotency-Key 被用于不同的剧本正文或目标时间线；请为每一次不同的导入请求生成新的键。",
            code="SCRIPT_IMPORT_IDEMPOTENCY_CONFLICT",
        )
    # This request produced no new version (it replayed a completed one), so
    # the response is marked as a replay even though the recorded original
    # commit was not; the rest of the outcome is returned verbatim.
    return replace(ScriptImportOutcome(**record.outcome), replayed=True)


def _record_idempotent_request(
    store: ProjectStore,
    project_id: str,
    operation_id: str | None,
    request_digest: str | None,
    outcome: ScriptImportOutcome,
) -> None:
    """Persist the completed result so a later retry of this key replays it.

    A no-op when the request carried no explicit key (both ids are ``None``):
    an unkeyed edit mints a fresh transaction each time and keeps no record.
    """

    if operation_id is None or request_digest is None:
        return
    record_store = _idempotency_store(store, project_id, operation_id)
    record_store.path.parent.mkdir(parents=True, exist_ok=True)
    record_store.write(
        ScriptImportIdempotencyRecord(
            operation_id=operation_id,
            request_digest=request_digest,
            outcome=asdict(outcome),
            created_at=datetime.now(UTC),
        ),
    )


def _script_import_operation(
    project_id: str,
    timeline_id: str,
    idempotency_key: str | None,
    checksum: str,
    source_name: str,
) -> tuple[str | None, str | None]:
    """Derive the deterministic operation id and payload digest for a key.

    Both are ``None`` when the caller supplied no explicit key, so every edit
    mints a fresh transaction and no replay record is kept.
    """

    if not idempotency_key:
        return None, None
    operation_id = _script_import_identity(
        project_id,
        timeline_id,
        idempotency_key,
    )
    request_digest = _script_import_request_digest(
        project_id,
        timeline_id,
        checksum,
        source_name,
    )
    return operation_id, request_digest


def _publish_script_file(
    file_store: AssetFileStore,
    content: bytes,
    *,
    file_id: str,
    relative_uri: str,
    checksum: str,
    indexed: IndexedFile,
) -> None:
    """Write the content-addressed script body, tolerating an existing copy.

    A concurrent import of identical content may have published the same
    addressable file first; that is fine as long as the indexed copy verifies.
    """

    staged = file_store.stage_bytes(
        content,
        staging_id=f"script-import-{file_id[:48]}",
    )
    try:
        file_store.publish(
            staged,
            relative_uri,
            expected_sha256=checksum,
            expected_size_bytes=len(content),
        )
    except AssetAlreadyExists:
        file_store.abandon(staged)
        if not file_store.inspect(indexed).available:
            raise


def _script_import_commit_metadata(
    commit_metadata: Mapping[str, Any],
    operation_id: str | None,
) -> dict[str, Any]:
    """Build commit metadata, pinning a deterministic transaction when keyed.

    Transaction identity is per *edit*, not per content.  Re-selecting a
    previously imported script (A -> B -> A) is a new edit and must not reuse
    A's already-COMMITTED transaction id, or the commit boundary rejects it as
    a duplicate.  An explicit request key still makes the transaction
    deterministic as a safety net, but the durable replay record checked in
    :func:`publish_script_import` is what turns a delayed retry into a no-op
    replay; without a key the boundary mints a fresh transaction.
    """

    metadata: dict[str, Any] = {
        **dict(commit_metadata),
        "_lifecycle_lock_held": True,
    }
    if operation_id is not None:
        metadata.setdefault("transaction_id", f"transaction-{operation_id}")
        metadata.setdefault("round_id", f"round-script-import-{operation_id}")
    return metadata


# A transaction that reached either of these states durably replaced the
# Project, so its script import committed even if the replay record did not.
_COMMITTED_JOURNAL_STATES = frozenset(
    {
        CommitJournalState.PROJECT_REPLACED,
        CommitJournalState.RUNTIME_FINALIZED,
    },
)


def _committed_script_version_id(
    store: ProjectStore,
    project_id: str,
    transaction_id: str,
    timeline_id: str,
) -> str | None:
    """The script version a committed transaction actually selected.

    Reads the transaction's durable ``candidate.json`` (kept for every
    committed transaction) and returns this timeline's script-slot
    ``selected_version_id``, or ``None`` when it cannot be read or parsed.
    Because the version id is content-addressed, comparing it against a
    retry's version id proves whether the same key carried the same body.
    """

    try:
        candidate = AtomicJsonRecordStore(
            store.project_root(project_id)
            / "runtime"
            / "transactions"
            / transaction_id
            / "candidate.json",
        ).read_or_none()
    except Exception:  # pylint: disable=broad-except
        # A corrupt/unreadable candidate cannot verify the original request.
        return None
    if not isinstance(candidate, dict):
        return None
    assets = candidate.get("assets")
    if not isinstance(assets, dict):
        return None
    slots = assets.get("artifact_slots_by_id")
    if not isinstance(slots, dict):
        return None
    slot = slots.get(timeline_script_slot_id(timeline_id))
    if not isinstance(slot, dict):
        return None
    selected = slot.get("selected_version_id")
    return selected if isinstance(selected, str) else None


def _replay_committed_import(
    store: ProjectStore,
    project_id: str,
    operation_id: str | None,
    request_digest: str | None,
    error: ProjectCommitError,
    *,
    transaction_id: str | None,
    base: ProjectSnapshot,
    timeline_id: str,
    version: ArtifactVersion,
    checksum: str,
    block_count: int,
    character_count: int,
) -> ScriptImportOutcome:
    """Replay a keyed import whose commit landed but whose record did not.

    A crash between :meth:`ProjectCommitBoundary.commit` and the durable
    replay record leaves the deterministic transaction COMMITTED with no
    record, so a later retry of the same key re-commits that transaction id
    and the boundary rejects it as a duplicate -- a 500 even though the
    original edit succeeded.  When the journal proves the project was really
    replaced, rebuild the outcome (current generation/etag, like the
    same-content replay in :func:`publish_script_import`), persist the
    missing record so future retries replay fast, and return it.  Anything
    else -- unkeyed, no journal, or a journal that never committed -- is a
    genuine failure, so ``error`` is re-raised untouched.
    """

    if operation_id is None or transaction_id is None:
        raise error
    journal = AtomicJsonRecordStore(
        store.project_root(project_id)
        / "runtime"
        / "transactions"
        / transaction_id
        / "journal.json",
        ProjectCommitJournal,
    ).read_or_none()
    if journal is None or journal.state not in _COMMITTED_JOURNAL_STATES:
        raise error
    # The journal proves *a* commit landed under this deterministic transaction
    # id, but not that it was *this* body: the id is derived from the key, so a
    # retry reusing the key with different content maps to the same committed
    # transaction.  Verify against the committed candidate (content-addressed
    # version id) before rebuilding a result, so a same-key/different-body
    # retry is rejected instead of fabricating a success for a version that
    # never landed -- and never persisting that fabrication as the replay
    # record for future retries.
    committed_version_id = _committed_script_version_id(
        store,
        project_id,
        transaction_id,
        timeline_id,
    )
    if committed_version_id is None:
        # The committed candidate cannot be read, so the original request
        # cannot be verified: surface the real failure, do not invent one.
        raise error
    if committed_version_id != version.version_id:
        raise ScriptImportError(
            "同一个 Idempotency-Key 已被用于不同的剧本正文；请为每一次不同的导入请求生成新的键。",
            code="SCRIPT_IMPORT_IDEMPOTENCY_CONFLICT",
        )
    outcome = ScriptImportOutcome(
        project_id=project_id,
        timeline_id=timeline_id,
        slot_id=version.slot_id,
        artifact_version_id=version.version_id,
        file_id=version.file_id,
        checksum=checksum,
        block_count=block_count,
        character_count=character_count,
        generation=base.generation,
        etag=base.etag,
        replayed=True,
    )
    _record_idempotent_request(
        store,
        project_id,
        operation_id,
        request_digest,
        outcome,
    )
    return outcome


def _pending_script_review_id(
    store: ProjectStore,
    project_id: str,
    version_id: str,
) -> str | None:
    """A still-pending review that would decide this exact script version.

    A ``REQUIRE_REVIEW`` import replaces the Project optimistically and records
    a pending Review that gates whether the new version is accepted.  Re-
    importing the identical body then hits the same-content replay while that
    review is still pending; without restoring its id the caller/tool would
    report the body as already current.  Matches a *still-PENDING* operation
    on the content-addressed version id -- inside its pointer (the version
    created on a first import) or as its ``after`` value (the slot
    re-selection) -- so a mixed review whose script line was already decided
    is never reported as 待审阅, and a different pending review never
    attaches.  ``None`` when no pending operation concerns this version.
    """

    from services.runtime_files.models import ReviewOperationDecision

    from .review import ProjectReviewService

    try:
        pending = ProjectReviewService(store).all_pending(project_id)
    except Exception:  # pylint: disable=broad-except
        # Review state is unreadable: fall back to the plain content replay
        # rather than failing an otherwise-valid identical import.
        return None
    for review in pending:
        for operation in review.operations:
            # A Review stays PENDING while *any* operation is undecided, so
            # only an operation that is itself still PENDING proves this script
            # version has not been decided yet.
            if operation.decision is not ReviewOperationDecision.PENDING:
                continue
            pointer = operation.json_pointer or ""
            if version_id in pointer or operation.after == version_id:
                return review.review_id
    return None


def publish_script_import(
    *,
    store: ProjectStore,
    commits: ProjectCommitBoundary,
    project_id: str,
    timeline_id: str,
    raw_text: str,
    source_name: str = "",
    provenance_refs: Sequence[str] = (),
    commit_metadata: Mapping[str, Any],
    observe_snapshot: Callable[[ProjectSnapshot], None] | None = None,
    idempotency_key: str | None = None,
) -> ScriptImportOutcome:
    """Write one script markdown payload as a selected ``timeline_script``.

    ``commit_metadata`` is forwarded to :meth:`ProjectCommitBoundary.commit`
    so the caller keeps control of origin and review policy: the HTTP route
    commits as a frontend edit while the Agent tool passes its own request
    context (which may require review).

    ``idempotency_key`` identifies *this edit request*, not its content.  When
    present the completed result is recorded under the key, so a delayed
    network retry replays it verbatim -- even after another edit has moved the
    current selection on -- instead of re-committing the same transaction id;
    reusing the key with a different payload is rejected as a conflict.  When
    absent every edit mints a fresh transaction, so re-selecting a previously
    imported script (A -> B -> A) never reuses that script's committed id.
    """

    markdown_text, block_count = normalize_script_text(raw_text)
    content = markdown_text.encode("utf-8")
    if len(content) > SCRIPT_IMPORT_MAX_BYTES:
        raise ScriptImportError(
            f"剧本正文 {len(content)} 字节超过直登上限 "
            f"{SCRIPT_IMPORT_MAX_BYTES} 字节；请按集或场次拆分后分别导入。",
            code="SCRIPT_IMPORT_TOO_LARGE",
        )
    checksum = sha256(content).hexdigest()
    version_id = script_version_id(project_id, timeline_id, checksum)
    file_id = script_import_file_id(project_id, checksum)
    relative_uri = script_file_relative_uri(file_id)
    now = datetime.now(UTC)
    file_store = AssetFileStore(store.project_root(project_id))
    # An explicit request key gets a deterministic operation id and payload
    # digest before the lock: the id makes the commit transaction stable (so a
    # retry maps back to the same transaction) and both drive the durable
    # replay record checked inside the lock below.
    operation_id, request_digest = _script_import_operation(
        project_id,
        timeline_id,
        idempotency_key,
        checksum,
        source_name,
    )

    with store.lifecycle_lock(project_id):
        base = store.read(project_id)
        project = base.project
        # Replay a completed keyed request before building any new edit: a
        # delayed network retry -- even after another edit moved the selection
        # on -- returns the original result instead of re-committing the same
        # transaction id (which the boundary rejects as a duplicate) and never
        # rewinds the script that is current now.
        replayed = _replay_idempotent_request(
            store,
            project_id,
            operation_id,
            request_digest,
        )
        if replayed is not None:
            return replayed
        if timeline_id.startswith(_SNAPSHOT_TIMELINE_PREFIX):
            raise ScriptImportError(
                "snapshot: 开头的时间线是用户回滚留下的历史副本，不能把剧本"
                "直登写在它上面；请传当前正在创作的真实 Timeline ID。",
                code="SCRIPT_IMPORT_SNAPSHOT_TIMELINE",
            )
        timeline = project.timelines.items.get(timeline_id)
        if timeline is None:
            available = ", ".join(project.timelines.order[:12]) or "（无）"
            raise ScriptImportError(
                f"timeline 不存在: {timeline_id}；当前时间线：{available}",
                code="SCRIPT_IMPORT_TIMELINE_NOT_FOUND",
            )
        slot_id = timeline_script_slot_id(timeline_id)
        slot = project.assets.artifact_slots_by_id.get(slot_id)
        if (
            slot is not None
            and slot.selected_version_id == version_id
            and version_id in slot.version_ids
        ):
            # Same content already selected: replay without a no-op commit.
            # ``fileId`` must be the indexed file the selected version points
            # at, never the artifact-version id: callers key file reads off
            # ``assets.files_by_id``, whose keys are file ids, and a version
            # id is not one of them (it would also duplicate
            # ``artifactVersionId``).
            selected = project.assets.artifact_versions_by_id.get(version_id)
            if (
                selected is None
                or selected.file_id not in project.assets.files_by_id
            ):
                raise ScriptImportError(
                    "剧本槽位选中的版本或文件索引缺失，无法复放该正文；请重新导入。",
                    code="SCRIPT_IMPORT_SLOT_CONFLICT",
                )
            # The same content can already be selected while a REQUIRE_REVIEW
            # commit for it is still pending (the Project is replaced
            # optimistically and the review gates acceptance).  Restore that
            # review id so the caller/tool reports "待审阅" instead of
            # claiming the body already landed as the current version.
            pending_review_id = _pending_script_review_id(
                store,
                project_id,
                version_id,
            )
            outcome = ScriptImportOutcome(
                project_id=project_id,
                timeline_id=timeline_id,
                slot_id=slot.slot_id,
                artifact_version_id=version_id,
                file_id=selected.file_id,
                checksum=checksum,
                block_count=block_count,
                character_count=len(markdown_text),
                generation=base.generation,
                etag=base.etag,
                replayed=True,
                review_id=pending_review_id,
            )
            # Record the content replay too: without it a later retry of this
            # key, after another edit moved the selection off ``version_id``,
            # would fall through to a fresh commit and rewind the current one.
            _record_idempotent_request(
                store,
                project_id,
                operation_id,
                request_digest,
                outcome,
            )
            return outcome

        working = project.model_copy(deep=True)
        try:
            version = add_script_version(
                working,
                timeline_id,
                markdown_text,
                file_id=file_id,
                checksum=checksum,
                name=_version_name(
                    timeline_title=timeline.title,
                    timeline_id=timeline_id,
                    source_name=source_name,
                ),
                now=now,
                based_on_generation=base.generation,
                provenance_refs=list(provenance_refs),
                input_fingerprint=None,
            )
        except ValueError as error:
            raise ScriptImportError(
                f"剧本槽位不可用：{error}",
                code="SCRIPT_IMPORT_SLOT_CONFLICT",
            ) from error
        version.metadata = {
            **version.metadata,
            "source": _SOURCE_KIND,
            "importedFromName": source_name[:160],
        }
        indexed = working.assets.files_by_id[version.file_id]

        if version.file_id == file_id:
            _publish_script_file(
                file_store,
                content,
                file_id=file_id,
                relative_uri=relative_uri,
                checksum=checksum,
                indexed=indexed,
            )

        metadata = _script_import_commit_metadata(
            commit_metadata,
            operation_id,
        )
        try:
            commit = commits.commit(
                base=base,
                candidate=working.model_dump(mode="json"),
                **metadata,
            )
        except ProjectCommitError as error:
            # The deterministic transaction may already be COMMITTED from an
            # earlier attempt that crashed before its replay record landed;
            # reconcile it into a replay instead of a duplicate-id 500.
            return _replay_committed_import(
                store,
                project_id,
                operation_id,
                request_digest,
                error,
                transaction_id=metadata.get("transaction_id"),
                base=base,
                timeline_id=timeline_id,
                version=version,
                checksum=checksum,
                block_count=block_count,
                character_count=len(markdown_text),
            )
        if observe_snapshot is not None:
            observe_snapshot(commit.snapshot)
        outcome = ScriptImportOutcome(
            project_id=project_id,
            timeline_id=timeline_id,
            slot_id=version.slot_id,
            artifact_version_id=version.version_id,
            file_id=version.file_id,
            checksum=checksum,
            block_count=block_count,
            character_count=len(markdown_text),
            generation=commit.snapshot.generation,
            etag=commit.snapshot.etag,
            replayed=False,
            review_id=(
                commit.review.review_id if commit.review is not None else None
            ),
            changed_pointers=[
                change.json_pointer
                for change in commit.changeset.changes
                if change.json_pointer is not None
            ],
        )
        # Persist the completed result keyed on the request id, so a delayed
        # retry replays it verbatim instead of re-committing the same
        # transaction id and failing as a duplicate.
        _record_idempotent_request(
            store,
            project_id,
            operation_id,
            request_digest,
            outcome,
        )
    return outcome


def _version_name(
    *,
    timeline_title: str,
    timeline_id: str,
    source_name: str,
) -> str:
    title = (timeline_title or "").strip() or timeline_id
    origin = (source_name or "").strip()
    label = f"剧本 · {title} · {origin}" if origin else f"剧本 · {title}"
    return label[:160]


def import_script_tool_manifest() -> dict[str, Any]:
    """Mainline-only tool: land an uploaded script text as this turn's 剧本."""

    return {
        "type": "function",
        "function": {
            "name": IMPORT_SCRIPT_TOOL_NAME,
            "description": (
                "把本轮已入库的**剧本素材**（.md/.txt 等 text 素材、用户"
                "粘贴的长文本附件，或 DOCX/PDF 文档剧本）直接登记为指定 "
                "Timeline 的 timeline_script 正文。服务端按文件索引读取并"
                "落版本（文档由服务端抽出文字层），你不需要、也不要把剧本"
                "正文重抄进参数。用于用户自带剧本/文稿：调用本工具即完成"
                "剧本登记，不需要为该素材创建 ProjectSource，也不要委派 "
                "source_intelligence_agent 理解它，更不要重新起草覆盖它。"
                "图片/视频/音频素材不适用本工具；DOCX/PDF 抽不出文字层"
                "（扫描件）时本工具会报错，那时才按文档规则处理。返回落"
                "版本的时间线、ArtifactVersion 与块数/字数，并在剧本待"
                "审阅时给出审阅 ID。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "timelineId": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "目标 Timeline 的真实 ID（如 timeline:main），"
                            "不要用 targetRef 形式或名称。"
                        ),
                    },
                    "assetVersionId": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "已入库剧本素材（文本或 DOCX/PDF）的 source "
                            "asset version ID。"
                        ),
                    },
                },
                "required": ["projectId", "timelineId", "assetVersionId"],
                "additionalProperties": False,
            },
        },
    }


__all__ = [
    "IMPORT_SCRIPT_TOOL_NAME",
    "SCRIPT_IMPORT_MAX_BYTES",
    "ScriptImportError",
    "ScriptImportOutcome",
    "import_script_tool_manifest",
    "is_importable_script_text",
    "normalize_script_text",
    "publish_script_import",
    "script_import_file_id",
]
