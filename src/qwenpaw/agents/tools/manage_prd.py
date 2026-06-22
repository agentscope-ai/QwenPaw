# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""Manage PRD tool — CRUD and mark_passed for prd.json stories."""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)

_REQUIRED_STORY_FIELDS = frozenset(
    {
        "id",
        "title",
        "description",
        "acceptanceCriteria",
        "priority",
        "passes",
        "notes",
    },
)


def _validate_priority(priority: Any) -> tuple[bool, str]:
    if isinstance(priority, bool):
        return False, "priority must be a positive integer, not a boolean"
    if not isinstance(priority, int):
        return (
            False,
            f"priority must be a positive integer, "
            f"got {type(priority).__name__}",
        )
    if priority < 1:
        return False, f"priority must be >= 1, got {priority}"
    return True, ""


def _to_kebab_case(text: str) -> str:
    """Convert text to kebab-case.

    Examples:
    - "AuthSystem" -> "auth-system"
    - "User Authentication" -> "user-authentication"
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    s = re.sub(r"[\s_]+", "-", s)
    return s.lower().strip("-")


def _validate_story(
    story: dict,
    index: int = -1,
    check_passes_notes: bool = True,
) -> tuple[bool, str]:
    if check_passes_notes:
        missing = _REQUIRED_STORY_FIELDS - set(story.keys())
    else:
        required_fields = frozenset(
            {"id", "title", "description", "acceptanceCriteria", "priority"},
        )
        missing = required_fields - set(story.keys())

    if missing:
        idx_label = f"story[{index}]" if index >= 0 else "story"
        return (
            False,
            f"{idx_label} missing fields: {', '.join(sorted(missing))}",
        )

    valid, err = _validate_priority(story.get("priority"))
    if not valid:
        return False, f"story '{story.get('id', '?')}' priority error: {err}"

    acceptance = story.get("acceptanceCriteria")
    if not isinstance(acceptance, list) or len(acceptance) == 0:
        return (
            False,
            f"story '{story.get('id', '?')}' acceptanceCriteria "
            "must be a non-empty array",
        )

    return True, ""


def _save_prd(prd_path: Path, prd: dict) -> str:
    """Save prd.json and create a timestamped snapshot.

    Saves a snapshot at ``loop_dir/snapshots/{timestamp}.json`` for
    frontend historical retrieval.  Keeps at most 50 snapshots;
    oldest are removed first.

    Returns the timestamp string.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # Write new prd.json
    prd_path.write_text(
        json.dumps(prd, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Save snapshot for frontend
    snapshot_dir = prd_path.parent / "snapshots"
    snapshot_dir.mkdir(exist_ok=True)
    snapshot_path = snapshot_dir / f"{timestamp}.json"
    try:
        snapshot_path.write_text(
            json.dumps(prd, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to create snapshot %s: %s", snapshot_path, exc)

    # Cleanup: keep at most 50 snapshots (oldest removed first)
    _MAX_SNAPSHOTS = 50
    try:
        snapshots = sorted(snapshot_dir.glob("*.json"))
        if len(snapshots) > _MAX_SNAPSHOTS:
            for old in snapshots[: len(snapshots) - _MAX_SNAPSHOTS]:
                old.unlink()
    except Exception as exc:
        logger.warning(
            "Failed to clean snapshots in %s: %s",
            snapshot_dir,
            exc,
        )

    logger.info(
        "Updated prd.json at: %s (snapshot: %s)",
        prd_path,
        snapshot_path,
    )
    return timestamp


def _error_response(message: str) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    {
                        "status": "error",
                        "message": message,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            ),
        ],
    )


def _ok_response(message: str, data: dict = None) -> ToolResponse:
    result = {
        "status": "ok",
        "message": message,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "_hint": (
            "Frontend auto-renders PRD. "
            "Output ONLY a short confirmation, NO tables/lists/summaries."
        ),
    }
    if data:
        result["data"] = data
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False),
            ),
        ],
    )


