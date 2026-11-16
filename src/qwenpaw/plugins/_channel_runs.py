# -*- coding: utf-8 -*-
"""Owned, ordered notifications for a live process channel's admitted runs."""

import asyncio
import logging
import json
from dataclasses import replace

from ..channel_protocol.outbound_budget import await_send, send_budget
from ..channel_protocol.models import RUN_EVENTS_CAPABILITY
from .channels import ChannelRunEvent
from .errors import ResourceError

logger = logging.getLogger(__name__)


class RunNotifications:
    def __init__(self, adapter):
        self.adapter = adapter
        self.runs = {}

    async def receive(self, params, request):
        adapter = self.adapter
        adapter._identity(params)
        adapter._guard()
        if RUN_EVENTS_CAPABILITY not in adapter._context.capabilities:
            raise ValueError("RUN_EVENTS_CAPABILITY_REQUIRED")
        identity = adapter._context.identity.to_mapping()
        names = {
            "response_handle",
            "phase",
            "run_id",
            "session_id",
            "user_id",
            "message_ids",
            "status",
            "sender_id",
            "acl_sender_id",
        }
        if set(params) != {*identity, *names} or any(
            not isinstance(params[key], str) for key in names - {"message_ids"}
        ):
            raise ValueError("INVALID_RUN_EVENT")
        ids = params["message_ids"]
        if (
            not isinstance(ids, list)
            or len(ids) > 4096
            or any(not isinstance(value, str) or not value for value in ids)
            or not params["run_id"]
            or params["phase"] not in {"start", "end"}
            or params["status"]
            not in {"running", "completed", "failed", "cancelled"}
            or (params["phase"] == "start") != (params["status"] == "running")
        ):
            raise ValueError("INVALID_RUN_EVENT")
        handle = params["response_handle"]
        state = self.runs.get(handle)
        if state is None:
            if params["phase"] != "start":
                raise ValueError("RUN_START_REQUIRED")
            target = adapter._target(handle)
            owner = json.loads(adapter._route_attrs(handle)["owner"])
            if (params["session_id"], params["user_id"]) != (
                owner["session_id"],
                owner["user_id"],
            ):
                raise ValueError("RUN_IDENTITY_MISMATCH")
            if len(self.runs) >= 4096:
                raise ResourceError("RUN_NOTIFICATION_CAPACITY")
            event = ChannelRunEvent(
                "start",
                params["run_id"],
                target.key,
                params["session_id"],
                params["user_id"],
                tuple(ids),
                "running",
                dict(target.metadata),
                params["sender_id"],
                params["acl_sender_id"],
            )
            state = {"event": event, "params": dict(params)}
            self.runs[handle] = state
        elif any(
            params[name] != state["params"][name]
            for name in names - {"phase", "status"}
        ):
            raise ValueError("RUN_IDENTITY_MISMATCH")
        phase = params["phase"]
        if phase == "end":
            if state.get("end_status", params["status"]) != params["status"]:
                raise ValueError("RUN_OUTCOME_CONFLICT")
            state["end_status"] = params["status"]
        if phase not in state:

            async def notify():
                if phase == "end":
                    try:
                        await asyncio.shield(state["start"])
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                try:
                    with send_budget(5):
                        await await_send(
                            adapter.driver.on_run(
                                adapter.ch,
                                replace(
                                    state["event"],
                                    phase=phase,
                                    status=params["status"],
                                ),
                            ),
                        )
                    return True
                except Exception:
                    logger.exception(
                        "Channel run notification failed: %s",
                        phase,
                    )
                    return False

            state[phase] = adapter.ch.resources.task(
                notify(),
                "channel run " + phase,
            )
        task = state[phase]
        done, _ = await asyncio.wait({task}, timeout=5)
        if not done and phase == "start" and not task.cancelling():
            task.cancel()
        return {
            "status": (
                "pending"
                if not done
                else "failed"
                if task.cancelled() or not task.result()
                else "complete"
            ),
        }

    def require_finished(self, handle):
        state = self.runs.get(handle)
        if state is not None:
            # Cancellation is terminal only after the actual task exits.
            # A cancelled end task may still leave its shielded start alive.
            if any(
                state.get(phase) is None or not state[phase].done()
                for phase in ("start", "end")
            ):
                raise ResourceError("RUN_NOTIFICATION_PENDING")

    def release(self, handle):
        self.require_finished(handle)
        self.runs.pop(handle, None)

    async def quiesce(self):
        tasks = {
            state[phase]
            for state in self.runs.values()
            for phase in ("start", "end")
            if phase in state and not state[phase].done()
        }
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=5)
            if pending:
                raise ResourceError("RUN_NOTIFICATION_PENDING")
