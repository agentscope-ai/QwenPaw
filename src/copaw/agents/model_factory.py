# -*- coding: utf-8 -*-
"""Factory for creating chat models and formatters."""

import logging
from typing import Any, List, Optional, Sequence, Tuple, Type, Union

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
from ..local_models import create_local_chat_model
from ..providers import ProviderManager
from ..providers.models import ModelSlotConfig
from ..providers.retry_chat_model import RetryChatModel
from ..token_usage import TokenRecordingModelWrapper

logger = logging.getLogger(__name__)


def _file_url_to_path(url: str) -> str:
    """
    Strip file:// to path. On Windows file:///C:/path -> C:/path not /C:/path.
    """
    s = url.removeprefix("file://")
    if len(s) >= 3 and s.startswith("/") and s[1].isalpha() and s[2] == ":":
        s = s[1:]
    return s


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
    return _CHAT_MODEL_FORMATTER_MAP.get(
        chat_model_class,
        OpenAIChatFormatter,
    )


# pylint: disable-next=too-many-statements
def _create_file_block_support_formatter(
    base_formatter_class: Type[FormatterBase],
) -> Type[FormatterBase]:
    """Create a formatter class with file block support."""

    class FileBlockSupportFormatter(base_formatter_class):
        """Formatter with file block support for tool results."""

        # pylint: disable=too-many-branches,too-many-statements
        async def _format(self, msgs):
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

            for msg in msgs:
                for block in msg.get_content_blocks():
                    if block.get("type") == "audio":
                        source = block.get("source")
                        if (
                            isinstance(source, dict)
                            and source.get("type") == "url"
                            and isinstance(source.get("url"), str)
                            and source["url"].startswith("file://")
                        ):
                            source["url"] = _file_url_to_path(source["url"])

            messages = await super()._format(msgs)

            if extra_contents:
                for message in messages:
                    for tc in message.get("tool_calls", []):
                        ec = extra_contents.get(tc.get("id"))
                        if ec:
                            tc["extra_content"] = ec

            if reasoning_contents:
                aligned_reasoning = []
                for msg in (m for m in msgs if m.role == "assistant"):
                    is_thinking_only = (
                        isinstance(msg.content, list)
                        and msg.content
                        and all(
                            block.get("type") == "thinking"
                            for block in msg.content
                        )
                    )
                    if not is_thinking_only:
                        aligned_reasoning.append(
                            reasoning_contents.get(id(msg)),
                        )

                out_assistant = [
                    message
                    for message in messages
                    if message.get("role") == "assistant"
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
                    for index, out_msg in enumerate(out_assistant):
                        if aligned_reasoning[index]:
                            out_msg["reasoning_content"] = aligned_reasoning[
                                index
                            ]

            return _strip_top_level_message_name(messages)

        @staticmethod
        def convert_tool_result_to_string(
            output: Union[str, List[dict]],
        ) -> tuple[str, Sequence[Tuple[str, dict]]]:
            if isinstance(output, str):
                return output, []

            try:
                return base_formatter_class.convert_tool_result_to_string(
                    output,
                )
            except ValueError as e:
                if "Unsupported block type: file" not in str(e):
                    raise

                textual_output = []
                multimodal_data = []

                for block in output:
                    if not isinstance(block, dict) or "type" not in block:
                        raise ValueError(
                            f"Invalid block: {block}, "
                            "expected a dict with 'type' key",
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
                if len(textual_output) == 1:
                    return textual_output[0], multimodal_data
                return (
                    "\n".join("- " + item for item in textual_output),
                    multimodal_data,
                )

    FileBlockSupportFormatter.__name__ = (
        f"FileBlockSupport{base_formatter_class.__name__}"
    )
    return FileBlockSupportFormatter


def _strip_top_level_message_name(messages: list[dict]) -> list[dict]:
    for message in messages:
        message.pop("name", None)
    return messages


def _has_configured_slot(slot: ModelSlotConfig | None) -> bool:
    return bool(slot and slot.provider_id and slot.model)


def _get_chat_model_class_for_provider(
    provider_id: str,
    *,
    manager: ProviderManager,
) -> Type[ChatModelBase]:
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"Provider '{provider_id}' not found.")
    if provider.is_local:
        return OpenAIChatModel
    return provider.get_chat_model_cls()


def _create_model_instance_for_provider(
    model_slot: ModelSlotConfig,
    *,
    manager: ProviderManager,
) -> Tuple[ChatModelBase, Type[ChatModelBase]]:
    provider = manager.get_provider(model_slot.provider_id)
    if provider is None:
        raise ValueError(f"Provider '{model_slot.provider_id}' not found.")

    if provider.is_local:
        model = create_local_chat_model(
            model_id=model_slot.model,
            stream=True,
            generate_kwargs={"max_tokens": None},
        )
        return model, OpenAIChatModel

    return (
        provider.get_chat_model_instance(
            model_slot.model,
        ),
        provider.get_chat_model_cls(),
    )


def _create_routing_endpoint(
    model_slot: ModelSlotConfig,
    *,
    manager: ProviderManager,
):
    from .routing_chat_model import RoutingEndpoint

    provider_id = model_slot.provider_id
    chat_model_class = _get_chat_model_class_for_provider(
        provider_id,
        manager=manager,
    )

    def _load_endpoint() -> tuple[ChatModelBase, FormatterBase]:
        model, loaded_chat_model_class = _create_model_instance_for_provider(
            model_slot,
            manager=manager,
        )
        formatter = _create_formatter_instance(loaded_chat_model_class)
        wrapped_model = TokenRecordingModelWrapper(provider_id, model)
        wrapped_model = RetryChatModel(wrapped_model)
        return wrapped_model, formatter

    return RoutingEndpoint(
        provider_id=provider_id,
        model_name=model_slot.model,
        formatter_family=_get_formatter_for_chat_model(chat_model_class),
        loader=_load_endpoint,
    )


def _create_routing_model_and_formatter(
    local_slot: ModelSlotConfig,
    cloud_slot: ModelSlotConfig,
    routing_cfg,
    *,
    manager: ProviderManager,
) -> Optional[Tuple[ChatModelBase, FormatterBase]]:
    from .routing_chat_model import RoutingChatModel

    try:
        local_endpoint = _create_routing_endpoint(
            local_slot,
            manager=manager,
        )
        cloud_endpoint = _create_routing_endpoint(
            cloud_slot,
            manager=manager,
        )
    except Exception:
        logger.warning(
            "Failed to create routing endpoint(s).",
            exc_info=True,
        )
        return None

    if local_endpoint.formatter_family is not cloud_endpoint.formatter_family:
        return None

    model: ChatModelBase = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=routing_cfg,
    )
    return model, _create_formatter_from_family(
        local_endpoint.formatter_family,
    )


