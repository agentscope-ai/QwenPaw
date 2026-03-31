# -*- coding: utf-8 -*-
"""Factory for creating chat models and formatters.

This module provides a unified factory for creating chat model instances
and their corresponding formatters based on configuration.

Example:
    >>> from copaw.agents.model_factory import create_model_and_formatter
    >>> model, formatter = create_model_and_formatter()
"""


import base64
import logging
import os
from typing import List, Sequence, Tuple, Type, Any, Union, Optional
from urllib.parse import urlparse

import agentscope._utils._common as agentscope_common
from agentscope.formatter import FormatterBase, OpenAIChatFormatter
from agentscope.model import ChatModelBase, OpenAIChatModel

try:
    from agentscope.formatter import AnthropicChatFormatter
    from agentscope.model import AnthropicChatModel
except ImportError:  # pragma: no cover - compatibility fallback
    AnthropicChatFormatter = None
    AnthropicChatModel = None

try:
    from agentscope.formatter import GeminiChatFormatter
    from agentscope.model import GeminiChatModel
except ImportError:  # pragma: no cover - compatibility fallback
    GeminiChatFormatter = None
    GeminiChatModel = None

from .utils.tool_message_utils import _sanitize_tool_messages
from ..providers import ProviderManager
from ..providers.retry_chat_model import (
    RetryChatModel,
    RetryConfig,
    RateLimitConfig,
)
from ..token_usage import TokenRecordingModelWrapper


def _file_url_to_path(url: str) -> str:
    """
    Strip file:// to path. On Windows file:///C:/path -> C:/path not /C:/path.
    """
    s = url.removeprefix("file://")
    # Windows: file:///C:/path yields "/C:/path"; remove leading slash.
    if len(s) >= 3 and s.startswith("/") and s[1].isalpha() and s[2] == ":":
        s = s[1:]
    return s


# ----------------------------------------------------------------------
# Monkeypatch AgentScope's URL fetcher to support local paths.
# This fixes cases where absolute Windows paths (e.g. D:\...) are
# treated as web URLs and passed to requests.get(), causing crashes.
# ----------------------------------------------------------------------

_original_get_bytes_from_web_url = agentscope_common._get_bytes_from_web_url

# A tiny 1x1 transparent PNG to use as a fallback instead of crashing
_TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _patched_get_bytes_from_web_url(url: str, max_retries: int = 3) -> str:
    """A patched version that handles local paths before falling back to requests."""
    # 1. Handle explicit file:// URLs
    if url.startswith("file://"):
        path = _file_url_to_path(url)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        logger.warning(f"Local file not found (from file://): {path}")
        return _TINY_PNG

    # 2. Handle absolute local paths (e.g. Windows D:\...)
    # Check if it's a real file on disk.
    if os.path.isfile(url):
        with open(url, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    # 3. If it looks like a local path but file is missing, avoid requests.get
    # because it will crash with 'No connection adapters found' for drive letters.
    is_likely_local = (
        ":" in url
        and not url.lower().startswith(
            ("http://", "https://", "ftp://", "data:"),
        )
    ) or (not url.lower().startswith("http") and url.startswith(("/", "\\")))

    if is_likely_local:
        logger.warning(f"Local file not found or invalid URL: {url}")
        return _TINY_PNG

    # 4. Fall back to original for real web URLs
    return _original_get_bytes_from_web_url(url, max_retries)


agentscope_common._get_bytes_from_web_url = _patched_get_bytes_from_web_url

# Also patch the formatters if they were already imported to ensure they use
# the patched version even if they did 'from .._utils._common import ...'
if GeminiChatFormatter is not None:
    try:
        import agentscope.formatter._gemini_formatter as gemini_fmt
        gemini_fmt._get_bytes_from_web_url = _patched_get_bytes_from_web_url
    except ImportError:
        pass

if AnthropicChatFormatter is not None:
    try:
        import agentscope.formatter._anthropic_formatter as anthropic_fmt
        anthropic_fmt._get_bytes_from_web_url = _patched_get_bytes_from_web_url
    except ImportError:
        pass


logger = logging.getLogger(__name__)


# TODO: remove after agentscope anthropic formatter updated
def _format_anthropic_image_block(image_block: dict) -> dict:
    """Format an image block for Anthropic API. If the source is a
    URLSource pointing to a local file, it will be converted to base64
    format.

    Args:
        image_block (`dict`):
            The image block to format.

    Returns:
        `dict`:
            A dictionary in Anthropic image block format.

    Raises:
        `ValueError`:
            If the source type or image format is not supported.
    """
    support_image_extensions = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    source = image_block["source"]

    if source["type"] == "base64":
        return {**image_block}

    url = source["url"]
    raw_url = _file_url_to_path(url)

    if os.path.exists(raw_url) and os.path.isfile(raw_url):
        ext = os.path.splitext(raw_url)[1].lower()
        media_type = support_image_extensions.get(ext)
        if media_type:
            with open(raw_url, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
                },
            }

    parsed_url = urlparse(raw_url)
    if parsed_url.scheme not in ("", "file"):
        return {
            "type": "image",
            "source": {
                "type": "url",
                "url": url,
            },
        }

    raise ValueError(
        f'Invalid image URL: "{url}". '
        "It should be a local file or a web URL.",
    )


