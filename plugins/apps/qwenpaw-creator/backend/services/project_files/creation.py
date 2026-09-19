# -*- coding: utf-8 -*-
"""Atomic Creator Project creation shared by HTTP and PawApp tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from domain.errors import ConflictError, StorageIntegrityError, ValidationError
from schemas.projects import (
    ExecutionPreauthorizationPolicy,
    ProjectCreateRequest,
    ProjectCreateResponse,
)
from services.runtime_files.errors import RuntimeFileError
from services.runtime_files.idempotency_store import IdempotencyRecordStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.models import (
    MessageChannel,
    MessageClassification,
)
from services.runtime_files.session_store import (
    ProjectRuntimeBootstrap,
    ProjectRuntimeSessionStore,
)

from .models import ExecutionPreauthorization, Project, ProjectSettings
from .poller import ProjectPoller
from .store import (
    ProjectAlreadyExists,
    ProjectIntegrityError,
    ProjectNotFound,
    ProjectStore,
    ProjectStoreError,
)

_CREATE_SCOPE = "POST /projects"


def stable_project_resource_id(kind: str, identity: str) -> str:
    value = uuid5(NAMESPACE_URL, f"qwenpaw-creator:{kind}:{identity}").hex
    return f"{kind}-{value}"


def _project_snapshot_id(project_id: str, generation: int = 0) -> str:
    value = uuid5(NAMESPACE_URL, f"{project_id}:{generation}").hex
    return f"project-snapshot-{value}"


def _request_hash(request: ProjectCreateRequest) -> str:
    return IdempotencyRecordStore.request_hash(
        {
            "scope": _CREATE_SCOPE,
            "request": request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        },
    )


def _settings(request: ProjectCreateRequest) -> ProjectSettings:
    preauthorization = (
        ExecutionPreauthorization.model_validate(
            request.execution_preauthorization.model_dump(mode="python"),
        )
        if request.execution_preauthorization is not None
        else None
    )
    return ProjectSettings(
        aspect_ratio=request.aspect_ratio,
        resolution=request.resolution,
        content_type=request.content_type,
        execution_preauthorization=preauthorization,
    )


def _header(project: Project) -> dict[str, Any]:
    preauthorization = project.settings.execution_preauthorization
    return {
        "id": project.project_id,
        "name": project.name,
        "description": project.description,
        "scenario": project.scenario,
        "aspectRatio": project.settings.aspect_ratio,
        "resolution": project.settings.resolution,
        "contentType": project.settings.content_type,
        **(
            {
                "executionPreauthorization": (
                    ExecutionPreauthorizationPolicy.model_validate(
                        preauthorization.model_dump(mode="python"),
                    ).model_dump(mode="json", by_alias=True)
                ),
            }
            if preauthorization is not None
            else {}
        ),
    }


class _RuntimeBootstrapReceipt(BaseModel):
    """Exact initial Runtime identities persisted with a creation receipt."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

    schema_version: Literal[1] = Field(alias="schemaVersion")
    goal_id: str | None = Field(
        alias="goalId",
        min_length=1,
        max_length=192,
    )
    initial_message_id: str | None = Field(
        alias="initialMessageId",
        min_length=1,
        max_length=256,
    )

    @model_validator(mode="after")
    def validate_identity_pair(self) -> _RuntimeBootstrapReceipt:
        if (self.goal_id is None) != (self.initial_message_id is None):
            raise ValueError(
                "goalId and initialMessageId must both be set or both be null",
            )
        return self


@dataclass(frozen=True, slots=True)
class ProjectCreationResult:
    """Internal result carrying the HTTP response and persisted identities."""

    response: ProjectCreateResponse
    goal_id: str | None
    initial_message_id: str | None


