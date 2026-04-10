# -*- coding: utf-8 -*-
"""Safe JSON session with filename sanitization for cross-platform
compatibility.

Windows filenames cannot contain: \\ / : * ? " < > |
This module wraps agentscope's SessionBase so that session_id and user_id
are sanitized before being used as filenames.
"""
import os
import re
import json
import logging

from typing import Union, Sequence

import aiofiles
from agentscope.session import SessionBase
from agentscope_runtime.engine.schemas.exception import ConfigurationException
from ...exceptions import AgentStateError

logger = logging.getLogger(__name__)


# Characters forbidden in Windows filenames
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')

# Maximum bytes for a single tool_result output before truncation
_TOOL_RESULT_MAX_BYTES = 50 * 1024  # 50KB


def _truncate_tool_result_output(
    output: Union[str, list],
    max_bytes: int,
    tool_name: str = "",
) -> Union[str, list]:
    """Truncate a tool_result output if it exceeds max_bytes.

    Args:
        output: The tool result output (string or list of content blocks)
        max_bytes: Maximum allowed bytes before truncation
        tool_name: Name of the tool for the truncation notice

    Returns:
        Truncated output with a notice if truncated, original otherwise
    """
    if isinstance(output, str):
        if len(output.encode("utf-8", errors="replace")) <= max_bytes:
            return output
        return (
            f"[auto-truncated] Original output exceeded {max_bytes:,} bytes "
            f"(tool: {tool_name}). "
            f"First 2000 chars:\n{output[:2000]}\n[truncated]"
        )

    if isinstance(output, list):
        for block in output:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text", "")
            if len(text.encode("utf-8", errors="replace")) <= max_bytes:
                continue
            block["text"] = (
                f"[auto-truncated] Original output exceeded {max_bytes:,} bytes "
                f"(tool: {tool_name}). "
                f"First 2000 chars:\n{text[:2000]}\n[truncated]"
            )
    return output


def _compact_tool_results_in_state(state_dicts: dict) -> dict:
    """Truncate oversized tool_result outputs before persisting to disk.

    This is a safety net that prevents giant tool outputs from being
    saved to session JSON files when the compact_tool_result hook hasn't
    had a chance to run yet (e.g., same-turn save in the finally block).
    """
    agent_state = state_dicts.get("agent")
    if not agent_state or not isinstance(agent_state, dict):
        return state_dicts

    memory_state = agent_state.get("memory")
    if not memory_state or not isinstance(memory_state, dict):
        return state_dicts

    content = memory_state.get("content")
    if not content or not isinstance(content, list):
        return state_dicts

    truncated_count = 0
    for item in content:
        if not isinstance(item, list) or len(item) < 1:
            continue
        msg_dict = item[0]
        if not isinstance(msg_dict, dict):
            continue

        msg_content = msg_dict.get("content")
        if not isinstance(msg_content, list):
            continue

        for block in msg_content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue

            output = block.get("output")
            if not output:
                continue

            output_size = len(
                json.dumps(output, ensure_ascii=False).encode(
                    "utf-8",
                    errors="replace",
                )
            )
            if output_size <= _TOOL_RESULT_MAX_BYTES:
                continue

            tool_name = block.get("name", "unknown")
            block["output"] = _truncate_tool_result_output(
                output,
                _TOOL_RESULT_MAX_BYTES,
                tool_name,
            )
            truncated_count += 1

    if truncated_count > 0:
        logger.info(
            "Session guard: truncated %d oversized tool_result(s) before save",
            truncated_count,
        )

    return state_dicts


def sanitize_filename(name: str) -> str:
    """Replace characters that are illegal in Windows filenames with ``--``.

    >>> sanitize_filename('discord:dm:12345')
    'discord--dm--12345'
    >>> sanitize_filename('normal-name')
    'normal-name'
    """
    return _UNSAFE_FILENAME_RE.sub("--", name)


class SafeJSONSession(SessionBase):
    """SessionBase subclass with filename sanitization and async file I/O.

    Overrides all file-reading/writing methods to use :mod:`aiofiles` so
    that disk I/O does not block the event loop.
    """

    def __init__(
        self,
        save_dir: str = "./",
    ) -> None:
        """Initialize the JSON session class.

        Args:
            save_dir (`str`, defaults to `"./"):
                The directory to save the session state.
        """
        self.save_dir = save_dir

    def _get_save_path(self, session_id: str, user_id: str) -> str:
        """Return a filesystem-safe save path.

        Overrides the parent implementation to ensure the generated
        filename is valid on Windows, macOS and Linux.
        """
        os.makedirs(self.save_dir, exist_ok=True)
        safe_sid = sanitize_filename(session_id)
        safe_uid = sanitize_filename(user_id) if user_id else ""
        if safe_uid:
            file_path = f"{safe_uid}_{safe_sid}.json"
        else:
            file_path = f"{safe_sid}.json"
        return os.path.join(self.save_dir, file_path)

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        **state_modules_mapping,
    ) -> None:
        """Save state modules to a JSON file using async I/O.

        Automatically truncates oversized tool_result outputs before
        persisting to prevent session file bloat and infinite
        compression loops.
        """
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }

        # Truncate oversized tool_results before writing to disk
        state_dicts = _compact_tool_results_in_state(state_dicts)

        session_save_path = self._get_save_path(session_id, user_id=user_id)
        with open(
            session_save_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(state_dicts, ensure_ascii=False))

        logger.info(
            "Saved session state to %s successfully.",
            session_save_path,
        )

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load state modules from a JSON file using async I/O."""
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as f:
                content = await f.read()
                states = json.loads(content)

            for name, state_module in state_modules_mapping.items():
                if name in states:
                    state_module.load_state_dict(states[name])
            logger.info(
                "Load session state from %s successfully.",
                session_save_path,
            )

        elif allow_not_exist:
            logger.info(
                "Session file %s does not exist. Skip loading session state.",
                session_save_path,
            )

        else:
            raise AgentStateError(
                session_id=session_id,
                message=(
                    f"Failed to load session state for file "
                    f"{session_save_path} because it does not exist"
                ),
            )

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        session_save_path = self._get_save_path(session_id, user_id=user_id)

        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as f:
                content = await f.read()
                states = json.loads(content)

        else:
            if not create_if_not_exist:
                raise AgentStateError(
                    session_id=session_id,
                    message=f"Session file {session_save_path} does not exist",
                )
            states = {}

        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                message="key path is empty",
            )

        cur = states
        for k in path[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]

        cur[path[-1]] = value

        with open(
            session_save_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(states, ensure_ascii=False))

        logger.info(
            "Updated session state key '%s' in %s successfully.",
            key,
            session_save_path,
        )

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Return the session state dict from the JSON file.

        Args:
            session_id (`str`):
                The session id.
            user_id (`str`, default to `""`):
                The user ID for the storage.
            allow_not_exist (`bool`, defaults to `True`):
                Whether to allow the session to not exist. If `False`, raises
                an error if the session does not exist.

        Returns:
            `dict`:
                The session state dict loaded from the JSON file. Returns an
                empty dict if the file does not exist and
                `allow_not_exist=True`.
        """
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as file:
                content = await file.read()
                states = json.loads(content)

            logger.info(
                "Get session state dict from %s successfully.",
                session_save_path,
            )
            return states

        if allow_not_exist:
            logger.info(
                "Session file %s does not exist. Return empty state dict.",
                session_save_path,
            )
            return {}

        raise AgentStateError(
            session_id=session_id,
            message=(
                f"Failed to get session state for file {session_save_path} "
                f"because it does not exist"
            ),
        )
