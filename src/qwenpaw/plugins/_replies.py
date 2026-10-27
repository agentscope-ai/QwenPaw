# -*- coding: utf-8 -*-
"""Explicit SDK replies carried through the existing runtime envelope."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from copy import deepcopy
from dataclasses import asdict

from agentscope.message import Msg
from pydantic import PrivateAttr


class _SDKReply(Msg):
    _sdk_public = PrivateAttr()

    def runtime_content(self):
        from ..schemas import (
            TextContent,
            ImageContent,
            AudioContent,
            VideoContent,
            FileContent,
            DataContent,
        )

        public = self._sdk_public
        result = []
        media = {
            "image": (ImageContent, "image_url"),
            "audio": (AudioContent, "data"),
            "video": (VideoContent, "video_url"),
            "file": (FileContent, "file_url"),
        }
        for index, block in enumerate(public.content):
            values = {
                **deepcopy(block.attributes),
                "id": block.id,
                "metadata": deepcopy(block.metadata),
                "sdk_attributes": deepcopy(block.attributes),
                "object": "content",
                "status": None,
                "msg_id": None,
                "delta": False,
                "index": index,
            }
            if block.type == "text":
                content = TextContent(
                    **{**values, "type": "text", "text": block.text},
                )
            elif block.type in media and block.attachment is not None:
                cls, url_field = media[block.type]
                attachment = asdict(block.attachment)
                content = cls(
                    **{
                        **values,
                        "type": block.type,
                        url_field: attachment["url"],
                        "attachment": attachment,
                        "preview_url": attachment["preview_url"],
                        "filename": attachment["name"],
                        "mime_type": attachment["mime_type"],
                    },
                )
            else:
                # Structured reasoning/hints/tool calls remain complete JSON.
                # The channel decides how to render these non-media blocks.
                content = DataContent(
                    **{**values, "type": "data", "data": asdict(block)},
                )
            result.append(content)
        return (
            result,
            deepcopy(public.metadata),
            {
                "format": "qwenpaw-sdk-message/1",
                "version": 1,
                "name": public.name,
                "role": public.role,
                "attributes": deepcopy(public.attributes),
            },
        )


def to_reply(message):
    from ._messages import to_host

    reply = _SDKReply.model_validate(to_host(message).model_dump())
    reply._sdk_public = deepcopy(message)
    return reply