def _validate_create_params(
    project: str,
    description: str,
    stories: list[dict] | str,
) -> tuple[bool, str]:
    """Validate create operation parameters. Returns (valid, error_msg)."""
    if not project or not project.strip():
        return False, "create requires 'project' parameter (project name)"
    if not description or not description.strip():
        return (
            False,
            "create requires 'description' parameter (project description)",
        )
    if stories is None:
        return False, "create requires 'stories' parameter (list of stories)"
    return True, ""


def _parse_stories(stories: list[dict] | str) -> tuple[list[dict] | None, str]:
    """Parse and validate stories. Returns (validated_stories, error_msg)."""
    if isinstance(stories, str):
        try:
            stories = json.loads(stories)
        except json.JSONDecodeError as exc:
            return None, f"stories JSON parse error: {exc}"
    if not isinstance(stories, list) or len(stories) == 0:
        return None, "stories must be a non-empty list"
    return stories, ""


def _build_story(story: dict) -> dict:
    """Build a validated story dict with default passes/notes."""
    story_dict = {
        "id": story.get("id"),
        "title": story.get("title"),
        "description": story.get("description"),
        "acceptanceCriteria": story.get("acceptanceCriteria"),
        "priority": story.get("priority"),
        "passes": False,
        "notes": "",
    }
    if "notes" in story and story["notes"]:
        story_dict["notes"] = story["notes"]
    return story_dict


def _validate_stories_list(
    stories: list[dict],
) -> tuple[list[dict] | None, str]:
    """Validate all stories and return list with defaults, or error."""
    existing_ids: set = set()
    validated: list[dict] = []
    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            return None, f"story[{i}] must be a dict object"
        valid, err = _validate_story(story, index=i, check_passes_notes=False)
        if not valid:
            return None, err
        story_id = story.get("id")
        if story_id in existing_ids:
            return None, f"story ID '{story_id}' is duplicated (story[{i}])"
        existing_ids.add(story_id)
        validated.append(_build_story(story))
    return validated, ""


async def _handle_create(
    _loop_path: Path,
    prd_path: Path,
    project: str = None,
    description: str = None,
    branch_name: str = None,
    stories: list[dict] | str = None,
) -> ToolResponse:
    """Handle create operation: create a new PRD."""
    valid, err = _validate_create_params(project, description, stories)
    if not valid:
        return _error_response(err)

    parsed, err = _parse_stories(stories)
    if parsed is None:
        return _error_response(err)

    validated_stories, err = _validate_stories_list(parsed)
    if validated_stories is None:
        return _error_response(err)

    if not branch_name or not branch_name.strip():
        project_kebab = _to_kebab_case(project)
        branch_name = f"mission/{project_kebab}"

    prd = {
        "project": project.strip(),
        "branchName": branch_name.strip(),
        "description": description.strip(),
        "userStories": validated_stories,
    }

    timestamp = _save_prd(prd_path, prd)

    return _ok_response(
        f"Created PRD: {project} with {len(validated_stories)} stories",
        data={
            "project": project,
            "branch_name": branch_name,
            "stories_count": len(validated_stories),
            "timestamp": timestamp,
        },
    )


def _parse_story_for_add(
    story: dict | str,
) -> tuple[dict | None, str]:
    """Parse and validate story parameter. Returns (story_dict, error_msg)."""
    if story is None:
        return None, "add requires 'story' parameter"
    if isinstance(story, str):
        try:
            story = json.loads(story)
        except json.JSONDecodeError as exc:
            return None, f"story JSON parse error: {exc}"
    if not isinstance(story, dict):
        return None, "story must be a dict object or JSON string"
    return story, ""


async def _handle_add(
    prd_path: Path,
    prd: dict,
    prd_stories: list[dict],
    story: dict | str,
) -> ToolResponse:
    """Handle add operation: add a new story to existing PRD."""
    story_dict, err = _parse_story_for_add(story)
    if story_dict is None:
        return _error_response(err)

    valid, err = _validate_story(story_dict)
    if not valid:
        return _error_response(err)

    if story_dict["id"] in {s.get("id") for s in prd_stories}:
        return _error_response(f"story ID '{story_dict['id']}' already exists")

    prd_stories.append(story_dict)
    timestamp = _save_prd(prd_path, prd)
    return _ok_response(
        f"Added story '{story_dict['id']}'",
        data={"timestamp": timestamp},
    )


