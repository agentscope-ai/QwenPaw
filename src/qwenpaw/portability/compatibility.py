# -*- coding: utf-8 -*-
"""State store for Mission-led migration compatibility work."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..utils.io_utils import get_sync_path_lock, write_json_atomic
from .compatibility_safety import (
    mcp_inline_secret_risks,
    redact_sensitive_text,
    safe_url,
    secret_names,
)

_BASE_TOOL_BUDGET = 32


class AssetType(StrEnum):
    SKILL = "skills"
    MCP = "mcp"
    PLUGIN = "plugins"
    SCHEDULED_TASK = "scheduled_tasks"


class AssetZone(StrEnum):
    REPAIR = "repair"
    MIGRATE = "migrate"


class RunState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED_LIMIT = "stopped_limit"


class PluginComponent(BaseModel):
    """One readable component of a staged Skill or plugin."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    kind: str
    paths: list[str] = Field(default_factory=list)


class TestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    summary: str
    evidence: list[str] = Field(default_factory=list)
    tested_at: datetime


class CompatibilityAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_key: str
    asset_type: AssetType
    source_id: str
    name: str
    zone: AssetZone = AssetZone.REPAIR
    reason: str = ""
    snapshot: dict[str, Any] = Field(default_factory=dict)
    tests: int = 0
    changes: list[str] = Field(default_factory=list)
    last_test: TestResult | None = None
    components: list[PluginComponent] = Field(default_factory=list)
    tool_calls: int = 0
    tool_budget: int = _BASE_TOOL_BUDGET
    test_budget: int = 12
    updated_at: datetime

    @property
    def budget_exhausted(self) -> bool:
        return self.tool_calls >= self.tool_budget


class CompatibilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "4"
    migration_id: str
    source: str
    created_at: datetime
    updated_at: datetime
    state: RunState = RunState.RUNNING
    assets: list[CompatibilityAsset] = Field(default_factory=list)
    stop_reason: str = ""

    @model_validator(mode="after")
    def validate_identity(self) -> "CompatibilityManifest":
        keys = [item.asset_key for item in self.assets]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate compatibility asset")
        return self

    def get_asset(self, key: str) -> CompatibilityAsset:
        direct = [item for item in self.assets if item.asset_key == key]
        if direct:
            return direct[0]
        matches = [item for item in self.assets if item.source_id == key]
        if len(matches) != 1:
            raise KeyError(f"unknown or ambiguous asset: {key}")
        return matches[0]

    def by_zone(self, zone: AssetZone) -> list[CompatibilityAsset]:
        return [item for item in self.assets if item.zone is zone]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any, limit: int = 4096) -> str:
    return redact_sensitive_text(value, limit=limit).replace("\x00", "")


def _snapshot(asset_type: AssetType, value: Any) -> dict[str, Any]:
    if asset_type is AssetType.SKILL:
        return {"description": _text(getattr(value, "description", ""), 2000)}
    if asset_type is AssetType.MCP:
        command = getattr(value, "command", "")
        args = list(getattr(value, "args", ()) or ())
        url = getattr(value, "url", "")
        env = getattr(value, "env", {})
        headers = getattr(value, "headers", {})
        risks = mcp_inline_secret_risks(
            command,
            args,
            url,
            env,
            headers,
            getattr(value, "cwd", ""),
        )
        return {
            "transport": _text(getattr(value, "transport", "stdio"), 30),
            "command": (
                "<redacted-unsafe-command>"
                if "command" in risks
                else _text(command)
            ),
            "args": (
                ["<redacted>"]
                if "args" in risks
                else [_text(item) for item in args[:100]]
            ),
            "cwd": (
                "<redacted>"
                if "cwd" in risks
                else _text(getattr(value, "cwd", ""))
            ),
            "url": safe_url(url),
            "required_secret_names": secret_names(env)
            + secret_names(headers, prefix="header:"),
        }
    if asset_type is AssetType.PLUGIN:
        install_source = str(getattr(value, "install_source", ""))
        return {
            "marketplace": _text(getattr(value, "marketplace", "")),
            "version": _text(getattr(value, "version", ""), 100),
            "install_source": (
                safe_url(install_source)
                if "://" in install_source
                else _text(install_source)
            ),
        }
    return {
        "schedule_type": _text(
            getattr(value, "schedule_type", "unsupported"),
            30,
        ),
        "cron": _text(getattr(value, "cron", ""), 200),
        "run_at": str(getattr(value, "run_at", "") or ""),
        "timezone": _text(getattr(value, "timezone", "UTC"), 100),
        "prompt": _text(getattr(value, "prompt", ""), 32_000),
        "cwd": _text(getattr(value, "cwd", "")),
    }


