# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Bounded jq execution for producing an in-memory Project candidate."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping

from services.runtime_files.runtime_dependencies import resolve_jq


class JqTransformError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JqLimits:
    timeout_seconds: float = 10.0
    max_output_bytes: int = 16 * 1024 * 1024


class JqProjectTransformer:
    """Run a jq program without a shell and return exactly one JSON object."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        limits: JqLimits | None = None,
    ) -> None:
        self.executable = executable or resolve_jq() or ""
        self.limits = limits or JqLimits()

    def transform(
        self,
        project: Mapping[str, Any],
        program: str,
        *,
        string_args: Mapping[str, str] | None = None,
        json_args: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.executable:
            raise JqTransformError("jq executable is not available")
        if not isinstance(program, str) or not program.strip():
            raise JqTransformError("jq program must be non-empty")

        jq_command = [self.executable, "--compact-output", "--exit-status"]
        normalized_string_args = dict(string_args or {})
        normalized_json_args = dict(json_args or {})
        # Preserve per-key variables ($name, $elements, ...) and also expose
        # the argument objects named by the tool schema. Models naturally use
        # forms such as `$jsonArgs.elements`; accepting both avoids needless
        # jq compile failures without breaking existing programs.
        jq_command.extend(
            [
                "--argjson",
                "stringArgs",
                json.dumps(
                    normalized_string_args,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "--argjson",
                "jsonArgs",
                json.dumps(
                    normalized_json_args,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ],
        )
        for name, value in sorted(normalized_string_args.items()):
            jq_command.extend(["--arg", name, value])
        for name, value in sorted(normalized_json_args.items()):
            jq_command.extend(
                [
                    "--argjson",
                    name,
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ],
            )
        jq_command.append(program)
        raw_input = json.dumps(
            dict(project),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                completed = subprocess.run(
                    jq_command,
                    input=raw_input,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=self.limits.timeout_seconds,
                    check=False,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "LC_ALL": "C.UTF-8",
                    },
                )
            except subprocess.TimeoutExpired as exc:
                raise JqTransformError("jq transform timed out") from exc
            stdout.seek(0, os.SEEK_END)
            output_size = stdout.tell()
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read(self.limits.max_output_bytes + 1)
            error_output = stderr.read(64 * 1024)
        if output_size > self.limits.max_output_bytes:
            raise JqTransformError(
                "jq output exceeds the configured Project limit",
            )
        if completed.returncode != 0:
            message = error_output.decode("utf-8", errors="replace").strip()
            raise JqTransformError(
                f"jq transform failed: {message or completed.returncode}",
            )
        try:
            values = [
                json.loads(line)
                for line in output.decode("utf-8").splitlines()
                if line.strip()
            ]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JqTransformError("jq returned invalid JSON") from exc
        if len(values) != 1 or not isinstance(values[0], dict):
            raise JqTransformError("jq must return exactly one JSON object")
        return values[0]