def _parse_fields(fields: dict | str) -> tuple[dict | None, str]:
    """Parse fields parameter. Returns (fields_dict, error_msg)."""
    if fields is None:
        return None, "update requires 'fields' parameter"
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except json.JSONDecodeError as exc:
            return None, f"fields JSON parse error: {exc}"
    if not isinstance(fields, dict):
        return None, "fields must be a dict object or JSON string"
    return fields, ""


async def _handle_update(
    prd_path: Path,
    prd: dict,
    prd_stories: list[dict],
    story_id: str,
    fields: dict | str,
) -> ToolResponse:
    """Handle update operation: update fields of an existing story."""
    if story_id is None:
        return _error_response("update requires 'story_id' parameter")

    fields, err = _parse_fields(fields)
    if fields is None:
        return _error_response(err)
    if not isinstance(fields, dict):
        return _error_response("update fields must be a dict")

    forbidden = {"id", "passes"}
    if any(k in forbidden for k in fields.keys()):
        return _error_response(
            f"cannot update forbidden fields: {', '.join(sorted(forbidden))}",
        )

    if "priority" in fields:
        valid, err = _validate_priority(fields["priority"])
        if not valid:
            return _error_response(f"priority error: {err}")

    found = False
    for s in prd_stories:
        if s.get("id") == story_id:
            s.update(fields)
            found = True
            break

    if found:
        timestamp = _save_prd(prd_path, prd)
        return _ok_response(
            f"Updated story '{story_id}'",
            data={
                "updated_fields": list(fields.keys()),
                "timestamp": timestamp,
            },
        )

    return _error_response(f"story not found: '{story_id}'")


async def _handle_delete(
    prd_path: Path,
    prd: dict,
    prd_stories: list[dict],
    story_ids: list[str],
) -> ToolResponse:
    """Handle delete operation: remove stories by ID."""
    if story_ids is None:
        return _error_response("delete requires 'story_ids' parameter")

    existing_ids = {s.get("id") for s in prd_stories}
    if all(sid not in existing_ids for sid in story_ids):
        return _error_response(f"no stories found: {', '.join(story_ids)}")

    prd["userStories"] = [
        s for s in prd_stories if s.get("id") not in story_ids
    ]
    timestamp = _save_prd(prd_path, prd)
    deleted = len([sid for sid in story_ids if sid in existing_ids])
    return _ok_response(
        f"Deleted {deleted} stories",
        data={"timestamp": timestamp},
    )


async def _handle_mark_passed(
    prd_path: Path,
    prd: dict,
    prd_stories: list[dict],
    story_ids: list[str],
) -> ToolResponse:
    """Handle mark_passed operation: mark stories as passed."""
    if story_ids is None:
        return _error_response("mark_passed requires 'story_ids' parameter")

    target_ids = set(story_ids)
    updated: list[str] = []
    for s in prd_stories:
        sid = s.get("id")
        if sid in target_ids:
            s["passes"] = True
            updated.append(sid)
            target_ids.discard(sid)

    timestamp = _save_prd(prd_path, prd)

    total = len(prd_stories)
    passed = len([s for s in prd_stories if s.get("passes")])

    return _ok_response(
        f"Marked {len(updated)} stories as passed",
        data={
            "updated": updated,
            "not_found": list(target_ids),
            "progress": {
                "passed": passed,
                "total": total,
                "all_done": passed == total and total > 0,
            },
            "timestamp": timestamp,
        },
    )


