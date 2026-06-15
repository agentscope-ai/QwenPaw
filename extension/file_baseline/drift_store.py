# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DriftReview:
    alert_id: str
    agent_id: str
    path: str
    approved_sha256: str
    current_sha256: str
    provenance: str
    status: str
    detected_at: str
    patch_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "agent_id": self.agent_id,
            "path": self.path,
            "approved_sha256": self.approved_sha256,
            "current_sha256": self.current_sha256,
            "provenance": self.provenance,
            "status": self.status,
            "detected_at": self.detected_at,
            "patch_path": self.patch_path,
        }


@dataclass(frozen=True)
class DriftUpsertResult:
    review: DriftReview
    created: bool


class DriftReviewStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def save_all(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def list_open(self) -> list[DriftReview]:
        reviews: list[DriftReview] = []
        for item in self.load_all():
            if item.get("status") != "pending_review":
                continue
            reviews.append(
                DriftReview(
                    alert_id=str(item.get("alert_id") or ""),
                    agent_id=str(item.get("agent_id") or "default"),
                    path=str(item.get("path") or ""),
                    approved_sha256=str(item.get("approved_sha256") or ""),
                    current_sha256=str(item.get("current_sha256") or ""),
                    provenance=str(item.get("provenance") or "startup_scan"),
                    status=str(item.get("status") or "pending_review"),
                    detected_at=str(item.get("detected_at") or ""),
                    patch_path=item.get("patch_path"),
                ),
            )
        return reviews

    def open_count(self) -> int:
        return len(self.list_open())

    def upsert_pending(
        self,
        *,
        agent_id: str,
        path: str,
        approved_sha256: str,
        current_sha256: str,
        provenance: str,
        patch_path: str | None,
    ) -> DriftUpsertResult:
        records = self.load_all()
        for item in records:
            if (
                item.get("status") == "pending_review"
                and item.get("agent_id") == agent_id
                and item.get("path") == path
                and item.get("current_sha256") == current_sha256
            ):
                alert_id = str(item.get("alert_id") or "")
                logger.info(
                    "file_baseline_drift_upsert action=dedupe alert_id=%s agent_id=%s "
                    "path=%s provenance=%s current_sha256=%s",
                    alert_id,
                    agent_id,
                    path,
                    provenance,
                    current_sha256[:12],
                )
                return DriftUpsertResult(
                    review=DriftReview(
                        alert_id=alert_id,
                        agent_id=agent_id,
                        path=path,
                        approved_sha256=str(item.get("approved_sha256") or approved_sha256),
                        current_sha256=current_sha256,
                        provenance=str(item.get("provenance") or provenance),
                        status="pending_review",
                        detected_at=str(item.get("detected_at") or _utc_now()),
                        patch_path=item.get("patch_path") or patch_path,
                    ),
                    created=False,
                )

        review = DriftReview(
            alert_id=str(uuid.uuid4()),
            agent_id=agent_id,
            path=path,
            approved_sha256=approved_sha256,
            current_sha256=current_sha256,
            provenance=provenance,
            status="pending_review",
            detected_at=_utc_now(),
            patch_path=patch_path,
        )
        records.insert(0, review.to_dict())
        self.save_all(records)
        logger.info(
            "file_baseline_drift_upsert action=new alert_id=%s agent_id=%s path=%s "
            "provenance=%s current_sha256=%s",
            review.alert_id,
            agent_id,
            path,
            provenance,
            current_sha256[:12],
        )
        return DriftUpsertResult(review=review, created=True)

    def resolve_for_path(self, *, agent_id: str, path: str, status: str) -> int:
        records = self.load_all()
        changed = 0
        for item in records:
            if (
                item.get("status") == "pending_review"
                and item.get("agent_id") == agent_id
                and item.get("path") == path
            ):
                item["status"] = status
                item["resolved_at"] = _utc_now()
                changed += 1
        if changed:
            self.save_all(records)
        return changed

    def resolve(self, alert_id: str, *, status: str) -> bool:
        records = self.load_all()
        changed = False
        for item in records:
            if item.get("alert_id") == alert_id and item.get("status") == "pending_review":
                item["status"] = status
                item["resolved_at"] = _utc_now()
                changed = True
        if changed:
            self.save_all(records)
        return changed

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()
