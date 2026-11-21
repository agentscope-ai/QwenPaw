"""将本人历史产物绑定到持久登记，不依赖旧服务器地址、文件根目录或访问令牌。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from uuid import UUID

from ...access.agent_repository import agent_database_id
from ...constant import WORKING_DIR
from ...workspaces.resolver import WorkspaceKind, WorkspaceResolver

_ARTIFACT_PATH = re.compile(r"^/api/console/artifacts/([0-9a-f-]{36})/download$", re.I)
_TEXT_ARTIFACT = re.compile(r"(?:https?://[^\s<>\"'()]+)?/api/console/artifacts/[0-9a-f-]{36}/download(?:\?[^\s<>\"'()]*)?", re.I)
_URL_FIELDS = {"file_url", "image_url", "video_url", "url"}


def _artifact_id(value: str) -> str | None:
    try:
        match = _ARTIFACT_PATH.fullmatch(urlsplit(value).path)
        return str(UUID(match[1])) if match else None
    except ValueError:
        return None


def _local_path(value: str) -> Path | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                return None
            raw = unquote(parsed.path)
        elif "/api/files/preview/" in parsed.path:
            raw = "/" + unquote(parsed.path.split("/api/files/preview/", 1)[1]).lstrip("/")
        elif not parsed.scheme and not value.startswith("/api/"):
            raw = value
        else:
            return None
        if re.match(r"^/[a-z]:/", raw, re.I):
            raw = raw[1:]
        path = Path(raw)
        return path.resolve() if path.is_absolute() else None
    except (ValueError, OSError):
        return None


def has_artifact_history_references(messages) -> bool:
    """普通文本或已登记上传附件不会触发额外的产物查询。"""
    for message in messages:
        for part in message.content or ():
            for field in ("file_url", "image_url", "video_url", "data"):
                value = getattr(part, field, None)
                if isinstance(value, str) and (_artifact_id(value) or _local_path(value)):
                    return True
            text = getattr(part, "text", None)
            if isinstance(text, str) and _TEXT_ARTIFACT.search(text):
                return True
            data = getattr(part, "data", None)
            if isinstance(data, dict) and "output" in data:
                # 大型外置载荷的历史摘要不含真实文件；完整载荷按需读取。
                output = data["output"]
                text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                if "/api/console/artifacts/" in text or "file://" in text:
                    return True
    return False


def normalize_owned_artifact_history(messages, artifacts, *, owner_user_id, agent_key,
                                     conversation_id, working_dir=WORKING_DIR,
                                     attachments=()) -> frozenset[str]:
    """只凭当前 owner、Agent、会话的有效登记重绑展示副本，不按文件名猜测。"""
    agent_id = agent_database_id(agent_key)
    root = WorkspaceResolver(working_dir=Path(working_dir)).resolve(
        kind=WorkspaceKind.USER_RUNTIME, resource_id=agent_key, actor_user_id=owner_user_id,
    ).path.resolve()
    by_id, by_path = {}, {}
    attachment_paths = set()
    for attachment in attachments:
        if attachment.lifecycle != "deleted":
            path = _local_path(attachment.storage_key)
            if path is not None:
                attachment_paths.add(path)
    for artifact in artifacts:
        if (artifact.owner_user_id != owner_user_id or artifact.agent_id != agent_id
                or artifact.conversation_id != conversation_id or artifact.status != "active"):
            continue
        path = (root / artifact.relative_path).resolve()
        if not path.is_relative_to(root):
            continue
        by_id[str(artifact.id)] = artifact
        by_path[path] = artifact

    for message in messages:
        unresolved = []

        def replace_url(value):
            if not isinstance(value, str):
                return value, None
            identifier = _artifact_id(value)
            path = _local_path(value) if identifier is None else None
            if path is not None and path in attachment_paths:
                return value, None
            record = by_id.get(identifier) if identifier else by_path.get(path)
            if record is not None:
                return f"/api/console/artifacts/{record.id}/download", record
            if identifier or path is not None:
                unresolved.append({"code": "artifact_reference_unavailable",
                    "message": "文件缺少当前会话的有效归属登记，无法自动恢复链接；请核对原件和产物记录。"})
            return value, None

        def replace_text(value):
            return _TEXT_ARTIFACT.sub(lambda match: replace_url(match[0])[0], value)

        def walk(value):
            if isinstance(value, list):
                return [walk(item) for item in value]
            if isinstance(value, dict):
                return {key: replace_url(item)[0] if key in _URL_FIELDS and isinstance(item, str)
                        else replace_text(item) if key == "text" and isinstance(item, str)
                        else walk(item) for key, item in value.items()}
            return value

        def normalize_tool_output(value):
            if not isinstance(value, list):
                return walk(value)
            # 旧发送结果的路径可能来自已迁移的服务器。只有同一条工具结果
            # 明确给出的唯一登记 ID，且它确属本人当前会话，才可替代该路径。
            media = [item for item in value if isinstance(item, dict)
                     and item.get("type") in {"data", "file", "image", "audio", "video"}
                     and isinstance(item.get("source"), dict)]
            identifiers = {
                identifier
                for item in value if isinstance(item, dict) and item.get("type") == "text"
                for match in _TEXT_ARTIFACT.finditer(str(item.get("text", "")))
                if (identifier := _artifact_id(match[0])) in by_id
            }
            if len(media) == 1 and len(identifiers) == 1:
                artifact = by_id[next(iter(identifiers))]
                media[0]["source"]["url"] = f"/api/console/artifacts/{artifact.id}/download"
                media[0]["name"] = artifact.original_name
            return walk(value)

        for part in message.content or ():
            for field in ("file_url", "image_url", "video_url", "data"):
                value = getattr(part, field, None)
                if isinstance(value, str):
                    replaced, record = replace_url(value)
                    setattr(part, field, replaced)
                    if record is not None and field == "file_url":
                        part.filename = record.original_name
            text = getattr(part, "text", None)
            if isinstance(text, str):
                part.text = replace_text(text)
            data = getattr(part, "data", None)
            if isinstance(data, dict) and "output" in data:
                # 不改写数据库/会话原始事实中共享的嵌套对象。
                data = deepcopy(data)
                output = data["output"]
                if isinstance(output, str) and len(output) < 128 * 1024:
                    try:
                        decoded = json.loads(output)
                    except ValueError:
                        data["output"] = replace_text(output)
                    else:
                        data["output"] = json.dumps(normalize_tool_output(decoded), ensure_ascii=False)
                elif not isinstance(output, str):
                    data["output"] = normalize_tool_output(output)
                part.data = data
        if unresolved:
            message.metadata = {**(message.metadata or {}), "qwenpaw_file_reference_status": unresolved[:20]}
    return frozenset(f"/api/console/artifacts/{identifier}/download" for identifier in by_id)