# TODO: remove after agentscope anthropic formatter updated
def _format_anthropic_messages(  # pylint: disable=too-many-branches
    msgs: list,
) -> list[dict]:
    """Format messages for Anthropic API with image block support.

    This replaces the default ``AnthropicChatFormatter._format`` so that
    ``_format_anthropic_image_block`` is applied to both top-level image
    blocks and image blocks nested inside ``tool_result`` outputs.
    """
    messages: list[dict] = []
    for index, msg in enumerate(msgs):
        content_blocks: list[dict] = []

        for block in msg.get_content_blocks():
            typ = block.get("type")
            if typ in ["thinking", "text"]:
                content_blocks.append({**block})

            elif typ == "image":
                content_blocks.append(
                    _format_anthropic_image_block(block),
                )

            elif typ == "tool_use":
                content_blocks.append(
                    {
                        "id": block.get("id"),
                        "type": "tool_use",
                        "name": block.get("name"),
                        "input": block.get("input", {}),
                    },
                )

            elif typ == "tool_result":
                output = block.get("output")
                if output is None:
                    content_value: list = [
                        {"type": "text", "text": None},
                    ]
                elif isinstance(output, list):
                    content_value = [
                        _format_anthropic_image_block(item)
                        if item.get("type") == "image"
                        else item
                        for item in output
                    ]
                else:
                    content_value = [
                        {"type": "text", "text": str(output)},
                    ]
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.get("id"),
                                "content": content_value,
                            },
                        ],
                    },
                )

        if msg.role == "system" and index != 0:
            role = "user"
        else:
            role = msg.role

        msg_anthropic: dict = {
            "role": role,
            "content": content_blocks or None,
        }

        if msg_anthropic["content"] or msg_anthropic.get(
            "tool_calls",
        ):
            messages.append(msg_anthropic)

    return messages


# Mapping from chat model class to formatter class
_CHAT_MODEL_FORMATTER_MAP: dict[Type[ChatModelBase], Type[FormatterBase]] = {
    OpenAIChatModel: OpenAIChatFormatter,
}
if AnthropicChatModel is not None and AnthropicChatFormatter is not None:
    _CHAT_MODEL_FORMATTER_MAP[AnthropicChatModel] = AnthropicChatFormatter
if GeminiChatModel is not None and GeminiChatFormatter is not None:
    _CHAT_MODEL_FORMATTER_MAP[GeminiChatModel] = GeminiChatFormatter


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


