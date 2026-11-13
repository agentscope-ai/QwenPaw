# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""The promise a demoted pointer makes has to be kept by this store."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

from services.file_agent_runtime import media_vault
from services.file_agent_runtime import driver as driver_module
from services.file_agent_runtime.driver import (
    FileAgentRuntimeError,
    FileCreatorAgentRuntime,
)
from services.workspace.content_store import ContentStore

pytestmark = pytest.mark.unit

# A payload with a real PNG header, so the type can be read back off the
# bytes exactly the way a provider would need it.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"frame" * 20_000
# A WEBP shares the "RIFF" framing with a WAV and only differs four bytes
# later, so reading the type off a stored picture means reading past the size
# field rather than matching a prefix.
_WEBP_BYTES = (
    b"RIFF"
    + (12).to_bytes(4, "little")
    + b"WEBP"
    + b"VP8 "
    + b"lossy frame" * 900
)
_WAV_BYTES = (
    b"RIFF" + (12).to_bytes(4, "little") + b"WAVE" + b"fmt " + b"\x00" * 8
)


def _data_url(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def test_a_stored_block_reads_back_byte_for_byte(tmp_path):
    """A pointer is only honest while the same bytes come back.

    The context guard rewrites a media part into a handle and calls it
    recallable. Recall has to deliver the original payload, not a re-encoded
    approximation of it, or the model is asked to trust a description of
    something nobody can check any more.
    """
    store = ContentStore(tmp_path)
    data_url = _data_url(_PNG_BYTES)

    handle = media_vault.store_data_url(data_url, store=store)
    restored = media_vault.load_by_handle(f"sha256:{handle}", store=store)

    assert handle == hashlib.sha256(_PNG_BYTES).hexdigest()
    assert restored is not None
    url, decoded_bytes = restored
    assert base64.b64decode(url.split(";base64,", 1)[1]) == _PNG_BYTES
    assert url.startswith("data:image/png;")
    assert decoded_bytes == len(_PNG_BYTES)


def test_the_same_image_demoted_twice_costs_one_copy(tmp_path):
    """Content addressing keeps one image from being stored twice."""
    store = ContentStore(tmp_path)
    data_url = _data_url(_PNG_BYTES)

    first = media_vault.store_data_url(data_url, store=store)
    second = media_vault.store_data_url(data_url, store=store)

    assert first == second
    # One stored copy, named by the digest the two pointers advertise.
    assert list(store.iter_digests(namespace="blob")) == [first]
    assert store.path_for(first).is_file()


def test_a_handle_that_is_not_a_digest_never_reaches_the_filesystem():
    """The model retypes pointers; a wrong one must not open paths."""
    assert media_vault.looks_like_digest("sha256:" + "a" * 64)
    assert media_vault.looks_like_digest("A" * 64)
    assert not media_vault.looks_like_digest("sha256:aaaa")
    assert not media_vault.looks_like_digest("../etc/passwd")
    assert not media_vault.looks_like_digest("z" * 64)
    assert media_vault.load_by_handle("z" * 64) is None


def test_a_failed_write_degrades_the_pointer_not_the_request(
    tmp_path,
    monkeypatch,
):
    """A vault that cannot write still leaves the caller a working pointer.

    Demotion exists to save a request that would otherwise be refused. Failing
    the write has to fall back to a pointer without recall, not turn a request
    that would have worked into an error the user sees.
    """

    def refuse(*_args, **_kwargs):
        raise OSError("data root is read-only")

    monkeypatch.setattr(ContentStore, "put_bytes", refuse)
    vault = media_vault.make_vault(ContentStore(tmp_path))

    assert vault(_data_url(_PNG_BYTES)) is None
    assert vault("https://example.com/a.png") is None
    assert vault("data:image/png;base64,not base64 at all") is None
    assert media_vault.split_data_url("https://example.com/a.png") is None


def test_an_unresolvable_data_root_stays_inside_the_vault(monkeypatch):
    """Opening the store is allowed to fail, and that failure never leaves.

    Every entry point resolves CREATOR_DATA_ROOT lazily, so a machine where it
    is unset or relative raises the moment a block is demoted. That is one more
    way the durable copy is missing: the turn keeps its pointer without a
    recall handle. Letting it escape would turn a request that would have
    worked into an error the user sees.
    """
    url = _data_url(_PNG_BYTES)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)

    assert media_vault.store_data_url(url) is None
    assert media_vault.make_vault()(url) is None
    assert media_vault.load_by_handle("a" * 64) is None
    assert media_vault.load_data_url("a" * 64, "image/png") is None

    monkeypatch.setenv("CREATOR_DATA_ROOT", "relative/path")
    assert media_vault.store_data_url(url) is None
    assert media_vault.load_by_handle("a" * 64) is None