@dataclass(frozen=True, slots=True)
class ProjectCreationService:
    projects: ProjectStore
    sessions: ProjectRuntimeSessionStore
    poller: ProjectPoller

    @staticmethod
    def project_id(client_request_id: str) -> str:
        return stable_project_resource_id("project", client_request_id)

    def lookup(
        self,
        request: ProjectCreateRequest,
    ) -> ProjectCreateResponse | None:
        result = self._lookup(request, require_runtime_identity=False)
        return result.response if result is not None else None

    def lookup_with_runtime_identity(
        self,
        request: ProjectCreateRequest,
    ) -> ProjectCreationResult | None:
        """Look up a new-format receipt with exact initial Runtime IDs."""

        return self._lookup(request, require_runtime_identity=True)

    def _lookup(
        self,
        request: ProjectCreateRequest,
        *,
        require_runtime_identity: bool,
    ) -> ProjectCreationResult | None:
        project_id = self.project_id(request.client_request_id)
        try:
            self.projects.read(project_id)
        except ProjectNotFound:
            return None
        except (ProjectIntegrityError, ProjectStoreError) as exc:
            raise StorageIntegrityError(str(exc)) from exc
        return self._existing_bootstrap(
            request,
            require_runtime_identity=require_runtime_identity,
        )

    def _existing_bootstrap(
        self,
        request: ProjectCreateRequest,
        *,
        require_runtime_identity: bool,
    ) -> ProjectCreationResult:
        client_request_id = request.client_request_id
        project_id = self.project_id(client_request_id)
        expected_session_id = stable_project_resource_id(
            "session",
            client_request_id,
        )
        expected_conversation_id = stable_project_resource_id(
            "conversation",
            client_request_id,
        )
        expected_snapshot_id = _project_snapshot_id(project_id)
        request_hash = _request_hash(request)
        try:
            self.projects.read(project_id)
            session = self.sessions.get_project_session(project_id)
            conversations = self.sessions.list_conversations(
                project_id,
                session.session_id,
            )
        except (
            ProjectIntegrityError,
            ProjectStoreError,
            RuntimeFileError,
        ) as exc:
            raise StorageIntegrityError(str(exc)) from exc
        defaults = [item for item in conversations if item.is_default]
        if len(defaults) != 1:
            raise StorageIntegrityError(
                "Project Runtime 必须且只能有一个默认 Conversation",
            )
        create_metadata = session.metadata.get("projectCreate")
        if not isinstance(create_metadata, dict):
            raise ConflictError("Project 已存在但缺少文件创建幂等记录")
        if (
            create_metadata.get("clientRequestId") != client_request_id
            or create_metadata.get("requestHash") != request_hash
        ):
            raise ConflictError("clientRequestId 已用于不同 Project payload")
        project_snapshot_id = create_metadata.get("projectSnapshotId")
        stored_response = create_metadata.get("response")
        if (
            session.session_id != expected_session_id
            or defaults[0].conversation_id != expected_conversation_id
            or project_snapshot_id != expected_snapshot_id
        ):
            raise StorageIntegrityError(
                "Project Runtime 创建记录与确定性身份不一致"
            )
        try:
            response = ProjectCreateResponse.model_validate(stored_response)
        except PydanticValidationError as exc:
            raise StorageIntegrityError("Project 创建响应快照损坏") from exc
        if (
            response.project_id != project_id
            or response.creator_session_id != expected_session_id
            or response.conversation_id != expected_conversation_id
            or response.project_snapshot_id != project_snapshot_id
            or response.header.get("id") != project_id
        ):
            raise StorageIntegrityError("Project 创建响应快照身份不一致")

        raw_runtime_bootstrap = create_metadata.get("runtimeBootstrap")
        if raw_runtime_bootstrap is None:
            if require_runtime_identity:
                raise ConflictError(
                    "Project 创建记录不包含 Runtime bootstrap 身份",
                )
            return ProjectCreationResult(
                response=response,
                goal_id=None,
                initial_message_id=None,
            )
        try:
            runtime_bootstrap = _RuntimeBootstrapReceipt.model_validate(
                raw_runtime_bootstrap,
            )
        except PydanticValidationError as exc:
            raise StorageIntegrityError(
                "Project Runtime bootstrap 创建记录损坏",
            ) from exc
        self._validate_runtime_bootstrap(
            request,
            response=response,
            runtime_bootstrap=runtime_bootstrap,
        )
        return ProjectCreationResult(
            response=response,
            goal_id=runtime_bootstrap.goal_id,
            initial_message_id=runtime_bootstrap.initial_message_id,
        )

    def _validate_runtime_bootstrap(
        self,
        request: ProjectCreateRequest,
        *,
        response: ProjectCreateResponse,
        runtime_bootstrap: _RuntimeBootstrapReceipt,
    ) -> None:
        has_initial_goal = request.initial_goal is not None
        if has_initial_goal != (runtime_bootstrap.goal_id is not None):
            raise StorageIntegrityError(
                "Project Runtime bootstrap 身份与 initialGoal 不一致",
            )
        if not has_initial_goal:
            return

        goal_id = runtime_bootstrap.goal_id
        initial_message_id = runtime_bootstrap.initial_message_id
        assert goal_id is not None
        assert initial_message_id is not None
        try:
            goal = self.sessions.get_goal(response.project_id, goal_id)
            messages = self.sessions.list_messages(
                response.project_id,
                response.creator_session_id,
            )
        except RuntimeFileError as exc:
            raise StorageIntegrityError(str(exc)) from exc
        message = next(
            (
                item
                for item in messages
                if item.message_id == initial_message_id
            ),
            None,
        )
        initial_goal = request.initial_goal
        assert initial_goal is not None
        expected_client_message_id = (
            f"initial-goal:{request.client_request_id}"
        )
        if (
            goal.project_id != response.project_id
            or goal.creator_session_id != response.creator_session_id
            or goal.conversation_id != response.conversation_id
            or goal.root_message_seq != 1
            or goal.intent != initial_goal
            or goal.metadata.get("source") != "initial_goal"
            or message is None
            or message.project_id != response.project_id
            or message.creator_session_id != response.creator_session_id
            or message.conversation_id != response.conversation_id
            or message.message_seq != goal.root_message_seq
            or message.role != "user"
            or message.source != "initial_goal"
            or message.channel is not MessageChannel.COMPOSER
            or message.classification
            is not MessageClassification.MUTATION_INSTRUCTION
            or message.client_message_id != expected_client_message_id
            or len(message.content_parts) != 1
            or message.content_parts[0].type != "text"
            or message.content_parts[0].text != initial_goal
        ):
            raise StorageIntegrityError(
                "Project Runtime bootstrap Goal/Message 身份不一致",
            )

    @staticmethod
    def _apply_template(project: Project, template_id: str) -> Project:
        from services.media_files.user_templates import load_user_template
        from services.media_files.video_templates import (
            VideoTemplate,
            VideoTemplateDesignFloor,
            apply_video_template_to_project,
            get_video_template,
        )

        template = get_video_template(template_id)
        if template is None:
            user_template = load_user_template(template_id)
            if user_template is None:
                raise ValidationError(f"未知的视频模板: {template_id}")
            template = VideoTemplate(
                template_id=user_template.template_id,
                name=user_template.name,
                description=user_template.description,
                content_type=user_template.content_type,
                scenario=user_template.scenario,
                opening_caption_blueprint=(
                    user_template.opening_caption_blueprint
                ),
                closing_caption_blueprint=(
                    user_template.closing_caption_blueprint
                ),
                default_transition_kind=(
                    user_template.default_transition_kind
                ),
                transition_blend_seconds=(
                    user_template.transition_blend_seconds
                ),
                caption_blueprint_order=tuple(
                    user_template.caption_blueprint_order,
                ),
                color_grade=user_template.color_grade,
                energy=user_template.energy,
                density=user_template.density,
                decoration=user_template.decoration,
                design_floor=VideoTemplateDesignFloor(
                    opening=user_template.design_floor_opening,
                    transitions=user_template.design_floor_transitions,
                    body=user_template.design_floor_body,
                    ending=user_template.design_floor_ending,
                ),
                decoration_catalog=(),
                frame_blueprint="",
                preview_description=user_template.preview_description,
                icon_emoji=user_template.icon_emoji,
            )
        return apply_video_template_to_project(project, template)

    def create(self, request: ProjectCreateRequest) -> ProjectCreateResponse:
        return self._create(request, require_runtime_identity=False).response

    def create_with_runtime_identity(
        self,
        request: ProjectCreateRequest,
    ) -> ProjectCreationResult:
        """Create or replay with exact persisted initial Runtime identities."""

        return self._create(request, require_runtime_identity=True)

    def _create(
        self,
        request: ProjectCreateRequest,
        *,
        require_runtime_identity: bool,
    ) -> ProjectCreationResult:
        replay = self._lookup(
            request,
            require_runtime_identity=require_runtime_identity,
        )
        if replay is not None:
            return replay

        client_request_id = request.client_request_id
        project_id = self.project_id(client_request_id)
        session_id = stable_project_resource_id("session", client_request_id)
        conversation_id = stable_project_resource_id(
            "conversation",
            client_request_id,
        )
        goal_id = (
            stable_project_resource_id("goal", client_request_id)
            if request.initial_goal is not None
            else None
        )
        message_id = (
            stable_project_resource_id("message", client_request_id)
            if request.initial_goal is not None
            else None
        )
        project_snapshot_id = _project_snapshot_id(project_id)
        request_hash = _request_hash(request)
        target_name = request.name.strip()
        if not target_name:
            raise ValidationError("项目名称不能为空")
        project = Project.new(
            project_id=project_id,
            name=target_name,
            description=request.description.strip(),
            scenario=request.scenario,
            settings=_settings(request),
        )
        if request.template_id:
            project = self._apply_template(project, request.template_id)
        response = ProjectCreateResponse(
            projectId=project_id,
            creatorSessionId=session_id,
            conversationId=conversation_id,
            projectSnapshotId=project_snapshot_id,
            header=_header(project),
        )

        with CrossProcessFileLock(self.projects.root / ".project-names.lock"):
            replay = self._lookup(
                request,
                require_runtime_identity=require_runtime_identity,
            )
            if replay is not None:
                return replay
            try:
                existing = self.projects.list()
            except (ProjectIntegrityError, ProjectStoreError) as exc:
                raise StorageIntegrityError(str(exc)) from exc
            if any(
                item.project_id != project_id and item.name == target_name
                for item in existing
            ):
                raise ValidationError(
                    f"项目名称「{target_name}」已存在，请使用其他名称",
                )

        holder: list[ProjectRuntimeBootstrap] = []

        def initialize(staged_project_root) -> None:
            holder.append(
                self.sessions.initialize_staged_project(
                    staged_project_root,
                    project_id,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    session_metadata={
                        "projectCreate": {
                            "clientRequestId": client_request_id,
                            "requestHash": request_hash,
                            "projectSnapshotId": project_snapshot_id,
                            "response": response.model_dump(
                                mode="json",
                                by_alias=True,
                            ),
                            "runtimeBootstrap": {
                                "schemaVersion": 1,
                                "goalId": goal_id,
                                "initialMessageId": message_id,
                            },
                        },
                    },
                    initial_goal=request.initial_goal,
                    goal_id=goal_id,
                    initial_message_id=message_id,
                    initial_client_message_id=(
                        f"initial-goal:{client_request_id}"
                        if request.initial_goal is not None
                        else None
                    ),
                ),
            )

        try:
            snapshot = self.projects.create(
                project,
                initialize_staged_project=initialize,
            )
        except ProjectAlreadyExists:
            return self._existing_bootstrap(
                request,
                require_runtime_identity=require_runtime_identity,
            )
        except (
            ProjectIntegrityError,
            ProjectStoreError,
            RuntimeFileError,
        ) as exc:
            raise StorageIntegrityError(str(exc)) from exc
        if len(holder) != 1:
            raise StorageIntegrityError(
                "Project Runtime 未随 Project 原子创建"
            )
        try:
            self.poller.note_commit(snapshot)
        except (ProjectIntegrityError, ProjectStoreError) as exc:
            raise StorageIntegrityError(str(exc)) from exc
        return self._existing_bootstrap(
            request,
            require_runtime_identity=require_runtime_identity,
        )


__all__ = [
    "ProjectCreationResult",
    "ProjectCreationService",
    "stable_project_resource_id",
]
