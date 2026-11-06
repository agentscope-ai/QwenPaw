# -*- coding: utf-8 -*-
"""Internal lossless conversion of SDK values and AgentScope messages."""

from copy import deepcopy

from .messages import Attachment, ContentBlock, Message
from .errors import SDKError

_PREVIEWS = "_sdk_attachment_previews"


def _block_shape(blocks, prefix=""):
    shape = {}
    for index, block in enumerate(blocks):
        path = f"{prefix}{index}"
        shape[path] = block.type
        nested = getattr(block, "output", getattr(block, "hint", ()))
        if not isinstance(nested, str):
            shape.update(_block_shape(nested, path + "."))
    return shape


def _block_key(block):
    return (block.type, getattr(block, "id", ""))


def _merge_refs(target, incoming, field):
    for key, value in incoming.items():
        if key in target and target[key] != value:
            raise SDKError(f"Blocks sharing an ID have conflicting {field}")
        target[key] = value


def _walk_pairs(public_blocks, host_blocks, prefix=""):
    for index, (public, host) in enumerate(zip(public_blocks, host_blocks)):
        path = f"{prefix}{index}"
        yield public, host, path
        if public.type in {"hint", "tool_result"} and not isinstance(
            public.output,
            str,
        ):
            yield from _walk_pairs(
                public.output,
                host.hint if public.type == "hint" else host.output,
                path + ".",
            )


def _metadata_refs(public_blocks, host_blocks):
    refs, seen = {}, {}
    for public, host, path in _walk_pairs(public_blocks, host_blocks):
        if public.type != "tool_result":
            _merge_refs(seen, {_block_key(host): public.metadata}, "metadata")
            if public.metadata:
                refs[path] = deepcopy(public.metadata)
    return refs


def _with_previews(metadata, refs, blocks, block_metadata=None):
    metadata = deepcopy(metadata)
    if refs or block_metadata or _PREVIEWS in metadata:
        envelope = {
            "format": "qwenpaw-attachment-previews/1",
            "refs": refs,
            "shape": _block_shape(blocks),
            "metadata": block_metadata or {},
        }
        if _PREVIEWS in metadata:
            envelope["original"] = metadata[_PREVIEWS]
        metadata[_PREVIEWS] = envelope
    return metadata


def _take_previews(metadata, blocks):
    metadata = deepcopy(metadata or {})
    envelope = metadata.get(_PREVIEWS)
    # Validate the envelope in short-circuit order before indexing fields.
    # pylint: disable=too-many-boolean-expressions
    if (
        not isinstance(envelope, dict)
        or set(envelope)
        not in (
            {"format", "refs", "shape", "metadata"},
            {"format", "refs", "shape", "metadata", "original"},
        )
        or envelope.get("format") != "qwenpaw-attachment-previews/1"
        or not isinstance(envelope.get("refs"), dict)
        or not isinstance(envelope.get("metadata"), dict)
        or not all(
            isinstance(key, str) and isinstance(value, dict)
            for key, value in envelope["metadata"].items()
        )
        or envelope.get("shape") != _block_shape(blocks)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in envelope["refs"].items()
        )
        or not set(envelope["refs"]).issubset(
            path for path, kind in envelope["shape"].items() if kind == "data"
        )
        or not set(envelope["metadata"]).issubset(envelope["shape"])
    ):
        return metadata, {}, {}
    if "original" in envelope:
        metadata[_PREVIEWS] = envelope["original"]
    else:
        metadata.pop(_PREVIEWS)
    return metadata, envelope["refs"], envelope["metadata"]


def _preview_refs(public_blocks, host_blocks):
    """Positions survive the host freezing a file URL into a new data block."""
    refs, seen = {}, {}
    for public, host, path in _walk_pairs(public_blocks, host_blocks):
        if public.attachment:
            _merge_refs(
                seen,
                {host.id: public.attachment.preview_url},
                "preview URLs",
            )
            if public.attachment.preview_url:
                refs[path] = public.attachment.preview_url
    return refs


