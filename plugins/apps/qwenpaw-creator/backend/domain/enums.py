# -*- coding: utf-8 -*-
"""Single-source string enums shared by runtime, API and tests."""

from __future__ import annotations

from enum import StrEnum


class ShotCamera(StrEnum):
    STATIC = "⊙ 静止"
    PUSH_IN = "↑ 推近"
    PULL_OUT = "↓ 拉远"
    PAN_RIGHT = "→ 横摇右"
    PAN_LEFT = "← 横摇左"
    CRANE = "↕ 升降"
    ORBIT = "◎ 环绕"
    HANDHELD = "～ 手持晃动"


class ShotFraming(StrEnum):
    WIDE = "全景"
    MEDIUM = "中景"
    CLOSE = "近景"
    CLOSE_UP = "特写"


class SpecialistRole(StrEnum):
    SOURCE_INTELLIGENCE = "source_intelligence_agent"
    VISUAL_DEVELOPMENT = "visual_development_agent"
    R2V_GENERATION_DIRECTOR = "r2v_generation_director"
    AI_EDITING_DIRECTOR = "ai_editing_director"


class CreatorSessionStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_RUNTIME = "WAITING_RUNTIME"
    INTERRUPT_REQUESTED = "INTERRUPT_REQUESTED"
    WAITING_USER_INPUT = "WAITING_USER_INPUT"
    WAITING_EXECUTION_AUTH = "WAITING_EXECUTION_AUTH"
    PENDING_REVIEW = "PENDING_REVIEW"
    RESUMING = "RESUMING"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class CreatorGoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING_REVIEW = "WAITING_REVIEW"
    RESUME_REQUIRED = "RESUME_REQUIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TransactionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETION_CHECK = "COMPLETION_CHECK"
    SEALING = "SEALING"
    PENDING_REVIEW = "PENDING_REVIEW"
    REVISING = "REVISING"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    NO_CHANGE = "NO_CHANGE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class SpecialistRunStatus(StrEnum):
    QUEUED = "QUEUED"
    QUEUED_CAPACITY = "QUEUED_CAPACITY"
    RUNNING_MODEL = "RUNNING_MODEL"
    WAITING_RUNTIME = "WAITING_RUNTIME"
    WAITING_AUTHORIZATION = "WAITING_AUTHORIZATION"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


TERMINAL_SPECIALIST_STATUSES = frozenset(
    {
        SpecialistRunStatus.SUCCEEDED,
        SpecialistRunStatus.BLOCKED,
        SpecialistRunStatus.FAILED,
        SpecialistRunStatus.STALE,
        SpecialistRunStatus.CANCELLED,
    },
)


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    QUARANTINED = "QUARANTINED"


class TaskKind(StrEnum):
    ASSET_INGEST = "asset_ingest"
    ASSET_IMPORT = "asset_import"
    SOURCE_INTELLIGENCE = "source_intelligence"
    SOURCE_MEMORY_BUILD = "source_memory_build"
    IMAGE_GENERATION = "image_generation"
    R2V_GENERATION = "r2v_generation"
    AI_EDIT_EXECUTE = "ai_edit_execute"
    COMPOSE = "compose"


class CreatorProgressPhase(StrEnum):
    SOURCE_INGEST = "source_ingest"
    SOURCE_INTELLIGENCE = "source_intelligence"
    CREATIVE_STRATEGY = "creative_strategy"
    VISUAL_DEVELOPMENT = "visual_development"
    TIMELINE_EDIT = "timeline_edit"
    TIMELINE_RENDER = "timeline_render"
    POST_PRODUCTION = "post_production"
    REVIEW = "review"
    COMPLETED = "completed"


class CreatorCommandType(StrEnum):
    GENERATE_SCRIPT = "GENERATE_SCRIPT"
    IMPORT_SCRIPT = "IMPORT_SCRIPT"
    SET_STRATEGY_TEXT = "SET_STRATEGY_TEXT"
    UPSERT_SHOT = "UPSERT_SHOT"
    DELETE_SHOT = "DELETE_SHOT"
    MOVE_SHOT = "MOVE_SHOT"
    BIND_REFERENCE = "BIND_REFERENCE"
    UNBIND_REFERENCE = "UNBIND_REFERENCE"
    GENERATE_STORYBOARD_PROMPT = "GENERATE_STORYBOARD_PROMPT"
    GENERATE_STORYBOARD_IMAGE = "GENERATE_STORYBOARD_IMAGE"
    GENERATE_CAST_LINEUP_IMAGE = "GENERATE_CAST_LINEUP_IMAGE"
    GENERATE_VIDEO_PROMPT = "GENERATE_VIDEO_PROMPT"
    GENERATE_R2V_VIDEO = "GENERATE_R2V_VIDEO"
    EXECUTE_EDIT = "EXECUTE_EDIT"
    ATTACH_SOURCE_ASSETS = "ATTACH_SOURCE_ASSETS"
    DETACH_SOURCE_ASSETS = "DETACH_SOURCE_ASSETS"
    SUPPLEMENT_ASSET = "SUPPLEMENT_ASSET"
    GENERATE_ASSET = "GENERATE_ASSET"
    SELECT_ARTIFACT_VERSION = "SELECT_ARTIFACT_VERSION"
    SET_FINAL_COMPOSE_SELECTION = "SET_FINAL_COMPOSE_SELECTION"
    SET_FINAL_COMPOSE_TRANSITION = "SET_FINAL_COMPOSE_TRANSITION"
    COMPOSE_FINAL_VIDEO = "COMPOSE_FINAL_VIDEO"
    ANALYZE_SOURCE_MEDIA = "ANALYZE_SOURCE_MEDIA"


DETERMINISTIC_COMMANDS = frozenset(
    {
        CreatorCommandType.IMPORT_SCRIPT,
        CreatorCommandType.SET_STRATEGY_TEXT,
        CreatorCommandType.UPSERT_SHOT,
        CreatorCommandType.DELETE_SHOT,
        CreatorCommandType.MOVE_SHOT,
        CreatorCommandType.BIND_REFERENCE,
        CreatorCommandType.UNBIND_REFERENCE,
        CreatorCommandType.ATTACH_SOURCE_ASSETS,
        CreatorCommandType.DETACH_SOURCE_ASSETS,
        CreatorCommandType.SUPPLEMENT_ASSET,
        CreatorCommandType.SELECT_ARTIFACT_VERSION,
        CreatorCommandType.SET_FINAL_COMPOSE_SELECTION,
        CreatorCommandType.SET_FINAL_COMPOSE_TRANSITION,
    },
)