def _recall_runtime() -> FileCreatorAgentRuntime:
    # The recall path reads the vault and nothing else, so it can be exercised
    # without assembling a whole runtime.
    return FileCreatorAgentRuntime.__new__(FileCreatorAgentRuntime)


def test_a_pointer_is_answered_with_the_original_media_part(
    tmp_path,
    monkeypatch,
):
    """The tool has to hand back what the pointer promised.

    A recalled block arrives as a native media part on a user turn, not as
    text inside a tool result: no provider reads a Base64 blob out of a JSON
    string, so a recall that only described the image would leave the model
    looking at a caption and believing it had looked again.
    """
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    store = ContentStore(tmp_path)
    digest = media_vault.store_data_url(_data_url(_PNG_BYTES), store=store)

    async def scenario():
        runtime = _recall_runtime()
        result = await runtime._run_recall_media(
            arguments={"handles": [f"sha256:{digest}"]},
        )
        return result, await runtime._recalled_media_content(result=result)

    result, parts = asyncio.run(scenario())

    assert result["recalled"][0]["handle"] == digest
    assert result["recalled"][0]["mime"] == "image/png"
    assert parts[-1]["type"] == "image_url"
    restored = parts[-1]["image_url"]["url"]
    assert base64.b64decode(restored.split(";base64,", 1)[1]) == _PNG_BYTES
    # The payload never lands in the durable tool result itself.
    assert "base64" not in json.dumps(result)


def test_a_handle_nobody_stored_is_reported_missing_not_guessed(
    tmp_path,
    monkeypatch,
):
    """A wrong handle costs a re-run, a guessed image costs the whole run."""
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))

    async def scenario():
        return await _recall_runtime()._run_recall_media(
            arguments={"handles": ["sha256:" + "f" * 64, "../../etc/passwd"]},
        )

    with pytest.raises(FileAgentRuntimeError, match="no restorable bytes"):
        asyncio.run(scenario())


def test_a_block_too_large_to_fit_stays_a_pointer(tmp_path, monkeypatch):
    """Recall cannot trade one budget failure for another.

    The pointer already records the size, so restoring bytes the request could
    never carry would only send the caller back to the refusal that demoted
    them in the first place.
    """
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setattr(driver_module, "MAX_RECALL_MEDIA_BYTES", 1024)
    store = ContentStore(tmp_path)
    digest = media_vault.store_data_url(_data_url(_PNG_BYTES), store=store)

    async def scenario():
        return await _recall_runtime()._run_recall_media(
            arguments={"handles": [digest]},
        )

    with pytest.raises(FileAgentRuntimeError, match="no restorable bytes"):
        asyncio.run(scenario())


def test_a_webp_frame_is_read_back_as_a_picture_not_as_audio():
    """A stored type is recovered from the bytes, and RIFF names a framing.

    Matching the four leading bytes alone would call every WEBP an audio/WAV,
    and the recall path only ships parts whose family a provider can display.
    A picture read back as audio therefore comes home as a sentence about a
    file the model was told it could not be shown.
    """
    assert media_vault.sniff_mime(_WEBP_BYTES) == "image/webp"
    assert media_vault.sniff_mime(_WAV_BYTES) == "audio/wav"
    assert media_vault.sniff_mime(_PNG_BYTES) == "image/png"
    assert (
        media_vault.sniff_mime(bytes(range(10))) == "application/octet-stream"
    )


def test_a_recalled_webp_reaches_the_model_as_an_image_part(
    tmp_path,
    monkeypatch,
):
    """The pointer promised a picture; recall has to deliver a picture."""
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    store = ContentStore(tmp_path)
    digest = media_vault.store_data_url(
        _data_url(_WEBP_BYTES, mime="image/webp"),
        store=store,
    )

    async def scenario():
        runtime = _recall_runtime()
        result = await runtime._run_recall_media(
            arguments={"handles": [f"sha256:{digest}"]},
        )
        return result, await runtime._recalled_media_content(result=result)

    result, parts = asyncio.run(scenario())

    assert result["recalled"][0]["mime"] == "image/webp"
    assert parts[-1]["type"] == "image_url"
    restored = parts[-1]["image_url"]["url"]
    assert restored.startswith("data:image/webp;")
    assert base64.b64decode(restored.split(";base64,", 1)[1]) == _WEBP_BYTES


