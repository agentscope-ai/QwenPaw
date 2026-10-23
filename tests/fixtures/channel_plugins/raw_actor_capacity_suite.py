"""Normal transport budget and lazy fallback errors, without external SDKs."""

from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize("mode", ["content", "text_sources"])
def test_normal_frame_budget_accepts_large_text_without_truncation(mode):
    from qwenpaw.channel_protocol.completed_text import project_completed_text
    from qwenpaw.channel_protocol.framing import FramingLimits

    text = "x" * (FramingLimits().max_frame_bytes // 4)
    parts, provenance = project_completed_text(
        NS(content=[NS(type="text", text=text)]), mode
    )
    assert parts == [{"type": "text", "text": text, "role": "message"}]
    if mode == "text_sources":
        assert provenance.top_texts == (text,)
    else:
        assert provenance is None


@pytest.mark.parametrize("mode", ["content", "text_sources"])
def test_ignored_iterator_and_oversized_text_fail_explicitly(mode):
    from qwenpaw.channel_protocol.completed_text import project_completed_text
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.framing import FramingLimits

    limit = FramingLimits().max_frame_bytes
    consumed = 0

    def ignored():
        nonlocal consumed
        while consumed <= limit:
            consumed += 1
            yield NS(type="image")
        pytest.fail("Ignored iterator was not bounded by transport capacity")

    for event in [
        NS(content=ignored()),
        NS(content=[NS(type="text", text="x" * (limit + 1))]),
    ]:
        with pytest.raises(ProtocolValidationError) as caught:
            project_completed_text(event, mode)
        assert caught.value.reason_code == "RAW_COMPLETED_TEXT_CAPACITY"
    assert 0 < consumed <= limit


@pytest.mark.parametrize("origin", ["content", "message"])
def test_fallback_accessor_failure_is_typed_and_not_treated_as_absence(origin):
    from qwenpaw.channel_protocol.completed_text import project_completed_text

    class Event:
        @property
        def content(self):
            if origin == "content":
                raise RuntimeError("private top failure")
            return []

        @property
        def message(self):
            if origin == "content":
                pytest.fail("Failed top content fell through to nested message")
            raise RuntimeError("private nested failure")

    parts, provenance = project_completed_text(Event(), "text_sources")
    assert parts == []
    assert provenance.to_mapping() == {
        "getter_state": "absent",
        "getter_texts": [],
        "top_texts": [],
        "nested_texts": [],
        "error_source": origin,
    }
