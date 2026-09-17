# -*- coding: utf-8 -*-
"""Read-only repository artifact classifier for deployment preparation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Classification:
    category: str
    recommendation: str


def classify_path(path: Path, tracked: bool) -> Classification:
    normalized = path.as_posix().lower()
    if normalized.startswith("data/") or (
        normalized.startswith("tmp/") and "/working/" in normalized
    ):
        return Classification("business_data", "保留在部署数据根，不进入镜像或 Git")
    if normalized.startswith(("tmp/", "logs/")):
        return Classification("evidence_or_backup", "人工归档；确认无业务数据后再清理")
    if normalized.startswith(("playwright-report/", ".pytest_cache/", "console/dist/")):
        return Classification("regenerable", "可由构建或测试重新生成")
    if normalized.startswith(("test-results/", "evidence/")) or normalized.endswith(
        (".dump", ".bak", ".tar.gz")
    ):
        return Classification("evidence_or_backup", "移到外部归档并按保留策略管理")
    if tracked:
        return Classification("tracked_maintenance_asset", "继续由 Git 管理")
    return Classification("unclassified_local", "人工复核后决定是否纳入版本管理")


def _tracked_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def build_report(root: Path) -> dict:
    tracked = _tracked_paths(root)
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {"files": 0, "bytes": 0, "examples": [], "recommendation": ""}
    )
    ignored_roots = {".git", ".venv", "node_modules"}
    for current, directories, files in os.walk(root, onerror=lambda _error: None):
        directories[:] = [name for name in directories if name not in ignored_roots]
        current_path = Path(current)
        for name in files:
            path = current_path / name
            try:
                relative = path.relative_to(root)
                size = path.stat().st_size
            except OSError:
                continue
            classification = classify_path(relative, relative.as_posix() in tracked)
            group = groups[classification.category]
            group["files"] = int(group["files"]) + 1
            group["bytes"] = int(group["bytes"]) + size
            group["recommendation"] = classification.recommendation
            examples = group["examples"]
            if isinstance(examples, list) and len(examples) < 20:
                examples.append(relative.as_posix())
    return {"root": str(root.resolve()), "categories": dict(sorted(groups.items()))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.root.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