def _identity(asset_type: AssetType, value: Any) -> tuple[str, str, str]:
    source_id = str(getattr(value, "source_id", "")).strip()
    name = str(getattr(value, "name", source_id)).strip() or source_id
    if not source_id:
        raise ValueError("compatibility asset requires source_id")
    return source_id, name, f"{asset_type.value}:{source_id}"


def save_manifest(path: Path | str, manifest: CompatibilityManifest) -> None:
    target = Path(path)
    with get_sync_path_lock(target):
        if target.is_symlink():
            raise ValueError("manifest cannot be a symlink")
        write_json_atomic(
            target,
            manifest.model_dump(mode="json"),
            new_file_mode=0o600,
        )
        os.chmod(target, 0o600)


def load_manifest(path: Path | str) -> CompatibilityManifest:
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise ValueError("invalid compatibility manifest")
    if stat.S_IMODE(target.stat().st_mode) & 0o077:
        os.chmod(target, 0o600)
    value = json.loads(target.read_text(encoding="utf-8"))
    return CompatibilityManifest.model_validate(value)


class CompatibilityStore:
    """Atomic state transitions for Mission compatibility work."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def prepare(
        self,
        *,
        migration_id: str,
        source: str,
        skills: Sequence[Any] = (),
        mcp_servers: Sequence[Any] = (),
        plugins: Sequence[Any] = (),
        scheduled_tasks: Sequence[Any] = (),
        components: dict[str, list[PluginComponent]] | None = None,
    ) -> CompatibilityManifest:
        if self.path.exists():
            raise FileExistsError(self.path)
        now = _now()
        assets: list[CompatibilityAsset] = []
        for asset_type, values in (
            (AssetType.SKILL, skills),
            (AssetType.MCP, mcp_servers),
            (AssetType.PLUGIN, plugins),
            (AssetType.SCHEDULED_TASK, scheduled_tasks),
        ):
            for value in values:
                source_id, name, key = _identity(asset_type, value)
                checklist = list((components or {}).get(key, ()))
                path_count = sum(len(item.paths) for item in checklist)
                assets.append(
                    CompatibilityAsset(
                        asset_key=key,
                        asset_type=asset_type,
                        source_id=source_id,
                        name=name,
                        snapshot=_snapshot(asset_type, value),
                        components=checklist,
                        tool_budget=min(
                            1_000,
                            _BASE_TOOL_BUDGET
                            + 2 * len(checklist)
                            + 4 * path_count,
                        ),
                        test_budget=min(120, max(12, 3 * len(checklist))),
                        updated_at=now,
                    ),
                )
        manifest = CompatibilityManifest(
            migration_id=migration_id,
            source=source,
            created_at=now,
            updated_at=now,
            assets=assets,
        )
        save_manifest(self.path, manifest)
        return manifest

    def _mutate(self, fn: Any) -> CompatibilityManifest:
        with get_sync_path_lock(self.path):
            manifest = load_manifest(self.path)
            fn(manifest)
            manifest.updated_at = _now()
            save_manifest(self.path, manifest)
            return manifest

    def finalize(
        self,
        key: str,
        *,
        passed: bool,
        summary: str,
        reason: str,
        evidence: Sequence[str] = (),
    ) -> CompatibilityManifest:
        def apply(manifest: CompatibilityManifest) -> None:
            asset = manifest.get_asset(key)
            if asset.zone is not AssetZone.REPAIR:
                raise RuntimeError(
                    "asset has already left the repair zone",
                )
            if asset.tests >= asset.test_budget:
                raise RuntimeError("compatibility test budget exhausted")
            asset.tests += 1
            asset.last_test = TestResult(
                passed=passed,
                summary=_text(summary, 1000),
                evidence=[_text(item, 1000) for item in evidence[:20]],
                tested_at=_now(),
            )
            if passed:
                asset.zone = AssetZone.MIGRATE
                asset.reason = _text(reason, 1000)
            asset.updated_at = _now()

        return self._mutate(apply)

    def consume(
        self,
        key: str,
        *,
        reserve: int = 0,
    ) -> CompatibilityAsset:
        result: CompatibilityAsset | None = None

        def apply(manifest: CompatibilityManifest) -> None:
            nonlocal result
            asset = manifest.get_asset(key)
            if asset.tool_calls >= asset.tool_budget - reserve:
                raise RuntimeError(
                    "this asset's tool-call budget is exhausted",
                )
            asset.tool_calls += 1
            asset.updated_at = _now()
            result = asset.model_copy(deep=True)

        self._mutate(apply)
        assert result is not None
        return result

    def mark_changed(self, key: str, change: str) -> CompatibilityManifest:
        def apply(manifest: CompatibilityManifest) -> None:
            asset = manifest.get_asset(key)
            if asset.zone is not AssetZone.REPAIR:
                raise RuntimeError("only repair-zone assets can be changed")
            asset.reason = ""
            asset.changes.append(_text(change, 500))
            asset.last_test = None
            asset.updated_at = _now()

        return self._mutate(apply)

    def complete(self) -> tuple[bool, str]:
        manifest = load_manifest(self.path)
        repair = len(manifest.by_zone(AssetZone.REPAIR))
        if repair:
            return (
                False,
                f"待修复区仍有 {repair} 项",
            )
        return True, "兼容清单已收敛"

    def finish(
        self,
        *,
        stopped: bool = False,
        reason: str = "",
    ) -> CompatibilityManifest:
        def apply(manifest: CompatibilityManifest) -> None:
            manifest.state = (
                RunState.STOPPED_LIMIT if stopped else RunState.COMPLETED
            )
            manifest.stop_reason = _text(reason, 1000)

        return self._mutate(apply)


def counts(manifest: CompatibilityManifest) -> dict[str, int]:
    result = {zone.value: len(manifest.by_zone(zone)) for zone in AssetZone}
    result["total"] = len(manifest.assets)
    return result


def write_summary(path: Path, manifest: CompatibilityManifest) -> None:
    """Write the concise migration narrative requested by the workflow."""
    labels = {
        AssetZone.MIGRATE: "待迁移区",
        AssetZone.REPAIR: "待修复区",
    }
    lines = [
        "# 工具和设置迁移记录",
        "",
        f"来源：{manifest.source}",
        f"状态：{manifest.state.value}",
    ]
    if manifest.stop_reason:
        lines.append(f"停止原因：{manifest.stop_reason}")
    lines.append("")
    for zone in (
        AssetZone.MIGRATE,
        AssetZone.REPAIR,
    ):
        lines.append(f"## {labels[zone]}")
        items = manifest.by_zone(zone)
        for item in items:
            budget = (
                f" [调用 {item.tool_calls}/{item.tool_budget}]"
                if item.budget_exhausted
                else ""
            )
            lines.append(
                f"- {item.asset_type.value}/{item.name}："
                f"{item.reason or '尚未完成兼容性修复'}{budget}",
            )
        if not items:
            lines.append("- 无")
        lines.append("")
    changed = [item for item in manifest.assets if item.changes]
    lines.append("## 修复摘要")
    lines.extend(f"- {item.name}：{'；'.join(item.changes)}" for item in changed)
    if not changed:
        lines.append("- 无")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


__all__ = [
    "AssetType",
    "AssetZone",
    "CompatibilityAsset",
    "CompatibilityManifest",
    "CompatibilityStore",
    "PluginComponent",
    "RunState",
    "counts",
    "load_manifest",
    "mcp_inline_secret_risks",
    "redact_sensitive_text",
    "save_manifest",
    "write_summary",
]