def create_model_and_formatter(
    agent_id: Optional[str] = None,
) -> Tuple[ChatModelBase, FormatterBase]:
    """Factory method to create model and formatter instances."""

    from ..app.agent_context import get_current_agent_id
    from ..config.config import load_agent_config
    from ..config.utils import load_config

    if agent_id is None:
        try:
            agent_id = get_current_agent_id()
        except Exception:
            pass

    manager = ProviderManager.get_instance()
    model_slot = None
    routing_cfg = None

    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            model_slot = agent_config.active_model
            routing_cfg = agent_config.llm_routing
        except Exception:
            pass

    if routing_cfg is None:
        routing_cfg = load_config().agents.llm_routing

    if _has_configured_slot(routing_cfg.local):
        cloud_slot = (
            routing_cfg.cloud
            if _has_configured_slot(routing_cfg.cloud)
            else (
                model_slot
                if _has_configured_slot(model_slot)
                else manager.get_active_model()
            )
        )
        if routing_cfg.enabled and _has_configured_slot(cloud_slot):
            assert cloud_slot is not None
            routed_model = _create_routing_model_and_formatter(
                routing_cfg.local,
                cloud_slot,
                routing_cfg,
                manager=manager,
            )
            if routed_model is not None:
                return routed_model

    if _has_configured_slot(model_slot):
        assert model_slot is not None
        provider_id = model_slot.provider_id
        model, chat_model_class = _create_model_instance_for_provider(
            model_slot,
            manager=manager,
        )
    else:
        model = ProviderManager.get_active_chat_model()
        active_model = manager.get_active_model()
        if active_model is None:
            raise ValueError("No active model configured.")
        provider_id = active_model.provider_id
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Active provider '{provider_id}' not found.")
        chat_model_class = (
            OpenAIChatModel
            if provider.is_local
            else provider.get_chat_model_cls()
        )

    formatter = _create_formatter_instance(chat_model_class)
    wrapped_model = TokenRecordingModelWrapper(provider_id, model)
    wrapped_model = RetryChatModel(wrapped_model)
    return wrapped_model, formatter


def _create_formatter_instance(
    chat_model_class: Type[ChatModelBase],
) -> FormatterBase:
    base_formatter_class = _get_formatter_for_chat_model(chat_model_class)
    return _create_formatter_from_family(base_formatter_class)


def _create_formatter_from_family(
    base_formatter_class: Type[FormatterBase],
) -> FormatterBase:
    formatter_class = _create_file_block_support_formatter(
        base_formatter_class,
    )
    image_promoting_bases: tuple[type, ...] = tuple(
        base
        for base in (OpenAIChatFormatter, GeminiChatFormatter)
        if base is not None
    )
    kwargs: dict[str, Any] = {}
    if image_promoting_bases and issubclass(
        base_formatter_class,
        image_promoting_bases,
    ):
        kwargs["promote_tool_result_images"] = True
    return formatter_class(**kwargs)


__all__ = ["create_model_and_formatter"]