def _tool_metadata(
    metadata,
    blocks,
    event,
    is_error,
    refs,
    block_metadata=None,
):
    encoded = _with_previews(metadata, refs, blocks, block_metadata)
    encoded["_sdk_tool_result"] = {
        "format": "qwenpaw-tool-result/1",
        "shape": _block_shape(blocks),
        "event": event,
        "is_error": is_error,
        "original": deepcopy(metadata),
    }
    return encoded


def _take_tool_metadata(metadata, blocks):
    decoded, previews, block_metadata = _take_previews(metadata, blocks)
    envelope = decoded.get("_sdk_tool_result")
    # Validate the envelope in short-circuit order before indexing fields.
    # pylint: disable=too-many-boolean-expressions
    if (
        isinstance(envelope, dict)
        and set(envelope)
        == {"format", "shape", "event", "is_error", "original"}
        and envelope["format"] == "qwenpaw-tool-result/1"
        and envelope["shape"] == _block_shape(blocks)
        and envelope["event"] in ("start", "delta", "result", "end")
        and isinstance(envelope["is_error"], bool)
        and isinstance(envelope["original"], dict)
    ):
        return (
            envelope["original"],
            previews,
            envelope["event"],
            envelope["is_error"],
            block_metadata,
        )
    return decoded, previews, None, False, block_metadata


def _to_block(block):
    if not isinstance(block, ContentBlock):
        raise SDKError(
            "Message content must contain public ContentBlock values",
        )
    try:
        return _build_block(block)
    except (ValueError, TypeError) as exc:
        raise SDKError(f"Invalid {block.type!r} content block: {exc}") from exc


def _build_block(block):
    from agentscope.message import (
        Base64Source,
        DataBlock,
        HintBlock,
        TextBlock,
        ThinkingBlock,
        ToolCallBlock,
        ToolResultBlock,
        URLSource,
    )

    values = deepcopy(block.attributes)
    if block.id:
        values["id"] = block.id
    if block.type == "text":
        return TextBlock(**{**values, "text": block.text})
    if block.type == "thinking":
        return ThinkingBlock(**{**values, "thinking": block.text})
    if block.type == "hint":
        hint = (
            block.text
            if not block.output
            else [_to_block(item) for item in block.output]
        )
        return HintBlock(**{**values, "hint": hint})
    if block.type == "tool_call":
        return ToolCallBlock(
            **{
                **values,
                "id": block.id,
                "name": block.name,
                "input": block.arguments,
                "state": block.state or "pending",
            },
        )
    if block.type == "tool_result":
        output = (
            block.output
            if isinstance(block.output, str)
            else [_to_block(item) for item in block.output]
        )
        refs = (
            {}
            if isinstance(output, str)
            else _preview_refs(block.output, output)
        )
        metadata = deepcopy(block.metadata)
        if refs or _PREVIEWS in metadata or "_sdk_tool_result" in metadata:
            metadata = _tool_metadata(
                metadata,
                () if isinstance(output, str) else output,
                "result",
                block.state == "error",
                refs,
            )
        return ToolResultBlock(
            **{
                **values,
                "id": block.id,
                "name": block.name,
                "output": output,
                "state": block.state or "running",
                "metadata": metadata,
            },
        )
    if (
        block.type in {"image", "audio", "video", "file"}
        and block.attachment is not None
    ):
        attachment = block.attachment
        if attachment.url.startswith("data:"):
            header, separator, data = attachment.url.partition(",")
            if not separator or not header.endswith(";base64"):
                raise SDKError("Inline attachments must use base64 data URLs")
            source = Base64Source(data=data, media_type=attachment.mime_type)
        else:
            source = URLSource(
                url=attachment.url,
                media_type=attachment.mime_type,
            )
        return DataBlock(
            **{**values, "source": source, "name": attachment.name or None},
        )
    raise SDKError(f"Unsupported or incomplete message block: {block.type!r}")


