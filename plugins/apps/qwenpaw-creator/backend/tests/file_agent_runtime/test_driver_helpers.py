# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Benign trailing closers execute the lossless prefix instead of failing.

Reproduces the 2026-08 production case: a 4.4KB streamed tool-call
argument ended with exactly one surplus ``}`` after a complete JSON
object, forcing a repair-and-retry turn even though dropping the tail
was provably lossless.
"""
from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.file_agent_runtime.model_client import _parse_tool_arguments
from services.file_agent_runtime.driver import (
    MAX_RECALL_HISTORY_BYTES,
    MAX_RECALL_HISTORY_SEARCH_HITS,
    FileCreatorAgentRuntime,
    _HOST_SUMMARY_RECALL_SENTENCE,
    _creator_summary_recall_wording,
    _message_text,
    _recall_media_pointer,
    _unfinished_video_element_ids,
)
from services.file_agent_runtime import driver as driver_module
from services.file_agent_runtime import model_context
from services.runtime_files.models import (
    CreatorMessageRecord,
    MessageChannel,
    MessageContentPart,
)
from services.project_files.models import (
    ArtifactSlot,
    ElementLocation,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)


pytestmark = pytest.mark.unit


def test_single_surplus_closing_brace_is_accepted_as_strict():
    payload = {"projectId": "p-1", "program": ".", "jsonArgs": {"a": 1}}
    raw = json.dumps(payload) + "}"

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert arguments == payload
    assert parse_error is None
    assert repaired is False
    assert strict_error is None


def test_trailing_real_content_still_goes_through_repair():
    # The tail carries information (a truncated sibling key): accepting the
    # prefix would silently drop it, so the repair path must stay in charge.
    payload = {"projectId": "p-1", "jsonArgs": {"a": 1}}
    raw = json.dumps(payload) + ', "program": "."}'

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert strict_error is not None
    assert repaired or parse_error is not None
    assert arguments != payload or repaired


# ---------------------------------------------------------------------------
# YOLO completion loop: unfinished video detection
# ---------------------------------------------------------------------------


def _element(element_id: str, start_tick: int = 0) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        label=element_id,
        span=TimelineSpan(start_tick=start_tick, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="测试叙事",
            storyboard_prompt="测试分镜",
        ),
    )


def _project_with_elements(*element_ids: str) -> Project:
    project = Project.new(project_id="p-yolo", name="YOLO Loop")
    timeline = project.timelines.items["timeline:main"]
    for index, element_id in enumerate(element_ids):
        timeline.elements_by_id[element_id] = _element(
            element_id,
            start_tick=index * 4_000,
        )
    return project


def _finish_video(project: Project, element_id: str) -> None:
    slot_id = f"element:{element_id}:main"
    project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
        slot_id=slot_id,
        kind="element_video",
        owner_ref=f"element:{element_id}",
        version_ids=["artifact-version-x"],
        selected_version_id="artifact-version-x",
    )


def test_elements_without_main_video_are_unfinished():
    project = _project_with_elements("elem:a", "elem:b", "elem:c")
    _finish_video(project, "elem:b")

    assert _unfinished_video_element_ids(project) == ["elem:a", "elem:c"]


def test_unselected_video_slot_is_still_unfinished():
    project = _project_with_elements("elem:a")
    slot_id = "element:elem:a:main"
    project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
        slot_id=slot_id,
        kind="element_video",
        owner_ref="element:elem:a",
        version_ids=[],
        selected_version_id=None,
    )

    assert _unfinished_video_element_ids(project) == ["elem:a"]


# ---- artifact 选区解析注入（方案 3.5b）----------------------------------


def _script_selection_project(tmp_path):
    """带一个 timeline_script 版本（含落盘文件）的 Project。"""

    import hashlib
    from datetime import UTC, datetime

    from services.project_files.script_artifacts import (
        add_script_version,
        script_file_relative_uri,
    )

    project = Project.new(project_id="p-selection", name="Selection")
    text = (
        "## 场 1 · 内景 · 旧宅大厅 · 夜\n\n"
        + "铺垫。" * 200
        + "\n\n**林晚**（低声）：这里……和二十年前一模一样。\n"
    )
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    version = add_script_version(
        project,
        "timeline:main",
        text,
        file_id="file-script-sel",
        checksum=checksum,
        name="剧本 v1",
        now=datetime(2026, 8, 15, tzinfo=UTC),
        based_on_generation=0,
    )
    payload_path = tmp_path / script_file_relative_uri("file-script-sel")
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(text, encoding="utf-8")
    return project, version, text


def test_parse_artifact_selection_path():
    from services.file_agent_runtime.driver import (
        _parse_artifact_selection_path,
    )

    assert _parse_artifact_selection_path(
        "artifact:script:timeline:main@artifact-1",
    ) == ("script:timeline:main", "artifact-1")
    # 非 artifact path（RFC 6901 指针）与残缺形式一律不解析。
    assert _parse_artifact_selection_path("/strategy/creative_brief") is None
    assert _parse_artifact_selection_path("artifact:slot-only") is None
    assert _parse_artifact_selection_path("artifact:@v") is None
    assert _parse_artifact_selection_path(None) is None


def test_artifact_selection_injects_window_around_offsets(tmp_path):
    from services.file_agent_runtime.driver import _artifact_selection_note

    project, version, text = _script_selection_project(tmp_path)
    target = "这里……和二十年前一模一样。"
    start = text.index(target)
    end = start + len(target)

    note = _artifact_selection_note(
        project,
        tmp_path,
        {
            "path": f"artifact:script:timeline:main@{version.version_id}",
            "start": start,
            "end": end,
            "label": "剧本正文",
        },
    )

    assert note is not None
    assert f"«{target}»" in note
    assert f"字符 {start}-{end}" in note
    # 窗口截断：正文远超 ±300 字符，注入必须带省略号且不含全文开头。
    assert note.count("…") >= 1
    assert "## 场 1" not in note


def test_invalid_selection_reports_fallback_note(tmp_path):
    from services.file_agent_runtime.driver import _artifact_selection_note

    project, version, _ = _script_selection_project(tmp_path)
    # 过期版本：报告选区版本已过期并指出当前版本。
    stale = _artifact_selection_note(
        project,
        tmp_path,
        {
            "path": "artifact:script:timeline:main@artifact-older",
            "start": 0,
            "end": 5,
        },
    )
    assert stale is not None
    assert "选区所在版本已过期" in stale
    assert version.version_id in stale
    # 未知槽位：报告选区目标已不存在。
    missing = _artifact_selection_note(
        project,
        tmp_path,
        {"path": "artifact:script:timeline:ghost@v1"},
    )
    assert missing is not None
    assert "已不存在" in missing


def test_message_text_appends_selection_notes(tmp_path):
    from types import SimpleNamespace

    from services.file_agent_runtime.driver import _message_text

    project, version, text = _script_selection_project(tmp_path)
    message = SimpleNamespace(
        content_parts=[],
        metadata={
            "context": {
                "selection": {
                    "path": (
                        "artifact:script:timeline:main"
                        f"@{version.version_id}"
                    ),
                    "start": 0,
                    "end": 4,
                    "text": text[:4],
                },
            },
        },
    )
    rendered = _message_text(message, project=project, project_root=tmp_path)
    assert "[选区上下文" in rendered
    # 不带 project 上下文时保持旧行为：只透传结构化 JSON。
    rendered_plain = _message_text(message)
    assert "[选区上下文" not in rendered_plain


# The local names the driver hands inline media to the provider on.
_MEDIA_ROW_VARIABLES = frozenset(
    {"user_content", "frame_content", "page_content"},
)


def _media_user_rows() -> list[tuple[str, bool]]:
    """Every user row literal in the driver that carries media parts."""
    tree = ast.parse(
        Path(driver_module.__file__).read_text(encoding="utf-8"),
    )
    rows: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        fields: dict[str, ast.expr] = {
            key.value: value
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        role = fields.get("role")
        content = fields.get("content")
        if not isinstance(role, ast.Constant) or role.value != "user":
            continue
        if (
            isinstance(content, ast.Name)
            and content.id in _MEDIA_ROW_VARIABLES
        ):
            rows.append((content.id, "source" in fields))
    return rows


def test_media_bearing_user_rows_say_the_runtime_observed_them():
    """Inline media rides the user role, so the stamp is the only tell.

    The provider's protocol refuses media on a tool row, which leaves the
    demotion ladder no way to separate a frame a reader tool sampled from a
    picture a person uploaded except by the source the driver wrote on the
    row. An unstamped row is traded as an attachment, and the record then
    reports a loss the runtime never had to take.
    """
    rows = _media_user_rows()

    assert {name for name, _stamped in rows} == set(_MEDIA_ROW_VARIABLES)
    assert [name for name, stamped in rows if not stamped] == []
    assert model_context.MEDIA_OBSERVATION_SOURCE in (
        model_context._AUTOMATED_HISTORY_SOURCES
    )


def _recall_record(
    seq: int,
    *,
    text: str = "",
    parts: list | None = None,
    conversation_id: str = "conversation-1",
) -> CreatorMessageRecord:
    """A durable turn exactly as ``recall_history`` reads it back."""
    return CreatorMessageRecord(
        message_id=f"message-{seq}",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id=conversation_id,
        message_seq=seq,
        role="tool",
        content_parts=(
            parts if parts is not None else [{"type": "text", "text": text}]
        ),
        source="runtime_action_result",
        channel=MessageChannel.RUNTIME,
        metadata={},
    )


def _run_recall_history(records, arguments):
    """Drive ``_run_recall_history`` over an in-memory session stub."""

    def list_messages(*_args, **_kwargs):
        return list(records)

    fake_self = SimpleNamespace(
        sessions=SimpleNamespace(list_messages=list_messages),
    )
    return asyncio.run(
        FileCreatorAgentRuntime._run_recall_history(
            fake_self,
            project_id="project-1",
            session_id="session-1",
            conversation_id="conversation-1",
            arguments=arguments,
        ),
    )


def test_recall_media_pointer_drops_inline_base64():
    """#2: a media part becomes a size/mime pointer, never its bytes."""
    payload = "A" * 4096
    part = MessageContentPart(
        type="image_url",
        image_url={
            "url": f"data:image/png;base64,{payload}",
            "mediaType": "image/png",
        },
    )
    pointer = _recall_media_pointer(part)
    assert payload not in pointer
    assert "image/png" in pointer
    assert "内联媒体" in pointer
    assert str(len(payload) * 3 // 4) in pointer


def test_message_text_media_as_pointer_keeps_base64_out_of_recall():
    """#2: recall renders media as a pointer; the live path is unchanged."""
    payload = "B" * 2048
    record = _recall_record(
        7,
        parts=[
            {"type": "text", "text": "看看这张图"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{payload}",
                    "mediaType": "image/jpeg",
                },
            },
        ],
    )
    recall = _message_text(record, media_as_pointer=True)
    assert payload not in recall
    assert "看看这张图" in recall
    assert "内联媒体" in recall
    # The default path still carries the bytes for a live turn.
    assert payload in _message_text(record)


