# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,using-constant-test,protected-access
# Test stubs override signatures for monkeypatch targets (unused-argument);
# ``if False: yield`` is the standard idiom for an async-generator no-op;
# the hooks deliberately install ``_extract_datapaw_metadata`` as a
# class-level helper (protected-access).
"""Tests for hooks.setup_channel_sse_hook and helpers."""
import asyncio


# ---------------------------------------------------------------------------
# _extract_datapaw_metadata
# ---------------------------------------------------------------------------


def test_extract_datapaw_metadata_returns_graph_id_and_node_id():
    from hooks import _extract_datapaw_metadata

    out = _extract_datapaw_metadata({"graph_id": "g1", "node_id": "n1"})
    assert out == {"graph_id": "g1", "node_id": "n1"}


def test_extract_datapaw_metadata_accepts_nested_metadata_shape():
    from hooks import _extract_datapaw_metadata

    out = _extract_datapaw_metadata(
        {"metadata": {"graph_id": "g1", "node_id": "n1", "extra": "ignored"}},
    )
    assert out == {"graph_id": "g1", "node_id": "n1"}


def test_extract_datapaw_metadata_returns_empty_when_no_keys():
    from hooks import _extract_datapaw_metadata

    assert _extract_datapaw_metadata({}) == {}
    assert _extract_datapaw_metadata({"unrelated": 1}) == {}


def test_extract_datapaw_metadata_handles_partial_keys():
    from hooks import _extract_datapaw_metadata

    out = _extract_datapaw_metadata({"graph_id": "g1"})
    assert out == {"graph_id": "g1"}
    assert "node_id" not in out


def test_extract_datapaw_metadata_handles_non_dict_input():
    from hooks import _extract_datapaw_metadata

    assert _extract_datapaw_metadata(None) == {}
    assert _extract_datapaw_metadata("string") == {}
    assert _extract_datapaw_metadata(123) == {}


# ---------------------------------------------------------------------------
# _format_task_event_as_sse
# ---------------------------------------------------------------------------


def test_format_task_event_with_model_dump_json():
    from hooks import _format_task_event_as_sse

    class FakeEvent:
        def model_dump_json(self):
            return '{"object": "task_status", "graph_id": "g1"}'

    out = _format_task_event_as_sse(FakeEvent())
    assert out == 'data: {"object": "task_status", "graph_id": "g1"}\n\n'


def test_format_task_event_fallback_for_plain_object():
    from hooks import _format_task_event_as_sse

    out = _format_task_event_as_sse("hello")
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    assert '"task_status"' in out


# ---------------------------------------------------------------------------
# stream_one wrapper drains queue between frames
# ---------------------------------------------------------------------------


def test_wrapped_stream_one_drains_datapaw_queue_between_frames():
    """Wrap stream_one async generator; queue events get yielded."""
    from hooks import _wrap_stream_one

    queue = asyncio.Queue()

    class FakeRequest:
        def __init__(self):
            self._datapaw_sse_queue = queue

    request = FakeRequest()

    class FakeEvent:
        def __init__(self, n):
            self.n = n

        def model_dump_json(self):
            return f'{{"object": "task_status", "n": {self.n}}}'

    async def orig(self, payload):
        yield "data: frame-1\n\n"
        # Datapaw pushes one event after frame-1
        await queue.put(FakeEvent(1))
        yield "data: frame-2\n\n"
        # And two more before tail
        await queue.put(FakeEvent(2))
        await queue.put(FakeEvent(3))

    wrapped = _wrap_stream_one(orig)

    async def _run():
        out = []
        async for frame in wrapped(None, request):
            out.append(frame)
        return out

    out = asyncio.run(_run())

    # Wrapper drains queue AFTER yielding each original frame. FakeEvent(1)
    # is put between frame-1 and frame-2 in orig, so it gets noticed only
    # after frame-2 yields. FakeEvent(2)/(3) are put before orig ends, so
    # they get drained on the tail flush.
    assert out == [
        "data: frame-1\n\n",
        "data: frame-2\n\n",
        'data: {"object": "task_status", "n": 1}\n\n',
        'data: {"object": "task_status", "n": 2}\n\n',
        'data: {"object": "task_status", "n": 3}\n\n',
    ]


def test_wrapped_stream_one_passthrough_when_no_queue():
    """If request has no _datapaw_sse_queue, behave as a pure passthrough."""
    from hooks import _wrap_stream_one

    request = object()  # no queue attached

    async def orig(self, payload):
        yield "data: a\n\n"
        yield "data: b\n\n"

    wrapped = _wrap_stream_one(orig)

    async def _run():
        return [f async for f in wrapped(None, request)]

    out = asyncio.run(_run())
    assert out == ["data: a\n\n", "data: b\n\n"]


# ---------------------------------------------------------------------------
# setup_channel_sse_hook installer
# ---------------------------------------------------------------------------


def test_setup_channel_sse_hook_patches_stream_one_and_adds_static_method():
    from hooks import setup_channel_sse_hook

    async def orig(self, payload):
        if False:
            yield None

    class FakeChannel:
        stream_one = orig

    setup_channel_sse_hook(_channel_cls=FakeChannel)

    assert FakeChannel.stream_one is not orig
    assert getattr(FakeChannel.stream_one, "_datapaw_patched", False) is True
    assert hasattr(FakeChannel, "_extract_datapaw_metadata")
    assert FakeChannel._extract_datapaw_metadata({"graph_id": "x"}) == {
        "graph_id": "x",
    }


def test_setup_channel_sse_hook_idempotent():
    from hooks import setup_channel_sse_hook

    async def orig(self, payload):
        if False:
            yield None

    class FakeChannel:
        stream_one = orig

    setup_channel_sse_hook(_channel_cls=FakeChannel)
    first = FakeChannel.stream_one
    setup_channel_sse_hook(_channel_cls=FakeChannel)

    assert FakeChannel.stream_one is first
