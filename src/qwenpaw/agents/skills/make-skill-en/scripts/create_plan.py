#!/usr/bin/env python3
"""Normalize and validate a make-skill v2 plan candidate."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "qwenpaw.make-skill-plan.v2"
ALLOWED_TYPES = (
    "instruction",
    "template",
    "workflow",
)
ALLOWED_EXECUTIONS = ("foreground", "background")
ALLOWED_TEST_MODES = ("off", "smoke", "eval")
PACKAGE_DIRS = frozenset(
    {"scripts", "references", "templates", "assets", "evals"},
)
PACKAGE_FILES = frozenset({"agents/openai.yaml"})
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PLAN_FIELDS = {
    "schema",
    "revision",
    "focus",
    "name",
    "goal",
    "type",
    "batch",
    "steps",
    "package",
    "execution",
    "test",
    "warnings",
}


class InputError(Exception):
    """Structured input errors safe to return to the caller."""

    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("invalid input")
        self.errors = errors


def error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def load_json_input(input_path: str | None) -> Any:
    """Read one JSON value from --input or stdin."""
    try:
        text = (
            Path(input_path).read_text(encoding="utf-8")
            if input_path
            else sys.stdin.read()
        )
    except OSError as exc:
        raise InputError(
            [error("input-read-failed", "input", str(exc))],
        ) from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(
            [
                error(
                    "invalid-json",
                    "input",
                    f"Invalid JSON at line {exc.lineno}, column {exc.colno}.",
                ),
            ],
        ) from None


def _text(value: Any, path: str, errors: list[dict[str, str]]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(error("required-string", path, "Must be non-empty."))
        return ""
    return value.strip()


def _string_list(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    required: bool,
) -> list[str]:
    if not isinstance(value, list):
        errors.append(error("invalid-list", path, "Must be an array."))
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(
                error(
                    "invalid-list-item",
                    f"{path}[{index}]",
                    "Must be a non-empty string.",
                ),
            )
            continue
        cleaned = item.strip()
        if cleaned not in result:
            result.append(cleaned)
    if required and not result:
        errors.append(error("empty-list", path, "Must not be empty."))
    return result


def _normalize_name(value: Any, errors: list[dict[str, str]]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(error("required-string", "name", "Must be non-empty."))
        return ""
    name = re.sub(
        r"-+",
        "-",
        re.sub(r"[\s_]+", "-", value.strip().lower()),
    )
    if len(name) > 64:
        errors.append(
            error("name-too-long", "name", "Use at most 64 characters."),
        )
    if not NAME_PATTERN.fullmatch(name):
        errors.append(
            error(
                "invalid-name",
                "name",
                "Use lowercase ASCII letters, digits, and internal hyphens.",
            ),
        )
    return name


def _package_path(
    value: str,
    index: int,
    errors: list[dict[str, str]],
) -> str:
    path = f"package[{index}]"
    parts = value.split("/")
    if (
        not value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or value.endswith("/")
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        errors.append(
            error(
                "unsafe-package-path",
                path,
                "Use a portable relative file path without traversal.",
            ),
        )
        return value
    if (
        value != "SKILL.md"
        and value not in PACKAGE_FILES
        and parts[0] not in PACKAGE_DIRS
    ):
        errors.append(
            error(
                "unsupported-package-location",
                path,
                (
                    "Use scripts, references, templates, assets, evals, or "
                    "the optional agents/openai.yaml file."
                ),
            ),
        )
    return value


def normalize_plan(candidate: Any) -> dict[str, Any]:
    """Return a canonical v2 plan or raise InputError."""
    if not isinstance(candidate, dict):
        raise InputError(
            [error("invalid-input", "", "Input must be a JSON object.")],
        )

    errors: list[dict[str, str]] = []
    for key in sorted(set(candidate) - PLAN_FIELDS):
        errors.append(error("unknown-field", key, "Not part of SkillPlan v2."))
    if candidate.get("schema") not in (None, SCHEMA):
        errors.append(error("invalid-schema", "schema", f"Must be {SCHEMA}."))

    revision = candidate.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        errors.append(
            error("invalid-revision", "revision", "Must be a positive integer."),
        )
        revision = 1

    focus = _text(candidate.get("focus"), "focus", errors)
    name = _normalize_name(candidate.get("name"), errors)
    goal = _text(candidate.get("goal"), "goal", errors)

    skill_type = _text(candidate.get("type"), "type", errors)
    if skill_type and skill_type not in ALLOWED_TYPES:
        errors.append(
            error(
                "invalid-type",
                "type",
                f"Choose from: {', '.join(ALLOWED_TYPES)}.",
            ),
        )
    raw_batch = candidate.get("batch")
    batch = raw_batch if isinstance(raw_batch, bool) else False
    if skill_type == "workflow" and not isinstance(raw_batch, bool):
        errors.append(
            error(
                "required-boolean",
                "batch",
                "A workflow must explicitly set batch to true or false.",
            ),
        )
    elif (
        skill_type in ALLOWED_TYPES
        and skill_type != "workflow"
        and "batch" in candidate
        and raw_batch is not False
    ):
        errors.append(
            error(
                "type-batch-mismatch",
                "batch",
                "For a non-workflow Skill, omit batch or set it to false.",
            ),
        )
        batch = False
    steps = _string_list(candidate.get("steps"), "steps", errors, required=True)
    raw_package = _string_list(
        candidate.get("package"),
        "package",
        errors,
        required=True,
    )
    package: list[str] = []
    for index, item in enumerate(raw_package):
        item = _package_path(item, index, errors)
        if item not in package:
            package.append(item)
    if "SKILL.md" not in package:
        errors.append(
            error("missing-skill-md", "package", "Must include SKILL.md."),
        )
    if skill_type == "template" and not any(
        path.startswith(("templates/", "assets/")) for path in package
    ):
        errors.append(
            error(
                "type-package-mismatch",
                "package",
                "A template Skill must include a real template or asset file.",
            ),
        )
    has_batch_file = any(
        path.startswith("scripts/") and path.endswith(".batch.json")
        for path in package
    )
    if skill_type in ALLOWED_TYPES and batch != has_batch_file:
        message = (
            "A batch-enabled workflow must include scripts/*.batch.json."
            if batch
            else "scripts/*.batch.json requires a batch-enabled workflow."
        )
        errors.append(
            error(
                "type-package-mismatch",
                "package",
                message,
            ),
        )

    execution = candidate.get("execution", "foreground")
    if execution not in ALLOWED_EXECUTIONS:
        errors.append(
            error(
                "invalid-execution",
                "execution",
                f"Choose from: {', '.join(ALLOWED_EXECUTIONS)}.",
            ),
        )
        execution = "foreground"

    raw_test = candidate.get("test", {"mode": "off", "target": ""})
    if not isinstance(raw_test, dict):
        errors.append(error("invalid-test", "test", "Must be an object."))
        raw_test = {}
    for key in sorted(set(raw_test) - {"mode", "target"}):
        errors.append(
            error("unknown-field", f"test.{key}", "Not part of SkillPlan v2."),
        )
    test_mode = raw_test.get("mode", "off")
    if test_mode not in ALLOWED_TEST_MODES:
        errors.append(
            error(
                "invalid-test-mode",
                "test.mode",
                f"Choose from: {', '.join(ALLOWED_TEST_MODES)}.",
            ),
        )
        test_mode = "off"
    test_target = ""
    if test_mode != "off":
        test_target = _text(raw_test.get("target"), "test.target", errors)

    warnings = _string_list(
        candidate.get("warnings", []),
        "warnings",
        errors,
        required=False,
    )
    if errors:
        raise InputError(errors)

    return {
        "schema": SCHEMA,
        "revision": revision,
        "focus": focus,
        "name": name,
        "goal": goal,
        "type": skill_type,
        "batch": batch,
        "steps": steps,
        "package": package,
        "execution": execution,
        "test": {"mode": test_mode, "target": test_target},
        "warnings": warnings,
    }


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        help="Read JSON from this file instead of stdin.",
    )
    args = parser.parse_args()
    try:
        plan = normalize_plan(load_json_input(args.input))
    except InputError as exc:
        emit(
            {
                "ok": False,
                "stage": "plan",
                "errors": exc.errors,
                "warnings": [],
            },
        )
        return 2
    emit(
        {
            "ok": True,
            "stage": "plan",
            "plan": plan,
            "errors": [],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
