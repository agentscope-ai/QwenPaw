# -*- coding: utf-8 -*-
"""Factory for creating chat models and formatters.

This module provides a unified factory for creating chat model instances
and their corresponding formatters based on configuration.

Example:
    >>> from copaw.agents.model_factory import create_model_and_formatter
    >>> model, formatter = create_model_and_formatter()
"""

import logging
import re
from copy import deepcopy
from typing import Sequence, Tuple, Type, Any
from functools import wraps

from agentscope.formatter import FormatterBase, OpenAIChatFormatter
from agentscope.model import ChatModelBase, OpenAIChatModel
from agentscope.message import Msg
import agentscope

try:
    from agentscope.formatter import AnthropicChatFormatter
    from agentscope.model import AnthropicChatModel
except ImportError:  # pragma: no cover - compatibility fallback
    AnthropicChatFormatter = None
    AnthropicChatModel = None

from .utils.tool_message_utils import _sanitize_tool_messages
from ..providers import ProviderManager


def _file_url_to_path(url: str) -> str:
    """
    Strip file:// to path. On Windows file:///C:/path -> C:/path not /C:/path.
    """
    s = url.removeprefix("file://")
    # Windows: file:///C:/path yields "/C:/path"; remove leading slash.
    if len(s) >= 3 and s.startswith("/") and s[1].isalpha() and s[2] == ":":
        s = s[1:]
    return s