def _from_block(block, previews=None, block_metadata=None, path="0"):
    values = (
        block.model_dump(mode="json") if hasattr(block, "model_dump") else {}
    )
    mapped = {
        "text": ("text",),
        "thinking": ("thinking",),
        "tool_call": ("name", "input", "state"),
        "tool_result": ("name", "output", "state", "metadata"),
        "hint": ("hint",),
        "data": ("source", "name"),
    }
    for key in ("type", "id", *mapped.get(block.type, ())):
        values.pop(key, None)
    common = {"id": getattr(block, "id", ""), "attributes": deepcopy(values)}
    if block.type != "tool_result":
        common["metadata"] = deepcopy((block_metadata or {}).get(path, {}))
    if block.type == "text":
        return ContentBlock(text=block.text, **common)
    if block.type == "thinking":
        return ContentBlock("thinking", text=block.thinking, **common)
    if block.type == "tool_call":
        return ContentBlock(
            "tool_call",
            name=block.name,
            arguments=block.input,
            state=str(block.state),
            **common,
        )
    if block.type == "tool_result":
        metadata, inner_previews, _, _, inner_metadata = _take_tool_metadata(
            block.metadata,
            () if isinstance(block.output, str) else block.output,
        )
        result_previews = {
            **{
                f"{path}.{key}": value for key, value in inner_previews.items()
            },
            **(previews or {}),
        }
        result_metadata = {
            **{
                f"{path}.{key}": value for key, value in inner_metadata.items()
            },
            **(block_metadata or {}),
        }
        output = (
            block.output
            if isinstance(block.output, str)
            else tuple(
                _from_block(
                    item,
                    result_previews,
                    result_metadata,
                    f"{path}.{index}",
                )
                for index, item in enumerate(block.output)
            )
        )
        return ContentBlock(
            "tool_result",
            name=block.name,
            output=output,
            state=str(block.state),
            metadata=metadata,
            **common,
        )
    if block.type == "hint":
        common["attributes"]["source"] = block.source
        return ContentBlock(
            "hint",
            text=block.hint if isinstance(block.hint, str) else "",
            output=(
                ()
                if isinstance(block.hint, str)
                else tuple(
                    _from_block(
                        item,
                        previews,
                        block_metadata,
                        f"{path}.{index}",
                    )
                    for index, item in enumerate(block.hint)
                )
            ),
            **common,
        )
    if block.type == "data":
        source = block.source
        url = (
            str(source.url)
            if source.type == "url"
            else f"data:{source.media_type};base64,{source.data}"
        )
        kind = source.media_type.split("/", 1)[0]
        return ContentBlock(
            kind if kind in {"image", "audio", "video"} else "file",
            attachment=Attachment(
                url,
                source.media_type,
                block.name or "",
                (previews or {}).get(path, ""),
            ),
            **common,
        )
    raise SDKError(f"Unsupported message block: {block.type!r}")


def to_host(message: Message):
    from agentscope.message import Msg

    if not isinstance(message, Message):
        raise SDKError("Expected a public Message")
    if message.role not in {"user", "assistant", "system"}:
        raise SDKError(
            "Messages use user, assistant or system roles; tool results are "
            "assistant content blocks",
        )
    try:
        blocks = [_to_block(block) for block in message.content]
        metadata = _with_previews(
            message.metadata,
            _preview_refs(message.content, blocks),
            blocks,
            _metadata_refs(message.content, blocks),
        )
        return Msg(
            **{
                **deepcopy(message.attributes),
                "name": message.name,
                "role": message.role,
                "content": blocks,
                "metadata": metadata,
            },
        )
    except (ValueError, TypeError) as exc:
        raise SDKError(f"Invalid message: {exc}") from exc


def from_host(message) -> Message:
    content = message.content
    metadata, previews, block_metadata = _take_previews(
        message.metadata,
        () if isinstance(content, str) else content,
    )
    blocks = (
        (ContentBlock(text=content),)
        if isinstance(content, str)
        else tuple(
            _from_block(block, previews, block_metadata, str(index))
            for index, block in enumerate(content)
        )
    )
    attributes = (
        message.model_dump(mode="json")
        if hasattr(message, "model_dump")
        else {}
    )
    for key in ("name", "role", "content", "metadata"):
        attributes.pop(key, None)
    return Message(
        message.role,
        blocks,
        message.name or "",
        metadata,
        attributes,
    )
