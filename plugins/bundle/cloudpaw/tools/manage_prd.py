# -*- coding: utf-8 -*-
"""Manage PRD tool — CRUD and mark_passed for prd.json stories."""

import json
import logging
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
        return False, "priority 必须是整数，不能是布尔值"
    if not isinstance(priority, int):
        return False, f"priority 必须是整数类型，当前类型: {type(priority).__name__}"
    if priority < 1:
        return False, f"priority 必须是正整数（>=1），当前值: {priority}"
    return True, ""


def _to_kebab_case(text: str) -> str:
    """将文本转换为 kebab-case。

    例如:
    - "AuthSystem" → "auth-system"
    - "User Authentication" → "user-authentication"
    - "already-kebab" → "already-kebab"
    """
    import re

    # 添加连字符到驼峰命名
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    # 替换空格和下滑线为连字符
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
        # create 操作不需要 story 中有 passes/notes，会自动填充
        required_fields = frozenset(
            {"id", "title", "description", "acceptanceCriteria", "priority"},
        )
        missing = required_fields - set(story.keys())

    if missing:
        idx_label = f"story[{index}]" if index >= 0 else "story"
        return False, f"{idx_label} 缺少字段: {', '.join(sorted(missing))}"

    valid, err = _validate_priority(story.get("priority"))
    if not valid:
        return False, f"story '{story.get('id', '?')}' priority 错误: {err}"

    acceptance = story.get("acceptanceCriteria")
    if not isinstance(acceptance, list) or len(acceptance) == 0:
        return (
            False,
            f"story '{story.get('id', '?')}' acceptanceCriteria 必须是非空字符串数组",
        )

    return True, ""


