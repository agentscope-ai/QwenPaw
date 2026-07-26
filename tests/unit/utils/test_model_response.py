# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Tests for the shared chat-model response helpers."""
from types import SimpleNamespace

import pytest

from qwenpaw.utils.model_response import (
    consume_model_response,
    extract_response_text,
    safe_attr,
)


class _DictLike(dict):
    """agentscope ``ChatResponse`` shape: ``__getattr__`` is dict lookup, so a
    missing key raises ``KeyError`` from ``getattr`` instead of defaulting."""

    __getattr__ = dict.__getitem__


def test_safe_attr_swallows_dict_getattr_keyerror():
    assert safe_attr(_DictLike({"content": "x"}), "text") is None
    assert safe_attr({"text": "hi"}, "text") == "hi"
    assert safe_attr(SimpleNamespace(text="obj"), "text") == "obj"


@pytest.mark.parametrize(
    "response,expected",
    [
        (None, ""),
        ("hello", "hello"),
        ({"text": "hi"}, "hi"),
        ({"content": "hi"}, "hi"),
        ({"content": [{"type": "text", "text": "chunk"}]}, "chunk"),
        ({}, ""),
        (SimpleNamespace(text="obj-text"), "obj-text"),
        (_DictLike({"content": "fallback"}), "fallback"),
    ],
    ids=[
        "none",
        "str",
        "dict-text",
        "dict-content-str",
        "dict-content-list",
        "dict-empty",
        "obj-text-attr",
        "chatresponse-getattr-keyerror",
    ],
)
def test_extract_response_text(response, expected):
    assert extract_response_text(response) == expected


async def test_consume_non_streaming():
    async def model(messages, **kw):
        return SimpleNamespace(text="done")

    assert await consume_model_response(model, []) == "done"


async def test_consume_streaming_takes_last_non_empty_chunk():
    async def model(messages, **kw):
        async def gen():
            for t in ("par", "partial", ""):
                yield SimpleNamespace(text=t)

        return gen()

    assert await consume_model_response(model, []) == "partial"


async def test_consume_forwards_call_kwargs():
    seen = {}

    async def model(messages, **kw):
        seen.update(kw)
        return SimpleNamespace(text="ok")

    await consume_model_response(model, [], disable_thinking=True)
    assert seen == {"disable_thinking": True}