# pylint: disable-next=too-many-statements
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
            # 1. Sanitize tool messages
            msgs = _sanitize_tool_messages(msgs)

            # 2. Extract reasoning and extra content
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
                        # 3. Handle media blocks with local file references
            # Convert file:// URLs to paths and prevent crashes from missing files
            for msg in msgs:
                if not isinstance(msg.content, list):
                    continue
                new_content = []
                for block in msg.content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") in ("audio", "image", "video")
                    ):
                        source = block.get("source")
                        if (
                            isinstance(source, dict)
                            and source.get("type") == "url"
                            and isinstance(source.get("url"), str)
                        ):
                            url = source["url"]
                            if url.startswith("file://"):
                                url = _file_url_to_path(url)
                                source["url"] = url

                            # Check if it's a local path (Windows drive letter
                            # or no scheme)
                            is_local = (
                                ":" in url
                                and not url.lower().startswith(
                                    ("http://", "https://", "ftp://", "data:"),
                                )
                            ) or (
                                not url.lower().startswith(
                                    ("http://", "https://", "ftp://", "data:"),
                                )
                                and url.startswith("/")
                            )

                            if is_local and not os.path.exists(url):
                                logger.warning(
                                    f"Media file not found: {url}. "
                                    "Replacing with placeholder to "
                                    "avoid crash.",
                                )
                                new_content.append(
                                    {
                                        "type": "text",
                                        "text": f"[Media file not found: {url}]",
                                    },
                                )
                                continue
                    new_content.append(block)
                msg.content = new_content

            # 4. Delegate to base formatter or override for Anthropic
            # TODO: remove after agentscope anthropic formatter updated
            if AnthropicChatFormatter is not None and issubclass(
                base_formatter_class,
                AnthropicChatFormatter,
            ):
                messages = _format_anthropic_messages(msgs)
            else:
                messages = await super()._format(msgs)
            if extra_contents:
                for message in messages:
                    for tc in message.get("tool_calls", []):
                        ec = extra_contents.get(tc.get("id"))
                        if ec:
                            tc["extra_content"] = ec

            if reasoning_contents:
                # Build a list of reasoning values aligned with surviving
                # assistant messages.  The parent formatter drops
                # thinking-only messages (no content/tool_calls), so we
                # predict survivors and collect reasoning only for those.
                aligned_reasoning = []
                for m in (msg for msg in msgs if msg.role == "assistant"):
                    is_thinking_only = (
                        isinstance(m.content, list)
                        and m.content
                        and all(b.get("type") == "thinking" for b in m.content)
                    )
                    if not is_thinking_only:
                        aligned_reasoning.append(
                            reasoning_contents.get(id(m)),
                        )

                out_assistant = [
                    m for m in messages if m.get("role") == "assistant"
                ]

                if len(aligned_reasoning) != len(out_assistant):
                    logger.warning(
                        "Assistant message count mismatch after formatting "
                        "(%d expected survivors, %d actual). "
                        "Skipping reasoning_content injection.",
                        len(aligned_reasoning),
                        len(out_assistant),
                    )
                else:
                    for i, out_msg in enumerate(out_assistant):
                        if aligned_reasoning[i]:
                            out_msg["reasoning_content"] = aligned_reasoning[i]

            return _strip_top_level_message_name(messages)

        @staticmethod
        def convert_tool_result_to_string(
            output: Union[str, List[dict]],
        ) -> tuple[str, Sequence[Tuple[str, dict]]]:
            """Extend parent class to support file blocks and filter missing local files."""
            if isinstance(output, str):
                return output, []

            # Pre-filter: if any media block points to a missing local file,
            # we should skip it or convert it to text to prevent downstream
            # promotion logic from crashing.
            filtered_output = []
            for block in output:
                if isinstance(block, dict):
                    media_path = (
                        block.get("path")
                        or block.get("url")
                        or (
                            block.get("source", {}).get("url")
                            if isinstance(block.get("source"), dict)
                            else None
                        )
                    )
                    if isinstance(media_path, str):
                        # Detect local but missing file
                        path = (
                            _file_url_to_path(media_path)
                            if media_path.startswith("file://")
                            else media_path
                        )
                        is_local = (
                            ":" in path
                            and not path.lower().startswith(
                                ("http://", "https://", "ftp://", "data:"),
                            )
                        ) or (
                            not path.lower().startswith("http")
                            and path.startswith(("/", "\\"))
                        )

                        if is_local and not os.path.exists(path):
                            logger.warning(
                                f"Skipping missing tool result file: {path}",
                            )
                            # Convert to text representation instead of media block
                            filtered_output.append(
                                {
                                    "type": "text",
                                    "text": f"[Missing file: {path}]",
                                },
                            )
                            continue
                filtered_output.append(block)

            output = filtered_output

            # Try parent class method
            try:
                return base_formatter_class.convert_tool_result_to_string(
                    output,
                )
            except ValueError as e:
                # Same custom logic for 'file' type as before...
                if "Unsupported block type: file" not in str(e):
                    raise

                textual_output = []
                multimodal_data = []

                for block in output:
                    if not isinstance(block, dict) or "type" not in block:
                        continue

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
                        try:
                            (
                                text,
                                data,
                            ) = base_formatter_class.convert_tool_result_to_string(
                                [block],
                            )
                            textual_output.append(text)
                            multimodal_data.extend(data)
                        except Exception as e:
                            logger.warning(f"Error converting tool result block, skipping. Block: {block}, Error: {e}")

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


