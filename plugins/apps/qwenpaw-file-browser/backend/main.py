# -*- coding: utf-8 -*-
"""QwenPaw File Browser PawApp entry point."""
# pylint: disable=wrong-import-order,wrong-import-position

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from qwenpaw.constant import WORKING_DIR
from qwenpaw.pawapp import (
    PawApp,
    SetupCheckRegistration,
    SetupEntryDescriptor,
    SetupEntryRegistration,
    SetupOpenAction,
    SetupRequest,
    SetupRequirement,
    SetupResult,
)
from qwenpaw.pawapp.tasks import TaskScope, TaskStoreError
from qwenpaw.pawapp.tasks.binding import ActionRegistration
from qwenpaw.pawapp.tasks.contracts import content_digest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from file_browser import (  # noqa: E402
    ACTION_ID,
    APP_ID,
    ENTRY_ID,
    REQUIREMENT_ID,
    FileBrowserStore,
    FileBrowserTaskAdapter,
    directory_available,
    list_directory_action_descriptor,
    make_input_resolver,
    make_setup_checker,
)


def _state_path() -> Path:
    configured = os.getenv("QWENPAW_FILE_BROWSER_STATE_DIR", "").strip()
    root = (
        Path(configured).expanduser()
        if configured
        else (WORKING_DIR / "pawapp-file-browser")
    )
    return root.resolve() / "state.sqlite3"


store = FileBrowserStore(_state_path())
app = PawApp("QwenPaw File Browser", app_id=APP_ID)
app.enable_standard_capabilities()


async def open_directory_setup(request: SetupRequest) -> SetupOpenAction:
    if request.scope.app_id != APP_ID or request.entry_id != ENTRY_ID:
        raise TaskStoreError("setup_scope_mismatch")
    return SetupOpenAction(
        app_id=APP_ID,
        request_id=request.request_id,
        entry_id=ENTRY_ID,
        presentation=request.presentation,
        path=(
            f"/apps/{APP_ID}?setup=default-directory"
            f"&setupRequest={request.request_id}"
        ),
    )


app.setup_entry(
    SetupEntryRegistration(
        descriptor=SetupEntryDescriptor(
            id=ENTRY_ID,
            entry_ref="file-browser.directory-settings",
            focus="default-directory",
            presentations=("app_entry",),
        ),
        opener=open_directory_setup,
    ),
).setup_check(
    SetupCheckRegistration(
        requirement=SetupRequirement(
            id=REQUIREMENT_ID,
            summary="Choose a default directory for omitted list inputs.",
            required_for=(ACTION_ID,),
            authority="AppLocal",
            setup_entry_ref=ENTRY_ID,
            check_ref="file-browser.check-default-root@1",
            type_ref="qwenpaw-file-browser:directory-preference@1",
        ),
        checker=make_setup_checker(store),
    ),
).task_action(
    ActionRegistration(
        action=list_directory_action_descriptor(),
        factory=lambda: FileBrowserTaskAdapter(store),
        settings_entry=f"/apps/{APP_ID}",
        requirement_ids=(REQUIREMENT_ID,),
        input_resolver=make_input_resolver(store),
    ),
)


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_revision: Annotated[int, Field(ge=0)]
    setup_request_id: Annotated[
        str,
        Field(min_length=1, max_length=256),
    ] | None = None


def _principal(request: Request) -> str:
    return str(getattr(request.state, "user", None) or "default")


def _scope(
    request: Request,
) -> TaskScope:
    header_values = request.headers.getlist("X-Agent-Id")
    if len(header_values) != 1 or not header_values[0].strip():
        raise HTTPException(status_code=400, detail="workspace_required")
    workspace_id = header_values[0].strip()
    claims = header_values + request.query_params.getlist("agent_id")
    if any(item != workspace_id for item in claims):
        raise HTTPException(status_code=403, detail="task_scope_mismatch")
    return TaskScope(
        principal_id=_principal(request),
        workspace_id=workspace_id,
        app_id=APP_ID,
    )


def _error(exc: TaskStoreError) -> HTTPException:
    status = 409
    if exc.code == "context_conflict":
        status = 409
    elif exc.code.endswith("_unavailable"):
        status = 422
    return HTTPException(status_code=status, detail=exc.code)


router = APIRouter(prefix="/preferences", tags=["file-browser"])


@router.get("/directory")
async def get_directory_preference(
    request: Request,
):
    scope = _scope(request)
    preference = await asyncio.to_thread(store.preference, scope)
    return {
        "directory": preference.directory,
        "revision": preference.revision,
        "updated_at": preference.updated_at,
        "available": bool(
            preference.directory and directory_available(preference.directory),
        ),
    }


@router.put("/directory")
async def put_directory_preference(
    request: Request,
    body: PreferenceUpdate,
):
    scope = _scope(request)
    setup_record = None
    if body.setup_request_id is not None:
        coordinator = request.app.state.pawapp_setup
        try:
            setup_scope, setup_record = await coordinator.backend_request(
                scope.principal_id,
                APP_ID,
                body.setup_request_id,
            )
        except TaskStoreError as exc:
            raise _error(exc) from None
        if setup_scope != scope or (
            setup_record.request.entry_id != ENTRY_ID
            or setup_record.request.requirement_ids != (REQUIREMENT_ID,)
        ):
            raise HTTPException(
                status_code=409,
                detail="setup_result_scope_mismatch",
            )
    try:
        preference = await asyncio.to_thread(
            store.save_preference,
            scope,
            body.directory,
            expected_revision=body.expected_revision,
            setup_request_id=body.setup_request_id,
        )
    except TaskStoreError as exc:
        raise _error(exc) from None

    if setup_record is not None and body.setup_request_id is not None:
        result = SetupResult(
            request_id=body.setup_request_id,
            result_id="setup_result_"
            + content_digest(
                {
                    "request_id": body.setup_request_id,
                    "revision": preference.revision,
                    "directory": preference.directory,
                },
            )[:32],
            outcome="saved",
            changed_requirement_ids=(REQUIREMENT_ID,),
            config_revisions={REQUIREMENT_ID: preference.revision},
        )
        await request.app.state.pawapp_setup.complete(scope, result)
    return {
        "directory": preference.directory,
        "revision": preference.revision,
        "updated_at": preference.updated_at,
        "available": True,
    }


app.include_router(router)
