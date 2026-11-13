# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-outer-name

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import uuid4

import requests

import config as e2e_config


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class CreatorApiClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + e2e_config.API_PREFIX
        self.session = requests.Session()

    def health_ok(self, timeout: int = 30) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = self.session.get(f"{self.base}/health", timeout=5)
                payload = response.json()
                if (
                    response.status_code == 200
                    and payload.get("status") == "ok"
                    and payload.get("runtime") == "creator-filesystem"
                ):
                    return True
            except (requests.RequestException, ValueError):
                pass
            time.sleep(1)
        return False

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(
            f"{self.base}{path}",
            timeout=kwargs.pop("timeout", 30),
            **kwargs,
        )

    def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        **kwargs,
    ) -> requests.Response:
        return self.session.post(
            f"{self.base}{path}",
            json=json,
            timeout=kwargs.pop("timeout", 60),
            **kwargs,
        )

    def patch(
        self,
        path: str,
        json: dict[str, Any],
        **kwargs,
    ) -> requests.Response:
        return self.session.patch(
            f"{self.base}{path}",
            json=json,
            timeout=kwargs.pop("timeout", 60),
            **kwargs,
        )

    def post_file(
        self,
        path: str,
        files: dict,
        data: dict | None = None,
        **kwargs,
    ) -> requests.Response:
        return self.session.post(
            f"{self.base}{path}",
            files=files,
            data=data or {},
            timeout=kwargs.pop("timeout", 120),
            **kwargs,
        )

    def create_project(
        self,
        name: str,
        *,
        description: str = "Timeline/Element E2E Project",
        aspect_ratio: str = "16:9",
    ) -> dict[str, Any]:
        client_id = f"e2e-project-{uuid4()}"
        response = self.post(
            "/projects",
            json={
                "clientRequestId": client_id,
                "name": name,
                "description": description,
                "scenario": "general",
                "aspectRatio": aspect_ratio,
                "resolution": "720P",
                "contentType": None,
            },
            headers={"Idempotency-Key": client_id},
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["projectSnapshotId"]
        return payload

    def delete_project(self, project_id: str) -> None:
        key = f"e2e-delete-{uuid4()}"
        response = self.session.delete(
            f"{self.base}/projects/{project_id}",
            headers={"Idempotency-Key": key},
            timeout=30,
        )
        if response.status_code not in (204, 404):
            response.raise_for_status()

    def project_snapshot(self, project_id: str) -> dict[str, Any]:
        response = self.get(f"/projects/{project_id}/project")
        response.raise_for_status()
        return response.json()

    def replace_elements(
        self,
        project_id: str,
        *,
        snapshot: dict[str, Any],
        timeline_id: str,
        before: dict[str, Any],
        elements: dict[str, Any],
    ) -> dict[str, Any]:
        command_id = f"e2e-elements-{uuid4()}"
        response = self.patch(
            f"/projects/{project_id}/project",
            json={
                "clientCommandId": command_id,
                "editSessionId": f"e2e-edit-{uuid4()}",
                "baseGeneration": snapshot["generation"],
                "baseEtag": snapshot["etag"],
                "operations": [
                    {
                        "op": "replace",
                        "path": (
                            f"/timelines/items/{timeline_id}/elements_by_id"
                        ),
                        "value": elements,
                        "expectedValueHash": _json_hash(before),
                    },
                ],
            },
            headers={"Idempotency-Key": command_id},
        )
        response.raise_for_status()
        return response.json()

    def wait_task(
        self,
        project_id: str,
        task_id: str,
        *,
        timeout: float = 30,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self.get(f"/projects/{project_id}/tasks/{task_id}")
            response.raise_for_status()
            task = response.json()
            if task["status"] in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "QUARANTINED",
            }:
                return task
            time.sleep(0.2)
        raise AssertionError(f"Task {task_id} did not finish in {timeout}s")

    def models_config(self) -> dict[str, Any]:
        response = self.get("/models/config")
        response.raise_for_status()
        return response.json()