def _monkey_patch(func):
    """A monkey patch wrapper for agentscope <= 1.0.16dev"""

    @wraps(func)
    async def wrapper(
        self,
        msgs: list[Msg],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        for msg in msgs:
            if isinstance(msg.content, str):
                continue
            if isinstance(msg.content, list):
                for block in msg.content:
                    if (
                        block["type"] in ["audio", "image", "video"]
                        and block.get("source", {}).get("type") == "url"
                    ):
                        url = block["source"]["url"]
                        if url.startswith("file://"):
                            block["source"]["url"] = _file_url_to_path(url)
        return await func(self, msgs, **kwargs)

    return wrapper


if agentscope.__version__ in ["1.0.16dev", "1.0.16"]:
    OpenAIChatFormatter.format = _monkey_patch(OpenAIChatFormatter.format)


logger = logging.getLogger(__name__)


# Mapping from chat model class to formatter class
_CHAT_MODEL_FORMATTER_MAP: dict[Type[ChatModelBase], Type[FormatterBase]] = {
    OpenAIChatModel: OpenAIChatFormatter,
}
if AnthropicChatModel is not None and AnthropicChatFormatter is not None:
    _CHAT_MODEL_FORMATTER_MAP[AnthropicChatModel] = AnthropicChatFormatter


def _get_formatter_for_chat_model(
    chat_model_class: Type[ChatModelBase],
) -> Type[FormatterBase]:
    """Get the appropriate formatter class for a chat model.

    Args:
        chat_model_class: The chat model class

    Returns:
        Corresponding formatter class, defaults to OpenAIChatFormatter
    """
    return _CHAT_MODEL_FORMATTER_MAP.get(
        chat_model_class,
        OpenAIChatFormatter,
    )


def _create_file_block_support_formatter(
    base_formatter_class: Type[FormatterBase],
) -> Type[FormatterBase]:
    """Create a formatter class with file block support.

    This factory function extends any Formatter class to support file blocks
    in tool results, which are not natively supported by AgentScope.

    Args:
        base_formatter_class: Base formatter class to extend

    Returns:
        Enhanced formatter class with file block support
    """

    class FileBlockSupportFormatter(base_formatter_class):
        """Formatter with file block support for tool results."""

        # pylint: disable=too-many-branches
        async def _format(self, msgs):
            """Override to sanitize tool messages, handle thinking blocks,
            and relay ``extra_content`` (Gemini thought_signature).

            This prevents OpenAI API errors from improperly paired
            tool messages, preserves reasoning_content from "thinking"
            blocks that the base formatter skips, and ensures
            ``extra_content`` on tool_use blocks (e.g. Gemini
            thought_signature) is carried through to the API request.
            """
            msgs = _normalize_messages_for_model(msgs)
            msgs = _sanitize_tool_messages(msgs)

            reasoning_contents = {}
            extra_contents: dict[str, Any] = {}
            for msg in msgs:
                if msg.role != "assistant":
                    continue
                for block in msg.get_content_blocks():
                    if block.get("type") == "thinking":
                        thinking = block.get("thinking", "")
                        if thinking:
                            reasoning_contents[id(msg)] = thinking
                        break
                for block in msg.get_content_blocks():
                    if (
                        block.get("type") == "tool_use"
                        and "extra_content" in block
                    ):
                        extra_contents[block["id"]] = block["extra_content"]

            messages = await super()._format(msgs)

            if extra_contents:
                for message in messages:
                    for tc in message.get("tool_calls", []):
                        ec = extra_contents.get(tc.get("id"))
                        if ec:
                            tc["extra_content"] = ec

            if reasoning_contents:
                in_assistant = [m for m in msgs if m.role == "assistant"]
                out_assistant = [
                    m for m in messages if m.get("role") == "assistant"
                ]
                if len(in_assistant) != len(out_assistant):
                    logger.warning(
                        "Assistant message count mismatch after formatting "
                        "(%d before, %d after). "
                        "Skipping reasoning_content injection.",
                        len(in_assistant),
                        len(out_assistant),
                    )
                else:
                    for in_msg, out_msg in zip(
                        in_assistant,
                        out_assistant,
                    ):
                        reasoning = reasoning_contents.get(id(in_msg))
                        if reasoning:
                            out_msg["reasoning_content"] = reasoning

            return _strip_top_level_message_name(messages)

        @staticmethod
        def convert_tool_result_to_string(
            output: str | list[dict],
        ) -> tuple[str, Sequence[Tuple[str, dict]]]:
            """Extend parent class to support file blocks.

            Uses try-first strategy for compatibility with parent class.

            Args:
                output: Tool result output (string or list of blocks)

            Returns:
                Tuple of (text_representation, multimodal_data)
            """
            if isinstance(output, str):
                return output, []

            # Try parent class method first
            try:
                return base_formatter_class.convert_tool_result_to_string(
                    output,
                )
            except ValueError as e:
                if "Unsupported block type: file" not in str(e):
                    raise

                # Handle output containing file blocks
                textual_output = []
                multimodal_data = []

                for block in output:
                    if not isinstance(block, dict) or "type" not in block:
                        raise ValueError(
                            "Invalid block for tool result conversion; "
                            "expected dict with 'type' key",
                        ) from e

                    if block["type"] == "file":
                        file_path = block.get("path", "") or block.get(
                            "url",
                            "",
                        )
                        file_name = block.get("name", file_path)

                        textual_output.append(
                            f"The returned file '{file_name}' "
                            f"can be found at: {file_path}",
                        )
                        multimodal_data.append((file_path, block))
                    else:
                        # Delegate other block types to parent class
                        (
                            text,
                            data,
                        ) = base_formatter_class.convert_tool_result_to_string(
                            [block],
                        )
                        textual_output.append(text)
                        multimodal_data.extend(data)

                if len(textual_output) == 0:
                    return "", multimodal_data
                elif len(textual_output) == 1:
                    return textual_output[0], multimodal_data
                else:
                    return (
                        "\n".join("- " + _ for _ in textual_output),
                        multimodal_data,
                    )

    FileBlockSupportFormatter.__name__ = (
        f"FileBlockSupport{base_formatter_class.__name__}"
    )
    return FileBlockSupportFormatter


def _strip_top_level_message_name(
    messages: list[dict],
) -> list[dict]:
    """Strip top-level `name` from OpenAI chat messages.

    Some strict OpenAI-compatible backends reject `messages[*].name`
    (especially for assistant/tool roles) and may return 500/400 on
    follow-up turns. Keep function/tool names unchanged.
    """
    for message in messages:
        message.pop("name", None)
    return messages


_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE_REL_RE = re.compile(r"^[A-Za-z]:[^\\/]")


def _extract_local_path_from_url(url: Any) -> str | None:
    """Return a local filesystem path if url points to local file."""
    if not isinstance(url, str) or not url:
        return None

    url = url.strip()
    lowered = url.lower()

    local_path: str | None = None

    if lowered.startswith("file://"):
        local_path = _file_url_to_path(url)
    elif lowered.startswith(("http://", "https://", "data:")):
        local_path = None
    elif _WINDOWS_ABS_PATH_RE.match(url):
        local_path = url
    elif _WINDOWS_DRIVE_REL_RE.match(url):
        local_path = url
    elif url.startswith(("/", "\\")):
        local_path = url
    elif url.startswith(("./", "../", ".\\", "..\\", "~/")):
        local_path = url
    elif "://" in url:
        local_path = None
    else:
        # Non-URL fallback: treat remaining values as local paths.
        local_path = url

    return local_path


def _sanitize_local_media_block(block: dict) -> tuple[dict, bool]:
    """Replace local media/file blocks with safe text placeholders."""
    block_type = block.get("type")
    if block_type not in {"image", "audio", "video", "file"}:
        return block, False

    source = block.get("source")
    local_path = _extract_local_path_from_url(
        block.get("path") or block.get("url"),
    )
    if not local_path and isinstance(source, dict):
        local_path = _extract_local_path_from_url(
            source.get("url") or source.get("path"),
        )
    elif not local_path and isinstance(source, str):
        local_path = _extract_local_path_from_url(source)
    if not local_path:
        return block, False

    if block_type == "file":
        text = "[Local file omitted for model call]"
    else:
        text = "[Local media omitted for model call]"
    return {"type": "text", "text": text}, True


def _sanitize_local_media_in_value(value: Any) -> tuple[Any, bool]:
    """Recursively sanitize local media blocks in nested structures."""
    if isinstance(value, list):
        new_list = []
        changed = False
        for item in value:
            new_item, item_changed = _sanitize_local_media_in_value(item)
            new_list.append(new_item)
            changed = changed or item_changed
        return new_list, changed

    if isinstance(value, dict):
        replaced_block, replaced = _sanitize_local_media_block(value)
        if replaced:
            return replaced_block, True

        new_dict = {}
        changed = False
        for key, item in value.items():
            if key == "output" and isinstance(item, list):
                output_list = []
                output_changed = False
                for output_item in item:
                    if isinstance(output_item, dict):
                        (
                            new_item,
                            item_changed,
                        ) = _sanitize_local_media_in_value(
                            output_item,
                        )
                        output_list.append(new_item)
                        output_changed = output_changed or item_changed
                    else:
                        output_list.append(
                            {"type": "text", "text": str(output_item)},
                        )
                        output_changed = True
                new_dict[key] = output_list
                changed = changed or output_changed
                continue

            if isinstance(item, (list, dict)):
                new_item, item_changed = _sanitize_local_media_in_value(item)
                new_dict[key] = new_item
                changed = changed or item_changed
            else:
                new_dict[key] = item
        return (new_dict, True) if changed else (value, False)

    return value, False


_LOCAL_PATH_TEXT_RE = re.compile(
    r"(?i)(file://\S+|(?:[A-Za-z]:[\\/]|/|\./|\.\./|~/)\S+)",
)


def _sanitize_local_paths_in_text(text: str) -> str:
    """Redact local path tokens from free-form text."""
    return _LOCAL_PATH_TEXT_RE.sub("[LOCAL_PATH]", text)


def _normalize_messages_for_model(msgs: list[Msg]) -> list[Msg]:
    """Normalize messages before formatting for model APIs."""
    normalized: list[Msg] = []

    for msg in msgs:
        new_content = None
        content = msg.content

        if isinstance(content, str):
            sanitized = _sanitize_local_paths_in_text(content)
            new_content = [{"type": "text", "text": sanitized}]
        elif not isinstance(content, list):
            new_content = [{"type": "text", "text": str(content)}]
        else:
            fixed_blocks: list[dict] = []
            changed = False
            for block in content:
                if not isinstance(block, dict):
                    fixed_blocks.append({"type": "text", "text": str(block)})
                    changed = True
                    continue

                sanitized_block, replaced = _sanitize_local_media_in_value(
                    block,
                )
                if replaced:
                    block = sanitized_block
                    changed = True

                block_type = (
                    block.get("type") if isinstance(block, dict) else None
                )

                if not isinstance(block_type, str):
                    fixed_blocks.append({"type": "text", "text": str(block)})
                    changed = True
                    continue

                fixed_blocks.append(block)

            if changed:
                new_content = fixed_blocks

        if new_content is None:
            normalized.append(msg)
        else:
            msg_copy = deepcopy(msg)
            msg_copy.content = new_content
            normalized.append(msg_copy)

    return normalized


def create_model_and_formatter() -> Tuple[ChatModelBase, FormatterBase]:
    """Factory method to create model and formatter instances.

    This method handles both local and remote models, selecting the
    appropriate chat model class and formatter based on configuration.

    Args:
        llm_cfg: Resolved model configuration. If None, will call
            get_active_llm_config() to fetch the active configuration.

    Returns:
        Tuple of (model_instance, formatter_instance)

    Example:
        >>> model, formatter = create_model_and_formatter()
    """
    # Fetch config if not provided
    model = ProviderManager.get_active_chat_model()

    # Create the formatter based on chat_model_class
    formatter = _create_formatter_instance(model.__class__)

    return model, formatter


def _create_formatter_instance(
    chat_model_class: Type[ChatModelBase],
) -> FormatterBase:
    """Create a formatter instance for the given chat model class.

    The formatter is enhanced with file block support for handling
    file outputs in tool results.

    Args:
        chat_model_class: The chat model class

    Returns:
        Formatter instance with file block support
    """
    base_formatter_class = _get_formatter_for_chat_model(chat_model_class)
    formatter_class = _create_file_block_support_formatter(
        base_formatter_class,
    )
    return formatter_class()


__all__ = [
    "create_model_and_formatter",
]
