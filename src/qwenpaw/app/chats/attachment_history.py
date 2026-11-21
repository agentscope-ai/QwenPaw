"""将本人已登记附件的旧链接转换为当前站点的稳定读取入口。"""

from copy import deepcopy
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from ...access.agent_repository import agent_database_id

_PATH = re.compile(r"^/api/(?:agents/([A-Za-z0-9_.-]+)/)?console/attachments/([0-9a-f-]{36})(?:/download)?$", re.I)
_TEXT = re.compile(r"(?:https?://[^\s<>\"'()]+)?/api/(?:agents/[A-Za-z0-9_.-]+/)?console/attachments/[0-9a-f-]{36}(?:/download)?(?:\?[^\s<>\"'()]*)?", re.I)


def normalize_attachment_history(messages, attachments):
    by_id = {str(record.id): record for record in attachments if record.lifecycle != "deleted"}

    def url(value):
        try:
            match = _PATH.fullmatch(urlsplit(value).path)
            record = by_id.get(str(UUID(match[2]))) if match else None
            if record is not None and (not match[1] or agent_database_id(match[1]) == record.agent_id):
                return f"/api/console/attachments/{record.id}"
        except ValueError:
            pass
        return value

    def walk(value):
        if isinstance(value, str):
            return _TEXT.sub(lambda match: url(match[0]), value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    for message in messages:
        for part in message.content or ():
            for field in ("file_url", "image_url", "video_url", "data", "text"):
                value = getattr(part, field, None)
                if isinstance(value, str):
                    setattr(part, field, walk(value))
            data = getattr(part, "data", None)
            if isinstance(data, dict) and "output" in data:
                data = deepcopy(data)
                output = data["output"]
                if isinstance(output, str) and len(output) < 128 * 1024:
                    try:
                        output = json.loads(output)
                    except ValueError:
                        data["output"] = walk(output)
                    else:
                        data["output"] = json.dumps(walk(output), ensure_ascii=False)
                elif not isinstance(output, str):
                    data["output"] = walk(output)
                part.data = data
