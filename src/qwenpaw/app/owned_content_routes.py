"""只让独立核验所有者的内容读取到达处理器，不授予 Agent 运行权限。"""
from __future__ import annotations

import re

from fastapi import Request

_ID = r"[0-9a-fA-F-]{36}"
_OWNED_READS = (
    re.compile(r"/console/personal-library/(?:index|documents(?:/page)?)"),
    re.compile(rf"/console/personal-library/documents/{_ID}/(?:text|download)"),
    re.compile(rf"/console/attachments(?:/{_ID})?"),
    re.compile(r"/console/chat/task/[A-Za-z0-9_-]{1,128}"),
    re.compile(r"/cron/jobs/[^/]+(?:/history)?"),
)


def allows_owned_content_read(request: Request) -> bool:
    """受控入口各自验证 owner；public、控制动作和 SSE 不在此规则内。"""
    if request.method.upper() not in {"GET", "HEAD"}:
        return False
    if request.headers.get("X-Agent-Governance") is not None:
        return False
    path = request.url.path
    if path.startswith("/api/"):
        path = path[4:]
    if path.startswith("/agents/"):
        parts = path.split("/", 3)
        if len(parts) != 4:
            return False
        path = "/" + parts[3]
    path = path.rstrip("/")
    if path == "/cron/jobs":
        return request.query_params.getlist("scope") in ([], ["mine"])
    if path == "/workspace/memory" or path.startswith("/workspace/memory/"):
        return request.query_params.getlist("scope") == ["private"]
    return any(pattern.fullmatch(path) for pattern in _OWNED_READS)
