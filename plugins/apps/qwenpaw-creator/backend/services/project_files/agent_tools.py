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
from hashlib import sha256
import json
from typing import Any, Mapping
import threading

from json_repair import repair_json
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from services.runtime_files.models import (
    ChangeOrigin,
    ReviewBoundary,
    ReviewPolicy,
)
from utils.logger import setup_logger

from .assets import AssetFileStore
from .candidate_normalization import normalize_project_candidate
from .commit import PROTECTED_EXACT_POINTERS, ProjectCommitBoundary
from .jq_transform import JqProjectTransformer
from .models import EditPlan, Project, TimelineElement
from .patch_ops import PatchOpError, apply_patch_ops
from .schema_prompt import ProjectSchemaPrompt, build_project_schema_prompt
from .store import ProjectSnapshot, ProjectStore

logger = setup_logger("creator.project_files.agent_tools")


class _AdvisoryDedup:
    """Bounded, thread-safe per-project dedupe of advisory content hashes.

    Commits from concurrent requests share this module-level cache, so the
    read-check-write must run under a lock; the LRU cap keeps a
    long-running server from accumulating one entry per project forever.
    """

    def __init__(self, max_size: int = 256) -> None:
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._max = max_size
        self._lock = threading.Lock()

    def seen(self, key: str, digest: str) -> bool:
        """Record *digest* for *key*; True when it was already current."""
        with self._lock:
            if self._cache.get(key) == digest:
                self._cache.move_to_end(key)
                return True
            self._cache[key] = digest
            self._cache.move_to_end(key)
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)
            return False

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# Per-project dedupe of the latest plan-advisory content hash: the model
# is nudged once per distinct gap, never spammed on every commit.
_PLAN_ADVISORY_SEEN = _AdvisoryDedup()

# Cut-boundary advisory dedupe + a small transcript-boundary cache keyed
# by the intelligence file checksum (index bytes are immutable per hash).
_CUT_ADVISORY_SEEN = _AdvisoryDedup()
_TRANSCRIPT_BOUNDARY_CACHE: OrderedDict[str, tuple[int, ...]] = OrderedDict()
_TRANSCRIPT_BOUNDARY_CACHE_MAX = 16
# Audio-first cutting (WT-B5): a spoken-source cut endpoint further than
# this from every ASR sentence boundary earns a hint (never a block).
CUT_BOUNDARY_TOLERANCE_MS = 300


def _edit_plan_missing_fields(plan: EditPlan | None) -> list[str]:
    """Which taste-contract fields the plan advisory should ask for."""
    if plan is None:
        return [
            "edit_plan",
            "concept",
            "pacing",
            "design_floor.opening",
            "design_floor.transitions",
            "design_floor.body",
            "design_floor.ending",
        ]
    missing: list[str] = []
    if not plan.concept.strip():
        missing.append("concept")
    if not plan.pacing.strip():
        missing.append("pacing")
    for slot in ("opening", "transitions", "body", "ending"):
        if not getattr(plan.design_floor, slot).strip():
            missing.append(f"design_floor.{slot}")
    return missing


def _transcript_boundaries_ms(
    project: Project,
    project_root: Any,
    intelligence_version_id: str,
) -> tuple[int, ...]:
    """Sorted ASR sentence boundaries (ms) of one intelligence version.

    Empty when the version/file is absent or carries no speech; results
    are cached by the immutable index-file checksum.
    """
    record = project.assets.intelligence_versions_by_id.get(
        intelligence_version_id,
    )
    if record is None:
        return ()
    indexed = project.assets.files_by_id.get(record.file_id)
    if indexed is None or indexed.kind != "source_intelligence":
        return ()
    cached = _TRANSCRIPT_BOUNDARY_CACHE.get(indexed.checksum)
    if cached is not None:
        _TRANSCRIPT_BOUNDARY_CACHE.move_to_end(indexed.checksum)
        return cached
    payload = AssetFileStore(project_root).read_verified(indexed)
    raw = json.loads(payload.decode("utf-8"))
    boundaries: set[int] = set()
    for segment in raw.get("transcript") or []:
        if not isinstance(segment, dict):
            continue
        start = segment.get("startMs")
        end = segment.get("endMs")
        if isinstance(start, int) and not isinstance(start, bool):
            boundaries.add(start)
        if isinstance(end, int) and not isinstance(end, bool):
            boundaries.add(end)
    result = tuple(sorted(boundaries))
    _TRANSCRIPT_BOUNDARY_CACHE[indexed.checksum] = result
    while len(_TRANSCRIPT_BOUNDARY_CACHE) > _TRANSCRIPT_BOUNDARY_CACHE_MAX:
        _TRANSCRIPT_BOUNDARY_CACHE.popitem(last=False)
    return result


