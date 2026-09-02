#!/usr/bin/env python3
"""Validate a private Skill package and bind it to a content digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

import create_plan
import init_draft

DRAFT_ID_PATTERN = re.compile(r"[a-f0-9]{24}")
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
PLACEHOLDER_PATTERN = re.compile(r"\$\{([^{}]+)\}")
ARG_PATTERN = re.compile(r"args\.([A-Za-z0-9_.-]+)")
STEP_PATTERN = re.compile(r"steps\.(\d+)(?:\.[A-Za-z0-9_.-]+)?")
VAR_PATTERN = re.compile(r"vars\.[A-Za-z_][A-Za-z0-9_.-]*")


def _failure(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "ok": False,
        "stage": "validate",
        "errors": errors,
        "warnings": [],
        "package_tree": [],
        "digest": "",
    }


def _resolve_draft(
    workspace: Path,
    draft_id: str,
) -> tuple[Path, Path, dict[str, Any]] | dict[str, Any]:
    try:
        draft_base = init_draft.private_drafts_root(workspace, create=False)
    except RuntimeError as exc:
        return _failure(
            [create_plan.error("unsafe-draft-root", "draft_id", str(exc))],
        )
    draft_root = draft_base / draft_id
    if draft_root.is_symlink() or not draft_root.is_dir():
        return _failure(
            [
                create_plan.error(
                    "draft-not-found",
                    "draft_id",
                    "The private draft does not exist or is not a directory.",
                ),
            ],
        )

    plan_path = draft_root / "plan.json"
    if plan_path.is_symlink() or not plan_path.is_file():
        return _failure(
            [
                create_plan.error(
                    "missing-plan",
                    "plan.json",
                    "The approved plan snapshot is missing.",
                ),
            ],
        )
    try:
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan = create_plan.normalize_plan(raw_plan)
    except (OSError, json.JSONDecodeError) as exc:
        return _failure(
            [create_plan.error("invalid-plan", "plan.json", str(exc))],
        )
    except create_plan.InputError as exc:
        return _failure(
            [
                create_plan.error(
                    item["code"],
                    f"plan.{item['path']}" if item["path"] else "plan",
                    item["message"],
                )
                for item in exc.errors
            ],
        )
    if raw_plan != plan:
        return _failure(
            [
                create_plan.error(
                    "noncanonical-plan",
                    "plan.json",
                    "The approved plan snapshot is not canonical SkillPlan v2 JSON.",
                ),
            ],
        )

    skill_dir = draft_root / plan["name"]
    if skill_dir.is_symlink() or not skill_dir.is_dir():
        return _failure(
            [
                create_plan.error(
                    "missing-skill-directory",
                    plan["name"],
                    "The planned Skill directory is missing.",
                ),
            ],
        )
    return draft_root, skill_dir, plan


def _inspect_tree(
    skill_dir: Path,
    errors: list[dict[str, str]],
) -> tuple[list[str], bool]:
    files: list[str] = []
    has_symlink = False
    try:
        paths = sorted(
            skill_dir.rglob("*"),
            key=lambda path: path.relative_to(skill_dir).as_posix(),
        )
    except OSError as exc:
        errors.append(create_plan.error("tree-read-failed", "", str(exc)))
        return files, has_symlink

    for path in paths:
        relative = path.relative_to(skill_dir).as_posix()
        if path.is_symlink():
            has_symlink = True
            errors.append(
                create_plan.error(
                    "symlink-not-allowed",
                    relative,
                    "Skill packages must not contain symbolic links.",
                ),
            )
        elif path.is_file():
            files.append(relative)
        elif path.is_dir():
            try:
                empty = next(path.iterdir(), None) is None
            except OSError:
                empty = False
            if empty:
                errors.append(
                    create_plan.error(
                        "empty-directory",
                        relative,
                        "Remove empty generated directories.",
                    ),
                )
        else:
            errors.append(
                create_plan.error(
                    "unsupported-file-type",
                    relative,
                    "Only regular files and directories are allowed.",
                ),
            )
    return files, has_symlink


def _validate_frontmatter(
    skill_dir: Path,
    plan: dict[str, Any],
    errors: list[dict[str, str]],
) -> str:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file() or skill_md.is_symlink():
        errors.append(
            create_plan.error(
                "missing-skill-md",
                "SKILL.md",
                "SKILL.md is required.",
            ),
        )
        return ""
    try:
        content = skill_md.read_text(encoding="utf-8")
        from qwenpaw.agents.skill_system.store import validate_skill_content

        name, description = validate_skill_content(content)
    except Exception as exc:
        errors.append(
            create_plan.error("invalid-frontmatter", "SKILL.md", str(exc)),
        )
        return ""

    if name != plan["name"] or name != skill_dir.name:
        errors.append(
            create_plan.error(
                "name-mismatch",
                "SKILL.md.name",
                "Frontmatter name, directory name, and approved name must match.",
            ),
        )
    if len(description) > 1024:
        errors.append(
            create_plan.error(
                "description-too-long",
                "SKILL.md.description",
                "Use at most 1024 characters.",
            ),
        )

    return content


def _validate_links(
    skill_dir: Path,
    content: str,
    errors: list[dict[str, str]],
) -> None:
    root = skill_dir.resolve()
    for raw_target in LINK_PATTERN.findall(content):
        target = raw_target.strip("<>")
        if not target or target.startswith(("#", "/")):
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        candidate = (skill_dir / target).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(
                create_plan.error(
                    "reference-escape",
                    "SKILL.md",
                    f"Reference escapes the Skill directory: {raw_target}",
                ),
            )
            continue
        if not candidate.exists():
            errors.append(
                create_plan.error(
                    "broken-reference",
                    "SKILL.md",
                    f"Referenced path does not exist: {raw_target}",
                ),
            )


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _validate_batch(
    data: Any,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    actions = data.get("actions") if isinstance(data, dict) else data
    if not isinstance(actions, list) or not actions:
        errors.append(
            create_plan.error(
                "invalid-batch",
                path,
                "Batch JSON must be a non-empty action array or contain one.",
            ),
        )
        return
    if len(actions) > 50:
        errors.append(
            create_plan.error(
                "too-many-batch-actions",
                path,
                "run_tool_batch accepts at most 50 actions.",
            ),
        )
    for index, action in enumerate(actions):
        action_path = f"{path}.actions[{index}]"
        if not isinstance(action, dict):
            errors.append(
                create_plan.error(
                    "invalid-batch-action",
                    action_path,
                    "Each action must be an object.",
                ),
            )
            continue
        tool_name = action.get("tool_name") or action.get("tool")
        if not isinstance(tool_name, str) or not tool_name.strip():
            errors.append(
                create_plan.error(
                    "missing-tool-name",
                    action_path,
                    "Each action must name a tool.",
                ),
            )
        elif tool_name == "run_tool_batch":
            errors.append(
                create_plan.error(
                    "recursive-batch",
                    action_path,
                    "Nested run_tool_batch calls are not allowed.",
                ),
            )
        arguments = action.get("arguments") or action.get("args") or {}
        if not isinstance(arguments, dict):
            errors.append(
                create_plan.error(
                    "invalid-tool-arguments",
                    action_path,
                    "Action arguments must be an object.",
                ),
            )
            continue
        for value in _strings(arguments):
            matches = PLACEHOLDER_PATTERN.findall(value)
            if value.count("${") != len(matches):
                errors.append(
                    create_plan.error(
                        "invalid-placeholder",
                        action_path,
                        "Placeholders must use balanced ${...} syntax.",
                    ),
                )
            for placeholder in matches:
                step_match = STEP_PATTERN.fullmatch(placeholder)
                if step_match:
                    if int(step_match.group(1)) >= index:
                        errors.append(
                            create_plan.error(
                                "forward-step-reference",
                                action_path,
                                "A step may reference only an earlier action.",
                            ),
                        )
                elif not (
                    ARG_PATTERN.fullmatch(placeholder)
                    or VAR_PATTERN.fullmatch(placeholder)
                ):
                    errors.append(
                        create_plan.error(
                            "invalid-placeholder",
                            action_path,
                            f"Unsupported placeholder: ${{{placeholder}}}",
                        ),
                    )


def _digest(
    skill_dir: Path,
    files: list[str],
    plan: dict[str, Any],
) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    for relative in files:
        encoded_path = relative.encode("utf-8")
        data = (skill_dir / relative).read_bytes()
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def validate_draft(
    workspace: Path,
    draft_id: str,
    *,
    resolved: tuple[Path, Path, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolved or _resolve_draft(workspace, draft_id)
    if isinstance(resolved, dict):
        return resolved
    _, skill_dir, plan = resolved
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    files, has_symlink = _inspect_tree(skill_dir, errors)

    planned = set(plan["package"])
    actual = set(files)
    for path in sorted(planned - actual):
        errors.append(
            create_plan.error(
                "missing-planned-file",
                path,
                "Create every file in the approved package.",
            ),
        )
    for path in sorted(actual - planned):
        errors.append(
            create_plan.error(
                "unplanned-file",
                path,
                "Remove it or revise and re-approve the plan.",
            ),
        )

    skill_md = _validate_frontmatter(skill_dir, plan, errors)
    if skill_md:
        _validate_links(skill_dir, skill_md, errors)

    for relative in files:
        path = skill_dir / relative
        if relative.startswith("scripts/") and path.suffix == ".py":
            try:
                compile(path.read_bytes(), relative, "exec")
            except (OSError, SyntaxError) as exc:
                errors.append(
                    create_plan.error("invalid-python", relative, str(exc)),
                )
        if relative.startswith(("scripts/", "evals/")) and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(
                    create_plan.error("invalid-json", relative, str(exc)),
                )
                continue
            if relative.endswith(".batch.json"):
                _validate_batch(data, relative, errors)
        if relative == "agents/openai.yaml":
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Top-level YAML value must be an object.")
            except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
                errors.append(
                    create_plan.error("invalid-openai-yaml", relative, str(exc)),
                )

    security_scan = "skipped"
    if not has_symlink:
        try:
            from qwenpaw.agents.skill_system.store import scan_skill_dir_or_raise

            scan_skill_dir_or_raise(skill_dir, plan["name"])
            security_scan = "completed"
        except Exception as exc:
            security_scan = "failed"
            errors.append(
                create_plan.error("security-scan-failed", "", str(exc)),
            )

    digest = ""
    if not errors:
        try:
            digest = _digest(skill_dir, files, plan)
        except OSError as exc:
            errors.append(
                create_plan.error("file-read-failed", "", str(exc)),
            )
    return {
        "ok": not errors,
        "stage": "validate",
        "name": plan["name"],
        "errors": errors,
        "warnings": warnings,
        "package_tree": files,
        "digest": digest,
        "summary": {
            "files": len(files),
            "python_files": sum(path.endswith(".py") for path in files),
            "json_files": sum(path.endswith(".json") for path in files),
            "security_scan": security_scan,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        help="Read JSON from this file instead of stdin.",
    )
    args = parser.parse_args()
    try:
        payload = create_plan.load_json_input(args.input)
        if not isinstance(payload, dict):
            raise create_plan.InputError(
                [create_plan.error("invalid-input", "", "Input must be an object.")],
            )
        unknown = sorted(set(payload) - {"workspace", "draft_id"})
        if unknown:
            raise create_plan.InputError(
                [
                    create_plan.error(
                        "unknown-field",
                        unknown[0],
                        "Not part of the validation contract.",
                    ),
                ],
            )
        workspace = init_draft.resolve_workspace(payload.get("workspace"))
        draft_id = payload.get("draft_id")
        if not isinstance(draft_id, str) or not DRAFT_ID_PATTERN.fullmatch(draft_id):
            raise create_plan.InputError(
                [
                    create_plan.error(
                        "invalid-draft-id",
                        "draft_id",
                        "Must be an id returned by init_draft.py.",
                    ),
                ],
            )
    except create_plan.InputError as exc:
        create_plan.emit(
            {
                "ok": False,
                "stage": "validate",
                "errors": exc.errors,
                "warnings": [],
            },
        )
        return 2

    result = validate_draft(workspace, draft_id)
    create_plan.emit(result)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