def _load_prd(prd_path: Path) -> tuple[dict | None, str]:
    """Load and parse prd.json. Returns (prd_dict, error_msg)."""
    try:
        prd = json.loads(prd_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"prd.json format error: {exc}"
    return prd, ""


async def manage_prd(
    loop_dir: str,
    operation: str,
    story: dict | str = None,
    story_id: str = None,
    story_ids: list[str] = None,
    fields: dict | str = None,
    # create operation params
    project: str = None,
    description: str = None,
    branch_name: str = None,
    stories: list[dict] | str = None,
) -> ToolResponse:
    """Create or modify the PRD (prd.json) for the current mission.

    This is the ONLY correct way to create or modify prd.json
    in Mission Mode. Do NOT use write_file or edit_file on prd.json.

    The frontend automatically renders the PRD as an interactive table
    after a successful create/add/update/delete/mark_passed operation.

    AFTER THIS TOOL SUCCEEDS: Output ONLY ONE short confirmation
    sentence (e.g. "PRD 已创建，包含 N 个 story，请确认。"). Do NOT
    output story lists, tables, summaries, deployment plans, or any
    PRD content — the frontend handles all rendering.

    Operations:
    - create: Create a new PRD with project info and stories (Phase 1)
    - add: Add a new story to existing PRD
    - update: Update fields of an existing story
    - delete: Remove stories by ID
    - mark_passed: Mark stories as passed (Phase 2 verification)

    Args:
        loop_dir (`str`):
            Mission loop directory absolute path.
        operation (`str`):
            Operation type: "create" | "add" | "update" | "delete" |
            "mark_passed".
        story (`dict | str`, optional):
            For "add": new story object or JSON string.
            Required fields: id, title, description, acceptanceCriteria,
            priority(int), passes(false), notes.
        story_id (`str`, optional):
            For "update": the story ID to update.
        story_ids (`list[str]`, optional):
            For "delete"/"mark_passed": list of story IDs.
        fields (`dict | str`, optional):
            For "update": dict of fields to update.
            Allowed: title, description, acceptanceCriteria, priority, notes.
            Forbidden: id, passes.
        project (`str`, optional):
            For "create": project name (required).
        description (`str`, optional):
            For "create": project description (required).
        branch_name (`str`, optional):
            For "create": branch name, format "mission/<kebab-case>".
            Auto-generated if not specified.
        stories (`list[dict] | str`, optional):
            For "create": list of story dicts or JSON string.
            Each story needs: id (US-XXX), title, description,
            acceptanceCriteria (non-empty array), priority (positive int).
            passes/notes are auto-filled.

    Returns:
        `ToolResponse`: JSON result with status and message.
    """
    loop_path = Path(loop_dir).expanduser().resolve()
    prd_path = loop_path / "prd.json"

    if not loop_path.is_dir():
        return _error_response(f"Mission directory not found: {loop_dir}")

    op = operation.lower().strip()

    # --- create: bypass PRD loading ---
    if op == "create":
        if prd_path.exists():
            try:
                existing = json.loads(prd_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and isinstance(
                    existing.get("userStories"),
                    list,
                ):
                    return _error_response(
                        "prd.json already exists with valid schema, "
                        "cannot overwrite. "
                        "Use add/update/delete to modify the existing PRD.",
                    )
            except (json.JSONDecodeError, OSError):
                pass
            logger.info(
                "prd.json exists but has invalid schema; "
                "overwriting with new PRD",
            )
        return await _handle_create(
            loop_path,
            prd_path,
            project,
            description,
            branch_name,
            stories,
        )

    # --- all other ops need an existing valid prd.json ---
    if not prd_path.exists():
        return _error_response(f"prd.json not found: {prd_path}")

    prd, err = _load_prd(prd_path)
    if prd is None:
        return _error_response(err)

    prd_stories: list[dict[str, Any]] = prd.get("userStories") or prd.get(
        "stories",
        [],
    )

    # --- dispatch by operation ---
    if op == "add":
        return await _handle_add(prd_path, prd, prd_stories, story)

    if op == "update":
        return await _handle_update(
            prd_path,
            prd,
            prd_stories,
            story_id,
            fields,
        )

    if op == "delete":
        return await _handle_delete(prd_path, prd, prd_stories, story_ids)

    if op == "mark_passed":
        return await _handle_mark_passed(
            prd_path,
            prd,
            prd_stories,
            story_ids,
        )

    allowed = "add, update, delete, mark_passed"
    return _error_response(
        f"invalid operation: '{op}'. allowed: {allowed}",
    )