# A handle is all recall has to work from, and the byte store keeps bytes
# only, so the media type has to come back off the payload. Each of these
# opens with a framing signature rather than a format one: RIFF names a
# container with the deciding tag four bytes past a size field, EBML names a
# family, and an ISO-base box puts its brand after its length.
_AVI_BYTES = (
    b"RIFF" + (12).to_bytes(4, "little") + b"AVI " + b"LIST" + b"hdrl" * 40
)
_WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 8 + b"webm" + b"\x00" * 64
_MKV_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 8 + b"matroska" + b"\x00" * 64
_MOV_BYTES = b"\x00\x00\x00\x18" + b"ftyp" + b"qt  " + b"\x00" * 8
_M4V_BYTES = b"\x00\x00\x00\x18" + b"ftyp" + b"M4V " + b"\x00" * 8
_AVIF_BYTES = b"\x00\x00\x00\x1c" + b"ftyp" + b"avif" + b"\x00" * 12
_MP4_BYTES = b"\x00\x00\x00\x18" + b"ftyp" + b"isom" + b"\x00" * 8


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_AVI_BYTES, "video/x-msvideo"),
        (_WEBM_BYTES, "video/webm"),
        (_MKV_BYTES, "video/x-matroska"),
        (_MOV_BYTES, "video/quicktime"),
        (_AVIF_BYTES, "image/avif"),
        (_M4V_BYTES, "video/mp4"),
        (_MP4_BYTES, "video/mp4"),
    ],
)
def test_a_stored_container_is_named_by_what_it_holds(payload, expected):
    """Reading four bytes is a guess the stored file can contradict.

    The type decides whether a recalled block is handed to the model as
    something it can look at, so an AVI answering "audio/wav" and a WebM
    answering "opaque bytes" both describe a clip the runtime is about to
    claim it cannot show.
    """
    assert media_vault.sniff_mime(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_WEBM_BYTES, "video/webm"),
        (_MKV_BYTES, "video/x-matroska"),
        (_AVI_BYTES, "video/x-msvideo"),
        (_MOV_BYTES, "video/quicktime"),
    ],
)
def test_a_recalled_clip_reaches_the_model_as_a_video_part(
    tmp_path,
    monkeypatch,
    payload,
    expected,
):
    """The pointer named a video; recall has to deliver one.

    The vault keeps bytes, not the declaration the upload arrived with, so a
    clip is restored by reading the payload. Every container the Creator
    runtime inlines has to answer with a displayable family, because the
    alternative is a sentence telling the model it was shown nothing.
    """
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    store = ContentStore(tmp_path)
    digest = media_vault.store_data_url(
        _data_url(payload, mime=expected),
        store=store,
    )

    async def scenario():
        runtime = _recall_runtime()
        result = await runtime._run_recall_media(
            arguments={"handles": [digest]},
        )
        return result, await runtime._recalled_media_content(result=result)

    result, parts = asyncio.run(scenario())

    assert result["recalled"][0]["mime"] == expected
    assert parts[-1]["type"] == "video_url"
    restored = parts[-1]["video_url"]["url"]
    assert restored.startswith(f"data:{expected};")
    assert base64.b64decode(restored.split(";base64,", 1)[1]) == payload


def test_a_missing_type_does_not_answer_for_the_stored_bytes(tmp_path):
    """A generic declaration is the question, not the answer.

    ``data:;base64,`` carries no type and the parser records that gap as
    opaque bytes. Letting the gap stand would hand a stored picture back as
    something no provider can display, so the bytes keep the vote.
    """
    store = ContentStore(tmp_path)
    digest = media_vault.store_data_url(
        _data_url(_PNG_BYTES, mime=media_vault.GENERIC_MIME),
        store=store,
    )

    url = media_vault.load_data_url(
        digest,
        media_vault.GENERIC_MIME,
        store=store,
    )
    assert url.startswith("data:image/png;base64,")

    loaded = media_vault.load_by_handle(digest, mime="", store=store)
    assert loaded is not None
    assert loaded[0].startswith("data:image/png;base64,")
    assert loaded[1] == len(_PNG_BYTES)


