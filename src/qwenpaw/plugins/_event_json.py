# -*- coding: utf-8 -*-
"""Serialize immutable observations without leaking MappingProxy objects."""

from collections.abc import Mapping
from dataclasses import fields

from .events import ChatEvent, JSONData, StreamContent, StreamMessage


def convert(value) -> JSONData:
    if isinstance(value, (ChatEvent, StreamMessage, StreamContent)):
        return event_dict(value)
    if isinstance(value, Mapping):
        return {key: convert(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [convert(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError("Event contains a non-JSON value")


def event_dict(event) -> dict[str, JSONData]:
    if (
        isinstance(event, ChatEvent)
        and event.object == "content"
        and event.content
    ):
        return {**event_dict(event.content[0]), "object": "content"}
    result = {key: convert(value) for key, value in event.attributes.items()}
    for item in fields(event):
        if item.name == "attributes":
            continue
        value = getattr(event, item.name)
        result[item.name] = convert(value)
    return result
