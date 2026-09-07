#!/usr/bin/env python3
"""Revalidate and publish a private Skill draft through SkillService."""

from __future__ import annotations

import argparse
import re
import shutil

import create_plan
import init_draft
import validate_skill

DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}")


def _emit_error(
    code: str,
    path: str,
    message: str,
    *,
    warnings: list[dict[str, str]] | None = None,
) -> None:
    create_plan.emit(
        {
            "ok": False,
            "stage": "publish",
            "errors": [create_plan.error(code, path, message)],
            "warnings": warnings or [],
        },
    )


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
        unknown = sorted(
            set(payload) - {"workspace", "draft_id", "expected_digest"},
        )
        if unknown:
            raise create_plan.InputError(
                [
                    create_plan.error(
                        "unknown-field",
                        unknown[0],
                        "Not part of the publication contract.",
                    ),
                ],
            )
        workspace = init_draft.resolve_workspace(payload.get("workspace"))
        draft_id = payload.get("draft_id")
        if not isinstance(
            draft_id, str
        ) or not validate_skill.DRAFT_ID_PATTERN.fullmatch(
            draft_id,
        ):
            raise create_plan.InputError(
                [
                    create_plan.error(
                        "invalid-draft-id",
                        "draft_id",
                        "Must be an id returned by init_draft.py.",
                    ),
                ],
            )
        expected_digest = payload.get("expected_digest")
        if not isinstance(expected_digest, str) or not DIGEST_PATTERN.fullmatch(
            expected_digest,
        ):
            raise create_plan.InputError(
                [
                    create_plan.error(
                        "invalid-digest",
                        "expected_digest",
                        "Must be the SHA-256 digest returned by validation.",
                    ),
                ],
            )
    except create_plan.InputError as exc:
        create_plan.emit(
            {
                "ok": False,
                "stage": "publish",
                "errors": exc.errors,
                "warnings": [],
            },
        )
        return 2

    resolved = validate_skill._resolve_draft(workspace, draft_id)
    if isinstance(resolved, dict):
        create_plan.emit({**resolved, "stage": "publish"})
        return 3
    draft_root, skill_dir, plan = resolved

    validation = validate_skill.validate_draft(
        workspace,
        draft_id,
        resolved=resolved,
    )
    if not validation["ok"]:
        create_plan.emit(
            {
                **validation,
                "stage": "publish",
            },
        )
        return 3
    if validation["digest"] != expected_digest:
        _emit_error(
            "digest-mismatch",
            "expected_digest",
            "The draft changed after validation; validate it again.",
            warnings=validation["warnings"],
        )
        return 3

    try:
        from qwenpaw.agents.skill_system.workspace_service import SkillService

        result = SkillService(workspace).install_skill_directory(
            skill_dir,
            enable=True,
            source="agent",
        )
    except Exception as exc:
        _emit_error(
            "publish-failed",
            plan["name"],
            str(exc),
            warnings=validation["warnings"],
        )
        return 5

    if not result["success"]:
        if result.get("reason") == "conflict":
            create_plan.emit(
                {
                    "ok": False,
                    "stage": "publish",
                    "errors": [
                        create_plan.error(
                            "skill-conflict",
                            plan["name"],
                            "A workspace Skill with this name already exists.",
                        ),
                    ],
                    "warnings": validation["warnings"],
                    "suggested_name": result["suggested_name"],
                },
            )
            return 4
        _emit_error(
            "publish-failed",
            plan["name"],
            f"SkillService rejected the install: {result.get('reason', 'unknown')}",
            warnings=validation["warnings"],
        )
        return 5

    cleanup_warning: list[dict[str, str]] = []
    try:
        shutil.rmtree(draft_root)
    except OSError as exc:
        cleanup_warning.append(
            create_plan.error(
                "draft-cleanup-failed",
                str(draft_root),
                str(exc),
            ),
        )

    create_plan.emit(
        {
            "ok": True,
            "stage": "publish",
            "name": result["name"],
            "enabled": result["enabled"],
            "path": result["path"],
            "files": validation["package_tree"],
            "validation": validation["summary"],
            "invocation": f"/{result['name']}",
            "errors": [],
            "warnings": validation["warnings"] + cleanup_warning,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
