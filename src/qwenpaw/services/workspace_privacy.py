"""Agent 配置目录中的旧私人运行数据必须经独立对象授权读取。"""

_PRIVATE_RUNTIME_NAMES = frozenset({
    "sessions", "dialog", "mem_session", "mem_metadata", "mem_agent",
    "media", "documents", "资料", "artifacts", "产物", "tool_result", "tool_results",
    "jobs_history", ".qwenpaw", ".scroll", "chats.json", "jobs.json", "history.db",
})


def is_private_agent_runtime_path(path: str) -> bool:
    return path.replace("\\", "/").split("/", 1)[0].casefold() in _PRIVATE_RUNTIME_NAMES