def _save_prd(prd_path: Path, prd: dict) -> None:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_name = f"prd.json.bak.{timestamp}"
    backup_path = prd_path.parent / backup_name
    try:
        if prd_path.exists():
            backup_path.write_text(
                prd_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
    except Exception as exc:
        logger.warning("Failed to create backup %s: %s", backup_name, exc)
    prd_path.write_text(
        json.dumps(prd, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Updated prd.json at: %s (backup: %s)", prd_path, backup_name)


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


async def _handle_create(  # pylint: disable=too-many-return-statements
    _loop_path: Path,
    prd_path: Path,
    project: str = None,
    description: str = None,
    branch_name: str = None,
    stories: list[dict] | str = None,
) -> ToolResponse:
    """处理 create 操作：创建新的 PRD。

    Args:
        _loop_path: Mission 目录路径（保留供将来使用）
        prd_path: prd.json 路径
        project: 项目名称（必填）
        description: 项目描述（必填）
        branch_name: 分支名称（可选，自动生成）
        stories: stories 列表或 JSON 字符串（必填）

    Returns:
        ToolResponse: 创建结果
    """
    if not project or not project.strip():
        return _error_response("create 操作需要 project 参数（项目名称）")

    if not description or not description.strip():
        return _error_response("create 操作需要 description 参数（项目描述）")

    if stories is None:
        return _error_response("create 操作需要 stories 参数（story 列表）")

    # 解析 stories
    if isinstance(stories, str):
        try:
            stories = json.loads(stories)
        except json.JSONDecodeError as exc:
            return _error_response(f"stories JSON 解析失败: {exc}")

    if not isinstance(stories, list) or len(stories) == 0:
        return _error_response("stories 必须是非空列表")

    # 批量验证 stories
    existing_ids = set()
    validated_stories = []

    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            return _error_response(f"story[{i}] 必须是字典对象")

        # 验证 story 格式（不要求已有 passes/notes 字段，会自动填充）
        valid, err = _validate_story(story, index=i, check_passes_notes=False)
        if not valid:
            return _error_response(err)

        # 检查 ID 重复
        story_id = story.get("id")
        if story_id in existing_ids:
            return _error_response(f"story ID '{story_id}' 重复（story[{i}]）")
        existing_ids.add(story_id)

        # 自动填充必填字段
        story_dict = {
            "id": story_id,
            "title": story.get("title"),
            "description": story.get("description"),
            "acceptanceCriteria": story.get("acceptanceCriteria"),
            "priority": story.get("priority"),
            "passes": False,
            "notes": "",
        }

        # 保留可选的 notes 字段（如果有）
        if "notes" in story and story["notes"]:
            story_dict["notes"] = story["notes"]

        validated_stories.append(story_dict)

    # 生成分支名称（如果未指定）
    if not branch_name or not branch_name.strip():
        project_kebab = _to_kebab_case(project)
        branch_name = f"mission/{project_kebab}"

    # 构建 PRD 对象
    prd = {
        "project": project.strip(),
        "branchName": branch_name.strip(),
        "description": description.strip(),
        "userStories": validated_stories,
    }

    # 保存 PRD
    _save_prd(prd_path, prd)

    return _ok_response(
        f"已创建 PRD: {project}，包含 {len(validated_stories)} 个 story",
        data={
            "project": project,
            "branch_name": branch_name,
            "stories_count": len(validated_stories),
        },
    )


async def manage_prd(  # noqa: E501 # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
    loop_dir: str,
    operation: str,
    story: dict | str = None,
    story_id: str = None,
    story_ids: list[str] = None,
    fields: dict | str = None,
    # create 操作参数
    project: str = None,
    description: str = None,
    branch_name: str = None,
    stories: list[dict] | str = None,
) -> ToolResponse:
    """Create or modify the PRD (prd.json) for the current mission.

    ⚠️ IMPORTANT: This is the ONLY correct way to create or modify prd.json
    in Mission Mode.  Do NOT use write_file or edit_file on prd.json.

    The frontend automatically renders the PRD as an interactive table
    after a successful create/add/update/delete/mark_passed operation.

    ⚠️ AFTER THIS TOOL SUCCEEDS: Output ONLY ONE short confirmation
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
        return _error_response(f"Mission 目录不存在: {loop_dir}")

    if operation.lower().strip() == "create":
        if prd_path.exists():
            try:
                existing = json.loads(prd_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and isinstance(
                    existing.get("userStories"),
                    list,
                ):
                    return _error_response(
                        "prd.json 已存在且格式正确，不允许覆盖。"
                        "如需修改现有 PRD，请使用 add/update/delete 操作。",
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

    if not prd_path.exists():
        return _error_response(f"prd.json 未找到: {prd_path}")

    operation = operation.lower().strip()
    valid_operations = ["add", "update", "delete", "mark_passed"]
    if operation not in valid_operations:
        return _error_response(
            f"无效操作: '{operation}'。允许: {', '.join(valid_operations)}",
        )

    try:
        prd = json.loads(prd_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _error_response(f"prd.json 格式错误: {exc}")

    prd_stories: list[dict[str, Any]] = prd.get("userStories") or prd.get(
        "stories",
        [],
    )

    if operation == "add":
        if story is None:
            return _error_response("add 操作需要 story 参数")

        if isinstance(story, str):
            try:
                story = json.loads(story)
            except json.JSONDecodeError as exc:
                return _error_response(f"story JSON 解析失败: {exc}")

        if not isinstance(story, dict):
            return _error_response("story 必须是字典对象或 JSON 字符串")

        valid, err = _validate_story(story)
        if not valid:
            return _error_response(err)

        if story["id"] in {s.get("id") for s in prd_stories}:
            return _error_response(f"story ID '{story['id']}' 已存在")

        prd_stories.append(story)
        _save_prd(prd_path, prd)
        return _ok_response(f"已添加 story '{story['id']}'")

    elif operation == "update":
        if story_id is None:
            return _error_response("update 操作需要 story_id 参数")
        if fields is None:
            return _error_response("update 操作需要 fields 参数")

        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except json.JSONDecodeError as exc:
                return _error_response(f"fields JSON 解析失败: {exc}")

        if not isinstance(fields, dict):
            return _error_response("fields 必须是字典对象或 JSON 字符串")

        forbidden = {"id", "passes"}
        if any(k in forbidden for k in fields.keys()):
            return _error_response(f"禁止更新字段: {', '.join(forbidden)}")

        if "priority" in fields:
            valid, err = _validate_priority(fields["priority"])
            if not valid:
                return _error_response(f"priority 错误: {err}")

        for s in prd_stories:
            if s.get("id") == story_id:
                s.update(fields)
                _save_prd(prd_path, prd)
                return _ok_response(
                    f"已更新 story '{story_id}'",
                    data={"updated_fields": list(fields.keys())},
                )

        return _error_response(f"未找到 story: '{story_id}'")

    elif operation == "delete":
        if story_ids is None:
            return _error_response("delete 操作需要 story_ids 参数")

        existing_ids = {s.get("id") for s in prd_stories}
        if all(sid not in existing_ids for sid in story_ids):
            return _error_response(f"未找到任何 story: {', '.join(story_ids)}")

        prd["userStories"] = [
            s for s in prd_stories if s.get("id") not in story_ids
        ]
        _save_prd(prd_path, prd)
        deleted = len([sid for sid in story_ids if sid in existing_ids])
        return _ok_response(f"已删除 {deleted} 个 story")

    elif operation == "mark_passed":
        if story_ids is None:
            return _error_response("mark_passed 操作需要 story_ids 参数")

        target_ids = set(story_ids)
        updated: list[str] = []
        for s in prd_stories:
            sid = s.get("id")
            if sid in target_ids:
                s["passes"] = True
                updated.append(sid)
                target_ids.discard(sid)

        _save_prd(prd_path, prd)

        total = len(prd_stories)
        passed = len([s for s in prd_stories if s.get("passes")])

        return _ok_response(
            f"已将 {len(updated)} 个 story 标记为通过",
            data={
                "updated": updated,
                "not_found": list(target_ids),
                "progress": {
                    "passed": passed,
                    "total": total,
                    "all_done": passed == total and total > 0,
                },
            },
        )

    return _error_response(f"未知操作: {operation}")
