# -*- coding: utf-8 -*-
"""共享应用所有者、目录和管理员发布 API。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from ...access.actor import ActorContext
from ...access.dependencies import get_actor, require_multi_user_mode
from ...identity.runtime import get_identity_schema
from ...constant import WORKING_DIR
from ...publications.dependencies import (
    DependencyManifestError,
    PostgresDependencyAuthority,
    PublicationDependencyValidator,
)
from ...publications.repository import (
    PostgresSharedAppRepository,
    PublicationStateConflict,
)
from ...publications.service import (
    PublicationAccessError,
    PublicationDependencyError,
    PublicationStateError,
    SharedAppService,
)
from ...publications.snapshot import PublicationSnapshotBuilder
from ...workspaces import WorkspaceKind, WorkspaceResolutionDenied, WorkspaceResolver


class SharedAppRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except PublicationAccessError as exc:
                raise HTTPException(403, str(exc)) from exc
            except PublicationDependencyError as exc:
                raise HTTPException(
                    422,
                    {
                        "code": str(exc),
                        "dependencies": [item.model_dump() for item in exc.report.items],
                    },
                ) from exc
            except PublicationStateError as exc:
                code = str(exc)
                status = 404 if code.endswith("not_found") else 409
                if code == "PUBLICATION_BASELINE_INVALID":
                    status = 422
                raise HTTPException(status, code) from exc
            except PublicationStateConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except DependencyManifestError as exc:
                raise HTTPException(422, str(exc)) from exc
            except WorkspaceResolutionDenied as exc:
                raise HTTPException(422, str(exc)) from exc
            except (SQLAlchemyError, OSError) as exc:
                raise HTTPException(503, "publication_authority_unavailable") from exc

        return guarded


router = APIRouter(
    tags=["shared-apps"],
    route_class=SharedAppRoute,
    dependencies=[Depends(require_multi_user_mode)],
)


def get_shared_app_service() -> SharedAppService:
    repository = PostgresSharedAppRepository(schema=get_identity_schema())
    resolver = WorkspaceResolver(working_dir=WORKING_DIR)

    def source_workspace(workspace_key: str):
        path = PurePosixPath(workspace_key)
        if len(path.parts) == 2 and path.parts[0] == "workspaces":
            return resolver.resolve(
                kind=WorkspaceKind.DRAFT,
                resource_id=path.parts[1],
                workspace_key=workspace_key,
            ).path
        from ...config import load_config

        candidate = Path(workspace_key).expanduser()
        if not candidate.is_absolute():
            raise WorkspaceResolutionDenied("invalid_draft_workspace_key")
        resolved = candidate.resolve()
        registered = {
            Path(profile.workspace_dir).expanduser().resolve()
            for profile in load_config().agents.profiles.values()
        }
        if resolved not in registered or resolved.is_symlink():
            raise WorkspaceResolutionDenied("invalid_draft_workspace_key")
        return resolved

    async def build_manifest(app, draft):
        from ...access.agent_repository import agent_database_id
        from ...agents.effective_model import resolve_effective_model
        from ...config import load_config
        from ...config.config import load_agent_config

        agent_key = next(
            (
                key
                for key in load_config().agents.profiles
                if agent_database_id(key) == app.agent_id
            ),
            None,
        )
        if agent_key is None:
            raise PublicationStateError("shared_app_source_unavailable")
        config = load_agent_config(agent_key)
        model = resolve_effective_model(config)
        display = draft.manifest.get("display")
        if not isinstance(display, dict):
            raise DependencyManifestError("publication_display_required")
        dependencies = await repository.build_dependency_manifest(app.agent_id)
        return {
            "display": {
                "name": str(display.get("name") or "").strip(),
                "description": str(display.get("description") or "").strip(),
            },
            "model": model.model_dump(),
            **dependencies,
            "runtime": {
                "backend": config.backend,
                "language": config.language,
                "approval_level": config.approval_level,
            },
        }

    return SharedAppService(
        repository,
        PublicationDependencyValidator(PostgresDependencyAuthority(repository)),
        snapshot_builder=PublicationSnapshotBuilder(WORKING_DIR),
        source_workspace_resolver=source_workspace,
        manifest_builder=build_manifest,
    )


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAppBody(StrictBody):
    agent_id: str = Field(min_length=1, max_length=128)


class DraftBody(StrictBody):
    manifest: dict[str, Any]


class SubmissionBody(StrictBody):
    draft_revision: int = Field(ge=1)


class ReviewBody(StrictBody):
    decision: Literal["approved", "rejected"]
    review_note: str = Field(default="", max_length=4000)


class ReviewNoteBody(StrictBody):
    review_note: str = Field(default="", max_length=4000)


class PointerBody(StrictBody):
    publication_id: UUID
    expected_current_id: UUID | None = None


class RetireBody(StrictBody):
    expected_current_id: UUID


def _app(item) -> dict[str, Any]:
    return item.model_dump(mode="json")


def _publication(item, *, include_manifest: bool = True) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    if not include_manifest:
        manifest = item.immutable_manifest
        payload["immutable_manifest"] = {
            "display": manifest.get("display", {}),
            "model": manifest.get("model", {}),
        }
        payload.pop("baseline_workspace_key", None)
        for field in (
            "submitted_by",
            "reviewed_by",
            "review_note",
            "reviewed_at",
            "retired_at",
        ):
            payload.pop(field, None)
    return payload


@router.get("/shared-apps/mine")
async def list_mine(
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return {"items": [_app(item) for item in await service.list_mine(actor)]}


@router.post("/shared-apps", status_code=201)
async def create_app(
    body: CreateAppBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _app(await service.create_app(actor, body.agent_id))


@router.post("/shared-apps/{app_id}/drafts", status_code=201)
async def save_draft(
    app_id: UUID,
    body: DraftBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return (await service.save_draft(actor, app_id, body.manifest)).model_dump(mode="json")


@router.get("/shared-apps/{app_id}/drafts")
async def list_drafts(
    app_id: UUID,
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    apps = await service.list_mine(actor)
    if all(item.id != app_id for item in apps):
        raise PublicationAccessError("shared_app_owner_required")
    return {
        "items": [
            item.model_dump(mode="json")
            for item in await service.repository.list_drafts(app_id)
        ]
    }


@router.get("/shared-apps/{app_id}/publications")
async def list_publications(
    app_id: UUID,
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    apps = await service.list_mine(actor)
    if all(item.id != app_id for item in apps):
        raise PublicationAccessError("shared_app_owner_required")
    return {
        "items": [
            _publication(item)
            for item in await service.repository.list_publications(app_id)
        ]
    }


@router.post("/shared-apps/{app_id}/submissions", status_code=201)
async def submit(
    app_id: UUID,
    body: SubmissionBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _publication(
        await service.submit(actor, app_id, body.draft_revision),
    )


@router.get("/shared-app-catalog")
async def catalog(
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return {
        "items": [
            _publication(item, include_manifest=False)
            for item in await service.list_catalog(actor)
        ]
    }


@router.get("/shared-app-catalog/{app_id}")
async def catalog_detail(
    app_id: UUID,
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    publication = next(
        (
            item
            for item in await service.list_catalog(actor)
            if item.shared_app_id == app_id
        ),
        None,
    )
    if publication is None:
        raise PublicationStateError("shared_app_not_found")
    return _publication(publication, include_manifest=False)


@router.post("/shared-app-catalog/{app_id}/conversations", status_code=201)
async def start_conversation(
    app_id: UUID,
    request: Request,
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    app = await service.repository.get_app(app_id)
    if app is None:
        raise PublicationStateError("shared_app_not_found")
    from ...access.agent_repository import agent_database_id
    from ...config import load_config

    agent_key = next(
        (
            key
            for key in load_config().agents.profiles
            if agent_database_id(key) == app.agent_id
        ),
        None,
    )
    if agent_key is None:
        raise PublicationStateError("shared_app_source_unavailable")
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise PublicationStateError("agent_runtime_unavailable")
    workspace = await manager.get_agent(agent_key)
    result = await service.start_conversation(
        actor,
        app_id,
        agent_key=agent_key,
        chat_manager=workspace.chat_manager,
        workspace_resolver=WorkspaceResolver(working_dir=WORKING_DIR),
        working_dir=WORKING_DIR,
    )
    result.pop("workspace_key", None)
    return result


@router.get("/admin/shared-app-publications")
async def pending_publications(
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    service._require_admin(actor)
    return {"items": [
        {
            **_publication(row["publication"]),
            "app_status": row["app_status"],
            "current_publication_id": (
                str(row["current_publication_id"])
                if row["current_publication_id"] else None
            ),
        }
        for row in await service.repository.list_admin_publications()
    ]}


@router.get("/admin/shared-app-publications/{publication_id}")
async def admin_publication_detail(
    publication_id: UUID,
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    service._require_admin(actor)
    publication = await service.repository.get_publication(publication_id)
    if publication is None:
        raise PublicationStateError("publication_not_found")
    return _publication(publication)


@router.post("/admin/shared-app-publications/{publication_id}/approve")
async def approve_publication(
    publication_id: UUID,
    body: ReviewNoteBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _publication(
        await service.review(actor, publication_id, "approved", body.review_note)
    )


@router.post("/admin/shared-app-publications/{publication_id}/reject")
async def reject_publication(
    publication_id: UUID,
    body: ReviewNoteBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _publication(
        await service.review(actor, publication_id, "rejected", body.review_note)
    )


@router.post("/admin/shared-app-publications/{publication_id}/review")
async def review(
    publication_id: UUID,
    body: ReviewBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _publication(
        await service.review(
            actor, publication_id, body.decision, body.review_note
        )
    )


@router.post("/admin/shared-app-publications/{publication_id}/publish")
async def publish(
    publication_id: UUID,
    body: PointerBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    if body.publication_id != publication_id:
        raise PublicationStateError("publication_id_mismatch")
    publication = await service.repository.get_publication(publication_id)
    if publication is None:
        raise PublicationStateError("publication_not_found")
    return _app(
        await service.publish(
            actor,
            app_id=publication.shared_app_id,
            publication_id=publication_id,
            expected_current_id=body.expected_current_id,
        )
    )


@router.post("/admin/shared-apps/{app_id}/retire")
async def retire(
    app_id: UUID,
    body: RetireBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _app(
        await service.retire(
            actor, app_id, expected_current_id=body.expected_current_id
        )
    )


@router.post("/admin/shared-apps/{app_id}/rollback")
async def rollback(
    app_id: UUID,
    body: PointerBody = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: SharedAppService = Depends(get_shared_app_service),
):
    return _app(
        await service.rollback(
            actor,
            app_id,
            body.publication_id,
            expected_current_id=body.expected_current_id,
        )
    )
