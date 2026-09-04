# -*- coding: utf-8 -*-
"""Timeline script drafting over Project files（方案 3.3 script_draft）。

用文本模型依据 Timeline 的 title/synopsis、项目创作策略与素材理解摘要
起草该叙事节点的剧本 markdown（约定格式见
services/project_files/script_markdown.py），产物作为 ``timeline_script``
ArtifactVersion 写回 AssetIndex 并 selected —— 由此免费获得多版本 /
stale / provenance / Review 的既有机制。零媒体开销：只消耗一次文本
模型调用；``input_fingerprint`` 防重算，同输入重复派发直接复放。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from domain.errors import ValidationError
from models import text_model
from services.project_files.assets import AssetAlreadyExists, AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    Project,
    Timeline,
    narrative_timeline_ids,
)
from services.project_files.script_artifacts import (
    add_script_version,
    script_file_relative_uri,
    timeline_script_slot_id,
)
from services.project_files.script_markdown import (
    parse_script_markdown,
    serialize_script_blocks,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from utils.logger import setup_logger

logger = setup_logger("media_files.script")

# 素材理解摘要注入上限：控制 prompt 体积，避免长素材撑爆输入窗口。
_MAX_INTELLIGENCE_SOURCES = 3
_MAX_INTELLIGENCE_CHARS = 1_500

_SCRIPT_SYSTEM_PROMPT = (
    "你是短视频/短剧编剧。用约定格式 markdown 输出一集完整剧本，"
    "只输出剧本正文，不要输出任何解释或代码围栏。格式约定：\n"
    "- 场次头：`## 场 N · 内景/外景 · 地点 · 时间`；\n"
    "- 台词：`**角色名**（括注，可省略）：台词正文`，一行一句；\n"
    "- 钩子/悬念：markdown 引用块 `> ...`；\n"
    "- 动作/口播 segment：普通段落；\n"
    "- 仅剪辑体裁且素材真实存在时，才可用其真实版本 id 引用时间码："
    "`[标签](source-version://<素材版本id>?in=<tick>&out=<tick>)`"
    "（tick 为该素材时间线刻度）。\n"
    "- 生成体裁（无上传素材）剧本通篇纯文字：禁止虚构任何"
    " `[...](xxx://...)` 媒体链接或图片，画面呈现交给后续分镜/视频阶段。\n"
    "台词密度遵循短剧规范（约每 2-3 个镜头至少一句台词），"
    "对白使用口语化中文。"
)


@dataclass(frozen=True, slots=True)
class FileScriptExecutionResult:
    timeline_id: str
    slot_id: str
    artifact_version_id: str
    file_id: str
    project_etag: str
    project_generation: int
    replayed: bool


def _stable_id(prefix: str, project_id: str, idempotency_key: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:file-script:{prefix}:{project_id}:{idempotency_key}",
    ).hex
    return f"{prefix}-{digest}"


def _timeline_id_from_ref(target_ref: str) -> str:
    value = target_ref.strip().removeprefix("timeline:")
    if not value:
        raise ValidationError(f"invalid timeline ref: {target_ref!r}")
    return value


def _intelligence_digest(
    services: CreatorFileServices,
    project: Project,
) -> tuple[str, list[str]]:
    """素材理解摘要（截断）与其 provenance refs。

    读取失败只降级为空摘要，绝不阻断剧本起草。
    """

    chunks: list[str] = []
    refs: list[str] = []
    store = AssetFileStore(
        services.projects.project_root(project.project_id),
    )
    for source_id in project.sources.sources.order:
        if len(refs) >= _MAX_INTELLIGENCE_SOURCES:
            break
        source = project.sources.sources.items[source_id]
        intelligence_id = source.current_intelligence_version_id
        if intelligence_id is None:
            continue
        intelligence = project.assets.intelligence_versions_by_id.get(
            intelligence_id,
        )
        if intelligence is None:
            continue
        indexed = project.assets.files_by_id.get(intelligence.file_id)
        if indexed is None:
            continue
        try:
            text = store.read_verified(indexed).decode(
                "utf-8",
                errors="replace",
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "script draft skips unreadable intelligence file %s",
                intelligence.file_id,
                exc_info=True,
            )
            continue
        chunks.append(
            f"【素材理解 · {source.display_name} · exact 素材版本 "
            f"{intelligence.source_asset_version_id}】\n"
            + text[:_MAX_INTELLIGENCE_CHARS],
        )
        refs.append(f"asset-version:{intelligence.source_asset_version_id}")
    return "\n\n".join(chunks), refs


def _narrative_context(project: Project, timeline_id: str) -> str:
    """本集在整体结构中的位置：前后集。"""

    lines: list[str] = []
    for index, other_id in enumerate(
        narrative_timeline_ids(project),
        start=1,
    ):
        other = project.timelines.items[other_id]
        marker = "←本集" if other_id == timeline_id else ""
        lines.append(
            f"{index}. {other.title or other_id}"
            f"（{other.synopsis or '暂无梗概'}）{marker}",
        )
    return "\n".join(lines)


def _build_script_prompt(
    project: Project,
    timeline: Timeline,
    intelligence_digest: str,
) -> str:
    strategy = project.strategy
    duration = (
        f"{timeline.planned_duration_seconds:.0f} 秒"
        if timeline.planned_duration_seconds
        else (
            f"{project.settings.target_duration_seconds:.0f} 秒"
            if project.settings.target_duration_seconds
            else "未指定"
        )
    )
    genre_hint = (
        "本项目是素材剪辑项目：输出剪辑体剧本，每个段落引用素材时间码链接。"
        if project.scenario == "video_edit"
        else "输出场次体（叙事）或口播体（讲解/带货）剧本，按题材自行选择。"
    )
    sections = [
        f"项目：{project.name}（{project.description or '无描述'}）",
        (
            f"本集（叙事节点）：{timeline.title or timeline.timeline_id}\n"
            f"梗概：{timeline.synopsis or '暂无，请依据整体策略构思'}\n"
            f"目标时长：{duration}"
        ),
        (
            "创作策略：\n"
            f"- brief：{strategy.creative_brief or '无'}\n"
            f"- 受众：{strategy.audience or '无'}\n"
            f"- 创意方向：{strategy.creative_direction or '无'}\n"
            f"- 约束：{strategy.constraints or '无'}"
        ),
        "整体结构：\n" + _narrative_context(project, timeline.timeline_id),
        genre_hint,
    ]
    if intelligence_digest:
        sections.append(intelligence_digest)
    sections.append("请为本集撰写完整剧本 markdown。")
    return "\n\n".join(sections)


def _intelligence_version_ids(project: Project) -> list[str]:
    """The intelligence versions the prompt digest reads, in source order."""

    ids: list[str] = []
    for source_id in project.sources.sources.order:
        if len(ids) >= _MAX_INTELLIGENCE_SOURCES:
            break
        source = project.sources.sources.items[source_id]
        if source.current_intelligence_version_id is not None:
            ids.append(source.current_intelligence_version_id)
    return ids


def _request_fingerprint(
    project: Project,
    timeline: Timeline,
    *,
    guidance: str,
) -> str:
    # Every persisted input that reaches the prompt must be covered here;
    # otherwise an edited input silently replays a stale version. The user's
    # explicit rewrite guidance is an input too — identical retries of the
    # same guidance still replay, but new guidance must reach the model.
    digest = hashlib.sha256(
        "\x1f".join(
            [
                timeline.timeline_id,
                timeline.title,
                timeline.synopsis,
                str(timeline.planned_duration_seconds or ""),
                project.strategy.creative_brief,
                project.strategy.audience,
                project.strategy.creative_direction,
                project.strategy.constraints,
                # The prompt embeds the whole narrative structure (episode
                # list + branch edges); new episodes/edges must re-draft.
                _narrative_context(project, timeline.timeline_id),
                guidance,
                *_intelligence_version_ids(project),
            ],
        ).encode("utf-8"),
    ).hexdigest()
    return f"sha256:{digest}"


def _existing_replay(
    services: CreatorFileServices,
    project: Project,
    timeline_id: str,
    fingerprint: str,
    *,
    etag: str,
    generation: int,
) -> FileScriptExecutionResult | None:
    """同输入防重算：选中版本的 input_fingerprint 命中且未 stale 即复放。"""

    del services
    slot = project.assets.artifact_slots_by_id.get(
        timeline_script_slot_id(timeline_id),
    )
    if slot is None or slot.selected_version_id is None:
        return None
    version = project.assets.artifact_versions_by_id.get(
        slot.selected_version_id,
    )
    if (
        version is None
        or version.stale
        or version.input_fingerprint != fingerprint
    ):
        return None
    return FileScriptExecutionResult(
        timeline_id=timeline_id,
        slot_id=slot.slot_id,
        artifact_version_id=version.version_id,
        file_id=version.file_id,
        project_etag=etag,
        project_generation=generation,
        replayed=True,
    )


def _publish_script_version(
    services: CreatorFileServices,
    *,
    project_id: str,
    timeline_id: str,
    markdown_text: str,
    idempotency_key: str,
    fingerprint: str,
    provenance_refs: list[str],
) -> FileScriptExecutionResult:
    """落盘 markdown 文件并通过提交边界写回索引（commit 时全量校验）。"""

    content = markdown_text.encode("utf-8")
    checksum = hashlib.sha256(content).hexdigest()
    file_id = _stable_id("file-script", project_id, idempotency_key)
    relative_uri = script_file_relative_uri(file_id)
    now = datetime.now(UTC)
    project_root = services.projects.project_root(project_id)
    file_store = AssetFileStore(project_root)

    with services.projects.lifecycle_lock(project_id):
        base = services.projects.read(project_id)
        if timeline_id not in base.project.timelines.items:
            raise ValidationError(f"timeline 已不存在: {timeline_id}")
        working = base.project.model_copy(deep=True)
        version = add_script_version(
            working,
            timeline_id,
            markdown_text,
            file_id=file_id,
            checksum=checksum,
            name=(
                f"剧本 · "
                f"{working.timelines.items[timeline_id].title or timeline_id}"
            )[:160],
            now=now,
            based_on_generation=base.generation,
            provenance_refs=provenance_refs,
            input_fingerprint=fingerprint,
        )
        indexed = working.assets.files_by_id[version.file_id]
        if version.file_id == file_id:
            staged = file_store.stage_bytes(
                content,
                staging_id=f"script-{file_id[:48]}",
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
        commit = services.commits.commit(
            base=base,
            candidate=working.model_dump(mode="json"),
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id=idempotency_key,
            round_id=_stable_id("round", project_id, idempotency_key),
            transaction_id=_stable_id(
                "transaction",
                project_id,
                idempotency_key,
            ),
            advance_accepted_baseline=True,
            _lifecycle_lock_held=True,
        )
        services.poller.note_commit(commit.snapshot)
    return FileScriptExecutionResult(
        timeline_id=timeline_id,
        slot_id=version.slot_id,
        artifact_version_id=version.version_id,
        file_id=version.file_id,
        project_etag=commit.snapshot.etag,
        project_generation=commit.snapshot.generation,
        replayed=False,
    )


async def execute_file_script_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
) -> FileScriptExecutionResult:
    """起草一条 timeline 的剧本并作为 timeline_script 版本写回。"""

    timeline_id = _timeline_id_from_ref(target_ref)
    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    project = snapshot.project
    timeline = project.timelines.items.get(timeline_id)
    if timeline is None:
        raise ValidationError(f"timeline 不存在: {timeline_id}")

    guidance = str(arguments.get("guidance") or "").strip()
    fingerprint = _request_fingerprint(project, timeline, guidance=guidance)
    # Stale re-drafts share the node's dispatch idempotency key but must not
    # reuse a previous publish transaction. Staleness triggers on more inputs
    # than the fingerprint covers (e.g. element edits), so scope the durable
    # ids by fingerprint AND the slot's existing version count — the N-th
    # re-draft of identical prompt inputs is still a fresh transaction.
    # Identical fresh inputs never reach publish: the semantic replay below
    # returns the existing version first.
    slot = project.assets.artifact_slots_by_id.get(
        timeline_script_slot_id(timeline_id),
    )
    revision = len(slot.version_ids) if slot is not None else 0
    idempotency_key = f"{idempotency_key}:{fingerprint[:16]}:r{revision}"
    replay = _existing_replay(
        services,
        project,
        timeline_id,
        fingerprint,
        etag=snapshot.etag,
        generation=snapshot.generation,
    )
    if replay is not None:
        logger.info(
            "script draft semantic replay: project=%s timeline=%s version=%s",
            project_id,
            timeline_id,
            replay.artifact_version_id,
        )
        return replay

    intelligence_digest, intelligence_refs = await asyncio.to_thread(
        _intelligence_digest,
        services,
        project,
    )
    prompt = _build_script_prompt(project, timeline, intelligence_digest)
    if guidance:
        prompt += f"\n\n额外修改意见（必须遵循）：{guidance}"
    raw = await text_model.chat_completion(
        prompt,
        system_prompt=_SCRIPT_SYSTEM_PROMPT,
        temperature=0.4,
    )
    # 归一化到约定块格式：解析/序列化双向无损，保证前端块级渲染与
    # 块级 diff 有稳定基线。
    markdown_text = serialize_script_blocks(parse_script_markdown(raw))
    if not markdown_text.strip():
        raise ValidationError("剧本起草结果为空，请调整策略/梗概后重试")

    return await asyncio.to_thread(
        _publish_script_version,
        services,
        project_id=project_id,
        timeline_id=timeline_id,
        markdown_text=markdown_text,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        provenance_refs=intelligence_refs,
    )


__all__ = [
    "FileScriptExecutionResult",
    "execute_file_script_command",
]