def create_model_and_formatter(
    agent_id: Optional[str] = None,
) -> Tuple[ChatModelBase, FormatterBase]:
    """Factory method to create model and formatter instances.

    This method handles both local and remote models, selecting the
    appropriate chat model class and formatter based on configuration.

    Args:
        agent_id: Optional agent ID to load agent-specific model config.
            If None, tries to get from context, then falls back to global.

    Returns:
        Tuple of (model_instance, formatter_instance)

    Example:
        >>> model, formatter = create_model_and_formatter()
    """
    from ..app.agent_context import get_current_agent_id
    from ..config.config import load_agent_config

    # Determine agent_id (parameter > context > None)
    if agent_id is None:
        try:
            agent_id = get_current_agent_id()
        except Exception:
            pass

    # Try to get agent-specific model first
    model_slot = None
    retry_config = None
    rate_limit_config = None
    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            model_slot = agent_config.active_model
            retry_config = RetryConfig(
                enabled=agent_config.running.llm_retry_enabled,
                max_retries=agent_config.running.llm_max_retries,
                backoff_base=agent_config.running.llm_backoff_base,
                backoff_cap=agent_config.running.llm_backoff_cap,
            )
            rate_limit_config = RateLimitConfig(
                max_concurrent=agent_config.running.llm_max_concurrent,
                max_qpm=agent_config.running.llm_max_qpm,
                pause_seconds=agent_config.running.llm_rate_limit_pause,
                jitter_range=agent_config.running.llm_rate_limit_jitter,
                acquire_timeout=agent_config.running.llm_acquire_timeout,
            )
        except Exception:
            pass

    # Create chat model from agent-specific or global config
    if model_slot and model_slot.provider_id and model_slot.model:
        # Use agent-specific model
        manager = ProviderManager.get_instance()
        provider = manager.get_provider(model_slot.provider_id)
        if provider is None:
            raise ValueError(
                f"Provider '{model_slot.provider_id}' not found.",
            )

        model = provider.get_chat_model_instance(model_slot.model)
        provider_id = model_slot.provider_id
    else:
        # Fallback to global active model
        model = ProviderManager.get_active_chat_model()
        global_model = ProviderManager.get_instance().get_active_model()
        if not global_model:
            raise ValueError(
                "No active model configured. "
                "Please configure a model using 'copaw models config' "
                "or set an agent-specific model.",
            )
        provider_id = global_model.provider_id

    # Create the formatter based on the real model class
    formatter = _create_formatter_instance(model.__class__)

    # Wrap with retry logic for transient LLM API errors
    wrapped_model = TokenRecordingModelWrapper(provider_id, model)
    wrapped_model = RetryChatModel(
        wrapped_model,
        retry_config=retry_config,
        rate_limit_config=rate_limit_config,
    )

    return wrapped_model, formatter


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
    kwargs: dict[str, Any] = {}
    if issubclass(
        base_formatter_class,
        (OpenAIChatFormatter, GeminiChatFormatter),
    ):
        kwargs["promote_tool_result_images"] = True
    return formatter_class(**kwargs)


__all__ = [
    "create_model_and_formatter",
]
