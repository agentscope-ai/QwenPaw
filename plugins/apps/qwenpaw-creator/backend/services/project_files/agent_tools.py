# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Model-facing read/jq tools over the single-file Project authority.

The model supplies only the Project identity and a jq transformation.  The
base snapshot for three-way merge is the last snapshot this request-scoped
boundary actually observed; the model never echoes ETags.  Request
provenance and Review policy are captured by the Runtime before this
boundary is constructed; they are never accepted as model tool arguments.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from typing import Any, Mapping
import threading

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from services.runtime_files.models import (
    ChangeOrigin,
    ReviewBoundary,
    ReviewPolicy,
)

from .assets import AssetFileStore
from .commit import PROTECTED_EXACT_POINTERS, ProjectCommitBoundary
from .jq_transform import JqProjectTransformer
from .models import Project, TimelineElement
from .schema_prompt import ProjectSchemaPrompt, build_project_schema_prompt
from .store import ProjectSnapshot, ProjectStore


READ_PROJECT_TOOL_NAME = "read_project"
READ_PROJECT_FILE_TOOL_NAME = "read_project_file"
JQ_PROJECT_TOOL_NAME = "jq_project"
ELEMENTS_AT_TOOL_NAME = "elements_at"
_DEFAULT_TEXT_PAGE_BYTES = 64 * 1024
_MAX_TEXT_PAGE_BYTES = 256 * 1024


class AgentProjectToolError(RuntimeError):
    """Base error for the Project tool boundary."""


class UnknownAgentProjectTool(AgentProjectToolError):
    pass


class _ToolModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        revalidate_instances="always",
    )


class ReadProjectToolInput(_ToolModel):
    project_id: str = Field(alias="projectId", min_length=1)


class ReadProjectFileToolInput(_ToolModel):
    project_id: str = Field(alias="projectId", min_length=1)
    file_id: str = Field(alias="fileId", min_length=1)
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(
        default=_DEFAULT_TEXT_PAGE_BYTES,
        alias="maxBytes",
        # Four bytes are enough for every valid UTF-8 code point, allowing a
        # page to make progress without ever exceeding the caller's byte cap.
        ge=4,
        le=_MAX_TEXT_PAGE_BYTES,
    )


class JqProjectToolInput(_ToolModel):
    project_id: str = Field(alias="projectId", min_length=1)
    # Deprecated model-facing field. The Runtime now selects the base
    # snapshot itself; a value sent by an older prompt/history is tolerated
    # and ignored so it cannot fail an otherwise valid call.
    base_etag: str | None = Field(default=None, alias="baseEtag")
    program: str = Field(min_length=1)
    string_args: dict[str, str] = Field(
        default_factory=dict,
        alias="stringArgs",
    )
    json_args: dict[str, Any] = Field(
        default_factory=dict,
        alias="jsonArgs",
    )


class ElementsAtToolInput(_ToolModel):
    project_id: str = Field(alias="projectId", min_length=1)
    timeline_id: str = Field(alias="timelineId", min_length=1)
    tick: int = Field(ge=0)
    include_disabled: bool = Field(default=False, alias="includeDisabled")