def _off_boundary_endpoints(
    element: TimelineElement,
    boundaries: tuple[int, ...],
    ticks_per_second: int,
) -> list[dict[str, Any]]:
    """Endpoints of one edit's source range that miss every sentence edge."""
    render_source = element.render_source
    findings: list[dict[str, Any]] = []
    endpoints: list[tuple[str, int | None]] = [
        ("in", getattr(render_source, "source_in_tick", None)),
        ("out", getattr(render_source, "source_out_tick", None)),
    ]
    for endpoint, tick in endpoints:
        if tick is None:
            continue
        cut_ms = round(tick * 1000 / ticks_per_second)
        nearest = min(boundaries, key=lambda item, cut=cut_ms: abs(item - cut))
        offset = cut_ms - nearest
        if abs(offset) > CUT_BOUNDARY_TOLERANCE_MS:
            findings.append(
                {
                    "elementId": element.element_id,
                    "endpoint": endpoint,
                    "cutMs": cut_ms,
                    "nearestSentenceBoundaryMs": nearest,
                    "offsetMs": offset,
                },
            )
    return findings


READ_PROJECT_TOOL_NAME = "read_project"
READ_PROJECT_FILE_TOOL_NAME = "read_project_file"
JQ_PROJECT_TOOL_NAME = "jq_project"
PATCH_PROJECT_TOOL_NAME = "patch_project"
ELEMENTS_AT_TOOL_NAME = "elements_at"
_DEFAULT_TEXT_PAGE_BYTES = 64 * 1024
_MAX_TEXT_PAGE_BYTES = 256 * 1024


