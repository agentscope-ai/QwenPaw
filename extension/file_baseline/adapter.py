# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import soul_guardian_script


@dataclass(frozen=True)
class DriftFinding:
    path: str
    approved_sha256: str
    current_sha256: str
    patch_path: str | None = None
    error: str | None = None


class SoulGuardianAdapter:
    """Subprocess wrapper around clawsec soul-guardian."""

    def __init__(self, script_path: Path | None = None) -> None:
        self.script_path = script_path or soul_guardian_script()

    def _run(
        self,
        *,
        workspace_root: Path,
        state_dir: Path,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            str(self.script_path),
            "--state-dir",
            str(state_dir),
            *args,
        ]
        return subprocess.run(
            cmd,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def write_policy(self, state_dir: Path, policy: dict[str, Any]) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        policy_path = state_dir / "policy.json"
        policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def init(
        self,
        *,
        workspace_root: Path,
        state_dir: Path,
        actor: str = "qwenpaw",
    ) -> None:
        proc = self._run(
            workspace_root=workspace_root,
            state_dir=state_dir,
            args=["init", "--actor", actor, "--note", "persona-baseline-init"],
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"soul-guardian init failed ({proc.returncode}): {proc.stderr.strip()}",
            )

    def check_no_restore(
        self,
        *,
        workspace_root: Path,
        state_dir: Path,
        actor: str = "qwenpaw",
    ) -> tuple[list[DriftFinding], int]:
        proc = self._run(
            workspace_root=workspace_root,
            state_dir=state_dir,
            args=[
                "check",
                "--no-restore",
                "--output-format",
                "json",
                "--actor",
                actor,
                "--note",
                "persona-baseline-check",
            ],
        )
        drifts = self._parse_drift(proc.stdout)
        if proc.returncode not in (0, 2):
            raise RuntimeError(
                f"soul-guardian check failed ({proc.returncode}): {proc.stderr.strip()}",
            )
        if drifts:
            status = self.status(workspace_root=workspace_root, state_dir=state_dir)
            drifts = self._enrich_drifts(drifts, status)
        return drifts, proc.returncode

    def status(
        self,
        *,
        workspace_root: Path,
        state_dir: Path,
    ) -> dict[str, Any]:
        proc = self._run(
            workspace_root=workspace_root,
            state_dir=state_dir,
            args=["status"],
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"soul-guardian status failed ({proc.returncode}): {proc.stderr.strip()}",
            )
        return json.loads(proc.stdout)

    def restore_file(
        self,
        *,
        workspace_root: Path,
        state_dir: Path,
        relative_path: str,
        actor: str = "qwenpaw",
    ) -> None:
        approved = state_dir / "approved" / relative_path.replace("\\", "/")
        target = workspace_root / relative_path
        if approved.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(approved.read_bytes())
            return

        proc = self._run(
            workspace_root=workspace_root,
            state_dir=state_dir,
            args=[
                "restore",
                "--file",
                relative_path,
                "--actor",
                actor,
                "--note",
                "persona-baseline-restore",
            ],
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"soul-guardian restore failed ({proc.returncode}): {proc.stderr.strip()}",
            )

    def approve_file(
        self,
        *,
        workspace_root: Path,
        state_dir: Path,
        relative_path: str,
        actor: str = "qwenpaw",
    ) -> None:
        proc = self._run(
            workspace_root=workspace_root,
            state_dir=state_dir,
            args=[
                "approve",
                "--file",
                relative_path,
                "--actor",
                actor,
                "--note",
                "persona-baseline-accept",
            ],
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"soul-guardian approve failed ({proc.returncode}): {proc.stderr.strip()}",
            )

    @staticmethod
    def _parse_drift(stdout: str) -> list[DriftFinding]:
        for line in stdout.splitlines():
            marker = "SOUL_GUARDIAN_DRIFT "
            if not line.startswith(marker):
                continue
            payload = json.loads(line[len(marker) :])
            findings: list[DriftFinding] = []
            for item in payload.get("files", []):
                if item.get("error"):
                    findings.append(
                        DriftFinding(
                            path=item["path"],
                            approved_sha256="",
                            current_sha256="",
                            error=item["error"],
                        ),
                    )
                    continue
                findings.append(
                    DriftFinding(
                        path=item["path"],
                        approved_sha256="",
                        current_sha256="",
                        patch_path=item.get("patch"),
                    ),
                )
            return findings
        return []

    @staticmethod
    def _enrich_drifts(
        drifts: list[DriftFinding],
        status: dict[str, Any],
    ) -> list[DriftFinding]:
        by_path = {item["path"]: item for item in status.get("files", [])}
        enriched: list[DriftFinding] = []
        for drift in drifts:
            info = by_path.get(drift.path, {})
            enriched.append(
                DriftFinding(
                    path=drift.path,
                    approved_sha256=str(info.get("approvedSha") or ""),
                    current_sha256=str(info.get("currentSha") or ""),
                    patch_path=drift.patch_path,
                    error=drift.error,
                ),
            )
        return enriched
