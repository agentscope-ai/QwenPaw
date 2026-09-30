# -*- coding: utf-8 -*-
"""Optional Record product entry. Owns no Helper process or Act capability."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from qwenpaw.plugins.api import PluginApi
from qwenpaw.utils.io_utils import run_sync_io, write_text_atomic_async

from .record_replay import (
    DesktopLearningService,
    DesktopRecordingService,
    EventStreamClient,
    EventStreamDesktopRecorder,
)
from .record_replay.api import build_router


class FeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class RecordAndReplayPlugin:
    """Own product eligibility, requests, and service lifetime.

    Native recording state remains in the shared Helper.
    """

    def __init__(self, state_path: Path | None = None, service_factory=None):
        self._state_path = state_path
        self._service_factory = service_factory or self._new_service
        self._service = None
        self._learning = None
        self._enabled = False
        self._closed = False
        self._requests = set()
        self._lifecycle_lock = asyncio.Lock()
        self._recovered = False

    @staticmethod
    def _new_service():
        # No legacy bridge and no import of the optional `computer_use`
        # package. HostRuntime is an application-provided shared capability.
        return DesktopRecordingService(
            event_stream_recorder=EventStreamDesktopRecorder(
                EventStreamClient(),
            ),
        )

    def register(self, api: PluginApi):
        if self._state_path is None:
            from qwenpaw.constant import WORKING_DIR

            self._state_path = (
                Path(WORKING_DIR)
                / "plugin_runtime"
                / api.plugin_id
                / "feature_state.json"
            )
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._enabled = (
                isinstance(payload, dict) and payload.get("enabled") is True
            )
        except FileNotFoundError:
            self._enabled = True
        except (OSError, ValueError):
            self._enabled = False
        if self._enabled:
            self._create_services()
        router = APIRouter()

        @router.get("/feature")
        async def feature():
            return self.feature_status()

        @router.put("/feature")
        async def set_feature(body: FeatureRequest):
            return await self.set_enabled(body.enabled)

        # Keep the empty status path exact (no trailing-slash redirect).
        # The registry mounts these guarded APIRoutes under the plugin prefix.
        router.routes.extend(build_router(self.request_scope).routes)
        api.register_http_router(
            router,
            prefix="/desktop/recording",
            tags=["record-and-replay"],
        )
        api.register_startup_hook("recover_recordings", self.recover)
        api.register_shutdown_hook("close_recording", self.close, priority=0)

    def _create_services(self):
        self._service = self._service_factory()
        self._learning = DesktopLearningService()

    def feature_status(self):
        return {
            "enabled": self._enabled and not self._closed,
            "supported_platform": sys.platform == "darwin",
            "capture_mode": "events-only",
        }

    async def request_scope(self, request: Request):
        await self.recover()
        if self._closed or not self._enabled:
            raise HTTPException(403, "recording_plugin_disabled")
        if sys.platform != "darwin":
            raise HTTPException(503, "recording_platform_unsupported")
        task = asyncio.current_task()
        self._requests.add(task)
        # Snapshot this generation; a later enable creates fresh services.
        request.state.desktop_recording_service = self._service
        request.state.desktop_learning_service = self._learning
        try:
            yield
        finally:
            self._requests.discard(task)

    async def _close_services(self):
        pending = [
            t for t in self._requests if t is not asyncio.current_task()
        ]
        for task in pending:
            task.cancel()
        try:
            if self._service is not None:
                await self._service.close()
        finally:
            await asyncio.gather(*pending, return_exceptions=True)
            self._service = None
            self._learning = None

    async def set_enabled(self, enabled: bool):
        async with self._lifecycle_lock:
            if self._closed:
                raise HTTPException(403, "recording_plugin_disabled")
            if not enabled:
                # Close eligibility before waiting for any in-flight request.
                self._enabled = False
                await self._close_services()
            try:
                await write_text_atomic_async(
                    self._state_path,
                    json.dumps({"enabled": enabled}),
                )
            except OSError as exc:
                raise HTTPException(
                    503,
                    "recording_preference_save_failed",
                ) from exc
            if enabled and not self._enabled:
                self._create_services()
                self._enabled = True
            return self.feature_status()

    async def close(self):
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self._enabled = False
            await self._close_services()
        # No persistent flag change on unload/shutdown, and no deletion of
        # recordings, generated Skills, Helper binaries or other plugin state.

    async def recover(self):
        async with self._lifecycle_lock:
            if self._closed or not self._enabled or self._recovered:
                return
            from qwenpaw.config.utils import load_config

            config = await run_sync_io(load_config)
            await DesktopRecordingService.recover_workspaces(
                profile.workspace_dir
                for profile in config.agents.profiles.values()
                if getattr(profile, "workspace_dir", None)
            )
            self._recovered = True


plugin = RecordAndReplayPlugin()