class AgentProjectToolError(RuntimeError):
    """Base error for the Project tool boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROJECT_TOOL_ERROR",
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = dict(details or {})


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


class PatchProjectToolInput(_ToolModel):
    project_id: str = Field(alias="projectId", min_length=1)
    # Each op is validated by ``apply_patch_ops`` so failures carry the
    # exact op index instead of an opaque pydantic location.
    ops: list[dict[str, Any]] = Field(min_length=1)

    @field_validator("ops", mode="before")
    @classmethod
    def _decode_stringified_ops(cls, value: Any) -> Any:
        # Field trip 2026-08-05: the model double-encoded ops as a JSON
        # string on its very first call. When the string parses to a list
        # the decode is lossless, so refusing it only costs a retry turn.
        # Second field trip the same day: the stringified array itself
        # carried a bracket slip (a missing comma at char 973), so strict
        # parsing bounced it with a misleading "must not be a string"
        # message and the model resent verbatim into the breaker. Streamed
        # tool arguments already flow through json_repair; the same repair
        # applies here, guarded to structure-only fixes by re-checking the
        # result is a list of objects.
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                repaired = repair_json(value, return_objects=True)
                if isinstance(repaired, list) and all(
                    isinstance(item, Mapping) for item in repaired
                ):
                    return repaired
                return value
            if isinstance(decoded, list):
                return decoded
        return value


def _patch_project_input_error(arguments: Mapping[str, Any]) -> str:
    """Name the actual defect instead of a generic shape lecture.

    A stringified ops payload whose inner JSON carries a bracket slip
    must hear where the slip is — "must not be a string" made the model
    resend verbatim into the non-progress breaker.
    """

    base = (
        "patch_project 参数无效：ops 必须是操作对象数组（如 "
        '[{"op": "replace", "path": "/name", "value": "..."}]）。'
    )
    ops = arguments.get("ops")
    if isinstance(ops, str):
        try:
            json.loads(ops)
        except json.JSONDecodeError as decode_error:
            return (
                base + f"收到的 ops 是字符串，且内部 JSON 存在语法错误（"
                f"第 {decode_error.pos} 字符附近：{decode_error.msg}）。"
                "请修复该处语法后以 JSON 数组（非字符串）重发。"
            )
        return base + "收到的 ops 是字符串，请直接发送 JSON 数组。"
    if isinstance(ops, Mapping):
        return base + "收到的 ops 是单个对象，请包裹为数组。"
    return base


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
    # Redundant identity echoes stripped before validation; see
    # ``candidate_normalization``. Tells the model what was removed so the
    # habit is not silently reinforced.
    normalized_pointers: list[str] = Field(
        default_factory=list,
        alias="normalizedPointers",
    )
    review_id: str | None = Field(default=None, alias="reviewId")
    # Advisory in-run review of the committed creative text (run_review
    # sync bypass). Populated only when CREATOR_SYNC_REVIEW_ENABLED is on
    # and the commit touched reviewable pointers; the model sees it on its
    # next turn and decides whether to revise.
    review_advisory: dict[str, Any] | None = Field(
        default=None,
        alias="reviewAdvisory",
    )
    # Advisory taste-contract nudge (upstream plan_gate, softened): set
    # when this commit ADDED edit/motion_clip Elements to a Timeline whose
    # edit_plan is missing or incomplete. Never blocks the commit; the
    # model may fill the plan in or knowingly proceed.
    plan_advisory: dict[str, Any] | None = Field(
        default=None,
        alias="planAdvisory",
    )
    # Advisory audio-first cut check (WT-B5, soft): set when this commit
    # ADDED edit Elements whose spoken-source endpoints sit further than
    # CUT_BOUNDARY_TOLERANCE_MS from every ASR sentence boundary. Never
    # blocks the commit.
    cut_advisory: dict[str, Any] | None = Field(
        default=None,
        alias="cutAdvisory",
    )


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
            "jsonArgs 中的 object 已经是 jq object，应直接赋值或合并；"
            "仅当输入确实是 [{key,value}] 数组时才使用 from_entries。"
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
                        "object 参数已经是 jq object，不要再对它使用 from_entries。"
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["projectId", "program"],
            "additionalProperties": False,
        },
    },
    PATCH_PROJECT_TOOL_NAME: {
        "description": (
            "用一组小而扁平的操作列表修改 Project，适用于 90% 的日常写入"
            "（新建/更新实体、Element、改字段）；需要计算的复杂变换才用 "
            "jq_project。每个 op 独立且浅（value 嵌套勿超 2 层）："
            'add/replace/remove 用 RFC 6901 path（如 "/timelines/items/'
            'timeline:main/elements_by_id/elem:x"，数组末尾用 "-"）；'
            "upsert_entity 用于 EntityCollection（如 visual.entities 或某实体的 "
            "variants），Runtime 自动同步 items 与 order。创建带 shots 的 "
            "Element 时先用一个 op 建骨架（shots 空集合），再逐个 op 补 shot。"
            "整个 ops 列表原子提交：全部成功或全部不生效，失败时报告出错的 "
            "op 序号与 path。禁止触碰 Runtime 保护字段与媒体写回区。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "minLength": 1},
                "ops": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": [
                                    "add",
                                    "replace",
                                    "remove",
                                    "upsert_entity",
                                ],
                            },
                            "path": {
                                "type": "string",
                                "description": (
                                    "add/replace/remove 的 RFC 6901 目标路径"
                                ),
                            },
                            "value": {
                                "description": (
                                    "add/replace/upsert_entity 的写入值；" "保持浅嵌套"
                                ),
                            },
                            "collection": {
                                "type": "string",
                                "description": (
                                    "upsert_entity 目标 EntityCollection 的路径"
                                ),
                            },
                            "id": {
                                "type": "string",
                                "description": (
                                    "upsert_entity 写入的实体 key，须与 value "
                                    "内的身份字段一致"
                                ),
                            },
                        },
                        "required": ["op"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["projectId", "ops"],
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
    (
        ("creation", "overlay"),
        "Overlay creation 的动效字段（emotion、entrance、exit、"
        "intensity、theme、variant、motif、html、fps、loop、"
        "design_notes）必须放在 creation.motion 子对象内，"
        "不得直接写在 creation 上；"
        "Overlay 没有 overlay_kind 字段：台词卡把文案写入 text，"
        "text 为空的装饰/媒体 Overlay 必须携带非空 prompt 或引用版本",
    ),
)
# Root-level model validators surface with an empty ``loc``, so path-prefix
# hints never match them; these hints key on the error message instead.
# More specific needles must come first.
_PROJECT_SCHEMA_MESSAGE_HINTS: tuple[tuple[str, str], ...] = (
    (
        "visual variant binding references missing variant",
        "绑定的 variantId 必须已存在于该实体的 variants.items 中；"
        "先创建 Variant（并在 required_variant_ids 声明）再在 Element 中绑定，"
        "或检查 variant id 拼写",
    ),
    (
        "visual variant binding",
        "visual_variant_refs 的每个 entityId 必须同时出现在同一 creation 的 "
        "character_refs/prop_refs/scene_ref 中；先把实体加入引用列表"
        "（或移除该绑定）再提交",
    ),
    (
        "must not be authored via jq_project",
        "artifact_slots_by_id 与 elements outputs 是媒体管线的写回区，"
        "禁止用 jq_project 手写或补全；视频/分镜产物只能通过委派对应的"
        "生成 Director 产生，生成完成后 Runtime 会自动写回",
    ),
)
_MAX_SCHEMA_ERROR_LINES = 8

# Fields that live on TimelineElement itself. A bracket slip in a large
# nested payload routinely drops them inside ``creation`` instead, which
# surfaces as several "Field required" errors that never name the real
# mistake.
_ELEMENT_LEVEL_FIELDS = frozenset(
    {
        "element_id",
        "span",
        "label",
        "location",
        "outputs",
        "render_source",
        "z_index",
        "enabled",
    },
)


def _misnested_element_field_hint(item: Mapping[str, Any]) -> str:
    """Name the bracket-misplacement when element fields sit in creation."""

    if item.get("type") != "missing":
        return ""
    loc = item.get("loc") or ()
    if not loc or str(loc[-1]) not in _ELEMENT_LEVEL_FIELDS:
        return ""
    parent = item.get("input")
    if not isinstance(parent, Mapping):
        return ""
    creation = parent.get("creation")
    if isinstance(creation, Mapping) and str(loc[-1]) in creation:
        return (
            "花括号层级错位：该 element 级字段被误嵌进了 creation 内部。"
            "请把 element_id/span/label 等字段提到与 creation 同级，"
            "creation 内只保留 type 及创作字段"
        )
    return ""


def _translate_project_schema_error(error: ValidationError) -> str:
    """Render post-jq Project validation errors as located, fixable items."""

    items = error.errors()
    lines: list[str] = []
    for item in items[:_MAX_SCHEMA_ERROR_LINES]:
        loc = tuple(str(part) for part in item.get("loc", ()))
        path = ".".join(loc) or "$"
        message = str(item.get("msg", "invalid"))
        hint = ""
        for prefix, text in _PROJECT_SCHEMA_HINTS:
            if loc[: len(prefix)] == prefix or any(
                loc[index : index + len(prefix)] == prefix
                for index in range(len(loc) - len(prefix) + 1)
            ):
                hint = f"（{text}）"
                break
        else:
            for needle, text in _PROJECT_SCHEMA_MESSAGE_HINTS:
                if needle in message:
                    hint = f"（{text}）"
                    break
            else:
                misnested = _misnested_element_field_hint(item)
                if misnested:
                    hint = f"（{misnested}）"
                elif item.get("type") == "extra_forbidden":
                    hint = (
                        "（该字段不在 Project Schema 中，"
                        "请对照 system prompt 里的 PROJECT_JSON_SCHEMA）"
                    )
        lines.append(f"- {path}: {message}{hint}")
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
        candidate = self._apply_agent_edit_impacts(base, candidate)
        normalized_pointers = normalize_project_candidate(candidate)
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
                code="JQ_RESULT_NOT_PROJECT_ROOT",
                details={"changedProtectedPointers": changed_protected},
            )
        result = self.commits.commit(
            base=base,
            candidate=candidate,
            **self.context.commit_metadata(),
        )
        self._remember(result.snapshot)
        snapshot = self._snapshot_result(result.snapshot)
        commit_result = AgentProjectCommitResult(
            **snapshot.model_dump(mode="python"),
            transactionId=result.transaction_id,
            changedPointers=[
                change.json_pointer
                for change in result.changeset.changes
                if change.json_pointer is not None
            ],
            normalizedPointers=normalized_pointers,
            reviewId=result.review.review_id
            if result.review is not None
            else None,
        )
        advisory = self._sync_review_advisory(commit_result)
        if advisory is not None:
            commit_result = commit_result.model_copy(
                update={"review_advisory": advisory},
            )
        plan_advisory = self._edit_plan_advisory(base.project, commit_result)
        if plan_advisory is not None:
            commit_result = commit_result.model_copy(
                update={"plan_advisory": plan_advisory},
            )
        cut_advisory = self._cut_boundary_advisory(base.project, commit_result)
        if cut_advisory is not None:
            commit_result = commit_result.model_copy(
                update={"cut_advisory": cut_advisory},
            )
        return commit_result

    def _apply_agent_edit_impacts(
        self,
        base: ProjectSnapshot,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        """Invalidate downstream renders for agent commits (fail-open).

        Manual edits already run apply_frontend_edit_impacts so a changed
        Timeline marks its selected final render stale; agent jq/patch
        commits must do the same, otherwise the unattended compose node
        reads the old master as DONE and the corrected cut is never
        rendered.
        """
        try:
            from services.project_files.edit_impact import (
                apply_frontend_edit_impacts,
            )
            from services.project_files.json_pointer import diff_json

            base_data = base.project.model_dump(mode="json")
            pointers = [
                change.pointer for change in diff_json(base_data, candidate)
            ]
            if not pointers:
                return candidate
            updated, _ = apply_frontend_edit_impacts(
                candidate,
                pointers,
                base=base_data,
            )
            return updated
        except Exception:
            logger.exception("agent edit impact application failed")
            return candidate

    def _sync_review_advisory(
        self,
        commit_result: AgentProjectCommitResult,
    ) -> dict[str, Any] | None:
        """Advisory in-run review of freshly committed creative text.

        Runs only for agent-run commits (a round_id proves the provenance)
        and only when the sync-review switch is on; strictly fail-open so
        the commit result is never disturbed by review problems.
        """
        if self.context.round_id is None:
            return None
        try:
            from models.config import is_sync_review_enabled

            if not is_sync_review_enabled():
                return None
            # Lazy import keeps the review stack out of the tool boundary
            # module graph while the switch is off.
            from services.run_review.text_review import maybe_sync_review

            return maybe_sync_review(
                project_id=commit_result.project.project_id,
                project_root=self.store.project_root(
                    commit_result.project.project_id,
                ),
                project_json=commit_result.project.model_dump(mode="json"),
                changed_pointers=commit_result.changed_pointers,
                transaction_id=commit_result.transaction_id,
            )
        except Exception:
            logger.exception("sync review advisory failed")
            return None

    def _edit_plan_advisory(
        self,
        base_project: Project,
        commit_result: AgentProjectCommitResult,
    ) -> dict[str, Any] | None:
        """Advisory taste-contract nudge (upstream plan_gate, softened).

        Emitted when an agent commit ADDED ``edit``/``motion_clip``
        Elements to a Timeline whose ``edit_plan`` is missing or
        incomplete. Purely advisory: the commit has already succeeded and
        the model may fill the plan in or knowingly proceed. Repeated
        identical hints for the same Timeline are deduplicated so the
        nudge never turns into spam. Strictly fail-open.
        """
        if self.context.round_id is None:
            return None
        try:
            hints: list[dict[str, Any]] = []
            after_timelines = commit_result.project.timelines.items
            before_timelines = base_project.timelines.items
            for timeline_id, timeline in after_timelines.items():
                before = before_timelines.get(timeline_id)
                before_ids = (
                    set(before.elements_by_id) if before is not None else set()
                )
                added = [
                    element_id
                    for element_id, element in timeline.elements_by_id.items()
                    if element_id not in before_ids
                    and getattr(element.creation, "type", None)
                    in ("edit", "motion_clip")
                ]
                if not added:
                    continue
                plan = timeline.edit_plan
                if plan is not None and plan.mechanical_exemption:
                    continue
                missing = _edit_plan_missing_fields(plan)
                if not missing:
                    continue
                hints.append(
                    {
                        "timelineId": timeline_id,
                        "addedElementIds": added,
                        "missing": missing,
                    },
                )
            if not hints:
                return None
            digest = sha256(
                json.dumps(
                    [
                        {
                            "timelineId": hint["timelineId"],
                            "missing": hint["missing"],
                        }
                        for hint in hints
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8"),
            ).hexdigest()
            dedupe_key = commit_result.project.project_id
            if _PLAN_ADVISORY_SEEN.seen(dedupe_key, digest):
                return None
            return {
                "kind": "edit_plan",
                "hints": hints,
                "message": (
                    "本次提交新增了剪辑/动效片段，但目标 Timeline 的 "
                    "edit_plan（品味契约）尚未写全。标准流程是先用 "
                    "jq_project 写入 timelines.items[目标].edit_plan（一句话"
                    "concept、三旋钮 dials、signature_device、pacing 能量骨架、"
                    "design_floor 四槽位）再装配；已有充分创作理由可说明后"
                    "继续。本提示不阻断提交。"
                ),
            }
        except Exception:
            logger.exception("edit plan advisory failed")
            return None

    def _cut_boundary_advisory(
        self,
        base_project: Project,
        commit_result: AgentProjectCommitResult,
    ) -> dict[str, Any] | None:
        """Advisory audio-first cut check (WT-B5, soft validation).

        For edit Elements ADDED by this agent commit whose source carries
        an ASR transcript, endpoints further than the tolerance from every
        sentence boundary earn a structured hint. Sources without speech
        (pure BGM) never hint; the commit itself is untouched (fail-open).
        """
        if self.context.round_id is None:
            return None
        try:
            project = commit_result.project
            project_root = self.store.project_root(project.project_id)
            hints: list[dict[str, Any]] = []
            before_timelines = base_project.timelines.items
            for timeline_id, timeline in project.timelines.items.items():
                before = before_timelines.get(timeline_id)
                before_ids = (
                    set(before.elements_by_id) if before is not None else set()
                )
                for element_id, element in timeline.elements_by_id.items():
                    creation = element.creation
                    if (
                        element_id in before_ids
                        or getattr(creation, "type", None) != "edit"
                        or element.render_source is None
                    ):
                        continue
                    intelligence_id = getattr(
                        creation,
                        "source_intelligence_version_id",
                        None,
                    )
                    if intelligence_id is None:
                        continue
                    boundaries = _transcript_boundaries_ms(
                        project,
                        project_root,
                        intelligence_id,
                    )
                    if not boundaries:
                        continue
                    for finding in _off_boundary_endpoints(
                        element,
                        boundaries,
                        timeline.ticks_per_second,
                    ):
                        hints.append(
                            {"timelineId": timeline_id, **finding},
                        )
            if not hints:
                return None
            digest = sha256(
                json.dumps(hints, ensure_ascii=False, sort_keys=True).encode(
                    "utf-8",
                ),
            ).hexdigest()
            dedupe_key = project.project_id
            if _CUT_ADVISORY_SEEN.seen(dedupe_key, digest):
                return None
            return {
                "kind": "cut_boundary",
                "toleranceMs": CUT_BOUNDARY_TOLERANCE_MS,
                "hints": hints,
                "message": (
                    "本次新增的剪辑片段中，以下切点离最近的 ASR 句边界超过 "
                    f"{CUT_BOUNDARY_TOLERANCE_MS}ms。audio-first 剪辑原则："
                    "语音素材的切点应落在句子边界，避免截断半句。可按 "
                    "nearestSentenceBoundaryMs 微调 render_source 的进出点；"
                    "若是有意为之（如留白/气口）可忽略。本提示不阻断提交。"
                ),
            }
        except Exception:
            logger.exception("cut boundary advisory failed")
            return None

    def patch_project(
        self,
        *,
        project_id: str,
        ops: list[Mapping[str, Any]],
    ) -> AgentProjectCommitResult:
        """Apply a flat operation list and commit through the same boundary.

        The candidate is derived deterministically from the last observed
        base plus *ops*, so bracket depth never travels through the model.
        Everything downstream — protected pointers, schema validation,
        normalization, three-way merge and review — is the identical
        pipeline jq_project uses.
        """

        request = PatchProjectToolInput(projectId=project_id, ops=list(ops))
        base = self._base(request.project_id)
        candidate = base.project.model_dump(mode="json")
        apply_patch_ops(candidate, request.ops)
        candidate = self._apply_agent_edit_impacts(base, candidate)
        normalized_pointers = normalize_project_candidate(candidate)
        result = self.commits.commit(
            base=base,
            candidate=candidate,
            **self.context.commit_metadata(),
        )
        self._remember(result.snapshot)
        snapshot = self._snapshot_result(result.snapshot)
        commit_result = AgentProjectCommitResult(
            **snapshot.model_dump(mode="python"),
            transactionId=result.transaction_id,
            changedPointers=[
                change.json_pointer
                for change in result.changeset.changes
                if change.json_pointer is not None
            ],
            normalizedPointers=normalized_pointers,
            reviewId=result.review.review_id
            if result.review is not None
            else None,
        )
        advisory = self._sync_review_advisory(commit_result)
        if advisory is not None:
            commit_result = commit_result.model_copy(
                update={"review_advisory": advisory},
            )
        plan_advisory = self._edit_plan_advisory(base.project, commit_result)
        if plan_advisory is not None:
            commit_result = commit_result.model_copy(
                update={"plan_advisory": plan_advisory},
            )
        cut_advisory = self._cut_boundary_advisory(base.project, commit_result)
        if cut_advisory is not None:
            commit_result = commit_result.model_copy(
                update={"cut_advisory": cut_advisory},
            )
        return commit_result

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
                raise AgentProjectToolError(
                    translated,
                    code="JQ_ARGUMENTS_MALFORMED",
                    details={
                        "validationErrors": exc.errors(
                            include_context=False,
                            include_input=False,
                            include_url=False,
                        ),
                    },
                ) from exc
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
                    code="JQ_PROJECT_SCHEMA_INVALID",
                    details={
                        "validationErrors": exc.errors(
                            include_context=False,
                            include_input=False,
                            include_url=False,
                        ),
                    },
                ) from exc
        elif tool_name == PATCH_PROJECT_TOOL_NAME:
            try:
                request = PatchProjectToolInput.model_validate(
                    dict(arguments),
                )
            except ValidationError as exc:
                raise AgentProjectToolError(
                    _patch_project_input_error(arguments),
                    code="PATCH_PROJECT_INPUT_INVALID",
                    details={
                        "validationErrors": exc.errors(
                            include_context=False,
                            include_input=False,
                            include_url=False,
                        ),
                    },
                ) from exc
            try:
                result = self.patch_project(
                    project_id=request.project_id,
                    ops=request.ops,
                )
            except PatchOpError as exc:
                raise AgentProjectToolError(
                    f"patch_project 操作无效，项目未被修改：{exc}。"
                    "请修正该 op 后重发整个 ops 列表。",
                    code="PATCH_OPS_INVALID",
                ) from exc
            except ValidationError as exc:
                raise AgentProjectToolError(
                    _translate_project_schema_error(exc),
                    code="PATCH_PROJECT_SCHEMA_INVALID",
                    details={
                        "validationErrors": exc.errors(
                            include_context=False,
                            include_input=False,
                            include_url=False,
                        ),
                    },
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
