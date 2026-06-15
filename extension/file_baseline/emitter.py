# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from .drift_store import DriftReview, DriftReviewStore

logger = logging.getLogger(__name__)

InboxAppendFn = Callable[..., Awaitable[dict]]
PushAppendFn = Callable[..., Awaitable[None]]
SSEPublishFn = Callable[[dict], Awaitable[None]]


@dataclass
class FileBaselineAlertEmitter:
    drift_store: DriftReviewStore
    is_enabled: Callable[[], bool]
    inbox_append: InboxAppendFn | None = None
    push_append: PushAppendFn | None = None
    sse_publish: SSEPublishFn | None = None

    async def emit_drift(
        self,
        *,
        agent_id: str,
        path: str,
        approved_sha256: str,
        current_sha256: str,
        provenance: str,
        patch_path: str | None = None,
    ) -> DriftReview | None:
        if not self.is_enabled():
            return None

        upsert = self.drift_store.upsert_pending(
            agent_id=agent_id,
            path=path,
            approved_sha256=approved_sha256,
            current_sha256=current_sha256,
            provenance=provenance,
            patch_path=patch_path,
        )
        review = upsert.review
        if not upsert.created:
            logger.info(
                "file_baseline_drift_emit skipped=dedupe alert_id=%s agent_id=%s path=%s "
                "provenance=%s current_sha256=%s",
                review.alert_id,
                agent_id,
                path,
                provenance,
                current_sha256[:12],
            )
            return review

        title = (
            "Persona file changed (startup scan)"
            if provenance == "startup_scan"
            else "Persona file changed"
        )
        body = (
            f"{path} no longer matches the approved baseline. "
            "Open Settings → Security → Integrity Check to review."
        )
        logger.warning(
            "Persona drift detected: agent=%s path=%s provenance=%s",
            agent_id,
            path,
            provenance,
        )

        inbox_event_id = ""
        if self.inbox_append is not None:
            inbox_event = await self.inbox_append(
                agent_id=agent_id,
                source_type="file_baseline_protection",
                source_id=review.alert_id,
                event_type="file_baseline_drift",
                status="pending_review",
                severity="high",
                title=title,
                body=body,
                payload={
                    "alert_id": review.alert_id,
                    "path": path,
                    "agent_id": agent_id,
                    "provenance": provenance,
                    "approved_sha256": approved_sha256,
                    "current_sha256": current_sha256,
                    "patch_path": patch_path,
                    "deep_link": (
                        f"/security?tab=integrityProtection&fileBaselineAlertId={review.alert_id}"
                    ),
                },
            )
            inbox_event_id = str(inbox_event.get("id") or "")

        sse_payload = {
            "type": "file_baseline_drift",
            "alert_id": review.alert_id,
            "agent_id": agent_id,
            "path": path,
            "approved_sha256": approved_sha256,
            "current_sha256": current_sha256,
            "patch_path": patch_path,
            "provenance": provenance,
            "detected_at": review.detected_at,
        }
        await self._publish_sse(sse_payload)

        logger.warning(
            "file_baseline_drift_emit alert_id=%s agent_id=%s path=%s provenance=%s "
            "current_sha256=%s inbox_event_id=%s",
            review.alert_id,
            agent_id,
            path,
            provenance,
            current_sha256[:12],
            inbox_event_id or "-",
        )

        return review

    async def emit_baseline_updated(
        self,
        *,
        agent_id: str,
        path: str,
        new_sha256: str,
    ) -> None:
        if not self.is_enabled():
            return
        await self._publish_sse(
            {
                "type": "file_baseline_updated",
                "agent_id": agent_id,
                "path": path,
                "new_sha256": new_sha256,
            },
        )

    async def emit_alert_resolved(
        self,
        *,
        alert_id: str,
        agent_id: str,
        path: str,
        action: str,
    ) -> None:
        if not self.is_enabled():
            return
        await self._publish_sse(
            {
                "type": "file_baseline_alert_resolved",
                "alert_id": alert_id,
                "agent_id": agent_id,
                "path": path,
                "action": action,
            },
        )

    async def _publish_sse(self, payload: dict) -> None:
        if self.sse_publish is not None:
            await self.sse_publish(payload)
