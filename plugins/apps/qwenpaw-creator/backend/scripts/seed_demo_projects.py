# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Create repeatable demo projects through the public Creator HTTP API.

This script intentionally has no storage/database imports and never writes a
Project tree itself.  Project bootstrap, immutable asset ingest, and the first
goal message all go through the same API boundaries used by the product UI.

Run from any directory while the standalone backend is available::

    python backend/scripts/seed_demo_projects.py \
        --base-url http://127.0.0.1:18112/api/qwenpaw-creator
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5

import httpx


@dataclass(frozen=True, slots=True)
class DemoProject:
    slug: str
    name: str
    description: str
    scenario: str
    goal: str
    brief_name: str
    brief_text: str


DEMOS: tuple[DemoProject, ...] = (
    DemoProject(
        slug="short-drama",
        name="Creator 示例：雪夜重逢",
        description="三段式短剧示例，用于验证规划、视觉资产与 R2V 工作台。",
        scenario="short_drama",
        goal=(
            "请制作一部约 36 秒、16:9、720P 的三段式短剧《雪夜重逢》。"
            "先在 Timeline 上规划 R2V Element 与 Shot，再补齐角色、雪夜车站场景与关键道具的视觉资产；"
            "每个 R2V Element 不超过 15 秒，人物造型和环境光线要连续。"
        ),
        brief_name="雪夜重逢创作要求.txt",
        brief_text=(
            "主角：林夏，二十多岁，深色长外套，红围巾。\n"
            "场景：雪夜老车站，暖黄色站灯，远处有缓慢驶来的列车。\n"
            "结构：等待、误会解除、重逢；每段约 12 秒。\n"
            "限制：不改变人物服装；对白简短；镜头运动克制。\n"
        ),
    ),
    DemoProject(
        slug="video-edit",
        name="Creator 示例：采访精剪",
        description="访谈精剪示例，用于验证素材理解与 AI Edit 工作台。",
        scenario="video_edit",
        goal=(
            "请把素材要求整理为一支约 45 秒、16:9、720P 的采访精剪方案。"
            "保留完整核心观点，删除停顿和重复表达，开头先给出结论，结尾保留行动建议；"
            "把每个素材选择直接建立为 Edit Element，不要虚构素材中不存在的画面或对白。"
        ),
        brief_name="采访精剪要求.txt",
        brief_text=(
            "主题：小团队如何建立稳定的内容生产流程。\n"
            "核心观点：先明确验收标准，再缩短反馈回路，最后自动化重复步骤。\n"
            "剪辑要求：去除长停顿和口头禅；允许 J-cut；字幕需保留专有名词原文。\n"
            "说明：这是文字素材，后续可在 Assets 页面继续挂载真实采访视频。\n"
        ),
    ),
)


def _stable_uuid(slug: str, operation: str) -> str:
    return str(
        uuid5(NAMESPACE_URL, f"qwenpaw-creator-demo:{slug}:{operation}"),
    )


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        detail = response.text[:1000]
        raise RuntimeError(
            f"Creator API request failed: {response.request.method} "
            f"{response.request.url} -> {response.status_code}: {detail}",
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Creator API response must be a JSON object")
    return payload


def _wait_for_asset(
    client: httpx.Client,
    *,
    project_id: str,
    task_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        task = _json(client.get(f"/projects/{project_id}/tasks/{task_id}"))
        status = task.get("status")
        if status == "SUCCEEDED":
            return task
        if status in {"FAILED", "CANCELLED"}:
            raise RuntimeError(
                f"asset ingest task {task_id} ended as {status}: {task.get('error')}",
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"asset ingest task {task_id} did not finish in time",
            )
        time.sleep(poll_interval_seconds)


def _asset_version_id(payload: dict[str, Any]) -> str | None:
    direct = payload.get("assetVersionId")
    if isinstance(direct, str) and direct:
        return direct
    items = (payload.get("result") or {}).get("items") or []
    if len(items) == 1 and isinstance(items[0], dict):
        value = items[0].get("assetVersionId")
        return value if isinstance(value, str) and value else None
    return None


def seed_one(
    client: httpx.Client,
    demo: DemoProject,
    *,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 0.25,
) -> dict[str, Any]:
    project_key = _stable_uuid(demo.slug, "project")
    project = _json(
        client.post(
            "/projects",
            headers={"Idempotency-Key": project_key},
            json={
                "clientRequestId": project_key,
                "name": demo.name,
                "description": demo.description,
                "scenario": demo.scenario,
                "aspectRatio": "16:9",
                "resolution": "720P",
                "contentType": None,
            },
        ),
    )
    project_id = str(project["projectId"])

    asset_key = _stable_uuid(demo.slug, "brief-asset")
    asset = _json(
        client.post(
            f"/projects/{project_id}/assets",
            headers={"Idempotency-Key": asset_key},
            json={
                "clientRequestId": asset_key,
                "kind": "text",
                "name": demo.brief_name,
                "value": demo.brief_text,
                "postIngestAction": "NONE",
            },
        ),
    )
    version_id = _asset_version_id(asset)
    if version_id is None:
        task_id = str(asset["taskId"])
        task = _wait_for_asset(
            client,
            project_id=project_id,
            task_id=task_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        version_id = _asset_version_id(task)
    if version_id is None:
        raise RuntimeError(
            "successful asset ingest did not return one immutable AssetVersion",
        )

    message_key = _stable_uuid(demo.slug, "initial-message")
    accepted = _json(
        client.post(
            f"/projects/{project_id}/messages",
            headers={"Idempotency-Key": message_key},
            json={
                "clientMessageId": message_key,
                "conversationId": project["conversationId"],
                "content": [{"type": "text", "text": demo.goal}],
                "assetVersionRefs": [f"asset-version:{version_id}"],
            },
        ),
    )
    return {
        "slug": demo.slug,
        "projectId": project_id,
        "creatorSessionId": project["creatorSessionId"],
        "conversationId": project["conversationId"],
        "projectSnapshotId": project["projectSnapshotId"],
        "assetVersionId": version_id,
        "messageSeq": accepted["messageSeq"],
        "appendState": accepted["appendState"],
    }


def seed_all(
    client: httpx.Client,
    demos: Iterable[DemoProject] = DEMOS,
) -> list[dict[str, Any]]:
    return [seed_one(client, demo) for demo in demos]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv(
            "CREATOR_API_BASE_URL",
            "http://127.0.0.1:18112/api/qwenpaw-creator",
        ),
        help="Creator public API base URL",
    )
    parser.add_argument(
        "--slug",
        choices=[demo.slug for demo in DEMOS],
        action="append",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print deterministic demo inputs without calling the API",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    selected = [
        demo for demo in DEMOS if not args.slug or demo.slug in args.slug
    ]
    if args.dry_run:
        print(
            json.dumps(
                [asdict(demo) for demo in selected],
                ensure_ascii=False,
                indent=2,
            ),
        )
        return 0
    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        timeout=90.0,
    ) as client:
        results = seed_all(client, selected)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