def test_recall_history_expand_returns_pointer_not_base64():
    """#2 end to end: expand hands back history, not a data URL."""
    payload = "C" * 8192
    records = [
        _recall_record(
            3,
            parts=[
                {"type": "text", "text": "上传的参考图"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{payload}",
                        "mediaType": "image/png",
                    },
                },
            ],
        ),
    ]
    result = _run_recall_history(
        records,
        {"projectId": "project-1", "op": "expand", "lo": 3, "hi": 3},
    )
    text = result["entries"][0]["text"]
    assert payload not in text
    assert "上传的参考图" in text
    assert "内联媒体" in text


def test_recall_history_search_ignores_base64_substrings():
    """#2: a keyword must not match bytes a media part no longer dumps."""
    payload = "D" * 4096
    records = [
        _recall_record(
            1,
            parts=[
                {"type": "text", "text": "普通文本"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{payload}",
                        "mediaType": "image/png",
                    },
                },
            ],
        ),
    ]
    result = _run_recall_history(
        records,
        {"projectId": "project-1", "op": "search", "query": "D" * 64},
    )
    assert result["entries"] == []


def test_recall_history_search_charges_full_entries_at_ceiling():
    """#6: each hit is charged its serialized cost; the loop stops at 64KiB.

    Reproduces the reviewer's case (many matching turns, metadata-only
    entries) where an unbounded append re-inflated the response past the
    ceiling. Here the byte cap binds before the hit cap.
    """
    records = [
        _recall_record(seq, text="needle " + "x" * 600)
        for seq in range(1, 501)
    ]
    result = _run_recall_history(
        records,
        {"projectId": "project-1", "op": "search", "query": "needle"},
    )
    entries = result["entries"]
    assert result["truncated"] is True
    # No empty matches slipped in after the budget was spent.
    assert all(entry["match"] for entry in entries)
    size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    assert size < MAX_RECALL_HISTORY_BYTES + 4096
    # The unbounded version produced ~440KB; this stays an order below.
    assert size < 100 * 1024


def test_recall_history_search_caps_hit_count():
    """#6: tiny matches hit the 200-entry cap before the byte ceiling."""
    records = [_recall_record(seq, text="needle") for seq in range(1, 501)]
    result = _run_recall_history(
        records,
        {"projectId": "project-1", "op": "search", "query": "needle"},
    )
    assert len(result["entries"]) == MAX_RECALL_HISTORY_SEARCH_HITS
    assert result["truncated"] is True


def test_creator_summary_recall_wording_replaces_host_table():
    """#3: the host ``conversation_history`` line becomes Creator's."""
    host = _HOST_SUMMARY_RECALL_SENTENCE.format(lo=12, hi=34)
    background = f"## 背景\n主角名字已定。\n{host}\n"
    result = _creator_summary_recall_wording(background, 12, 34)
    assert "conversation_history" not in result
    assert "recall_history" in result
    assert "messageSeq 12" in result
    assert "主角名字已定" in result


def test_creator_summary_recall_wording_scrubs_reworded_host_line():
    """#3: even if the host rewords, the dead table name must not leak."""
    background = "Archived rows stay in conversation_history for later."
    result = _creator_summary_recall_wording(background, 1, 9)
    assert "conversation_history" not in result
    assert "the durable conversation store" in result
