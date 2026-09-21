"""Native audio handoff into the current ordinary Chat."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from ...providers.realtime_voice import ProviderEvent, RealtimeProviderSession
from .contracts import VoiceAdmissionMode, VoiceTaskReceipt
from .task_bridge import VoiceTaskBridge

VoiceHandoffAction = Literal["handoff"]
_TOOL_ACTIONS: dict[str, tuple[VoiceHandoffAction, VoiceAdmissionMode]] = {
    # Match ordinary Chat and Codex-style handoff semantics: the same action
    # starts an idle Chat run or steers its active run.  The realtime model
    # must not choose the scheduler mode.
    "handoff_to_chat": ("handoff", "steer"),
}


@dataclass(frozen=True)
class VoiceWorkInput:
    """One provider-native work request admitted to ordinary Chat."""

    input_id: str
    call_id: str
    source_id: str
    request_text: str
    action: VoiceHandoffAction
    admission_mode: VoiceAdmissionMode


@dataclass(frozen=True)
class VoiceHandoffResult:
    """Application custody result for a native handoff call."""

    work: VoiceWorkInput
    receipt: VoiceTaskReceipt
    replayed: bool = False


class VoiceHandoffError(ValueError):
    """A native call cannot be admitted as ordinary Chat work."""


class VoiceHandoffController:
    """Validate, admit and acknowledge provider-native work actions.

    The native audio model decides conversation versus work. This class does
    not inspect transcripts or classify intent; it only enforces identity,
    schema and current-Chat admission semantics.
    """

    def __init__(
        self,
        provider: RealtimeProviderSession,
        bridge: VoiceTaskBridge,
    ) -> None:
        self._provider = provider
        self._bridge = bridge
        self._results: dict[str, asyncio.Future[VoiceHandoffResult]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def parse(event: ProviderEvent) -> VoiceWorkInput:
        if event.kind != "tool.call":
            raise VoiceHandoffError("not a realtime tool call")
        call_id = str(event.data.get("call_id") or event.correlation_id or "").strip()
        name = str(event.data.get("name") or "").strip()
        action = _TOOL_ACTIONS.get(name)
        if not call_id or action is None:
            raise VoiceHandoffError("unknown or unidentified realtime tool call")
        try:
            arguments = json.loads(str(event.data.get("arguments") or ""))
        except json.JSONDecodeError as exc:
            raise VoiceHandoffError("invalid realtime tool arguments") from exc
        if not isinstance(arguments, dict) or set(arguments) != {"request_text"}:
            raise VoiceHandoffError("invalid realtime tool argument schema")
        request_text = str(arguments.get("request_text") or "").strip()
        if not request_text or len(request_text) > 8000:
            raise VoiceHandoffError("realtime work request is empty or too long")
        digest = hashlib.sha256(call_id.encode()).hexdigest()
        return VoiceWorkInput(
            input_id=f"voice_{digest[:32]}",
            call_id=call_id,
            source_id=str(event.data.get("input_item_id") or "").strip(),
            request_text=request_text,
            action=action[0],
            admission_mode=action[1],
        )

    async def handle(self, event: ProviderEvent) -> VoiceHandoffResult:
        work = self.parse(event)
        async with self._lock:
            existing = self._results.get(work.call_id)
            if existing is None:
                existing = asyncio.get_running_loop().create_future()
                self._results[work.call_id] = existing
                owner = True
            else:
                owner = False
        if not owner:
            result = await asyncio.shield(existing)
            return VoiceHandoffResult(result.work, result.receipt, replayed=True)

        try:
            admission = await self._bridge.enqueue_input(
                work.request_text,
                idempotency_key=work.input_id,
                admission_mode=work.admission_mode,
            )
            receipt = await admission.wait()
        except asyncio.CancelledError:
            if not existing.done():
                existing.cancel()
            raise
        except Exception as exc:  # noqa: BLE001
            receipt = VoiceTaskReceipt(
                task_id="",
                task_ref="",
                accepted=False,
                status="failed",
                message=str(exc)[:500] or "The task could not be accepted.",
            )
        result = VoiceHandoffResult(work, receipt)
        try:
            await self._provider.complete_tool_call(
                work.call_id,
                {
                    "accepted": receipt.accepted,
                    "action": work.action,
                    "task_ref": receipt.task_ref,
                    "status": receipt.status,
                    **({"message": receipt.message} if receipt.message else {}),
                },
            )
        except BaseException as exc:
            if not existing.done():
                existing.set_exception(exc)
                existing.exception()
            raise
        if not existing.done():
            existing.set_result(result)
        return result

    async def handle_transcript(
        self,
        source_id: str,
        request_text: str,
    ) -> VoiceHandoffResult:
        """Steer a task-owned speech turn when the provider skipped its tool.

        Once ordinary Chat owns the conversation, its context is authoritative.
        This fallback uses the provider's final transcript only after the native
        response has proved that it did not call a handoff tool.
        """
        source_id = source_id.strip()
        request_text = request_text.strip()
        if not source_id or not request_text or len(request_text) > 8000:
            raise VoiceHandoffError("invalid task-owned speech transcript")
        digest = hashlib.sha256(source_id.encode()).hexdigest()
        work = VoiceWorkInput(
            input_id=f"voice_fallback_{digest[:32]}",
            call_id="",
            source_id=source_id,
            request_text=request_text,
            action="handoff",
            admission_mode="steer",
        )
        admission = await self._bridge.enqueue_input(
            work.request_text,
            idempotency_key=work.input_id,
            admission_mode=work.admission_mode,
        )
        return VoiceHandoffResult(work, await admission.wait())


__all__ = [
    "VoiceHandoffController",
    "VoiceHandoffError",
    "VoiceHandoffResult",
    "VoiceWorkInput",
]
