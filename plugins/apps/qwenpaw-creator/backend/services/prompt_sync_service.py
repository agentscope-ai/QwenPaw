# -*- coding: utf-8 -*-
"""
Explicit text-only prompt proposals with a frozen baseline and atomic accept.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError as ModelValidationError

from domain.errors import ConflictError, NotFoundError, ValidationError
from models import config as model_config
from models.reference_markers import canonical_marker_indices
from services.file_agent_runtime.model_client import AgentScopeAgentChatClient
from services.media_files.prompt_labels import media_prompt_entity_names
from services.media_files.visual_reference_resolution import (
    preview_r2v_reference_order,
)
from services.project_files.edit_impact import apply_frontend_edit_impacts
from services.project_files.models import (
    Project,
    StrictModel,
)
from services.storyboard_layout import declared_storyboard_panel_count
from services.project_files.prompt_sync import (
    digest,
    live_element,
    plan_input,
    prompt_sync_status,
)
from services.project_files.store import ProjectNotFound
from services.run_review.prompt_contract import (
    check_changed_r2v_prompt_contracts,
)
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.errors import RecordNotFoundError

PromptSyncSource = Literal[
    "currentPlan",
    "storyboardPrompt",
    "videoPrompt",
    "mixed",
]


class PromptProposal(StrictModel):
    proposal_id: str
    project_id: str
    timeline_id: str
    element_id: str
    baseline_token: str
    reference_fingerprint: str
    model_fingerprint: str
    source: PromptSyncSource = "currentPlan"
    before_narrative: str
    narrative: str
    before_storyboard_prompt: str
    before_video_prompt: str
    storyboard_prompt: str
    video_prompt: str


def _pointer(timeline_id: str, element_id: str) -> str:
    def escape(value: str) -> str:
        return value.replace("~", "~0").replace("/", "~1")

    return (
        f"/timelines/items/{escape(timeline_id)}"
        f"/elements_by_id/{escape(element_id)}/creation"
    )


def _model_fingerprint() -> str:
    return digest(
        (
            model_config.get_image_model_name(),
            model_config.get_video_model_name(),
            model_config.get_video_backend(),
        ),
    )


def _references(project: Project, element_id: str) -> dict:
    storyboard = preview_r2v_reference_order(
        project,
        element_id,
        stage="storyboard",
        image_model_name=model_config.get_image_model_name(),
    )
    video = preview_r2v_reference_order(project, element_id, stage="video")
    video_rows = video["references"]
    if not any(row.get("kind") == "storyboard" for row in video_rows):
        # Reserve the actual target's future storyboard role, never invent a
        # version ID or silently use a character image as the first storyboard.
        video_rows = [
            {
                "index": 1,
                "kind": "storyboard",
                "name": "本镜头的分镜图（尚未生成）",
            },
            *[{**row, "index": row["index"] + 1} for row in video_rows],
        ]
    return {
        "storyboard": storyboard["references"],
        "video": video_rows,
        "storyboardBudgetDroppedVersionIds": storyboard[
            "budgetDroppedVersionIds"
        ],
        "storyboardReferenceLimit": storyboard["referenceLimit"],
    }


def _context_token(
    document,
    timeline_id,
    element_id,
    references,
    model_fingerprint,
):
    """
    Bind a reviewed text snapshot to its real input order and model settings.
    """
    return digest(
        {
            "source": prompt_sync_status(document, timeline_id, element_id)[
                "baselineToken"
            ],
            "references": digest(references),
            "models": model_fingerprint,
        },
    )


def _validate_proposal_references(references: dict) -> None:
    if references.get("storyboardBudgetDroppedVersionIds"):
        # Legacy automatic trimming stops once canonical markers are authored.
        # Do not draft against a trimmed order that cannot survive acceptance.
        raise ValidationError(
            "参考图超出当前模型容量，请先明确整理分镜参考图列表",
        )
    limit = references.get("storyboardReferenceLimit")
    if references["storyboard"] and (
        limit is None or len(references["storyboard"]) > limit
    ):
        raise ValidationError("参考图超出当前模型容量，请先整理分镜参考图列表")
    if any(
        row.get("available") is False
        and not (
            stage == "video"
            and row.get("kind") == "storyboard"
            and not row.get("versionId")
        )
        for stage in ("storyboard", "video")
        for row in references[stage]
    ):
        raise ValidationError("当前参考图尚不可用，请先完成或重新选择参考图片")


def _complete_reference_mentions(prompt: str, references: list[dict]) -> str:
    """
    Fill only omitted bindings using the frozen, actual provider input order.
    """
    cited = set(canonical_marker_indices(prompt))
    additions = []
    for row in references:
        index = row["index"]
        if index in cited:
            continue
        name = re.sub(r"[（(]default[）)]", "", row["name"])
        usage = (
            "提供本镜头动作顺序，连续呈现动作，不展示宫格"
            if row.get("kind") == "storyboard"
            else "保持对应视觉内容的一致性"
        )
        additions.append(f"[Image {index}]是{name}，{usage}。")
    return prompt + (
        "\n\n参考图片补充：\n" + "\n".join(additions) if additions else ""
    )


def _validate_prompts(
    document: dict,
    timeline_id: str,
    element_id: str,
    references: dict,
    *,
    proposal: bool = False,
) -> None:
    _, element = live_element(document, timeline_id, element_id)
    creation = element["creation"]
    path = _pointer(timeline_id, element_id)
    report = check_changed_r2v_prompt_contracts(
        document,
        [path + "/storyboard_prompt", path + "/video_prompt"],
    )
    if not report["passed"]:
        raise ValidationError(
            "提示词尚未满足画幅或引用要求",
            details={"findings": report["findings"]},
        )
    for stage in ("storyboard", "video"):
        text = creation[f"{stage}_prompt"]
        indexes = canonical_marker_indices(text)
        if any(
            index < 1 or index > len(references[stage]) for index in indexes
        ):
            raise ValidationError("提示词引用了当前镜头没有的参考图")
        if proposal and set(indexes) != set(
            range(1, len(references[stage]) + 1),
        ):
            raise ValidationError(
                ("分镜图" if stage == "storyboard" else "视频")
                + "提示词缺少部分已绑定参考图片，请补充引用后重新生成",
            )
        if proposal and re.search(
            r"@image_\d|<<<image_\d|(?:图|图片)\s*\d",
            text,
        ):
            raise ValidationError(
                "参考图片请统一写成 [Image N]，模型格式由执行器转换",
            )


def _validate_plan(document: dict, timeline_id: str, element_id: str) -> None:
    _, element = live_element(document, timeline_id, element_id)
    if not str(element["creation"].get("narrative") or "").strip():
        raise ValidationError("请先填写片段内容，或从已有提示词同步内容")


class PromptSyncService:
    def __init__(self, services, *, client=None):
        self.services = services
        self.client = client

    def _read(self, project_id: str, timeline_id: str, element_id: str):
        try:
            snapshot = self.services.projects.read(project_id)
        except ProjectNotFound as error:
            raise NotFoundError("项目不存在") from error
        document = snapshot.project.model_dump(mode="json")
        live_element(document, timeline_id, element_id)
        return snapshot, document

    def status(
        self,
        project_id: str,
        timeline_id: str,
        element_id: str,
    ) -> dict:
        snapshot, document = self._read(project_id, timeline_id, element_id)
        _, element = live_element(document, timeline_id, element_id)
        creation = element["creation"]
        status = prompt_sync_status(document, timeline_id, element_id)
        layout_issue = (
            "分镜图提示词的格数不明确或互相冲突，请统一网格、分镜格数和关键帧数量后重新生成"
            if (
                status["status"] == "current"
                or "storyboardPrompt" in status["changedSources"]
            )
            and declared_storyboard_panel_count(creation["storyboard_prompt"])
            is None
            else None
        )
        return {
            **status,
            "validationMessage": layout_issue,
            "baselineToken": _context_token(
                document,
                timeline_id,
                element_id,
                _references(snapshot.project, element_id),
                _model_fingerprint(),
            ),
            "generation": snapshot.generation,
            "storyboardPrompt": creation["storyboard_prompt"],
            "videoPrompt": creation["video_prompt"],
            "narrative": creation["narrative"],
        }

    def _record(self, project_id: str, proposal_id: str):
        if not re.fullmatch(r"prompt-proposal-[a-f0-9]{32}", proposal_id):
            raise NotFoundError("提示词草稿不存在")
        return AtomicJsonRecordStore(
            self.services.projects.project_root(project_id)
            / "runtime"
            / "prompt-proposals"
            / f"{proposal_id}.json",
            PromptProposal,
        )

    # Keep frozen inputs and all model output checks in one proposal flow.
    # pylint: disable-next=too-many-statements
    async def propose(
        self,
        project_id: str,
        timeline_id: str,
        element_id: str,
        guidance: str = "",
        *,
        source: PromptSyncSource = "currentPlan",
    ) -> dict:
        snapshot, document = await asyncio.to_thread(
            self._read,
            project_id,
            timeline_id,
            element_id,
        )
        if source not in (
            "currentPlan",
            "storyboardPrompt",
            "videoPrompt",
            "mixed",
        ):
            raise ValidationError("请选择本次同步的内容来源")
        sync = prompt_sync_status(document, timeline_id, element_id)
        if len(sync["changedSources"]) > 1:
            source = "mixed"
        if source != "mixed" and not set(sync["changedSources"]).issubset(
            {source},
        ):
            raise ValidationError("同步来源与本次修改不一致，请使用最新修改的内容同步")
        if source == "currentPlan" or (
            source == "mixed" and "currentPlan" in sync["changedSources"]
        ):
            _validate_plan(document, timeline_id, element_id)
        # Derive everything from the same snapshot, not a second racing GET.
        _, element = live_element(document, timeline_id, element_id)
        creation = element["creation"]
        references = _references(snapshot.project, element_id)
        model_fingerprint = _model_fingerprint()
        _validate_proposal_references(references)
        baseline_token = _context_token(
            document,
            timeline_id,
            element_id,
            references,
            model_fingerprint,
        )
        from models.video_capabilities import video_model_prompt_guidance

        system = (
            "你是片段内容和生成提示词编辑。只返回JSON对象，恰好包含narrative、storyboardPrompt、"
            "videoPrompt三个非空字符串。"
            "narrative是这个生成单元的完整叙述，自然写清起止状态、动作顺序、运镜景别、节奏、衔接、对白、旁白及其他声音意图。"
            "narrative聚焦发生什么、如何呈现、声音和衔接，"
            "不复制分辨率、画幅、分镜网格、参考编号或提示词格式禁令；这些保留在对应提示词中。"
            "片段时长、人物、场景、道具和引用以fixedScope为准，不新增未绑定引用。"
            "source=currentPlan时，以当前片段内容和约束为准更新两份提示词；source=storyboardPrompt"
            "或videoPrompt时，"
            "以该提示词最新原文为准反向更新片段内容和另一份提示词。"
            "最后一条用户消息中的authoritativeInputs是本次权威原文，必须逐字保留。referenceOnly仅提供旧背景，"
            "不得恢复权威原文已经删除或改写的要求。把新增、删除、改写的动作、状态、顺序、次数、声音和禁止事项落实到目标正文。"
            "若改动仅为模型措辞、画布排版或引用写法，且不改变创作内容，保留已正确的叙述和另一份提示词，不为了同步机械改写。"
            "source=mixed时，changedSources中的改动同时是约束；无法同时满足时只返回"
            '{"conflict":"简短说明内容冲突"}，不要猜测取舍。'
            "对白和旁白直接写在叙述中，说明说话者、原文、语气和是否出镜开口；视频提示词完整保留所需人声，"
            "不新增源内容没有的人声或配乐，也不恢复已删除的台词。分镜图呈现对应表演，图中不绘制对白文字。"
            "三份正文用换行自然分段，清楚表达动作中间过程和首末衔接，不遗漏细节，不暴露内部ID。"
            "图片引用统一使用[Image N]，严格对应referenceOrder各阶段顺序；叙述使用人物和物件实际名称，不写模型引用语法。"
            "分镜提示词直接说明画布比例、每格比例、关键帧数量、平方网格和阅读顺序，不写抽象交付模式标签。"
            "按动作需要规划有信息价值的起始、中间过程、转折、反应和结束关键帧，通常使用4或9格；用户明确要求单帧时遵从。"
            "各格代表可见状态，不代表必须切镜。每格画幅与整图相同，多格有细而完整的分隔边界，无标题、序号、时码或对白文字。"
            "视频将关键帧中的动作连续展开，不显示整张宫格、拼贴、边框、字幕或幻灯片。保持角色、左右手、道具及首末状态一致。"
            + video_model_prompt_guidance(
                model_config.get_video_model_name(),
                model_config.get_video_backend(),
            )
        )
        plan = plan_input(document, timeline_id, element_id)
        inputs = {
            "currentPlan": creation["narrative"],
            "storyboardPrompt": creation["storyboard_prompt"],
            "videoPrompt": creation["video_prompt"],
        }
        authoritative_sources = (
            sync["changedSources"] or list(inputs)
            if source == "mixed"
            else [source]
        )
        authoritative_inputs = {
            key: inputs[key] for key in authoritative_sources
        }
        if (
            "storyboardPrompt" in authoritative_sources
            and declared_storyboard_panel_count(creation["storyboard_prompt"])
            is None
        ):
            raise ValidationError(
                "分镜图提示词的格数不明确或互相冲突，请统一网格、分镜格数和关键帧数量后重新生成",
            )
        target_fields = [
            "narrative" if key == "currentPlan" else key
            for key in inputs
            if key not in authoritative_sources
        ]
        context = {
            "source": source,
            "changedSources": sync["changedSources"],
            "referenceOnly": {
                key: value
                for key, value in inputs.items()
                if key not in authoritative_sources
            },
            "fixedScope": {
                **plan,
                "creation": {
                    k: v
                    for k, v in plan["creation"].items()
                    if k != "narrative"
                },
            },
            "independentNarration": [
                {
                    "script": row.get("creation", {}).get("script", ""),
                    "span": row.get("span", {}),
                }
                for row in document["timelines"]["items"][timeline_id][
                    "elements_by_id"
                ].values()
                if row.get("creation", {}).get("type") == "audio"
                and row.get("creation", {}).get("role") == "narration"
            ],
            "entityNames": {
                key: entity.name
                for key, entity in (
                    snapshot.project.visual.entities.items.items()
                )
            },
            "referenceOrder": references,
            "userGuidance": guidance,
        }
        authority = {
            "authoritativeInputs": authoritative_inputs,
            "targetFields": target_fields,
            "instruction": (
                "以下是本次必须落实的最新原文。保留其中每个具体要求，并明确同步到所有目标；"
                "旧目标只提供兼容的背景和风格，不能抵消这里新增或改写的细节。"
                "多项权威内容互相冲突时请返回conflict，不要自行选边。"
            ),
        }
        client = self.client or AgentScopeAgentChatClient(
            max_tokens=7000,
            temperature=0.2,
        )
        turn = await client.complete(
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": json.dumps(authority, ensure_ascii=False),
                },
            ],
            tools=[],
        )
        text = (turn.content or "").strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        try:
            result = json.loads(text)
        except (ValueError, TypeError) as error:
            raise ValidationError(
                "模型未返回可用的提示词草稿，请重新起草",
            ) from error
        if isinstance(result, dict) and set(result) == {"conflict"}:
            raise ValidationError(
                "当前多处编辑存在冲突，请先统一片段内容和提示词后再同步",
            )
        if (
            not isinstance(result, dict)
            or set(result) != {"narrative", "storyboardPrompt", "videoPrompt"}
            or not all(
                isinstance(value, str)
                and value.strip()
                and len(value) <= 24000
                for value in (
                    result.get("narrative"),
                    result.get("storyboardPrompt"),
                    result.get("videoPrompt"),
                )
            )
        ):
            raise ValidationError("模型返回的提示词格式不完整")
        storyboard_prompt = media_prompt_entity_names(
            result["storyboardPrompt"].strip(),
            snapshot.project,
        )
        video_prompt = media_prompt_entity_names(
            result["videoPrompt"].strip(),
            snapshot.project,
        )
        candidate = copy.deepcopy(document)
        narrative = media_prompt_entity_names(
            result["narrative"].strip(),
            snapshot.project,
        )
        target = live_element(candidate, timeline_id, element_id)[1][
            "creation"
        ]
        target.update(
            narrative=narrative,
            storyboard_prompt=storyboard_prompt,
            video_prompt=video_prompt,
        )
        # The user's edited sources are authoritative, including wording.
        # A model may rewrite the other representations, never these inputs.
        fields = {
            "currentPlan": "narrative",
            "storyboardPrompt": "storyboard_prompt",
            "videoPrompt": "video_prompt",
        }
        for key in authoritative_sources:
            target[fields[key]] = copy.deepcopy(creation[fields[key]])
        for stage, key in (
            ("storyboard", "storyboardPrompt"),
            ("video", "videoPrompt"),
        ):
            if key not in authoritative_sources:
                target[fields[key]] = _complete_reference_mentions(
                    target[fields[key]],
                    references[stage],
                )
        narrative = target["narrative"]
        storyboard_prompt = target["storyboard_prompt"]
        video_prompt = target["video_prompt"]
        _validate_plan(candidate, timeline_id, element_id)
        _validate_prompts(
            candidate,
            timeline_id,
            element_id,
            references,
            proposal=True,
        )
        proposal = PromptProposal(
            proposal_id=f"prompt-proposal-{uuid4().hex}",
            project_id=project_id,
            timeline_id=timeline_id,
            element_id=element_id,
            baseline_token=baseline_token,
            reference_fingerprint=digest(references),
            model_fingerprint=model_fingerprint,
            source=source,
            before_narrative=creation["narrative"],
            narrative=narrative,
            before_storyboard_prompt=creation["storyboard_prompt"],
            before_video_prompt=creation["video_prompt"],
            storyboard_prompt=storyboard_prompt,
            video_prompt=video_prompt,
        )

        # Do not recreate a deleted project even at the read/write boundary.
        def persist():
            with self.services.projects.lifecycle_lock(project_id):
                latest, _ = self._read(project_id, timeline_id, element_id)
                if latest.project.created_at != snapshot.project.created_at:
                    raise ConflictError("项目已重新建立，请重新起草提示词")
                self._record(project_id, proposal.proposal_id).create(proposal)

        await asyncio.to_thread(persist)
        return {
            "proposalId": proposal.proposal_id,
            "baselineToken": proposal.baseline_token,
            "source": source,
            "beforeNarrative": proposal.before_narrative,
            "narrative": narrative,
            "beforeStoryboardPrompt": proposal.before_storyboard_prompt,
            "beforeVideoPrompt": proposal.before_video_prompt,
            "storyboardPrompt": storyboard_prompt,
            "videoPrompt": video_prompt,
        }

    async def accept(
        self,
        project_id: str,
        timeline_id: str,
        element_id: str,
        proposal_id: str,
    ) -> dict:
        snapshot, document = await asyncio.to_thread(
            self._read,
            project_id,
            timeline_id,
            element_id,
        )
        try:
            proposal = await asyncio.to_thread(
                self._record(project_id, proposal_id).read,
            )
        except RecordNotFoundError as error:
            raise NotFoundError("提示词草稿不存在") from error
        except ModelValidationError as error:
            raise ConflictError("该草稿已过期，请基于当前片段内容重新同步") from error
        if (
            proposal.project_id,
            proposal.timeline_id,
            proposal.element_id,
        ) != (
            project_id,
            timeline_id,
            element_id,
        ):
            raise ConflictError("草稿不属于当前镜头")
        proposal_narrative = proposal.narrative
        status = prompt_sync_status(document, timeline_id, element_id)
        references = _references(snapshot.project, element_id)
        model_fingerprint = _model_fingerprint()
        if (
            _context_token(
                document,
                timeline_id,
                element_id,
                references,
                model_fingerprint,
            )
            != proposal.baseline_token
        ):
            current = live_element(document, timeline_id, element_id)[1][
                "creation"
            ]
            if (
                status["status"] == "current"
                and current["storyboard_prompt"] == proposal.storyboard_prompt
                and current["video_prompt"] == proposal.video_prompt
                and current["narrative"] == proposal_narrative
            ):
                restored = copy.deepcopy(document)
                live_element(restored, timeline_id, element_id)[1][
                    "creation"
                ].update(
                    narrative=proposal.before_narrative,
                    storyboard_prompt=proposal.before_storyboard_prompt,
                    video_prompt=proposal.before_video_prompt,
                )
                if (
                    _context_token(
                        restored,
                        timeline_id,
                        element_id,
                        references,
                        model_fingerprint,
                    )
                    == proposal.baseline_token
                ):
                    return {
                        "ok": True,
                        "generation": snapshot.generation,
                        "replayed": True,
                    }
            raise ConflictError("片段内容或提示词已更新，请按最新内容重新生成")
        if (
            digest(references) != proposal.reference_fingerprint
            or model_fingerprint != proposal.model_fingerprint
        ):
            raise ConflictError("参考图或模型设置已更新，请重新起草提示词")
        creation = live_element(document, timeline_id, element_id)[1][
            "creation"
        ]
        before_creation = copy.deepcopy(creation)
        creation.update(
            narrative=proposal_narrative,
            storyboard_prompt=proposal.storyboard_prompt,
            video_prompt=proposal.video_prompt,
        )
        fields = {
            "currentPlan": "narrative",
            "storyboardPrompt": "storyboard_prompt",
            "videoPrompt": "video_prompt",
        }
        sources = (
            (status["changedSources"] or list(fields))
            if proposal.source == "mixed"
            else [proposal.source]
        )
        if not set(status["changedSources"]).issubset(sources):
            raise ConflictError("同步草稿遗漏了本次修改，请重新同步")
        if any(
            creation[fields[key]] != before_creation[fields[key]]
            for key in sources
        ):
            raise ConflictError("同步结果修改了本次编辑的内容，请重新同步")
        _validate_plan(document, timeline_id, element_id)
        _validate_prompts(
            document,
            timeline_id,
            element_id,
            references,
            proposal=True,
        )
        return await self._commit(
            snapshot,
            document,
            timeline_id,
            element_id,
            model_fingerprint=model_fingerprint,
        )

    async def _commit(
        self,
        snapshot,
        document,
        timeline_id,
        element_id,
        *,
        model_fingerprint,
    ):
        def validate_context(_latest: dict) -> None:
            # The commit's exact ETag guard already proves the entire Project
            # (including references) unchanged. Only external model settings
            # remain to recheck under the write lock.
            if _model_fingerprint() != model_fingerprint:
                raise ConflictError(
                    "参考图、模型或片段内容已更新，请按最新内容重新生成",
                )

        source_token = prompt_sync_status(
            snapshot.project,
            timeline_id,
            element_id,
        )["baselineToken"]
        path = _pointer(timeline_id, element_id)
        document, _ = apply_frontend_edit_impacts(
            document,
            [
                path + "/narrative",
                path + "/storyboard_prompt",
                path + "/video_prompt",
            ],
            base=snapshot.project.model_dump(mode="json"),
        )
        from services.project_files import frontend_edit_hold

        # Commit listeners may immediately wake unattended dispatch.
        frontend_edit_hold.note_frontend_edit(
            snapshot.project.project_id,
            (element_id,),
        )
        result = await self.services.commit_candidate(
            base=snapshot,
            candidate=document,
            origin="frontend_edit",
            review_policy="auto_fix",
            prompt_sync_confirmation=(timeline_id, element_id, source_token),
            prompt_sync_expected_etag=snapshot.etag,
            prompt_sync_context_validator=validate_context,
        )
        return {"ok": True, "generation": result.snapshot.generation}