def test_the_specialist_turn_can_answer_a_demoted_pointer():
    """Regression on review finding ② (specialist cannot call recall_media).

    The demotion ladder runs inside ``source_model_client.complete``, so
    a specialist turn ends up with a "Call recall_media with that handle"
    pointer. Before the wiring below, the pointer was unactionable:
    ``FileSpecialistToolRegistry.manifest_for`` never listed the tool and
    ``specialist_tools.invoke`` raised
    ``ValidationError: Specialist manifest 不存在工具: recall_media``.

    A full delegate-loop test needs a Project plus a mocked VLM client;
    these source anchors are cheap and would fire on any refactor that
    drops one of the three required pieces.
    """
    import inspect

    source = inspect.getsource(driver_module.FileCreatorAgentRuntime)

    # (a) The tool has to appear on the manifest the model sees, otherwise
    #     the pointer the demoter wrote is a promise the tool list denies.
    assert "tool_manifest.append(_recall_media_tool_manifest())" in source

    # (b) The dispatch must reach the shared handler without falling into
    #     ``specialist_tools.invoke``, which is where the ValidationError
    #     used to raise.  The branch lives in the delegate loop body.
    assert (
        "if call.name == RECALL_MEDIA_TOOL_NAME:" in source
    ), "specialist loop must short-circuit recall_media"
    # Two call sites: one for the main agent, one added here for the
    # specialist loop.  A count check catches a refactor that quietly
    # removes only the specialist branch.
    assert (
        source.count("result = await self._run_recall_media(") == 2
    ), "both main and specialist loops must route recall_media to the handler"

    # (c) The bytes must arrive as native media on a user turn, not as a
    #     JSON blob in the tool result — no provider reads an image out
    #     of a text field.  The injection keys on this metadata tag.
    assert (
        '"recalledMediaForToolCallId": call.call_id' in source
    ), "specialist loop must inject recalled media as native parts"


def test_text_history_is_archived_and_recallable_not_just_cut():
    """Regression on the platform-scroll reuse for text history.

    The complaint was that compaction only pruned text history — leaving a
    bare ``elidedMessageCount`` with no way back — instead of archiving it
    with a recallable handle the way the platform scroll does. Three pieces
    have to stay wired: the durable map is emitted at elision, the tool is
    on every manifest, and both loops route the call to the shared handler.
    """
    import inspect

    runtime_source = inspect.getsource(driver_module.FileCreatorAgentRuntime)
    manifest_source = inspect.getsource(
        driver_module._creator_agent_tool_manifest,
    )
    context_source = inspect.getsource(
        driver_module.plan_history_compaction,
    )

    # (a) Elision now names the dropped turns by seq instead of a bare
    #     count, so the archived originals stay addressable.
    assert "archivedHistoryMap" in context_source
    assert "recoverableSeqRange" in context_source

    # (b) The recall tool is exposed on the main manifest (never behind a
    #     feature switch) and on the specialist delegate manifest.
    assert (
        "manifest.append(_recall_history_tool_manifest())" in manifest_source
    )
    assert (
        "tool_manifest.append(_recall_history_tool_manifest())"
        in runtime_source
    )

    # (c) Both dispatch sites route recall_history to the shared handler
    #     rather than into the role-scoped registry, which has no such tool
    #     and would raise ValidationError.
    assert (
        runtime_source.count("result = await self._run_recall_history(") == 2
    ), "both main and specialist loops must route recall_history"
    assert (
        "async def _run_recall_history(" in runtime_source
    ), "the handler must live on the runtime"


def test_continuation_summary_is_wired_and_fail_closed():
    """Reverse guard for the platform scroll's fourth relief lever.

    The prose continuation summary reuses the host library and rides beside
    the recall map, but it costs a model turn, so two properties must hold: it
    is genuinely generated from the archived slice and injected into the
    compaction marker, and it can never break a run. A refactor that quietly
    drops the call, or lets a provider error escape, fails here.
    """
    import inspect

    module_source = inspect.getsource(driver_module)
    runtime_source = inspect.getsource(driver_module.FileCreatorAgentRuntime)
    text_source = inspect.getsource(driver_module._continuation_message_text)
    summary_source = inspect.getsource(
        driver_module.FileCreatorAgentRuntime._plan_continuation_summary,
    )
    context_source = inspect.getsource(
        driver_module.compact_conversation_history,
    )

    # (a) The host library is imported behind a guard, so a standalone plugin
    #     install degrades to recall-only instead of failing to import.
    assert "_HOST_CONTINUATION_SUMMARY_AVAILABLE" in module_source

    # (b) The planner runs, is awaited from the loop, and its result reaches
    #     the serialized history through the compaction helper.
    assert "async def _plan_continuation_summary(" in runtime_source
    assert "await self._plan_continuation_summary(" in runtime_source
    assert "continuation_summary=continuation_summary" in text_source

    # (c) Fail-closed: any error yields empty relief, and the summary only
    #     ever lands on a real ``context_compaction`` marker.
    assert "except Exception" in summary_source
    assert 'return ""' in summary_source
    assert "continuationSummary" in context_source
