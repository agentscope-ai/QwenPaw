# -*- coding: utf-8 -*-
"""Bounded, read-only evidence for community drafts; never executes tools."""

from datetime import datetime
import json
import platform
import re
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .community_report import redact_report_text
from ..installation_origin import InstallationOrigin, validated_origin


class DiagnosticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origins: list[InstallationOrigin] = Field(
        default_factory=list,
        max_length=6,
    )
    minutes: int = Field(default=60, ge=5, le=1440)
    session_id: str = Field(default="", max_length=128)


def resource_key(origin: dict) -> tuple[str, str]:
    return origin["resource_type"], origin["resource_id"]


def skill_resources(workspace_dir: Path | None) -> list[dict]:
    from ..agents.skill_system.store import (
        read_skill_manifest,
        read_skill_pool_manifest,
    )

    manifests = [("pool", read_skill_pool_manifest())]
    if workspace_dir:
        manifests.append(("workspace", read_skill_manifest(workspace_dir)))
    resources = {}
    for location, manifest in manifests:
        for name, entry in manifest.get("skills", {}).items():
            if not isinstance(entry, dict):
                continue
            origin = validated_origin(entry.get("installation_origin"))
            if not origin:
                continue
            resources[resource_key(origin)] = {
                "name": name,
                "local_id": name,
                "origin": origin,
                "description": "",
                "status": {
                    "location": location,
                    "enabled": entry.get("enabled"),
                },
            }
    return list(resources.values())


def matching_logs(resources: list[dict], minutes: int) -> tuple[str, bool]:
    """Only timestamped entries naming a selected resource, with stack lines.

    This is a text match, not proof that the resource caused the failure.
    The fixed application log is the only file this function can read.
    """
    if not resources:
        return "", False

    from ..utils.logging import LOG_FILE_PATH

    needles = {
        str(value).casefold()
        for item in resources
        for value in (item["local_id"], item["name"])
        if len(str(value)) >= 3
    }
    try:
        with LOG_FILE_PATH.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 512 * 1024))
            raw = stream.read(512 * 1024).decode("utf-8", errors="replace")
    except OSError:
        return "", False
    lines = raw.splitlines()
    if size > 512 * 1024:
        lines = lines[1:]  # Do not parse a partial first record.
    cutoff = time.time() - minutes * 60
    records: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stamp = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
        if stamp:
            if current:
                records.append(current)
            try:
                recent = (
                    datetime.strptime(
                        stamp[0],
                        "%Y-%m-%d %H:%M:%S",
                    ).timestamp()
                    >= cutoff
                )
            except ValueError:
                recent = False
            current = [line] if recent else []
        elif current:
            current.append(line)
    if current:
        records.append(current)
    selected = [
        "\n".join(record)
        for record in records
        if any(needle in "\n".join(record).casefold() for needle in needles)
    ]
    text = redact_report_text("\n\n".join(selected))
    return (
        redact_report_text(text[-16000:]),
        size > 512 * 1024 or len(text) > 16000,
    )


def environment_evidence(resources: list[dict]) -> str:
    from ..__version__ import __version__

    return redact_report_text(
        json.dumps(
            {
                "qwenpaw_version": __version__,
                "system": platform.system(),
                "system_release": platform.release(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
                "resources": resources,
            },
            ensure_ascii=False,
            indent=2,
        )[:5000],
    )
