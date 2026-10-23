"""Raw typed provenance to real SIP Driver/platform/ASR/TTS vendor boundary."""
from types import SimpleNamespace as NS

import pytest

from sip_native_support import vendor, running, incoming, until
from qwenpaw.channel_protocol.completed_text import project_completed_text
from qwenpaw.channel_protocol.models import RawCompletedTextSources, SendParams
from qwenpaw.channel_protocol.errors import RpcError
from qwenpaw_channel_sip.helpers import _extract_text, _clean_for_tts

__all__ = ["vendor"]


def event_for(source):
    if source == "getter":

        class Event:
            def get_text_content(self):
                return [NS(text="  first "), NS(text="second  ")]

            @property
            def content(self):
                raise AssertionError("getter success must not read fallback")

        return Event()
    if source == "top":

        class Event:
            content = [
                NS(refusal="ignored refusal"),
                NS(text=""),
                NS(text=" top first "),
                NS(text="not spoken"),
            ]

            def get_text_content(self):
                return []

            @property
            def message(self):
                raise AssertionError("top success must not read nested")

        return Event()
    return NS(
        content=[NS(refusal="ignored refusal")],
        message=NS(content=[NS(text=" nested first "), NS(text="not spoken")]),
    )


def send(identity, inbound, event, delivery="raw-delivery"):
    parts, sources = project_completed_text(event, "text_sources")
    assert isinstance(sources, RawCompletedTextSources)
    wire = {
        **identity,
        "delivery_id": delivery,
        "to_handle": inbound["response_handle"],
        "operation": "message.create",
        "content_source": "event",
        "content_parts": parts,
        "raw_completed_text_sources": sources.to_mapping(),
    }
    parsed = SendParams.from_mapping(wire)
    assert parsed.raw_completed_text_sources == sources
    assert SendParams.from_mapping(parsed.to_mapping()) == parsed
    return parsed, sources


@pytest.mark.parametrize("mode", ["dev", "livekit"])
@pytest.mark.parametrize("source", ["getter", "top", "nested"])
async def test_raw_provenance_preserves_legacy_text_precedence_through_actual_playback(
    vendor, mode, source
):
    async with running(vendor, mode) as (driver, peer, identity):
        call = await incoming(vendor, mode)
        vendor.asrs[-1].sentence("question")
        await until(lambda: peer.batches)
        inbound = peer.batches[0]["events"][0]
        event = event_for(source)
        expected = _clean_for_tts(_extract_text(event))
        params, sources = send(identity, inbound, event)
        assert sources.error_source is None
        assert getattr(
            sources,
            {
                "getter": "getter_texts",
                "top": "top_texts",
                "nested": "nested_texts",
            }[source],
        )
        assert (
            driver.response_policy(
                inbound["response_handle"]
            ).raw_completed_text
            == "text_sources"
        )
        result = await driver._send(params, None)
        assert result["state"] == "acknowledged"
        assert vendor.synths[-1].text == expected
        if mode == "dev":
            assert call.writes == [bytes([128]) * 160]
        else:
            assert [frame.data for frame in vendor.sources[-1].frames] == [
                b"\0" * 960
            ]


@pytest.mark.parametrize("source", ["getter", "content", "message"])
async def test_extraction_error_is_typed_failed_without_fallback_audio(
    vendor, source
):
    class Event:
        def get_text_content(self):
            if source == "getter":
                raise RuntimeError("private getter exception")
            return []

        @property
        def content(self):
            if source == "content":
                raise RuntimeError("private content exception")
            return []

        @property
        def message(self):
            raise RuntimeError("private nested exception")

    async with running(vendor) as (driver, peer, identity):
        call = await incoming(vendor, "dev")
        vendor.asrs[-1].sentence("question")
        await until(lambda: peer.batches)
        params, sources = send(identity, peer.batches[0]["events"][0], Event())
        assert sources.error_source == source and params.content_parts == ()
        result = await driver._send(params, None)
        assert result["state"] == "failed"
        assert result["reason_code"] == "SIP_COMPLETED_TEXT_EXTRACTION_FAILED"
        assert "private" not in repr(result)
        assert not vendor.synths and not call.writes


async def test_raw_provenance_unknown_receipt_does_not_replay_native_audio(
    vendor,
):
    async with running(vendor) as (driver, peer, identity):
        call = await incoming(vendor, "dev")
        vendor.asrs[-1].sentence("question")
        await until(lambda: peer.batches)
        params, _ = send(
            identity, peer.batches[0]["events"][0], event_for("getter")
        )
        vendor.fail_write = True
        result = await driver._send(params, None)
        assert result["state"] == "unknown"
        vendor.fail_write = False
        assert await driver._send(params, None) == result
        assert len(call.writes) == len(vendor.synths) == 1


async def test_raw_send_without_declared_capability_cannot_reach_playback(
    vendor,
):
    async with running(vendor) as (driver, peer, identity):
        call = await incoming(vendor, "dev")
        vendor.asrs[-1].sentence("question")
        await until(lambda: peer.batches)
        params, _ = send(
            identity, peer.batches[0]["events"][0], event_for("top")
        )
        driver._context.capabilities = tuple(
            cap
            for cap in driver._context.capabilities
            if cap != "send.raw_completed_text.v1"
        )
        with pytest.raises(RpcError):
            await driver._send(params, None)
        assert not vendor.synths and not call.writes


async def test_event_without_raw_sources_is_failed_not_replaced_by_rendered_text(
    vendor,
):
    async with running(vendor) as (driver, peer, identity):
        call = await incoming(vendor, "dev")
        vendor.asrs[-1].sentence("question")
        await until(lambda: peer.batches)
        params, _ = send(
            identity, peer.batches[0]["events"][0], event_for("top")
        )
        wire = params.to_mapping()
        wire.pop("raw_completed_text_sources")
        result = await driver._send(SendParams.from_mapping(wire), None)
        assert (
            result["state"] == "failed"
            and result["reason_code"] == "SIP_RAW_COMPLETED_TEXT_UNAVAILABLE"
        )
        assert not vendor.synths and not call.writes