class AgentProjectToolContext(_ToolModel):
    """Runtime-only request provenance; this is not a model tool schema."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    origin: ChangeOrigin
    review_policy: ReviewPolicy = ReviewPolicy.AUTO_FIX
    review_boundary: ReviewBoundary | None = None
    caused_by_request_id: str | None = None
    caused_by_message_seq: int | None = Field(default=None, ge=1)
    round_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_review_provenance(self) -> AgentProjectToolContext:
        if self.review_policy is ReviewPolicy.REQUIRE_REVIEW:
            if self.origin not in {
                ChangeOrigin.AGENTDOCK_INTERRUPT,
                ChangeOrigin.AGENTDOCK_IDLE_GOAL,
            }:
                raise ValueError(
                    "only an AgentDock interrupt/idle-goal context may "
                    "require review",
                )
            if self.review_boundary is None:
                raise ValueError(
                    "review-required Agent tools need a ReviewBoundary",
                )
            if self.caused_by_request_id != self.review_boundary.request_id:
                raise ValueError(
                    "request provenance must match the ReviewBoundary",
                )
            if (
                self.caused_by_message_seq
                != self.review_boundary.request_message_seq
            ):
                raise ValueError(
                    "message provenance must match the ReviewBoundary",
                )
        elif self.review_boundary is not None:
            raise ValueError(
                "auto-fix Agent tools cannot carry a ReviewBoundary",
            )
        return self

    def commit_metadata(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "review_policy": self.review_policy,
            "review_boundary": self.review_boundary,
            "caused_by_request_id": self.caused_by_request_id,
            "caused_by_message_seq": self.caused_by_message_seq,
            "round_id": self.round_id,
            "advance_accepted_baseline": (
                self.review_policy is ReviewPolicy.AUTO_FIX
            ),
        }


class AgentProjectSnapshotResult(_ToolModel):
    project: Project
    generation: int = Field(ge=0)
    etag: str = Field(min_length=1)


class AgentProjectFileResult(_ToolModel):
    project_id: str = Field(alias="projectId")
    project_etag: str = Field(alias="projectEtag")
    file_id: str = Field(alias="fileId")
    kind: str
    media_type: str = Field(alias="mediaType")
    sha256: str
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    offset: int = Field(ge=0)
    next_offset: int = Field(alias="nextOffset", ge=0)
    eof: bool
    content: str


class AgentProjectCommitResult(AgentProjectSnapshotResult):
    transaction_id: str = Field(alias="transactionId", min_length=1)
    changed_pointers: list[str] = Field(alias="changedPointers")
    review_id: str | None = Field(default=None, alias="reviewId")


class AgentElementsAtResult(_ToolModel):
    project_id: str = Field(alias="projectId")
    project_etag: str = Field(alias="projectEtag")
    timeline_id: str = Field(alias="timelineId")
    tick: int = Field(ge=0)
    elements: list[TimelineElement]


AGENT_PROJECT_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    READ_PROJECT_TOOL_NAME: {
        "description": (
            "读取 project.json 的完整已验证快照，"
            "并返回 generation 与 ETag。修改前先调用此工具了解当前结构；"
            "jq_project 会自动基于你最近一次读到的快照提交，无需回传 ETag。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "minLength": 1},
            },
            "required": ["projectId"],
            "additionalProperties": False,
        },
    },
    READ_PROJECT_FILE_TOOL_NAME: {
        "description": (
            "按 fileId 读取 project.json Asset Index 中已校验的 UTF-8 文本文件。"
            "用于 large_text、source_intelligence 等索引内容；只支持字节 offset "
            "分页，绝不接受文件系统路径。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "minLength": 1},
                "fileId": {"type": "string", "minLength": 1},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "maxBytes": {
                    "type": "integer",
                    "minimum": 4,
                    "maximum": _MAX_TEXT_PAGE_BYTES,
                    "default": _DEFAULT_TEXT_PAGE_BYTES,
                },
            },
            "required": ["projectId", "fileId"],
            "additionalProperties": False,
        },
    },
    JQ_PROJECT_TOOL_NAME: {
        "description": (
            "在你最近读取的 Project 快照上运行一段 jq，"
            "Runtime 自动选择 base 并执行字段 CAS、三方合并、"
            "Pydantic 校验和原子发布。"
            "jq 必须输出且只输出完整 Project 根对象；不得以嵌套路径或子对象变量结束。"
            "必须原样保留 schema_version/project_id/generation/created_at/updated_at。"
            "绝不能在 program 中给这些保护字段赋值；updated_at 由 Runtime 自动维护。"
            "不要以 `$jsonArgs | ...` 开始变换；输入 Project `.` 必须始终作为输出根对象。"
            "批量内容通过 jsonArgs 传入，program 只负责结构化赋值。"
            "若单次参数体量极大（如数十个 Element），可拆分为少量几次调用以降低 JSON 出错风险。"
            "动态加法表达式在绑定 jq 变量前必须加括号，例如 "
            '("source:" + $logicalId) as $sourceKey；对象字段值中的运算也必须加括号。'
            "修改后自然返回当前完整 Project；不要在结尾返回修改前保存的根对象，"
            "否则会丢弃全部修改。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "minLength": 1},
                "program": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "作用于完整 Project 的 jq 变换；最后结果必须仍是完整 Project 根对象，"
                        "不要以 `| .timelines...`、`| $child` 等子对象选择结束。"
                    ),
                },
                "stringArgs": {
                    "type": "object",
                    "description": (
                        "通过 --arg 传入的短字符串参数；program 可使用 "
                        "$stringArgs.name，也兼容按 key 使用 $name。"
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "jsonArgs": {
                    "type": "object",
                    "description": (
                        "通过 --argjson 传入的结构化 JSON；新增多项时间线内容时应把对象集合放这里，"
                        "避免在 program 中拼接大段 JSON。program 可使用 "
                        "$jsonArgs.elements，也兼容按 key 使用 $elements。"
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["projectId", "program"],
            "additionalProperties": False,
        },
    },
    ELEMENTS_AT_TOOL_NAME: {
        "description": (
            "查询 Timeline 某一整数 tick 上按半开区间仍然活跃的完整 Element。"
            "默认排除 disabled，并按 (start_tick, element_id) 稳定排序；"
            "固定 ID 路径和其他筛选继续使用 read_project/jq_project。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "minLength": 1},
                "timelineId": {"type": "string", "minLength": 1},
                "tick": {"type": "integer", "minimum": 0},
                "includeDisabled": {"type": "boolean", "default": False},
            },
            "required": ["projectId", "timelineId", "tick"],
            "additionalProperties": False,
        },
    },
}


def agent_project_tool_manifest() -> tuple[dict[str, Any], ...]:
    """Return the fixed OpenAI/AgentScope-compatible Project tool manifest."""

    return tuple(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": definition["description"],
                "parameters": deepcopy(definition["parameters"]),
            },
        }
        for name, definition in AGENT_PROJECT_TOOL_SCHEMAS.items()
    )


def _find_key_paths(
    data: Any,
    key: str,
    *,
    limit: int = 3,
) -> list[str]:
    """Locate every (nested) occurrence of ``key`` for diagnostics."""

    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, Mapping):
            for child_key, child in node.items():
                child_path = f"{path}.{child_key}"
                if child_key == key:
                    found.append(child_path)
                    if len(found) >= limit:
                        return
                walk(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    walk(data, "$")
    return found


def _translate_jq_input_error(
    arguments: Mapping[str, Any],
    error: ValidationError,
) -> str | None:
    """Model-actionable message for the classic brace-misnesting failure."""

    missing = {
        item["loc"][0]
        for item in error.errors()
        if item.get("type") == "missing" and item.get("loc")
    }
    if "program" not in missing:
        return None
    nested = _find_key_paths(dict(arguments), "program")
    if nested:
        return (
            "jq_project 参数缺少顶层 program 字段，但在 "
            + "、".join(nested)
            + " 检测到 program——参数 JSON 花括号遗漏/错位，"
            "program 被嵌套进了其他字段内部。请重新生成调用："
            "program 必须是顶层字段；若 jsonArgs 体量巨大，"
            "请拆分为少量几次较小的 jq_project 调用。项目未被修改。"
        )
    return "jq_project 参数缺少顶层 program 字段，请补全后重试；项目未被修改。"


_PROJECT_SCHEMA_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("visual", "variants"),
        "variants 定义在 visual.entities.items[<entityId>].variants 之下，"
        "visual 顶层没有 variants 字段",
    ),
)
_MAX_SCHEMA_ERROR_LINES = 8


def _translate_project_schema_error(error: ValidationError) -> str:
    """Render post-jq Project validation errors as located, fixable items."""

    items = error.errors()
    lines: list[str] = []
    for item in items[:_MAX_SCHEMA_ERROR_LINES]:
        loc = tuple(str(part) for part in item.get("loc", ()))
        path = ".".join(loc) or "$"
        hint = ""
        for prefix, text in _PROJECT_SCHEMA_HINTS:
            if loc[: len(prefix)] == prefix:
                hint = f"（{text}）"
                break
        else:
            if item.get("type") == "extra_forbidden":
                hint = (
                    "（该字段不在 Project Schema 中，"
                    "请对照 system prompt 里的 PROJECT_JSON_SCHEMA）"
                )
        lines.append(f"- {path}: {item.get('msg', 'invalid')}{hint}")
    if len(items) > _MAX_SCHEMA_ERROR_LINES:
        lines.append(f"- ...另有 {len(items) - _MAX_SCHEMA_ERROR_LINES} 处错误")
    return (
        "jq 输出未通过 Project Schema 校验，项目未被修改：\n"
        + "\n".join(lines)
        + "\n请修正 program/jsonArgs 后重试。"
    )


class AgentProjectTools:
    """Request-scoped implementation of the indexed Project tool surface."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        context: AgentProjectToolContext,
        transformer: JqProjectTransformer | None = None,
        commits: ProjectCommitBoundary | None = None,
        max_cached_bases: int = 32,
    ) -> None:
        if max_cached_bases <= 0:
            raise ValueError("max_cached_bases must be positive")
        self.store = store
        self.context = AgentProjectToolContext.model_validate(context)
        self.transformer = transformer or JqProjectTransformer()
        self.commits = commits or ProjectCommitBoundary(store)
        # Generated once per process/schema and reused byte-for-byte across
        # every model turn, preserving the provider KV-cache prefix.
        self.schema_prompt: ProjectSchemaPrompt = build_project_schema_prompt()
        self.max_cached_bases = max_cached_bases
        self._cache_lock = threading.RLock()
        # Last snapshot this request-scoped boundary observed per Project.
        # jq_project commits against it; the model never echoes ETags.
        self._observed: OrderedDict[str, ProjectSnapshot] = OrderedDict()

    @staticmethod
    def _snapshot_result(
        snapshot: ProjectSnapshot,
    ) -> AgentProjectSnapshotResult:
        # Never expose the mutable Pydantic instance held by the base cache.
        return AgentProjectSnapshotResult(
            project=snapshot.project.model_copy(deep=True),
            generation=snapshot.generation,
            etag=snapshot.etag,
        )

    def _remember(self, snapshot: ProjectSnapshot) -> None:
        key = snapshot.project.project_id
        with self._cache_lock:
            self._observed[key] = snapshot
            self._observed.move_to_end(key)
            while len(self._observed) > self.max_cached_bases:
                self._observed.popitem(last=False)

    def _base(self, project_id: str) -> ProjectSnapshot:
        """The last observed snapshot, or the latest one on first contact."""

        with self._cache_lock:
            observed = self._observed.get(project_id)
            if observed is not None:
                self._observed.move_to_end(project_id)
                return observed
        latest = self.store.read(project_id)
        self._remember(latest)
        return latest

    def read_project(self, project_id: str) -> AgentProjectSnapshotResult:
        request = ReadProjectToolInput(projectId=project_id)
        snapshot = self.store.read(request.project_id)
        self._remember(snapshot)
        return self._snapshot_result(snapshot)

    def read_project_file(
        self,
        *,
        project_id: str,
        file_id: str,
        offset: int = 0,
        max_bytes: int = _DEFAULT_TEXT_PAGE_BYTES,
    ) -> AgentProjectFileResult:
        request = ReadProjectFileToolInput(
            projectId=project_id,
            fileId=file_id,
            offset=offset,
            maxBytes=max_bytes,
        )
        snapshot = self.store.read(request.project_id)
        indexed = snapshot.project.assets.files_by_id.get(request.file_id)
        if indexed is None:
            raise AgentProjectToolError(
                f"Project IndexedFile does not exist: {request.file_id!r}",
            )
        media_type = indexed.media_type.casefold().split(";", 1)[0].strip()
        if not (
            media_type.startswith("text/")
            or media_type
            in {
                "application/json",
                "application/ld+json",
                "application/xml",
            }
        ):
            raise AgentProjectToolError(
                f"IndexedFile is not readable UTF-8 text: {indexed.media_type!r}",
            )
        if request.offset > indexed.size_bytes:
            raise AgentProjectToolError(
                "read_project_file offset exceeds file size",
            )
        stream = AssetFileStore(
            self.store.project_root(request.project_id),
        ).open_verified(indexed)
        try:
            stream.seek(request.offset)
            buffered = stream.read(request.max_bytes)
        finally:
            stream.close()
        # Return only complete UTF-8 code points. The resulting nextOffset is
        # therefore always a valid boundary for the next page.
        raw = buffered
        while True:
            try:
                content = raw.decode("utf-8")
                break
            except UnicodeDecodeError as error:
                # A valid page can only fail at its trailing, incomplete code
                # point. Any error earlier in the page (or at the requested
                # offset) means the IndexedFile is not valid UTF-8 for this
                # byte-pagination contract.
                if (
                    error.reason != "unexpected end of data"
                    or request.offset + len(buffered) >= indexed.size_bytes
                ):
                    raise AgentProjectToolError(
                        "IndexedFile is not valid UTF-8 text",
                    ) from error
                raw = raw[: error.start]
        next_offset = request.offset + len(raw)
        return AgentProjectFileResult(
            projectId=request.project_id,
            projectEtag=snapshot.etag,
            fileId=indexed.file_id,
            kind=indexed.kind,
            mediaType=indexed.media_type,
            sha256=indexed.sha256,
            sizeBytes=indexed.size_bytes,
            offset=request.offset,
            nextOffset=next_offset,
            eof=next_offset >= indexed.size_bytes,
            content=content,
        )

    def jq_project(
        self,
        *,
        project_id: str,
        program: str,
        string_args: Mapping[str, str] | None = None,
        json_args: Mapping[str, Any] | None = None,
    ) -> AgentProjectCommitResult:
        request = JqProjectToolInput(
            projectId=project_id,
            program=program,
            stringArgs=dict(string_args or {}),
            jsonArgs=dict(json_args or {}),
        )
        base = self._base(request.project_id)
        candidate = self.transformer.transform(
            base.project.model_dump(mode="json"),
            request.program,
            string_args=request.string_args,
            json_args=request.json_args,
        )
        base_data = base.project.model_dump(mode="json")
        changed_protected = [
            pointer
            for pointer in sorted(PROTECTED_EXACT_POINTERS)
            if candidate.get(pointer[1:]) != base_data[pointer[1:]]
        ]
        if changed_protected:
            raise AgentProjectToolError(
                "jq_project 必须返回完整 Project 根对象并原样保留 Runtime 保护字段；"
                "当前输出缺失或改变了 "
                + ", ".join(changed_protected)
                + "。不要以 `| $child` 或嵌套路径选择结束 jq program。",
            )
        result = self.commits.commit(
            base=base,
            candidate=candidate,
            **self.context.commit_metadata(),
        )
        self._remember(result.snapshot)
        snapshot = self._snapshot_result(result.snapshot)
        return AgentProjectCommitResult(
            **snapshot.model_dump(mode="python"),
            transactionId=result.transaction_id,
            changedPointers=[
                change.json_pointer
                for change in result.changeset.changes
                if change.json_pointer is not None
            ],
            reviewId=result.review.review_id
            if result.review is not None
            else None,
        )

    def elements_at(
        self,
        *,
        project_id: str,
        timeline_id: str,
        tick: int,
        include_disabled: bool = False,
    ) -> AgentElementsAtResult:
        request = ElementsAtToolInput(
            projectId=project_id,
            timelineId=timeline_id,
            tick=tick,
            includeDisabled=include_disabled,
        )
        snapshot = self.store.read(request.project_id)
        self._remember(snapshot)
        return AgentElementsAtResult(
            projectId=request.project_id,
            projectEtag=snapshot.etag,
            timelineId=request.timeline_id,
            tick=request.tick,
            elements=snapshot.project.elements_at(
                request.timeline_id,
                request.tick,
                include_disabled=request.include_disabled,
            ),
        )

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate model-facing camelCase arguments and return JSON data."""

        if tool_name == READ_PROJECT_TOOL_NAME:
            request = ReadProjectToolInput.model_validate(dict(arguments))
            result: BaseModel = self.read_project(request.project_id)
        elif tool_name == READ_PROJECT_FILE_TOOL_NAME:
            request = ReadProjectFileToolInput.model_validate(dict(arguments))
            result = self.read_project_file(
                project_id=request.project_id,
                file_id=request.file_id,
                offset=request.offset,
                max_bytes=request.max_bytes,
            )
        elif tool_name == JQ_PROJECT_TOOL_NAME:
            try:
                request = JqProjectToolInput.model_validate(dict(arguments))
            except ValidationError as exc:
                translated = _translate_jq_input_error(arguments, exc)
                if translated is None:
                    raise
                raise AgentProjectToolError(translated) from exc
            try:
                result = self.jq_project(
                    project_id=request.project_id,
                    program=request.program,
                    string_args=request.string_args,
                    json_args=request.json_args,
                )
            except ValidationError as exc:
                raise AgentProjectToolError(
                    _translate_project_schema_error(exc),
                ) from exc
        elif tool_name == ELEMENTS_AT_TOOL_NAME:
            request = ElementsAtToolInput.model_validate(dict(arguments))
            result = self.elements_at(
                project_id=request.project_id,
                timeline_id=request.timeline_id,
                tick=request.tick,
                include_disabled=request.include_disabled,
            )
        else:
            raise UnknownAgentProjectTool(
                f"unknown Project tool: {tool_name!r}",
            )
        return result.model_dump(mode="json", by_alias=True)


# Explicit architectural name; ``AgentProjectTools`` remains the shorter
# request-runtime construction name.
AgentProjectToolBoundary = AgentProjectTools


__all__ = [
    "AGENT_PROJECT_TOOL_SCHEMAS",
    "ELEMENTS_AT_TOOL_NAME",
    "JQ_PROJECT_TOOL_NAME",
    "READ_PROJECT_FILE_TOOL_NAME",
    "READ_PROJECT_TOOL_NAME",
    "AgentProjectCommitResult",
    "AgentElementsAtResult",
    "AgentProjectFileResult",
    "AgentProjectSnapshotResult",
    "AgentProjectToolContext",
    "AgentProjectToolBoundary",
    "AgentProjectToolError",
    "AgentProjectTools",
    "JqProjectToolInput",
    "ElementsAtToolInput",
    "ReadProjectFileToolInput",
    "ReadProjectToolInput",
    "UnknownAgentProjectTool",
    "agent_project_tool_manifest",
]
