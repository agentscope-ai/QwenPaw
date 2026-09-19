# -*- coding: utf-8 -*-
"""Fail-closed local providers for the delegated video acceptance runner."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any

from services.file_agent_runtime import (
    AgentModelTurn,
    AgentToolCall,
    CallbackAgentChatClient,
)
from services.media_files.image_execution import ImageProvider
from services.media_files.r2v_execution import R2VProvider
from services.storage_root import require_creator_data_root
from utils.paths import task_work_root


ACCEPTANCE_RUNTIME_ENV = "CREATOR_ACCEPTANCE_FAKE_RUNTIME"
ACCEPTANCE_VIDEO_PATH_ENV = "CREATOR_ACCEPTANCE_VIDEO_PATH"
ACCEPTANCE_EVENT_LOG_ENV = "CREATOR_ACCEPTANCE_EVENT_LOG"
_PROJECT_PATTERN = re.compile(r"只处理 Project `([^`]+)`")
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _EventRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._once: set[tuple[str, str]] = set()

    @staticmethod
    def _encode(event: str, details: Mapping[str, Any]) -> bytes:
        return (
            json.dumps(
                {"event": event, **details},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

    def _append_locked(self, record: bytes) -> None:
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.write(descriptor, record)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def append(self, event: str, **details: Any) -> None:
        record = self._encode(event, details)
        with self._lock:
            self._append_locked(record)

    def append_once(self, event: str, identity: str, **details: Any) -> None:
        record = self._encode(event, details)
        key = (event, identity)
        with self._lock:
            if key in self._once:
                return
            self._once.add(key)
            self._append_locked(record)


class LocalAcceptanceImageProvider:
    def __init__(self, recorder: _EventRecorder) -> None:
        self._recorder = recorder

    async def generate(
        self,
        *,
        prompt: str,
        aspect_ratio: str,
        reference_image_urls: Sequence[str],
        mode: str = "generate",
        source_lang: str = "",
        target_lang: str = "",
    ) -> Mapping[str, Any]:
        del source_lang, target_lang
        self._recorder.append(
            "image.generate",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            reference_count=len(reference_image_urls),
            mode=mode,
        )
        return {"content": _PNG_BYTES, "media_type": "image/png"}


class LocalAcceptanceR2VProvider:
    def __init__(self, video_path: Path, recorder: _EventRecorder) -> None:
        self._video_path = video_path
        self._recorder = recorder
        self._checksum = hashlib.sha256(video_path.read_bytes()).hexdigest()

    async def submit(self, **arguments: Any) -> str:
        payload = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        provider_task_id = (
            "acceptance-r2v-"
            + hashlib.sha256(
                payload.encode("utf-8"),
            ).hexdigest()[:16]
        )
        self._recorder.append(
            "video.submit",
            provider_task_id=provider_task_id,
            duration_seconds=arguments.get("duration_seconds"),
            resolution=arguments.get("resolution"),
            ratio=arguments.get("ratio"),
        )
        return provider_task_id

    async def poll(self, provider_task_id: str) -> Mapping[str, Any]:
        target = task_work_root() / "acceptance-provider.mp4"
        if not target.exists():
            shutil.copyfile(self._video_path, target)
            target.chmod(0o600)
        self._recorder.append(
            "video.poll",
            provider_task_id=provider_task_id,
        )
        return {
            "status": "SUCCEEDED",
            "path": str(target),
            "checksum": self._checksum,
            "media_type": "video/mp4",
            "durationSeconds": 5,
        }

    async def submit_s2v(self, **_arguments: Any) -> str:
        raise RuntimeError("acceptance runtime does not support S2V")

    async def poll_s2v(self, _provider_task_id: str) -> Mapping[str, Any]:
        raise RuntimeError("acceptance runtime does not support S2V")


@dataclass(frozen=True, slots=True)
class AcceptanceRuntimeComponents:
    model_client: CallbackAgentChatClient
    image_provider: ImageProvider
    video_provider: R2VProvider


def _tool_results(
    messages: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    results: list[tuple[str, Mapping[str, Any]]] = []
    for message in messages:
        if message.get("role") != "tool" or message.get("failed") is True:
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            results.append((str(message.get("name") or ""), payload))
    return results


def _project_id(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content")
        if isinstance(content, str) and (match := _PROJECT_PATTERN.search(content)):
            return match.group(1)
    raise RuntimeError("acceptance Creator Agent cannot resolve project id")


def _node_succeeded(
    results: Sequence[tuple[str, Mapping[str, Any]]],
    node_id: str,
) -> bool:
    for name, payload in results:
        if name != "request_workgraph_execution":
            continue
        items = payload.get("items")
        if not isinstance(items, list):
            continue
        if any(
            isinstance(item, Mapping)
            and item.get("nodeId") == node_id
            and item.get("status") == "SUCCEEDED"
            for item in items
        ):
            return True
    return False


def _tool_turn(call_id: str, name: str, arguments: dict[str, Any]) -> AgentModelTurn:
    return AgentModelTurn(
        tool_calls=(
            AgentToolCall(
                call_id=call_id,
                name=name,
                arguments=arguments,
            ),
        ),
    )


def _acceptance_agent(recorder: _EventRecorder) -> CallbackAgentChatClient:
    async def callback(
        messages: Sequence[Mapping[str, Any]],
        _tools: Sequence[Mapping[str, Any]],
    ) -> AgentModelTurn:
        project_id = _project_id(messages)
        results = _tool_results(messages)
        if _node_succeeded(results, "compose:timeline:main"):
            recorder.append_once(
                "agent.complete",
                project_id,
                project_id=project_id,
            )
            return AgentModelTurn(content="视频已完成并发布。")
        if _node_succeeded(results, "video:shot-1"):
            recorder.append_once(
                "agent.compose",
                project_id,
                project_id=project_id,
            )
            return _tool_turn(
                "compose-final-video",
                "request_workgraph_execution",
                {
                    "projectId": project_id,
                    "targetRefs": ["timeline:timeline:main"],
                    "kinds": ["compose"],
                },
            )
        if _node_succeeded(results, "storyboard:shot-1"):
            recorder.append_once(
                "agent.video",
                project_id,
                project_id=project_id,
            )
            return _tool_turn(
                "generate-video",
                "request_workgraph_execution",
                {
                    "projectId": project_id,
                    "targetRefs": ["element:shot-1"],
                    "kinds": ["video"],
                },
            )
        if any(name == "patch_project" for name, _payload in results):
            recorder.append_once(
                "agent.storyboard",
                project_id,
                project_id=project_id,
            )
            return _tool_turn(
                "generate-storyboard",
                "request_workgraph_execution",
                {
                    "projectId": project_id,
                    "targetRefs": ["element:shot-1"],
                    "kinds": ["storyboard"],
                },
            )
        recorder.append_once(
            "agent.plan",
            project_id,
            project_id=project_id,
        )
        return _tool_turn(
            "add-r2v-shot",
            "patch_project",
            {
                "projectId": project_id,
                "ops": [
                    {
                        "op": "add",
                        "path": (
                            "/timelines/items/timeline:main/elements_by_id/shot-1"
                        ),
                        "value": {
                            "element_id": "shot-1",
                            "label": "Acceptance shot",
                            "span": {
                                "start_tick": 0,
                                "duration_tick": 5000,
                            },
                            "location": {},
                            "creation": {
                                "type": "r2v",
                                "narrative": (
                                    "A red paper kite rises slowly above a "
                                    "quiet green field."
                                ),
                                "storyboard_prompt": (
                                    "A red paper kite above a quiet green "
                                    "field, wide shot, daylight, 16:9."
                                ),
                                "video_prompt": (
                                    "[Image 1] is the storyboard. Animate "
                                    "the red paper kite rising slowly above "
                                    "the quiet field with a stable camera."
                                ),
                            },
                        },
                    },
                ],
            },
        )

    return CallbackAgentChatClient(callback)


def _required_local_file(value: str, *, label: str, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be absolute")
    path = path.resolve(strict=True)
    if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular file inside Creator data")
    return path


def build_acceptance_runtime() -> AcceptanceRuntimeComponents:
    if os.environ.get(ACCEPTANCE_RUNTIME_ENV) != "1":
        raise RuntimeError("local acceptance runtime was not explicitly enabled")
    root = require_creator_data_root().resolve()
    video_path = _required_local_file(
        os.environ.get(ACCEPTANCE_VIDEO_PATH_ENV, ""),
        label=ACCEPTANCE_VIDEO_PATH_ENV,
        root=root,
    )
    event_path = Path(os.environ.get(ACCEPTANCE_EVENT_LOG_ENV, "")).expanduser()
    if not event_path.is_absolute():
        raise RuntimeError(f"{ACCEPTANCE_EVENT_LOG_ENV} must be absolute")
    event_path = event_path.resolve(strict=False)
    if not event_path.is_relative_to(root):
        raise RuntimeError(
            f"{ACCEPTANCE_EVENT_LOG_ENV} must be inside Creator data",
        )
    event_path.parent.mkdir(parents=True, exist_ok=True)
    recorder = _EventRecorder(event_path)
    recorder.append("runtime.started")
    return AcceptanceRuntimeComponents(
        model_client=_acceptance_agent(recorder),
        image_provider=LocalAcceptanceImageProvider(recorder),
        video_provider=LocalAcceptanceR2VProvider(video_path, recorder),
    )


__all__ = [
    "ACCEPTANCE_EVENT_LOG_ENV",
    "ACCEPTANCE_RUNTIME_ENV",
    "ACCEPTANCE_VIDEO_PATH_ENV",
    "AcceptanceRuntimeComponents",
    "build_acceptance_runtime",
]
