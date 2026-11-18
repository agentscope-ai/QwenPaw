# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json

from agentscope.message import (
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
)
from agentscope.model import DashScopeChatModel
from agentscope.model._model_response import ChatResponse
import pytest

from services.file_agent_runtime.model_client import (
    MAX_RATE_LIMIT_RETRIES,
    AgentModelError,
    AgentStreamCallbackError,
    AgentStreamCallbackPassthrough,
    AgentModelTurn,
    AgentScopeAgentChatClient,
    AgentScopeVlmChatClient,
    AgentToolCall,
    CallbackAgentChatClient,
    ModelContextUnfitError,
    OverflowAfterOutputError,
    RateLimitExhaustedError,
    RateLimitRetryNotice,
    is_context_length_error,
    records_to_agentscope_messages,
)
from services.file_agent_runtime import model_client
from services.file_agent_runtime import media_vault
from services.file_agent_runtime import model_context
from services.workspace.content_store import ContentStore
from services.file_agent_runtime.model_context import (
    ModelContextBudgetError,
    _inline_media_relief,
    compact_conversation_history,
    plan_history_compaction,
    prepare_model_messages,
    render_archived_evidence,
)

pytestmark = pytest.mark.unit


def test_inline_media_is_charged_as_vision_tokens_not_base64_text():
    """A media-bearing contract message must fit the serialized budget.

    Regression guard: ``size()`` used to count the whole messages JSON as
    text, so one 2MB image inlined as a ~2.7MB Base64 data URL exceeded the
    384KB budget by itself. Media-bearing user messages are contract content
    that compaction may not drop, so the request was refused locally and never
    reached the provider — the understanding record just came back empty.
    """
    encoded = base64.b64encode(b"\x00" * (2 * 1024 * 1024)).decode()
    data_url = f"data:image/jpeg;base64,{encoded}"
    messages = [
        {"role": "system", "content": "项目创作契约"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "理解这张图"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    result = prepare_model_messages(messages, [])

    # Inline media is charged, never dropped or rewritten.
    assert result[1]["content"][1]["image_url"]["url"] == data_url
    assert result[0]["content"] == "项目创作契约"


def test_oversized_inline_media_is_still_refused():
    """The vision-token charge has a floor, so media is never free."""
    # 1MB decoded → charge = 1MB / 128 = 8KB, exactly the per-media floor.
    encoded = base64.b64encode(b"\x00" * (1024 * 1024)).decode()
    data_url = f"data:image/jpeg;base64,{encoded}"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    # Three floors are ~24KB of charged media. Under a 16KB budget nothing
    # fits and there is no droppable tool group, so the guard fails closed
    # instead of letting an oversized request reach the provider.
    with pytest.raises(ModelContextBudgetError):
        prepare_model_messages(messages, [], max_bytes=16 * 1024)


def test_long_production_compacts_automatic_history_but_keeps_human_input():
    human_sources = [
        "initial_goal",
        "user",
        "review_rejection_feedback",
        "custom",
    ]
    history = [
        {
            "role": "user",
            "source": source,
            "content": [{"type": "text", "text": f"{source}: 保留全部六集与对白"}],
        }
        for source in human_sources
    ]
    human_input = json.dumps(history, ensure_ascii=False)
    for index in range(80):
        history.append(
            {
                "role": "user",
                "source": (
                    "run_review_feedback"
                    if index % 2
                    else "render_review_feedback"
                ),
                "content": [
                    {
                        "type": "text",
                        "text": f"review-{index}:" + "自动审阅结果。" * 300,
                    },
                ],
            },
        )
    original = json.dumps(history, ensure_ascii=False)
    current = "继续第二集。不要重做已保留视频。"
    continuation = (
        "CONVERSATION_HISTORY_JSON="
        + original
        + "\n\nCURRENT_USER_REQUEST=\n"
        + current
    )
    result = prepare_model_messages(
        [
            {"role": "system", "content": "项目创作契约"},
            {"role": "user", "content": continuation},
        ],
        [],
    )
    assert len(json.dumps(result, ensure_ascii=False).encode()) < 384 * 1024
    view, request = result[1]["content"].split("\n\nCURRENT_USER_REQUEST=\n")
    retained = json.loads(view.split("CONVERSATION_HISTORY_JSON=", 1)[1])
    assert request == current
    assert [
        item for item in retained if item.get("source") in human_sources
    ] == [item | {"metadata": {}} for item in json.loads(human_input)]
    assert retained[-1] == history[-1] | {"metadata": {}}
    assert retained[0]["elidedMessageCount"] > 0
    assert json.dumps(history, ensure_ascii=False) == original

    # Genuine user requirements remain protected, even when they cannot fit.
    for item in history:
        item["source"] = "user"
    with pytest.raises(ModelContextBudgetError):
        prepare_model_messages(
            [
                {
                    "role": "user",
                    "content": "CONVERSATION_HISTORY_JSON="
                    + json.dumps(history, ensure_ascii=False)
                    + "\n\nCURRENT_USER_REQUEST=\n"
                    + current,
                },
            ],
            [],
        )


def test_inline_media_relief_is_additive_across_elided_slots():
    """Compaction carries relief incrementally, which needs additivity.

    ``compact_conversation_history`` no longer re-walks every message to
    recompute relief on each pass; it subtracts the item it just elided.
    That is only exact because relief sums over list items and an elided
    slot is worth zero, so the invariant itself is what this guards.
    """
    encoded = base64.b64encode(b"\x00" * (512 * 1024)).decode()
    media = {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }
    first = {"role": "user", "content": [media]}
    second = {"role": "user", "content": [media, media]}
    plain = {"role": "user", "content": "plain text"}
    history = [first, second, plain]

    whole = _inline_media_relief(history)
    assert whole == sum(_inline_media_relief(item) for item in history)
    assert _inline_media_relief(None) == 0

    elided = [first, None, plain]
    assert _inline_media_relief(elided) == whole - _inline_media_relief(
        second,
    )


def test_media_bearing_automatic_history_is_elided_under_budget():
    """Droppable reviews that carry inline media must actually leave.

    Pins the budget accounting where relief changes mid-loop. If the
    carried total were left un-decremented, ``json_bytes`` would shrink
    while relief stayed huge, the check would go negative, and
    compaction would stop after the first message — handing the provider
    a request still over budget instead of reaching it.
    """
    encoded = base64.b64encode(b"\x00" * (512 * 1024)).decode()
    media = {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }
    history = [
        {
            "role": "user",
            "source": "initial_goal",
            "content": [{"type": "text", "text": "保留全部六集与对白"}],
        },
    ]
    for index in range(6):
        history.append(
            {
                "role": "user",
                "source": "run_review_feedback",
                "content": [
                    {"type": "text", "text": f"review-{index}"},
                    # Two blocks, so even the cheapest remaining review still
                    # overflows this budget: the guard is that they all leave,
                    # not that compaction stops wherever pricing happens to
                    # allow a single one to linger.
                    media,
                    media,
                ],
            },
        )

    result = compact_conversation_history(history, max_bytes=4096)

    assert result[0]["source"] == "context_compaction"
    assert result[0]["elidedMessageCount"] == 6
    assert [item.get("source") for item in result[1:]] == ["initial_goal"]


def test_elided_turns_stay_recallable_by_seq():
    """A cut must stay an archive, not a hole nothing can read back.

    Reverse guard for the platform-scroll reuse: before it, compaction left
    only ``elidedMessageCount`` — an integer the model could not act on, so
    an early goal or decision that scrolled out was silently forgotten. Now
    the dropped turns are named by ``messageSeq`` oldest-first with a recall
    pointer, and the durable originals stay fetchable by ``recall_history``.
    """
    history = [
        {
            "role": "user",
            "source": "initial_goal",
            "messageSeq": 1,
            "content": [{"type": "text", "text": "保留全部六集与对白"}],
        },
    ]
    for index in range(6):
        history.append(
            {
                "role": "assistant",
                "source": "run_review_feedback",
                "messageSeq": 10 + index,
                "content": [
                    {"type": "text", "text": f"review-{index} " + "x" * 4096},
                ],
            },
        )

    result = compact_conversation_history(history, max_bytes=4096)

    elision = result[0]
    assert elision["source"] == "context_compaction"
    assert elision["elidedMessageCount"] > 0
    map_text = elision["archivedHistoryMap"]
    assert "[context compressed]" in map_text
    assert "recall_history" in map_text
    lo, hi = elision["recoverableSeqRange"]
    assert lo <= hi
    # The reused platform EvictionIndex lists evicted turns oldest-first,
    # either as individual ``· seq N`` lines (small archive) or folded to
    # per-block ``· seq lo–hi`` spans once the char budget is exceeded.
    # Parse whatever seq addresses appear and assert they stay ascending,
    # then assert both endpoints are named somewhere, so the contract holds
    # at every fold level instead of pinning one exact rendering format.
    marker = "\u00b7 seq "
    listed = [
        int(line.split(marker)[1].split()[0].split("\u2013")[0])
        for line in map_text.splitlines()
        if marker in line
    ]
    assert listed == sorted(listed)
    assert str(lo) in map_text and str(hi) in map_text


def test_archived_map_falls_back_to_local_format_without_host_index(
    monkeypatch,
):
    """A standalone install keeps the archive->recall contract.

    The platform odometer map is reused only when importable. With the host
    scroll absent, ``_render_archived_index`` must still hand back a
    ``[context compressed]`` map naming the durable seqs, so the reuse can
    never regress into the old silent hole.
    """
    monkeypatch.setattr(
        model_context,
        "_HOST_EVICTION_INDEX_AVAILABLE",
        False,
    )
    history = [
        {
            "role": "user",
            "source": "initial_goal",
            "messageSeq": 1,
            "content": [{"type": "text", "text": "keep all six episodes"}],
        },
    ]
    for index in range(6):
        history.append(
            {
                "role": "assistant",
                "source": "run_review_feedback",
                "messageSeq": 10 + index,
                "content": [
                    {"type": "text", "text": f"review-{index} " + "x" * 4096},
                ],
            },
        )

    elision = compact_conversation_history(history, max_bytes=4096)[0]
    map_text = elision["archivedHistoryMap"]
    assert "[context compressed]" in map_text
    assert "recall_history" in map_text
    # Local flat format uses ``seq . \u27e6headline\u27e7`` lines, not the
    # platform tier banners.
    assert any(" . \u27e6" in line for line in map_text.splitlines())
    assert "===== Tier" not in map_text
    lo, hi = elision["recoverableSeqRange"]
    assert (lo, hi) == (10, 15)


def test_archived_index_stays_recallable_when_the_map_folds():
    """A big archive must fold to per-block spans, not collapse to one line.

    Reverse guard for the stateless single-block regression: feeding the
    whole archive as one eviction block makes the platform drop it to a
    single endpoint line naming just the oldest and newest headlines the
    moment the char budget is exceeded - the recall pointers vanish exactly
    when the archive is largest. Splitting into per-block evictions keeps
    one span line per block, oldest-first, and Creator's own preamble
    replaces the host prose about a ``conversation_history`` table and an
    advanced recall tool a Creator session does not have.
    """
    archived = [
        {
            "seq": index,
            "role": "assistant",
            "source": "run_review_feedback",
            "content": [{"type": "text", "text": f"review turn {index}"}],
        }
        for index in range(1, 201)
    ]

    map_text, lo, hi = model_context._render_archived_index(archived)

    assert (lo, hi) == (1, 200)
    assert map_text.startswith("[context compressed]")
    assert "recall_history" in map_text
    # Host-specific prose must never leak into a Creator session's context.
    assert "conversation_history" not in map_text
    assert "advanced Python recall tool" not in map_text
    # Folded to one endpoint span per block: more than the single line a
    # one-block feed collapses to, and still ordered oldest-first.
    marker = "\u00b7 seq "
    spans = [line for line in map_text.splitlines() if marker in line]
    assert len(spans) > 1
    starts = [
        int(line.split(marker)[1].split()[0].split("\u2013")[0])
        for line in spans
    ]
    assert starts == sorted(starts)
    # The map rides on top of the byte gate, so it stays hard-bounded.
    assert len(map_text) <= (
        model_context.ARCHIVED_INDEX_CHAR_BUDGET
        + len(model_context._ARCHIVED_MAP_PREAMBLE)
        + 512
    )


def test_banner_less_host_render_reports_no_usable_body():
    """A host render without its banner has no body boundary to trust.

    ``_split_host_map_body`` slices at the first ``====`` banner. If a host
    upgrade changes the render and the banner disappears, the preamble and
    the body can no longer be told apart, so the caller must be told so
    instead of receiving prose naming a ``conversation_history`` table and
    an "advanced Python recall tool" a Creator session does not have.
    """
    host_render = (
        "[context compressed] The turns below were evicted from the live "
        "window but remain durable in conversation_history.\n"
        "\n"
        "For advanced recall (sessions, custom SQL) use a more advanced "
        "Python recall tool if one is available to you.\n"
        "1 . old turn\n"
    )

    assert model_context._split_host_map_body(host_render) is None


def test_banner_less_host_render_falls_back_to_creator_map(monkeypatch):
    """No banner means Creator draws its own map, not the host's prose.

    Prepending Creator's preamble to the whole host render would print the
    compression notice twice and promise a live-turn banner this call asks
    the host to omit. The data source is the same archived list, so the
    flat ``seq . headline`` map keeps every pointer without the prose.
    """

    class BannerlessLeaf:
        def __init__(self, *, seq, headline):
            self.seq = seq
            self.headline = headline

    class BannerlessIndex:
        def __init__(self, session_id):
            self.session_id = session_id

        def add_eviction(self, leaves, *, seq_lo, seq_hi):
            pass

        def render(self, **_kwargs):
            return (
                "[context compressed] The turns below were evicted from "
                "the live window but remain durable in "
                "conversation_history. The live turns follow after the "
                "banner at the end.\n"
                "For advanced recall (sessions, custom SQL) use a more "
                "advanced Python recall tool if one is available to you.\n"
                "1 . old turn\n"
            )

    monkeypatch.setattr(
        model_context,
        "_HOST_EVICTION_INDEX_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        model_context,
        "_HostEvictionIndex",
        BannerlessIndex,
    )
    monkeypatch.setattr(
        model_context,
        "_HostEvictionLeaf",
        BannerlessLeaf,
    )
    archived = [
        {
            "seq": 7,
            "role": "user",
            "source": "initial_goal",
            "content": [{"type": "text", "text": "keep the hero shot"}],
        },
    ]

    map_text, lo, hi = model_context._render_archived_index(archived)

    assert (lo, hi) == (7, 7)
    # Exactly one compression notice: Creator's own.
    assert map_text.count("[context compressed]") == 1
    assert "conversation_history" not in map_text
    assert "advanced Python recall tool" not in map_text
    assert "custom SQL" not in map_text
    assert "banner at the end" not in map_text
    # Creator's flat format carries the pointer the host prose dropped.
    assert "7 . \u27e6keep the hero shot\u27e7" in map_text


def test_continuation_summary_rides_on_the_elision_when_supplied():
    """The prose state cache is attached only when a caller produced one.

    Reverse guard for the platform-scroll reuse: the fourth relief lever is a
    continuation summary beside the recall map. Old compaction had no such
    argument at all (``TypeError`` here), and an unsolicited summary would put
    words in the marker the model never asked for — so absence must stay
    absence.
    """
    history = [
        {
            "role": "user",
            "source": "initial_goal",
            "messageSeq": 1,
            "content": [{"type": "text", "text": "keep all six episodes"}],
        },
    ]
    for index in range(6):
        history.append(
            {
                "role": "assistant",
                "source": "run_review_feedback",
                "messageSeq": 10 + index,
                "content": [
                    {"type": "text", "text": f"review-{index} " + "x" * 4096},
                ],
            },
        )

    without = compact_conversation_history(history, max_bytes=4096)
    assert "continuationSummary" not in without[0]

    summary = "## Active Task\nkeep six episodes\nStatus: in_progress\n"
    with_summary = compact_conversation_history(
        history,
        max_bytes=4096,
        continuation_summary=summary,
    )
    assert with_summary[0]["continuationSummary"] == summary
    # The recall map and the summary are complementary, never exclusive.
    assert "archivedHistoryMap" in with_summary[0]


def test_render_archived_evidence_bounds_covered_range_past_truncation():
    """A truncated preview must not shrink the range the summary may claim.

    The platform prompt is told the covered seq range is authoritative while
    the preview is bounded. If the bounds followed the truncated body instead
    of every archived turn, the model would be invited to forget the tail of
    the archived slice entirely.
    """
    archived = [
        {
            "seq": 10 + index,
            "role": "assistant",
            "source": "runtime_action_result",
            "content": [{"type": "text", "text": "y" * 2000}],
        }
        for index in range(12)
    ]

    evidence, (lo, hi) = render_archived_evidence(archived, max_chars=1500)

    assert (lo, hi) == (10, 21)
    # Truncation is real: the preview cannot hold all twelve turns.
    assert evidence.count("[seq:") < 12
    assert "[seq:10]" in evidence
    # And the planner exposes the same archived slice for it.
    _compacted, planned = plan_history_compaction(
        [
            {
                "role": "user",
                "source": "initial_goal",
                "messageSeq": 1,
                "content": [{"type": "text", "text": "anchor"}],
            },
            *(
                {
                    "role": "assistant",
                    "source": "run_review_feedback",
                    "messageSeq": 10 + index,
                    "content": [
                        {"type": "text", "text": "z" * 4096},
                    ],
                }
                for index in range(12)
            ),
        ],
        max_bytes=4096,
    )
    assert planned and all(isinstance(item["seq"], int) for item in planned)


@pytest.mark.parametrize(
    ("project_id", "generation", "superseded"),
    [
        ("project-1", None, False),
        ("project-1", 19, False),
        ("project-2", 21, False),
        ("project-1", 20, True),
        ("project-1", 21, True),
    ],
)
def test_new_snapshot_frees_history_space_for_script_and_skills(
    project_id,
    generation,
    superseded,
):
    human = "Keep all six episodes and the accepted films. " + "h" * 700
    previous = {
        "project": {"project_id": "project-1", "description": "old" * 5200},
        "generation": 20,
        "etag": "old-etag",
    }
    history = [
        {
            "role": "user",
            "source": "user",
            "content": [{"type": "text", "text": human}],
        },
        {
            "role": "tool",
            "content": [{"type": "text", "text": json.dumps(previous)}],
        },
    ]
    messages = [
        {"role": "system", "content": "s" * 9000},
        {
            "role": "user",
            "content": "CONVERSATION_HISTORY_JSON="
            + json.dumps(history)
            + "\n\nCURRENT_USER_REQUEST=\nContinue automatically.",
        },
    ]
    calls = []
    if generation is not None:
        calls.append(
            (
                "snapshot",
                json.dumps(
                    {
                        "project": {
                            "project_id": project_id,
                            "description": "current" * 700,
                        },
                        "generation": generation,
                        "etag": "current-etag",
                    },
                ),
            ),
        )
    calls.extend([("skill", "skill" * 1300), ("script", "script" * 1100)])
    for call_id, content in calls:
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "Read " + call_id,
                    "tool_calls": [
                        AgentToolCall(
                            call_id=call_id,
                            name="read_project",
                            arguments={},
                        ).history_dict(),
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": content,
                },
            ],
        )
    original = json.dumps(messages)
    result = prepare_model_messages(messages, [], max_bytes=32 * 1024)
    continuation = result[1]["content"]
    assert human in continuation
    assert continuation.endswith(
        "CURRENT_USER_REQUEST=\nContinue automatically.",
    )
    assert ("old" * 5200 in continuation) is not superseded
    if superseded:
        assert [m["tool_call_id"] for m in result if m["role"] == "tool"] == [
            "snapshot",
            "skill",
            "script",
        ]
    assert json.dumps(messages) == original


def _project_view_wire(count: int, *, first_generation: int = 0):
    """A run that keeps reading the Project: one exchange per turn."""
    messages = [
        {"role": "system", "content": "s" * 4000},
        {
            "role": "user",
            "source": "user",
            "content": "把六集分镜做完再交审阅",
        },
    ]
    for index in range(first_generation, first_generation + count):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "read_project",
                    "tool_calls": [
                        AgentToolCall(
                            call_id=f"read-{index}",
                            name="read_project",
                            arguments={},
                        ).history_dict(),
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"read-{index}",
                    "content": json.dumps(
                        {
                            "project": {
                                "project_id": "project-1",
                                "description": "d" * 9000,
                            },
                            "episodes": [
                                {"title": f"e{index}", "text": "t" * 600},
                            ],
                            "generation": index,
                            "etag": f"etag-{index}",
                        },
                    ),
                },
            ],
        )
    return messages


def _carried_views(sent):
    return [
        item for item in sent if model_context.is_carried_project_view(item)
    ]


def test_resuming_from_a_sent_turn_never_pins_a_second_project_view():
    """The compactor's carried view must not pile up when its output is fed
    back as the next turn's input.

    A run that resumes from the shape it last sent hands
    ``prepare_model_messages`` its own product. That view rides in the
    provider's user role, which compaction may never evict, and the marker
    naming it is stripped before the module returns — so recognizing the
    artifact by the marker alone pins one stale copy per turn until nothing
    left can move and the request refuses itself over bytes the runtime made.
    """
    budget = 16 * 1024
    wire = _project_view_wire(6)
    counts = []
    generations = []
    for turn in range(5):
        sent = prepare_model_messages(wire, [], max_bytes=budget)
        views = _carried_views(sent)
        counts.append(len(views))
        assert views, "a compacted turn must carry the newest project view"
        generations.append(
            json.loads(views[-1]["content"].partition("=")[2])["generation"],
        )
        # Exactly what adopting the sent shape does: the next turn resumes
        # from this list and answers with one more read.
        wire = list(sent)
        wire.extend(
            _project_view_wire(1, first_generation=20 + turn)[-2:],
        )
    assert counts == [1, 1, 1, 1, 1]
    assert generations == sorted(set(generations))


def test_second_compression_on_plain_text_result_keeps_the_carried_view():
    """A second compaction triggered by a non-snapshot tool result must not
    drop the only surviving project view.

    Reproduce the review finding: multiple ``read_project`` calls compact
    into a carried view; the next turn answers with a plain text tool
    result (no ``project`` payload). Pre-fix, the loop strips every
    ``is_carried_project_view`` row and then skips re-attaching because
    ``carried_snapshot`` is ``None`` — the model continues with no project
    state. Post-fix, the strip only runs when there is a replacement.
    """
    budget = 16 * 1024
    sent_1 = prepare_model_messages(
        _project_view_wire(6),
        [],
        max_bytes=budget,
    )
    first_views = _carried_views(sent_1)
    assert len(first_views) == 1
    gen_1 = json.loads(
        first_views[0]["content"].partition("=")[2],
    )["generation"]

    # One plain text tool exchange — big enough to reopen the loop, but
    # its result is not a project snapshot.
    follow_up = [
        {
            "role": "assistant",
            "content": "check_media",
            "tool_calls": [
                AgentToolCall(
                    call_id="plain-1",
                    name="check_media",
                    arguments={},
                ).history_dict(),
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "plain-1",
            "content": "x" * (budget + 4096),
        },
    ]
    sent_2 = prepare_model_messages(
        list(sent_1) + follow_up,
        [],
        max_bytes=budget,
    )
    views = _carried_views(sent_2)
    assert len(views) == 1, (
        "the newest project view must survive a second compression "
        "triggered by a non-snapshot tool result"
    )
    gen_2 = json.loads(views[0]["content"].partition("=")[2])["generation"]
    assert gen_2 == gen_1


def test_the_carried_view_is_recognized_after_it_leaves_the_compactor():
    """A view survives as its prefix alone, and that is what identifies it.

    The demotion ladder and the driver both re-prepare what a previous step
    already produced, so the artifact has to be recognizable by a consumer
    that never sees the marker.
    """
    sent = prepare_model_messages(
        _project_view_wire(6),
        [],
        max_bytes=16 * 1024,
    )
    views = _carried_views(sent)
    assert len(views) == 1
    assert "_context_snapshot" not in views[0]
    for item in sent:
        assert model_context.is_carried_project_view(item) is (item in views)


def _configure_text_model(
    monkeypatch: pytest.MonkeyPatch,
    *,
    protocol: str = "",
) -> None:
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_api_key",
        lambda: "test-api-key",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: "https://model.example/v1",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_model_name",
        lambda: "qwen3.7-plus",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_protocol",
        lambda: protocol,
    )


def _tools() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_project",
                "parameters": {
                    "type": "object",
                    "properties": {"projectId": {"type": "string"}},
                    "required": ["projectId"],
                },
            },
        },
    ]


def test_default_client_constructs_real_agentscope_dashscope_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_text_model(monkeypatch)

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, DashScopeChatModel)


@pytest.mark.parametrize(
    ("model_name", "expected_temperature"),
    [("qwen3.7-plus", 0.2), ("kimi-k3", None)],
)
def test_kimi_k3_omits_unsupported_temperature(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    expected_temperature: float | None,
) -> None:
    # DashScope rejects an explicit ``temperature`` for kimi-k3, so the client
    # must drop it and let the gateway apply the model default; every other
    # model keeps the Creator sampling default.
    _configure_text_model(monkeypatch)
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_model_name",
        lambda: model_name,
    )

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, DashScopeChatModel)
    assert configured.parameters.temperature == expected_temperature


def test_temperature_refusal_rebuilds_cached_model_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A first-turn refusal must invalidate the cached model so the *next*
    # Agent turn is rebuilt without a temperature. ``_configured_model()``
    # keys only on the connection tuple, which the capability flip does not
    # change, so the client has to drop ``model``/``_configuration`` itself.
    # pylint: disable=protected-access
    from models.model_capability_cache import get_capability_cache

    model_config = model_client.model_config
    _configure_text_model(monkeypatch)
    monkeypatch.setattr(
        model_config,
        "get_text_model_name",
        lambda: "brand-new-model",
    )
    cache = get_capability_cache()
    key = model_config._temperature_capability_key("brand-new-model")
    cache.clear(key)
    try:
        client = AgentScopeAgentChatClient()
        first = client._configured_model()
        assert isinstance(first, DashScopeChatModel)
        # Before any refusal the sampling default is still sent.
        assert first.parameters.temperature == 0.2

        async def _refuse(self, *_args, **_kwargs):
            raise RuntimeError(
                "Parameter 'temperature'=0.2 is not supported "
                "for brand-new-model",
            )

        monkeypatch.setattr(DashScopeChatModel, "__call__", _refuse)
        with pytest.raises(AgentModelError):
            asyncio.run(
                client.complete(
                    messages=[{"role": "user", "content": "ping"}],
                    tools=[],
                ),
            )

        # The refusal was learned and the cached model dropped, so the next
        # turn rebuilds and omits the temperature entirely.
        assert model_config.chat_temperature("brand-new-model", 0.2) is None
        assert client.model is None
        second = client._configured_model()
        assert second is not first
        assert second.parameters.temperature is None
    finally:
        cache.clear(key)


@pytest.mark.parametrize(
    ("protocol", "base_url"),
    [
        ("Anthropic Claude", "https://api.anthropic.com"),
        ("MiniMax", "https://api.minimaxi.com/anthropic"),
    ],
)
def test_anthropic_compatible_protocol_constructs_anthropic_chat_model(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    base_url: str,
) -> None:
    from agentscope.model import AnthropicChatModel

    _configure_text_model(monkeypatch, protocol=protocol)
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: base_url,
    )
    assert isinstance(
        AgentScopeAgentChatClient()._configured_model(),
        AnthropicChatModel,
    )


def test_anthropic_agent_uses_model_limit_instead_of_sdk_default(monkeypatch):
    _configure_text_model(monkeypatch, protocol="Anthropic Claude")
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_model_name",
        lambda: "MiniMax-M2.7",
    )
    client = AgentScopeAgentChatClient()
    configured = client._configured_model()
    captured = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("request captured before transport")

    monkeypatch.setattr(configured.client.messages, "create", capture)
    with pytest.raises(AgentModelError, match="request captured"):
        asyncio.run(
            client.complete(
                messages=[{"role": "user", "content": "ping"}],
                tools=[],
            ),
        )
    assert captured["max_tokens"] == 204800


def test_gemini_protocol_constructs_gemini_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscope.model import GeminiChatModel

    _configure_text_model(
        monkeypatch,
        protocol="Google Gemini",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: "https://generativelanguage.googleapis.com",
    )

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, GeminiChatModel)


def test_history_is_rehydrated_as_agentscope_tool_blocks() -> None:
    messages = records_to_agentscope_messages(
        [
            {"role": "system", "content": "schema"},
            {"role": "user", "content": "读取项目"},
            {
                "role": "assistant",
                "content": "先读取。",
                "tool_calls": [
                    {
                        "id": "call-read-1",
                        "type": "function",
                        "function": {
                            "name": "read_project",
                            "arguments": '{"projectId":"project-1"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-read-1",
                "name": "read_project",
                "content": '{"ok":false}',
                "failed": True,
            },
        ],
    )

    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"
    call = messages[2].content[-1]
    assert isinstance(call, ToolCallBlock)
    assert call.id == "call-read-1"
    assert call.name == "read_project"
    assert json.loads(call.input) == {"projectId": "project-1"}
    assert messages[3].role == "assistant"
    result = messages[3].content[0]
    assert isinstance(result, ToolResultBlock)
    assert result.id == call.id
    assert result.name == call.name
    assert result.output == '{"ok":false}'
    assert result.state == ToolResultState.ERROR.value


def test_vlm_anthropic_protocol_constructs_anthropic_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscope.model import AnthropicChatModel

    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_api_key",
        lambda: "vlm-key",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_base_url",
        lambda: "https://api.anthropic.com",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_model_name",
        lambda: "claude-sonnet-4-20250514",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_timeout_seconds",
        lambda: 180,
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_protocol",
        lambda: "Anthropic Claude",
    )

    configured = AgentScopeVlmChatClient()._configured_model()

    assert isinstance(configured, AnthropicChatModel)


def test_agentscope_client_streams_native_blocks_and_raw_argument_deltas() -> (
    None
):
    class StreamingAgentScopeModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.messages = None
            self.tools = None

        async def __call__(self, messages, *, tools=None):
            self.messages = messages
            self.tools = tools

            async def chunks():
                yield ChatResponse(
                    id="response-stream-1",
                    content=[
                        ThinkingBlock(thinking="先"),
                        TextBlock(text="项目"),
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='{"project',
                        ),
                    ],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-stream-1",
                    content=[
                        ThinkingBlock(thinking="分析"),
                        TextBlock(text="已读取"),
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='Id":"project-1"}',
                        ),
                    ],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-stream-1",
                    content=[
                        ThinkingBlock(thinking="先分析"),
                        TextBlock(text="项目已读取"),
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='{"projectId":"project-1"}',
                        ),
                    ],
                    is_last=True,
                )

            return chunks()

    text_deltas: list[str] = []
    thinking_deltas: list[str] = []
    tool_deltas: list[tuple[str, str, str]] = []

    async def on_text_delta(delta: str) -> None:
        text_deltas.append(delta)

    async def on_thinking_delta(delta: str) -> None:
        thinking_deltas.append(delta)

    async def on_tool_call_delta(
        call_id: str,
        name: str,
        arguments_delta: str,
    ) -> None:
        tool_deltas.append((call_id, name, arguments_delta))

    async def scenario():
        provider = StreamingAgentScopeModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        turn = await client.complete(
            messages=[
                {"role": "system", "content": "schema"},
                {"role": "user", "content": "读取项目"},
            ],
            tools=_tools(),
            on_text_delta=on_text_delta,
            on_thinking_delta=on_thinking_delta,
            on_tool_call_delta=on_tool_call_delta,
        )
        return provider, turn

    provider, turn = asyncio.run(scenario())

    assert provider.messages is not None
    assert [message.role for message in provider.messages] == [
        "system",
        "user",
    ]
    assert provider.tools == _tools()
    assert turn == AgentModelTurn(
        content="项目已读取",
        thinking="先分析",
        tool_calls=(
            AgentToolCall(
                call_id="call-read-1",
                name="read_project",
                arguments={"projectId": "project-1"},
            ),
        ),
        provider_message_id="response-stream-1",
    )
    assert text_deltas == ["项目", "已读取"]
    assert thinking_deltas == ["先", "分析"]
    assert tool_deltas == [
        ("call-read-1", "read_project", '{"project'),
        ("call-read-1", "read_project", 'Id":"project-1"}'),
    ]
    assert turn.tool_calls[0].raw_arguments == '{"projectId":"project-1"}'
    assert turn.tool_calls[0].raw_arguments_bytes == 25
    assert turn.tool_calls[0].provider_chunk_count == 2
    assert turn.finish_reason == "completed"


@pytest.mark.parametrize("ending", ["text", "tool", "final", "provider_error"])
def test_thinking_chunks_are_coalesced_without_losing_order_or_tail(
    monkeypatch,
    ending,
):
    clock = [0.0]
    monkeypatch.setattr(model_client, "monotonic", lambda: clock[0])
    fragments = [f"片段{i:03d}。" for i in range(120)]
    observed = []

    async def thinking(delta):
        observed.append(("thinking", delta))

    async def text(delta):
        observed.append(("text", delta))

    async def tool(_call_id, _name, delta):
        observed.append(("tool", delta))

    class Provider:
        calls = 0

        async def __call__(self, _messages, *, tools=None):
            self.calls += 1

            async def chunks():
                for fragment in fragments:
                    clock[0] += 0.01
                    yield ChatResponse(
                        id="coalesced",
                        is_last=False,
                        content=[ThinkingBlock(thinking=fragment)],
                    )
                if ending == "provider_error":
                    raise ValueError("invalid provider response")
                result = (
                    ToolCallBlock(
                        id="read",
                        name="read_project",
                        input="{}",
                    )
                    if ending == "tool"
                    else TextBlock(text="完成")
                )
                if ending != "final":
                    yield ChatResponse(
                        id="coalesced",
                        is_last=False,
                        content=[result],
                    )
                yield ChatResponse(
                    id="coalesced",
                    is_last=True,
                    content=[
                        ThinkingBlock(thinking="".join(fragments)),
                        result,
                    ],
                )

            return chunks()

    async def scenario():
        provider = Provider()
        request = AgentScopeAgentChatClient(provider).complete(
            messages=[],
            tools=_tools(),
            on_thinking_delta=thinking,
            on_text_delta=text,
            on_tool_call_delta=tool,
        )
        if ending == "provider_error":
            with pytest.raises(
                AgentModelError,
                match="invalid provider response",
            ):
                await request
        else:
            turn = await request
            assert turn.thinking == "".join(fragments)
        assert provider.calls == 1

    asyncio.run(scenario())
    thinking_parts = [delta for kind, delta in observed if kind == "thinking"]
    assert "".join(thinking_parts) == "".join(fragments)
    assert thinking_parts[0] == fragments[0]  # First activity is immediate.
    assert len(thinking_parts) == 4  # 120 durable writes become four.
    if ending in {"text", "tool"}:
        assert all(kind == "thinking" for kind, _ in observed[:-1])
        assert observed[-1][0] == ending


@pytest.mark.parametrize("failure", ["cancel", "persistence"])
def test_buffered_thinking_preserves_stop_and_persistence_failures(failure):
    observed = []

    async def callback(delta):
        observed.append(delta)
        if delta == "tail" and failure == "persistence":
            raise OSError("disk write failed")

    class Provider:
        calls = 0

        async def __call__(self, _messages, *, tools=None):
            self.calls += 1

            async def chunks():
                for delta in ("first", "tail"):
                    yield ChatResponse(
                        id="stopped",
                        is_last=False,
                        content=[ThinkingBlock(thinking=delta)],
                    )
                if failure == "cancel":
                    raise asyncio.CancelledError()
                yield ChatResponse(
                    id="stopped",
                    is_last=True,
                    content=[TextBlock(text="finished")],
                )

            return chunks()

    async def scenario():
        provider = Provider()
        expected = (
            asyncio.CancelledError
            if failure == "cancel"
            else AgentStreamCallbackError
        )
        with pytest.raises(expected):
            await AgentScopeAgentChatClient(provider).complete(
                messages=[],
                tools=[],
                on_thinking_delta=callback,
            )
        assert provider.calls == 1

    asyncio.run(scenario())
    assert observed == (
        ["first"] if failure == "cancel" else ["first", "tail"]
    )


def test_agentscope_client_repairs_truncated_native_tool_argument_json() -> (
    None
):
    class MalformedToolArgumentsModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            return ChatResponse(
                id="response-repaired-tool",
                content=[
                    ToolCallBlock(
                        id="call-read-repaired",
                        name="read_project",
                        input='{"projectId":"project-1","baseEtag":"etag-truncated',
                    ),
                ],
                is_last=True,
            )

    async def scenario() -> AgentModelTurn:
        client = AgentScopeAgentChatClient(
            MalformedToolArgumentsModel(),  # type: ignore[arg-type]
        )
        return await client.complete(
            messages=[{"role": "user", "content": "读取项目"}],
            tools=_tools(),
        )

    turn = asyncio.run(scenario())

    assert turn.tool_calls == (
        AgentToolCall(
            call_id="call-read-repaired",
            name="read_project",
            arguments={
                "projectId": "project-1",
                "baseEtag": "etag-truncated",
            },
        ),
    )
    repaired_call = turn.tool_calls[0]
    assert repaired_call.arguments_repaired is True
    assert repaired_call.raw_arguments_bytes == len(
        '{"projectId":"project-1","baseEtag":"etag-truncated'.encode(
            "utf-8",
        ),
    )
    assert repaired_call.strict_json_error is not None


def _final_tool_call_model(raw_input: str):
    class FinalToolCallModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            async def chunks():
                yield ChatResponse(
                    id="response-broken-1",
                    content=[
                        ToolCallBlock(
                            id="call-jq-1",
                            name="read_project",
                            input=raw_input,
                        ),
                    ],
                    is_last=True,
                )

            return chunks()

    return FinalToolCallModel()


def test_unrecoverable_tool_arguments_degrade_to_parse_error() -> None:
    async def scenario():
        client = AgentScopeAgentChatClient(
            _final_tool_call_model('"oops'),  # type: ignore[arg-type]
        )
        return await client.complete(messages=[], tools=_tools())

    turn = asyncio.run(scenario())
    call = turn.tool_calls[0]
    assert call.arguments == {}
    assert call.parse_error is not None
    assert "无法自动修复" in call.parse_error
    assert "oops" in call.parse_error


def test_agentscope_client_preserves_stream_control_exceptions() -> None:
    class StreamingAgentScopeModel:
        model = "qwen3.7-plus"

        async def __call__(self, _messages, *, tools=None):
            del tools

            async def chunks():
                yield ChatResponse(
                    id="response-control",
                    content=[TextBlock(text="部分输出")],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-control",
                    content=[TextBlock(text="完整输出")],
                    is_last=True,
                )

            return chunks()

    class StopStreaming(AgentStreamCallbackPassthrough):
        pass

    async def stop(_delta: str) -> None:
        raise StopStreaming("run revoked")

    async def scenario() -> None:
        client = AgentScopeAgentChatClient(StreamingAgentScopeModel())  # type: ignore[arg-type]
        with pytest.raises(StopStreaming, match="run revoked"):
            await client.complete(
                messages=[{"role": "user", "content": "开始"}],
                tools=[],
                on_text_delta=stop,
            )

    asyncio.run(scenario())


def test_agentscope_client_returns_unknown_native_tool_for_model_correction() -> (
    None
):
    class UnknownToolModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            return ChatResponse(
                id="response-unknown-tool",
                content=[
                    ToolCallBlock(
                        id="call-unknown",
                        name="invented_tool",
                        input='{"projectId":"project-1"}',
                    ),
                ],
                is_last=True,
            )

    async def scenario():
        client = AgentScopeAgentChatClient(  # type: ignore[arg-type]
            UnknownToolModel(),
        )
        return await client.complete(
            messages=[{"role": "user", "content": "读取"}],
            tools=_tools(),
        )

    turn = asyncio.run(scenario())
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "invented_tool"
    assert turn.tool_calls[0].arguments == {"projectId": "project-1"}


@pytest.mark.parametrize(
    "markup",
    [
        "<function=glob_search><parameter=pattern>story/outline.md</parameter></function>",
        '<tool_call>{"name":"read_project","arguments":{}}</tool_call>',
    ],
)
def test_agentscope_client_rejects_textual_tool_markup_before_text_callback(
    markup: str,
) -> None:
    class TextualToolModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            self.calls += 1
            return ChatResponse(
                id="response-text-tool",
                content=[TextBlock(text=markup)],
                is_last=True,
            )

    text_deltas: list[str] = []

    async def collect(delta: str) -> None:
        text_deltas.append(delta)

    async def scenario() -> TextualToolModel:
        provider = TextualToolModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        with pytest.raises(AgentModelError, match="ToolCallBlock"):
            await client.complete(
                messages=[{"role": "user", "content": "读取"}],
                tools=_tools(),
                on_text_delta=collect,
            )
        return provider

    provider = asyncio.run(scenario())
    # Markup degradation is stochastic, so the turn is retried before the
    # run is failed: original attempt plus four retries.
    assert provider.calls == 5
    assert text_deltas == []


def test_callback_client_keeps_stream_callback_failures_outside_model_errors() -> (
    None
):
    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="即将持久化")

    async def fail_persistence(_delta: str) -> None:
        raise OSError("runtime lock timeout")

    async def scenario() -> None:
        with pytest.raises(AgentStreamCallbackError) as raised:
            await CallbackAgentChatClient(callback).complete(
                messages=[{"role": "user", "content": "开始"}],
                tools=[],
                on_text_delta=fail_persistence,
            )
        assert isinstance(raised.value.cause, OSError)
        assert str(raised.value.cause) == "runtime lock timeout"

    asyncio.run(scenario())


def test_agentscope_client_retries_rate_limited_turns_until_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_client,
        "_rate_limit_retry_delay",
        lambda _attempt: 0.0,
    )

    class ThrottledModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages, *, tools=None):
            del messages, tools
            self.calls += 1
            raise RuntimeError(
                "<429> Throttling.RateQuota: Requests rate limit exceeded",
            )

    notices: list[RateLimitRetryNotice] = []

    async def on_retry(notice: RateLimitRetryNotice) -> None:
        notices.append(notice)

    async def scenario():
        provider = ThrottledModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        with pytest.raises(RateLimitExhaustedError) as raised:
            await client.complete(
                messages=[{"role": "user", "content": "开始"}],
                tools=_tools(),
                on_rate_limit_retry=on_retry,
            )
        return provider, raised.value

    provider, error = asyncio.run(scenario())

    # One original attempt plus every retry, then the run is given up on.
    assert provider.calls == MAX_RATE_LIMIT_RETRIES + 1
    assert error.retries == MAX_RATE_LIMIT_RETRIES
    assert [(notice.attempt, notice.max_attempts) for notice in notices] == [
        (attempt, MAX_RATE_LIMIT_RETRIES) for attempt in range(1, 6)
    ]


@pytest.mark.parametrize(
    "failure, delays, reason",
    [
        ("429 Too Many Requests", [2, 4], "rate_limit"),
        ("Connection reset by peer", [1], "transient"),
        ("empty", [0], "empty_response"),
    ],
    ids=["rate-limit", "connection-reset", "empty-response"],
)
def test_model_retry_recovery_reports_real_cause_and_backoff(
    monkeypatch,
    failure,
    delays,
    reason,
):
    notices = []
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(model_client.asyncio, "sleep", sleep)

    class RecoveringModel:
        model = "test-model"
        calls = 0

        async def __call__(self, messages, *, tools=None):
            self.calls += 1
            if self.calls <= len(delays):
                if failure == "empty":
                    return ChatResponse(id="empty", content=[], is_last=True)
                raise RuntimeError(failure)
            return ChatResponse(
                id="recovered",
                content=[TextBlock(text="继续生成")],
                is_last=True,
            )

    async def on_retry(notice):
        notices.append(notice)

    provider = RecoveringModel()
    result = asyncio.run(
        AgentScopeAgentChatClient(provider).complete(
            messages=[{"role": "user", "content": "继续"}],
            tools=_tools(),
            on_rate_limit_retry=on_retry,
        ),
    )
    assert result.content == "继续生成"
    assert provider.calls == len(delays) + 1
    assert [(n.reason, n.attempt, n.delay_seconds) for n in notices] == [
        (reason, attempt, delay) for attempt, delay in enumerate(delays, 1)
    ]
    assert sleeps == [delay for delay in delays if delay]


def test_inline_media_relief_gates_plain_text_but_prices_embedded_base64(
    monkeypatch,
):
    """Text drops out on a substring test; buried media is priced as media.

    The estimate walks the whole history every turn, so descending into
    strings is only safe when ordinary text is rejected without touching
    the regex. And a base64 payload hidden in a string is something the
    demotion walk retires, so it must not be billed at full text length -
    the inconsistency this replaced.
    """
    charges: list[str] = []
    original_charge = model_context._data_url_charge

    def spy(url, *, budget_bytes=model_context.MODEL_INPUT_BYTES):
        charges.append(url)
        return original_charge(url, budget_bytes=budget_bytes)

    monkeypatch.setattr(model_context, "_data_url_charge", spy)

    # Pure conversation text: relief is zero and the pricing regex never
    # even runs, so a megabyte serialized script costs one substring check.
    text_history = [
        {"role": "user", "content": "beat sheet " * 4000},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "notes " * 4000}],
        },
    ]
    assert _inline_media_relief(text_history) == 0
    assert charges == []

    # The gap this closes: a data URL buried in a string is now priced the
    # same as the identical URL under a ``url`` key - i.e. the same set the
    # demotion walk would strip.
    encoded = base64.b64encode(b"\x00" * (256 * 1024)).decode()
    url = f"data:image/jpeg;base64,{encoded}"
    embedded = _inline_media_relief(
        [{"role": "user", "content": f"tool answer: {url}"}],
    )
    keyed = _inline_media_relief(
        [{"role": "user", "content": {"url": url}}],
    )
    assert embedded == keyed > 0


def test_one_huge_screenshot_can_no_longer_refuse_its_own_request():
    """A single media block must never outgrow the entire input budget.

    Regression guard: the inline-media ceiling was an absolute 512KB, which
    is larger than ``MODEL_INPUT_BYTES`` itself. One big screenshot therefore
    overflowed the request all by itself, while compaction was forbidden from
    dropping the contract message carrying it — the turn got refused locally
    and never reached the provider.
    """
    encoded = base64.b64encode(b"\x00" * (8 * 1024 * 1024)).decode()
    data_url = f"data:image/png;base64,{encoded}"
    messages = [
        {"role": "system", "content": "项目创作契约"},
        {
            "role": "user",
            "source": "user",
            "content": [
                {"type": "text", "text": "理解这张图"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    result = prepare_model_messages(messages, [])

    # It fits now, and nothing about the human attachment was rewritten.
    assert result[1]["content"][1]["image_url"]["url"] == data_url
    ceiling = model_context._media_charge_bounds(
        model_context.MODEL_INPUT_BYTES,
    )[1]
    assert ceiling < model_context.MODEL_INPUT_BYTES


def test_derived_inline_media_demotes_to_a_pointer_and_spares_human_input():
    """Only media a tool produced can leave; a human attachment cannot."""
    encoded = base64.b64encode(b"\x00" * (4 * 1024 * 1024)).decode()
    data_url = f"data:image/jpeg;base64,{encoded}"
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call-frame",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
        {
            "role": "user",
            "source": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    result, receipt = model_context.demote_derived_inline_media(messages)

    stub = result[0]["content"][0]["text"]
    assert result[0]["content"][0]["type"] == "text"
    assert "image/jpeg" in stub
    assert "fingerprint=sha256:" in stub
    # The human upload stays byte-for-byte: no durable handle exists yet.
    assert result[1]["content"][0]["image_url"]["url"] == data_url
    assert receipt["demoted_blocks"] == 1
    assert receipt["human_attachment_blocks"] == 1


def test_media_inside_a_serialized_string_is_counted_as_the_media_it_is():
    """Census, demotion and the byte estimate now agree on embedded media.

    A payload a tool answered as plain text used to be billed at its full
    Base64 length and reported as no inline media, even though the demotion
    walk rewrites every string it passes and would happily trade it. The
    byte estimate now walks strings with the same pattern demotion uses, so
    a payload that can leave the history is priced as the media it is -
    which is both what a refusal can name and what a request pays.
    """
    encoded = base64.b64encode(b"\x00" * (2 * 1024 * 1024)).decode()
    data_url = f"data:image/jpeg;base64,{encoded}"
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call-frame",
            "content": json.dumps({"resultKind": "frame", "url": data_url}),
        },
        {
            "role": "user",
            "source": "user",
            "content": [{"type": "text", "text": data_url}],
        },
    ]

    blocks = model_context.collect_inline_media(messages)

    assert len(blocks) == 2
    assert {block["mime"] for block in blocks} == {"image/jpeg"}

    _result, receipt = model_context.demote_derived_inline_media(
        messages,
        vault=lambda _url: "h" * 64,
    )

    # One block traded and one kept as a person's, which is the census total: a
    # report that could not add up would be a guess about the request.
    assert receipt["demoted_blocks"] == 1
    assert receipt["human_attachment_blocks"] == 1
    traded = receipt["demoted_blocks"] + receipt["human_attachment_blocks"]
    assert traded == len(blocks)

    with pytest.raises(ModelContextBudgetError) as caught:
        prepare_model_messages(messages, [], max_bytes=16 * 1024)

    info = caught.value.diagnostics
    assert info["media_block_count"] == 2
    assert info["media_blocks"][0]["mime"] == "image/jpeg"
    # The embedded payload is now billed as the same media charge the census
    # reports and the ladder would retire, not at full Base64 text length:
    # relief equals (raw url length - one media charge) for each part.
    charge = model_context._data_url_charge(data_url, budget_bytes=16 * 1024)
    assert info["used_bytes"] < info["raw_bytes"]
    assert info["used_bytes"] == info["raw_bytes"] - 2 * (
        len(data_url) - charge
    )


def test_budget_failure_names_the_blocks_that_overflowed():
    """A refusal has to say what it blamed, not just that it refused."""
    encoded = base64.b64encode(b"\x00" * (1024 * 1024)).decode()
    data_url = f"data:image/jpeg;base64,{encoded}"
    media = {"type": "image_url", "image_url": {"url": data_url}}
    messages = [
        {"role": "user", "source": "user", "content": [media, media, media]},
    ]

    with pytest.raises(ModelContextBudgetError) as caught:
        prepare_model_messages(messages, [], max_bytes=16 * 1024)

    info = caught.value.diagnostics
    assert info["media_block_count"] == 3
    assert info["max_bytes"] == 16 * 1024
    assert info["used_bytes"] > info["max_bytes"]
    assert (
        info["media_blocks"][0]["charge"] == info["media_blocks"][-1]["charge"]
    )
    text = model_context.format_budget_failure(caught.value)
    assert "内联媒体 3 块" in text
    assert "image/jpeg" in text
    assert "user 16" in text or "user" in text


def test_media_clamp_ratio_env_cannot_disable_the_guard(monkeypatch):
    """The escape hatch tunes the ceiling; nonsense falls back to default."""
    monkeypatch.setenv("CREATOR_MEDIA_CLAMP_RATIO", "0.25")
    assert model_context._media_charge_bounds(100_000)[1] == 25_000
    for broken in ("0", "-1", "abc", ""):
        if broken:
            monkeypatch.setenv("CREATOR_MEDIA_CLAMP_RATIO", broken)
        else:
            monkeypatch.delenv("CREATOR_MEDIA_CLAMP_RATIO", raising=False)
        assert model_context._media_charge_bounds(100_000)[1] == 50_000


def test_a_tiny_clamp_ratio_cannot_price_a_screenshot_at_nothing(monkeypatch):
    """A legal-but-small share is clamped, never taken as "this media is free".

    0.0001 passes the sanity check, and multiplying the budget by it used to
    charge a 3840x2160 screenshot for a few dozen bytes - the guard then
    concluded there was room left for any number of images and the provider
    refused the request. The floor the same function documents has to survive
    the tuning knob.
    """
    monkeypatch.setenv("CREATOR_MEDIA_CLAMP_RATIO", "0.0001")
    budget = model_context.MODEL_INPUT_BYTES
    floor, ceiling = model_context._media_charge_bounds(budget)

    assert ceiling == int(budget * model_context.MIN_MEDIA_CLAMP_RATIO)
    assert floor == model_context._INLINE_MEDIA_MIN_BYTES

    charge = model_context._data_url_charge(
        _screenshot_data_url(3840, 2160),
        budget_bytes=budget,
    )
    assert charge == floor
    # A finite number of floor-priced blocks still has to be able to overflow
    # the budget; otherwise the knob has turned the media invisible.
    assert budget // charge < 100


def _screenshot_data_url(width: int, height: int) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (120, 120, 120)).save(
        buffer,
        format="PNG",
    )
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


@pytest.mark.skipif(
    not model_context._HOST_CONTEXT_ESTIMATOR_AVAILABLE,
    reason="host estimator is optional for standalone plugin installs",
)
def test_media_is_priced_by_the_hosts_vision_estimate():
    """One shared answer for "what will this image cost".

    The byte conversion saw a 3840x2160 screenshot as roughly 2K tokens, so a
    compactor watching it kept concluding there was room left. The host
    estimate counts Qwen-VL 28px patches and puts the same image near 11.8K.
    """
    from qwenpaw.agents.utils.media_token_estimate import (
        estimate_data_url_tokens,
    )

    data_url = _screenshot_data_url(3840, 2160)

    assert model_context._data_url_tokens(
        data_url,
    ) == estimate_data_url_tokens(data_url)
    # Explicitly above what the old /4 byte conversion could ever report.
    assert estimate_data_url_tokens(data_url) > 8_192 // 4


def test_token_budget_compacts_what_the_byte_guard_cannot_see():
    """A request can be small on the wire and enormous to the model.

    Inline media is floored in the byte budget, so a 4K screenshot plus one
    completed tool exchange stays well under 384KB while costing the provider
    tens of thousands of tokens. Only the window guard removes the exchange.
    """
    data_url = _screenshot_data_url(3840, 2160)
    verbose_result = "镜头描述 " * 12_000
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "read"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": verbose_result,
        },
        {
            "role": "user",
            "source": "user",
            "content": [
                {"type": "text", "text": "看这张图"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    # Without the window guard the exchange stays: bytes never crossed.
    unguarded = prepare_model_messages(messages, [])
    assert [item["role"] for item in unguarded].count("tool") == 1

    guarded = prepare_model_messages(messages, [], max_tokens=20_000)
    assert [item["role"] for item in guarded].count("tool") == 0
    assert model_context.estimate_input_tokens(guarded) <= 20_000


def test_input_token_budget_resolves_from_host_catalog(monkeypatch):
    """The host catalog provides the context window; env override wins.

    Before the host catalog was read the token guard stayed off until an
    operator declared a window, which left the byte transport floor as the
    sole limit.  The plugin now resolves the same published window the
    platform scroll uses, so every deployment prices against one ceiling.
    An explicit env still takes precedence, and junk values fall through
    to the catalog (or None when the host package is absent).
    """
    client = AgentScopeAgentChatClient.__new__(AgentScopeAgentChatClient)
    monkeypatch.delenv(
        model_context.MODEL_CONTEXT_TOKENS_ENV,
        raising=False,
    )
    budget = client._input_token_budget()
    if model_context._HOST_CONTEXT_WINDOW_AVAILABLE:
        assert budget is not None and budget > 0
    else:
        # Standalone plugin install without the host package.
        assert budget is None

    # An explicit env override still wins.
    monkeypatch.setenv(model_context.MODEL_CONTEXT_TOKENS_ENV, "32000")
    # Reserve: min(4096, max(1, int(32000 * 0.05))) = min(4096, 1600) = 1600
    assert client._input_token_budget() == 32000 - 1600

    monkeypatch.setenv(model_context.MODEL_CONTEXT_TOKENS_ENV, "8192")
    # Reserve: min(4096, max(1, int(8192 * 0.05))) = min(4096, 409) = 409
    assert client._input_token_budget() == 8192 - 409

    for junk in ("", "   ", "0", "-1", "thirty two thousand"):
        monkeypatch.setenv(model_context.MODEL_CONTEXT_TOKENS_ENV, junk)
        if model_context._HOST_CONTEXT_WINDOW_AVAILABLE:
            # Junk env falls through to the host catalog.
            assert client._input_token_budget() is not None
        else:
            assert client._input_token_budget() is None


def test_vlm_budget_is_priced_against_the_vlm_catalog_entry(monkeypatch):
    """The VLM client has to resolve its own model name when computing
    the token window.

    The catalog reports a much larger context for VLM models (e.g. a
    1,000,000 window for the multimodal tier vs. 126,976 for the text
    tier).  If ``_input_token_budget`` reads the text name on a VLM
    client, a 12-4K-frame turn (~142k vision tokens) collapses to recall
    pointers even though the actual VLM window has room for them.  A
    reverse mismatch admits input the VLM cannot accept.
    """
    seen: list[str] = []

    def _fake_context_window(model_name: str | None = None) -> int:
        seen.append(str(model_name))
        # Reserve math on a 126,976 window yields 122,880; on 1,000,000 it
        # yields 995,904.  The two numbers differ enough that a wrong
        # lookup is visible in the resolved budget alone.
        return 126_976 if model_name == "qwen-plus" else 1_000_000

    monkeypatch.delenv(
        model_context.MODEL_CONTEXT_TOKENS_ENV,
        raising=False,
    )
    monkeypatch.setattr(model_client, "context_window", _fake_context_window)
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_model_name",
        lambda: "qwen-plus",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )

    text_client = AgentScopeAgentChatClient.__new__(AgentScopeAgentChatClient)
    vlm_client = AgentScopeVlmChatClient.__new__(AgentScopeVlmChatClient)

    text_budget = text_client._input_token_budget()
    vlm_budget = vlm_client._input_token_budget()

    assert seen == ["qwen-plus", "qwen3.7-plus"]
    # Text: 126,976 - min(4096, 6348) = 126,976 - 4096 = 122,880.
    assert text_budget == 122_880
    # VLM: 1,000,000 - min(4096, 50,000) = 1,000,000 - 4096 = 995,904.
    assert vlm_budget == 995_904
    assert vlm_budget > text_budget


def test_media_that_arrives_as_a_url_is_outside_the_media_budget():
    """The documented boundary of this budget: inline bytes only.

    A DashScope (or MaaS) transport uploads the local file to the model's
    temporary object store and hands the provider a URL, so the request
    carries a few hundred bytes while the model still pays full vision tokens
    for the clip. Nothing in the media accounting can see that cost: the
    charge, the diagnostics and the demotion all key off a ``data:`` URL, and
    the window that would name it stays off until an operator declares one
    (see the context-budget section of the plugin README). Pinned as a known
    limit, so the day the budget learns to price fetched media this test is
    the record of which promise moved.
    """
    url = "https://dashscope-file.example/model-temp/clip.mp4?expires=17"
    attached = _attachment(url)
    inline = _attachment(_data_url(b"frame" * 5000))

    assert model_context.collect_inline_media(attached["content"]) == []
    assert model_context.collect_inline_media(inline["content"])

    # Nothing to refuse, and nothing to trade: the upload leaves untouched.
    assert prepare_model_messages([attached], [], max_bytes=1024) == [attached]

    _, receipt = model_context.demote_human_inline_media(
        [attached],
        vault=None,
    )
    assert receipt["demoted_blocks"] == 0


# ---------------------------------------------------------------------------
# P2: a demoted block stays recallable, and only proven pressure moves a
# human upload.
# ---------------------------------------------------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _data_url(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def _blob_vault(tmp_path):
    """A vault over the real content store, so handles name real bytes."""
    store = ContentStore(tmp_path)
    return media_vault.make_vault(store), store


def _attachment(data_url: str, *, seq: int = 7) -> dict:
    return {
        "role": "user",
        "source": "user",
        "messageSeq": seq,
        "content": [
            {"type": "text", "text": "按这张参考图改分镜"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }


def test_a_demoted_human_attachment_reads_back_byte_for_byte(tmp_path):
    """Pressure may move a person's upload, but never without its bytes.

    The pointer left in the vacated slot is the only answer to "what was the
    reference image", so the exact payload behind it has to come back. A
    demotion that could not promise that would be rewriting a requirement and
    calling the loss recallable.
    """
    payload = _PNG_MAGIC + b"frame" * 40_000
    data_url = _data_url(payload)
    vault, store = _blob_vault(tmp_path)
    digest = hashlib.sha256(payload).hexdigest()

    result, receipt = model_context.demote_human_inline_media(
        [_attachment(data_url)],
        vault=vault,
    )

    assert receipt["demoted_blocks"] == 1
    assert receipt["stored_blocks"] == 1
    assert receipt["refused_blocks"] == 0
    stub = result[0]["content"][1]
    assert stub["type"] == "text"
    # Announced as what it was: an unexplained hole where a person's screenshot
    # was reads like the person withdrew the requirement.
    assert "user attachment moved out of this request" in stub["text"]
    assert f"handle=sha256:{digest}" in stub["text"]
    assert "recall_media" in stub["text"]
    assert result[0]["content"][0]["text"] == "按这张参考图改分镜"

    recorded = result[0]["metadata"][model_context.DEMOTED_MEDIA_METADATA_KEY][
        0
    ]
    assert recorded["handle"] == digest
    assert recorded["mime"] == "image/png"
    assert recorded["decodedBytes"] == len(payload)
    assert recorded["messageSeq"] == 7
    assert recorded["estimatedTokens"] > 0

    restored = media_vault.load_by_handle(f"sha256:{digest}", store=store)
    assert restored is not None
    assert base64.b64decode(restored[0].split(";base64,", 1)[1]) == payload
    assert restored[1] == len(payload)


def test_a_human_attachment_without_a_durable_copy_is_never_rewritten():
    """The budget is allowed to fail; an upload is not allowed to vanish.

    Without a vault, or when the write itself fails, a demotion would leave a
    pointer to bytes nobody stored. Refusing keeps the person's input intact
    and the failure honest instead of trading one for the other.
    """
    payload = _PNG_MAGIC + b"frame" * 40_000
    data_url = _data_url(payload)
    messages = [_attachment(data_url)]

    for label, vault in (
        ("no vault at all", None),
        ("a vault that cannot write", lambda _url: None),
    ):
        result, receipt = model_context.demote_human_inline_media(
            messages,
            vault=vault,
        )

        assert receipt["demoted_blocks"] == 0, label
        assert receipt["refused_blocks"] == 1, label
        assert result[0]["content"][1]["image_url"]["url"] == data_url, label
        assert "metadata" not in result[0], label


def test_a_partially_storable_attachment_is_demoted_whole_or_not_at_all():
    """A requirement cut in half reads like a person who changed their mind."""
    first = _data_url(_PNG_MAGIC + b"frame" * 40_000)
    second = _data_url(b"second reference")
    first_digest = hashlib.sha256(_PNG_MAGIC + b"frame" * 40_000).hexdigest()

    def store_only_first(url: str) -> str | None:
        return first_digest if url == first else None

    message = {
        "role": "user",
        "source": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": first}},
            {"type": "image_url", "image_url": {"url": second}},
        ],
    }

    result, receipt = model_context.demote_human_inline_media(
        [message],
        vault=store_only_first,
    )

    assert receipt["demoted_blocks"] == 0
    assert receipt["refused_blocks"] == 2
    assert result[0]["content"][0]["image_url"]["url"] == first
    assert result[0]["content"][1]["image_url"]["url"] == second


def test_a_recalled_block_is_derived_media_again():
    """Recall must not re-pin the window it just freed.

    Bytes the Agent brought back are the runtime's own observation: the
    pointer that answered once can answer again, so the next tight budget has
    to be able to move them without reaching for a human message.
    """
    data_url = _data_url(b"\x00" * (2 * 1024 * 1024), mime="image/jpeg")
    messages = [
        {
            "role": "user",
            "source": model_context.MEDIA_RECALL_SOURCE,
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        },
    ]

    result, receipt = model_context.demote_derived_inline_media(messages)

    assert receipt["demoted_blocks"] == 1
    assert receipt["human_attachment_blocks"] == 0
    assert result[0]["content"][0]["type"] == "text"
    assert "inline media left this context" in result[0]["content"][0]["text"]


def test_history_compaction_keeps_the_handle_and_drops_the_rest():
    """A pointer outlives the turns between demotion and the recall.

    The handle is the only place a demoted attachment can be found from, so
    history compaction has to carry it; the tracing noise next to it does not
    belong in the model's input at all.
    """
    history = [
        {
            "role": "user",
            "source": "user",
            "messageSeq": 3,
            "content": [{"type": "text", "text": "参考图已移出本次请求"}],
            "metadata": {
                model_context.DEMOTED_MEDIA_METADATA_KEY: [
                    {"handle": "a" * 64},
                ],
                "streamingDiagnostics": {"chunks": 128},
            },
        },
    ]

    result = compact_conversation_history(history)

    kept = result[0]["metadata"]
    assert kept[model_context.DEMOTED_MEDIA_METADATA_KEY] == [
        {"handle": "a" * 64},
    ]
    assert "streamingDiagnostics" not in kept


def _ladder_payload() -> list[dict]:
    """A contract text plus one derived observation and one human upload."""
    data_url = _data_url(b"\x00" * (2 * 1024 * 1024), mime="image/jpeg")
    return [
        {"role": "system", "content": "A" * 5_000},
        {
            "role": "tool",
            "tool_call_id": "call-frame",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        },
        {
            "role": "user",
            "source": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        },
    ]


def _ladder_client(vault) -> AgentScopeAgentChatClient:
    client = AgentScopeAgentChatClient.__new__(AgentScopeAgentChatClient)
    built: list[str] = []

    def build_vault():
        built.append("vault")
        return vault

    client._media_vault = build_vault
    client._input_token_budget = lambda: None
    return client


def _refusal(max_bytes: int) -> ModelContextBudgetError:
    try:
        prepare_model_messages(_ladder_payload(), [], max_bytes=max_bytes)
    except ModelContextBudgetError as exc:
        return exc
    raise AssertionError("the ladder payload was expected to overflow")


def test_the_refusal_ladder_gives_up_its_own_observations_first():
    """A person's upload moves only after cheaper relief provably failed."""
    asked: list[str] = []

    def vault(url: str) -> str:
        asked.append(url)
        return "b" * 64

    failure = _refusal(12_000)
    client = _ladder_client(vault)

    prepared, _note = client._fit_refused_request(
        _ladder_payload(),
        [],
        max_bytes=12_000,
        failure=failure,
    )

    # The tool observation left; the attachment stayed exactly as sent.
    assert prepared[1]["content"][0]["type"] == "text"
    assert prepared[2]["content"][0]["image_url"]["url"] == (
        _ladder_payload()[2]["content"][0]["image_url"]["url"]
    )
    assert len(asked) == 1


def test_the_ladder_reaches_a_human_upload_only_under_proven_pressure():
    """When the runtime's own media is not enough, the upload goes recallably."""
    failure = _refusal(9_000)
    client = _ladder_client(lambda _url: "c" * 64)

    prepared, _note = client._fit_refused_request(
        _ladder_payload(),
        [],
        max_bytes=9_000,
        failure=failure,
    )

    assert [part["type"] for part in prepared[2]["content"]] == ["text"]
    assert "user attachment moved out of this request" in (
        prepared[2]["content"][0]["text"]
    )
    assert prepared[0]["content"] == "A" * 5_000
    assert prepared[1]["metadata"][model_context.DEMOTED_MEDIA_METADATA_KEY]
    assert prepared[2]["metadata"][model_context.DEMOTED_MEDIA_METADATA_KEY]


def test_a_refusal_that_survived_both_steps_says_what_it_gave_up():
    """A refusal after two steps has to name what it already sacrificed.

    The input that keeps failing is no longer the input the caller sent, so
    the error without the demotion record would be describing a request that
    nobody assembled. One upload stays put because no durable copy could be
    written for it, which is what makes the surviving request still too big
    after every movable block has moved.
    """
    archived = _data_url(b"\x10" * (2 * 1024 * 1024), mime="image/jpeg")
    unstorable = _data_url(b"\x20" * (2 * 1024 * 1024), mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * 5_000},
        {
            "role": "tool",
            "tool_call_id": "call-frame",
            "name": "read",
            "content": [
                {"type": "text", "text": "观察到的帧"},
                {"type": "image_url", "image_url": {"url": archived}},
            ],
        },
        {
            "role": "user",
            "source": "user",
            "content": [
                {"type": "text", "text": "第一张参考图"},
                {"type": "image_url", "image_url": {"url": archived}},
            ],
        },
        {
            "role": "user",
            "source": "user",
            "content": [
                {"type": "text", "text": "第二张参考图"},
                {"type": "image_url", "image_url": {"url": unstorable}},
            ],
        },
    ]
    max_bytes = 9_000

    def vault(url: str) -> str | None:
        return "f" * 64 if url == archived else None

    with pytest.raises(ModelContextBudgetError) as caught:
        prepare_model_messages(messages, [], max_bytes=max_bytes)
    client = _ladder_client(vault)

    with pytest.raises(ModelContextUnfitError) as unfit:
        client._fit_refused_request(
            messages,
            [],
            max_bytes=max_bytes,
            failure=caught.value,
        )

    text = str(unfit.value)
    assert "媒体降级记录" in text
    assert "派生观察媒体 1 块（已存档 1 块）" in text
    assert "真人附件媒体 1 块（已存档 1 块）" in text
    assert "sha256:" + "f" * 12 in text


def test_turning_demotion_off_restores_the_hard_local_refusal(monkeypatch):
    """The escape hatch is a switch, not a preference."""
    monkeypatch.setenv(
        model_context.MEDIA_OBSERVATION_DEGRADE_ENV,
        "0",
    )
    asked: list[str] = []
    client = _ladder_client(lambda url: asked.append(url) or "e" * 64)

    with pytest.raises(AgentModelError) as caught:
        client._fit_refused_request(
            _ladder_payload(),
            [],
            max_bytes=9_000,
            failure=_refusal(9_000),
        )

    assert "预算" in str(caught.value)
    assert "媒体降级记录" not in str(caught.value)
    assert asked == []


def test_only_the_priciest_upload_moves_when_one_was_enough():
    """Relief is paid out per attachment, and stops where the request fits.

    Two uploads and a contract text overflow together, and the bigger one alone
    clears the budget. Sweeping the batch would have spent a person's second
    reference image on pressure the first one caused, and the run would then
    have had nothing left to look at.
    """
    big = _data_url(b"\x22" * (13_000 * 128), mime="image/jpeg")
    small = _data_url(b"\x33" * (6_000 * 128), mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * 12_000},
        _attachment(big, seq=11),
        _attachment(small, seq=12),
    ]
    max_bytes = 30_000
    client = _ladder_client(lambda _url: "f" * 64)

    with pytest.raises(ModelContextBudgetError) as caught:
        prepare_model_messages(messages, [], max_bytes=max_bytes)

    prepared, note = client._fit_refused_request(
        messages,
        [],
        max_bytes=max_bytes,
        failure=caught.value,
    )

    assert [part["type"] for part in prepared[1]["content"]] == [
        "text",
        "text",
    ]
    assert prepared[2]["content"][1]["image_url"]["url"] == small
    assert prepared[2]["content"][0]["text"] == "按这张参考图改分镜"
    assert "真人附件媒体 1 块（已存档 1 块）" in note


def test_uploads_stay_put_when_text_is_what_overflows_the_budget():
    """An upload moves for media-shaped pressure, and for nothing else.

    The overage here is contract text: every inline block together costs less
    than the gap, so no number of demotions could fit the request. Running the
    ladder anyway would take a person's references away on the way to the
    identical failure, and the retry would take the rest.
    """
    first = _data_url(b"\x22" * (300 * 128), mime="image/jpeg")
    second = _data_url(b"\x33" * (300 * 128), mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * 40_000},
        _attachment(first, seq=21),
        _attachment(second, seq=22),
    ]
    max_bytes = 30_000
    stored: list[str] = []

    def store(url: str) -> str:
        stored.append(url)
        return "f" * 64

    client = _ladder_client(store)

    with pytest.raises(ModelContextBudgetError) as caught:
        prepare_model_messages(messages, [], max_bytes=max_bytes)

    with pytest.raises(ModelContextUnfitError) as unfit:
        client._fit_refused_request(
            messages,
            [],
            max_bytes=max_bytes,
            failure=caught.value,
        )

    assert stored == []
    assert "真人附件未移动" in str(unfit.value)
    assert [message["content"][1]["type"] for message in messages[1:]] == [
        "image_url",
        "image_url",
    ]


def test_the_gap_guard_only_dismisses_media_that_cannot_pay_for_the_gap():
    """The gate reads the refusal's own accounting and errs toward moving.

    Missing numbers and a token-window refusal stay with the ladder: a byte
    charge cannot answer a token gap, and a guard that dismissed relief on an
    unknown would turn a recoverable overflow into a hard refusal.
    """
    assert model_context.media_could_bridge_the_gap({})
    assert model_context.media_could_bridge_the_gap(
        {"max_bytes": 30_000, "used_bytes": 20_000, "media_charge_bytes": 0},
    )
    assert not model_context.media_could_bridge_the_gap(
        {
            "max_bytes": 30_000,
            "used_bytes": 60_000,
            "media_charge_bytes": 20_000,
        },
    )
    assert model_context.media_could_bridge_the_gap(
        {
            "max_bytes": 30_000,
            "used_bytes": 60_000,
            "media_charge_bytes": 40_000,
        },
    )


# ---------------------------------------------------------------------------
# P3: a provider that answers "too long" is recovered in two steps, and the
# classification vocabulary stays the platform's.
# ---------------------------------------------------------------------------

_OVERFLOW_MESSAGE = (
    "Error code: 400: This model's maximum context length is 32768 tokens. "
    "Your input has 51200 tokens."
)

# One block priced at 13,000 of the byte budget, so a 40,000-byte request holds
# the contract text plus two of them, while a halved request cannot hold the
# contract text plus even one.
_OVERFLOW_BLOCK_BYTES = 13_000 * model_context._INLINE_MEDIA_BYTES_DIVISOR
_OVERFLOW_CONTRACT_BYTES = 12_000
_OVERFLOW_BUDGET = 40_000


def _overflow_payload() -> tuple[list[dict], str, str]:
    """A contract text, one observed frame and one human upload."""
    derived = _data_url(b"\x11" * _OVERFLOW_BLOCK_BYTES, mime="image/jpeg")
    human = _data_url(b"\x22" * _OVERFLOW_BLOCK_BYTES, mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * _OVERFLOW_CONTRACT_BYTES},
        {
            "role": "user",
            "source": model_context.MEDIA_RECALL_SOURCE,
            "messageSeq": 9,
            "content": [{"type": "image_url", "image_url": {"url": derived}}],
        },
        _attachment(human, seq=11),
    ]
    return messages, derived, human


class _OverflowProvider:
    """Refuses the first ``failures`` calls as too long, then answers."""

    model = "qwen3.7-plus"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0
        self.requests: list[list] = []

    async def __call__(self, messages, *, tools=None):
        del tools
        self.calls += 1
        self.requests.append(list(messages))
        if self.calls <= self.failures:
            raise RuntimeError(_OVERFLOW_MESSAGE)
        return ChatResponse(
            id="response-overflow-recovered",
            content=[TextBlock(text="降级后的输入仍可用")],
            is_last=True,
        )


def _overflow_client(failures: int):
    """A client whose vault only records, so every demotion is auditable."""
    asked: list[str] = []

    def vault(url: str) -> str:
        asked.append(url)
        return hashlib.sha256(url.encode()).hexdigest()

    provider = _OverflowProvider(failures)
    client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
    client._media_vault = lambda: vault
    client._input_token_budget = lambda: None
    forced: list[int] = []
    original_fit = client._fit_refused_request

    def fitted(messages, tools, *, max_bytes, failure):
        forced.append(max_bytes)
        return original_fit(
            messages,
            tools,
            max_bytes=max_bytes,
            failure=failure,
        )

    client._fit_refused_request = fitted
    return client, provider, asked, forced


def _walk_content(node, wanted_key: str, found: list[str]) -> None:
    dump = getattr(node, "model_dump", None)
    if callable(dump):
        # AgentScope blocks are models, so the request has to be read the way
        # the provider will serialize it.
        node = dump()
    if isinstance(node, dict):
        value = node.get(wanted_key)
        if isinstance(value, str):
            found.append(value)
        for child in node.values():
            _walk_content(child, wanted_key, found)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _walk_content(item, wanted_key, found)


def _media_id(data_url: str) -> str:
    """A cheap, comparable name for one inline payload."""
    mime, _, encoded = data_url.partition(";base64,")
    return f"{mime.removeprefix('data:')}:{_b64_id(encoded)}"


def _b64_id(encoded: str) -> str:
    return hashlib.sha256(encoded.encode()).hexdigest()[:12]


def _request_media(native_messages) -> list[str]:
    """Which inline payloads one request the provider actually saw still had."""
    found: list[str] = []
    for message in native_messages:
        blocks = getattr(message, "content", None)
        for block in blocks if isinstance(blocks, (list, tuple)) else []:
            dump = getattr(block, "model_dump", None)
            shape = dump() if callable(dump) else block
            if not isinstance(shape, dict) or shape.get("type") != "data":
                continue
            source = shape.get("source") or {}
            found.append(
                f"{source.get('media_type')}:{_b64_id(str(source.get('data')))}",
            )
    return found


def _request_text(native_messages) -> str:
    found: list[str] = []
    for message in native_messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            found.append(content)
        _walk_content(content, "text", found)
    return "\n".join(found)


def test_a_provider_overflow_is_answered_by_gentle_relief_and_one_replay():
    """Only the runtime's own observation is traded for the second attempt.

    The provider said the request was too long, not that the conversation was
    wrong, so the retry gives up the frame a tool can produce again and keeps
    the person's upload byte for byte. The forced step belongs to a request
    that overflowed as well, not to this one.
    """
    messages, derived, human = _overflow_payload()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=1)
        notices: list[RateLimitRetryNotice] = []

        async def on_retry(notice: RateLimitRetryNotice) -> None:
            notices.append(notice)

        turn = await client.complete(
            messages=messages,
            tools=[],
            on_rate_limit_retry=on_retry,
            _context_budget_bytes=_OVERFLOW_BUDGET,
        )
        return provider, asked, forced, notices, turn

    provider, asked, forced, notices, turn = asyncio.run(scenario())

    assert turn.content == "降级后的输入仍可用"
    assert provider.calls == 2
    assert asked == [derived]
    assert _request_media(provider.requests[0]) == [
        _media_id(derived),
        _media_id(human),
    ]
    assert _request_media(provider.requests[1]) == [_media_id(human)]
    assert "inline media left this context" in _request_text(
        provider.requests[1],
    )
    assert "user attachment moved out of this request" not in _request_text(
        provider.requests[1],
    )
    assert forced == []
    # An overflow is deterministic: it is answered with a smaller request and
    # never with a wait.
    assert [(n.reason, n.delay_seconds) for n in notices] == [
        ("context_recovery", 0),
    ]


def test_the_gentle_retry_overflowing_too_forces_the_whole_ladder():
    """The second step is the one that may move a person's upload."""
    messages, derived, human = _overflow_payload()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=2)
        notices: list[RateLimitRetryNotice] = []

        async def on_retry(notice: RateLimitRetryNotice) -> None:
            notices.append(notice)

        turn = await client.complete(
            messages=messages,
            tools=[],
            on_rate_limit_retry=on_retry,
            _context_budget_bytes=_OVERFLOW_BUDGET,
        )
        return provider, asked, forced, notices, turn

    provider, asked, forced, notices, turn = asyncio.run(scenario())

    assert turn.content == "降级后的输入仍可用"
    assert provider.calls == 3
    # The frame the gentle step already archived is not written down twice:
    # the forced step is handed the request that was just refused, so only the
    # upload still looking for a home gets stored.
    assert asked == [derived, human]
    # Halved, so compaction also gives up the old tool exchanges.
    assert forced == [_OVERFLOW_BUDGET // 2]
    assert _request_media(provider.requests[2]) == []
    assert "user attachment moved out of this request" in _request_text(
        provider.requests[2],
    )
    # One recovery is one notice: the forced step is the tail of the same
    # boundary, not a second retry budget spending the first.
    assert [n.reason for n in notices] == ["context_recovery"]


def test_a_refusal_that_survived_both_recovery_steps_says_what_it_gave_up():
    """A provider that keeps saying no must not hide the degraded input.

    "It just keeps erroring" was unlocatable because the refusal described a
    request nobody assembled: the recovery had already moved media out of it.
    The final error carries that record, and stops after the two steps.
    """
    messages, derived, human = _overflow_payload()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=99)
        with pytest.raises(AgentModelError) as caught:
            await client.complete(
                messages=messages,
                tools=[],
                _context_budget_bytes=_OVERFLOW_BUDGET,
            )
        return provider, asked, forced, caught

    provider, asked, forced, caught = asyncio.run(scenario())

    # The recovery is bounded: original attempt, gentle retry, forced retry.
    assert provider.calls == 3
    assert asked == [derived, human]
    assert forced == [_OVERFLOW_BUDGET // 2]
    text = str(caught.value)
    assert "maximum context length" in text
    assert "媒体降级记录" in text
    assert "真人附件媒体 1 块（已存档 1 块）" in text
    # One frame left, so one frame is reported: rebuilding the record from the
    # refused request used to count the same block in both steps.
    assert text.count("派生观察媒体") == 1


def test_a_provider_failure_that_is_not_about_length_leaves_the_input_alone():
    """Recovery degrades input for a refusal that means "too long", only.

    Re-running a request the provider already answered another way would pay
    for the tokens a second time, and a content-policy refusal has nothing to
    gain from a smaller request.
    """
    messages, _derived, _human = _overflow_payload()

    class _PolicyRefusal:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages_, *, tools=None):
            del messages_, tools
            self.calls += 1
            raise RuntimeError("Error code: 400: content policy refused this")

    async def scenario():
        client, _provider, asked, forced = _overflow_client(failures=99)
        provider = _PolicyRefusal()
        client.model = provider  # type: ignore[assignment]
        with pytest.raises(AgentModelError) as caught:
            await client.complete(
                messages=messages,
                tools=[],
                _context_budget_bytes=_OVERFLOW_BUDGET,
            )
        return provider, asked, forced, caught

    provider, asked, forced, caught = asyncio.run(scenario())

    assert provider.calls == 1
    assert asked == []
    assert forced == []
    assert "content policy refused this" in str(caught.value)


def test_an_overflow_after_streamed_output_is_not_replayed():
    """Recovering would say the same answer twice, so it refuses instead.

    The platform boundary never replays output a model already spoke; the
    plugin reaches it through the same rule rather than a second one.
    """
    messages, _derived, _human = _overflow_payload()

    class _StreamThenOverflow:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages_, *, tools=None):
            del messages_, tools
            self.calls += 1

            async def chunks():
                yield ChatResponse(
                    id="response-partial",
                    content=[
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='{"proj',
                        ),
                    ],
                    is_last=False,
                )
                raise RuntimeError(_OVERFLOW_MESSAGE)

            return chunks()

    async def scenario():
        client, _provider, asked, forced = _overflow_client(failures=99)
        provider = _StreamThenOverflow()
        client.model = provider  # type: ignore[assignment]
        streamed: list[tuple[str, str, str]] = []

        async def on_tool_call_delta(
            call_id: str,
            name: str,
            delta: str,
        ) -> None:
            streamed.append((call_id, name, delta))

        with pytest.raises(OverflowAfterOutputError) as caught:
            await client.complete(
                messages=messages,
                tools=_tools(),
                on_tool_call_delta=on_tool_call_delta,
                _context_budget_bytes=_OVERFLOW_BUDGET,
            )
        return provider, asked, forced, streamed, caught

    provider, asked, forced, streamed, caught = asyncio.run(scenario())

    # The user already watched a tool call start; a second attempt would say
    # it twice.
    assert streamed == [("call-read-1", "read_project", '{"proj')]
    assert provider.calls == 1
    assert asked == []
    assert forced == []
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "maximum context length" in str(caught.value)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "This model's maximum context length is 32768 tokens"),
        (400, "This model's context window exceeded."),
        (400, "Range of input length should be [1, 30720]"),
        (400, "too many input tokens in this request"),
        (
            400,
            "The provided tokens (51200) exceeds the available context size "
            "(32768)",
        ),
        (None, "prompt is too long for the selected model"),
        (413, "input is too long for this gateway"),
        (422, "context_length_exceeded"),
    ],
)
def test_a_length_refusal_is_recognised_in_the_words_the_provider_uses(
    status,
    message,
):
    """One classifier, the platform's, widened only for transport reality.

    The platform's marker list is the single vocabulary here, so a gateway
    that answers 413/422 or leaks only text is still understood, while the
    plugin does not maintain a second list to drift from the first.
    """

    class _Refusal(RuntimeError):
        pass

    exc = _Refusal(f"Error code: {status}: {message}" if status else message)
    if status is not None:
        exc.status_code = status

    assert is_context_length_error(exc)


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 500: maximum context length backend is unhealthy",
        "Error code: 503: too many input tokens queued",
    ],
)
def test_a_server_side_failure_is_not_read_as_a_too_long_refusal(message):
    """A hiccup must not be answered by sacrificing the conversation.

    A 5xx says the provider failed, not that the input costs too much; the
    transient budget retries it as it is, and degrading would trade away
    media for nothing.
    """

    class _ServerFault(RuntimeError):
        pass

    exc = _ServerFault(message)
    exc.status_code = int(message.split("Error code: ", 1)[1][:3])

    assert not is_context_length_error(exc)


@pytest.mark.skipif(
    not model_client._HOST_OVERFLOW_RECOVERY_AVAILABLE,
    reason="the platform package is optional for standalone plugin installs",
)
def test_overflow_recovery_is_the_platform_function():
    """The retry boundary is imported, not reimplemented.

    A second recovery boundary in the plugin would be a second place where
    "one retry" and "never replay output" can disagree with the platform.
    Only ``call_with_overflow_recovery`` is delegated; the marker list and
    the classifier stay plugin-local so enabling compression does not have
    to patch the host package (see ``test_local_classifier_recognizes_...
    ``).
    """
    from qwenpaw.agents.context.overflow_recovery import (
        call_with_overflow_recovery as host_call,
    )

    assert model_client._HOST_OVERFLOW_RECOVERY_AVAILABLE
    assert model_client.call_with_overflow_recovery is host_call


def test_local_classifier_recognizes_provider_token_group_refusal():
    """A sentence only the plugin's group scan can catch, asserted on the
    consumer path.

    This refusal has no single marker from the list, so a green here proves
    the marker-group scan (not just single-marker matching) is wired in.
    """

    class _GatewayRefusal(Exception):
        pass

    refusal = _GatewayRefusal(
        "Error code: 400 - The input token count (290000) exceeds the "
        "maximum number of tokens allowed by the model",
    )
    assert model_client.is_context_overflow_error(refusal)
    assert is_context_length_error(refusal)


@pytest.mark.parametrize("status", [413, 422, None])
def test_group_only_length_refusal_is_understood_on_the_widened_path(status):
    """The 413/422/text-only path must scan marker groups too.

    ``is_context_overflow_error`` gates on a bare 400, so a group-only
    refusal never reaches its group scan there. The widened path used to
    check single markers only and dropped these silently; both paths now
    share one scan.
    """

    class _GatewayRefusal(Exception):
        pass

    message = (
        "The input token count (290000) exceeds the maximum number of "
        "tokens allowed by the model"
    )
    exc = _GatewayRefusal(
        f"Error code: {status}: {message}" if status else message,
    )
    if status is not None:
        exc.status_code = status

    assert not model_client.is_context_overflow_error(exc)
    assert is_context_length_error(exc)


def test_local_classifier_keeps_non_overflow_400s_out_of_recovery():
    """A 400 that isn't an overflow must not trigger the retry — malformed
    tool schemas, unsupported parameters, and media errors all keep their
    existing handling.
    """

    class _NonOverflow(Exception):
        pass

    assert not model_client.is_context_overflow_error(
        _NonOverflow("Error code: 400 - image_url is unsupported"),
    )
    assert not model_client.is_context_overflow_error(
        _NonOverflow("Error code: 500 - context length exceeded"),
    )


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 400 - maximum context length is 128000",
        "Error code: 400 - range of input length is [1, 983616]",
        "Error code: 400 - context_length_exceeded for prompt",
        "Error code: 400 - prompt is too long: 132k tokens",
        "Error code: 400 - too many input tokens in this request",
        "Error code: 400 - the provided tokens (51200) exceeds the "
        "available context size limit",
        "Error code: 400 - the input token count exceeds the maximum "
        "number of tokens allowed",
        "Error code: 400 - the input token count is more than the model "
        "only supports up to 32k",
    ],
)
def test_plugin_classifier_is_a_superset_of_the_host_inline(message):
    """The host keeps an inline copy of the marker list inside
    ``react_agent._is_context_overflow_error``; the plugin's list must be
    at least as wide.  Otherwise a refusal the host would recover from
    slips past the Creator retry path, which is exactly the drift the
    previous superset identity used to prevent.
    The host inline lives in ``react_agent``, which is a third optional
    import next to ``overflow_recovery`` and ``providers.error_utils``.
    Use ``importorskip`` (not ``_HOST_OVERFLOW_RECOVERY_AVAILABLE``) so the
    guard reflects what the test actually depends on.
    """
    QwenPawAgent = pytest.importorskip(
        "qwenpaw.agents.react_agent",
    ).QwenPawAgent

    exc = Exception(message)
    # Plugin must accept every provider refusal we've actually seen,
    # regardless of whether the current host inline recognizes it.
    # Without this, a host that narrows (e.g. dev/interactive-video drops
    # the tokens/exceeds group) makes the ``if host`` clause a no-op.
    assert model_client.is_context_overflow_error(exc), (
        f"plugin no longer accepts {message!r}",
    )
    if QwenPawAgent._is_context_overflow_error(exc):
        assert model_client.is_context_overflow_error(exc), (
            f"host accepts {message!r} but the plugin dropped it",
        )


def test_local_extract_status_code_matches_host_shapes():
    """The plugin keeps its own reader for standalone installs.  Every
    shape the host ``extract_status_code`` understands has to be handled
    here too, or a plugin running without the platform package misses
    the 400 gate on gateway-wrapped refusals.
    """

    class _Int(Exception):
        status_code = 400

    class _String(Exception):
        code = "413"

    class _Response(Exception):
        class _R:
            status = 422

        response = _R()

    class _Streaming(Exception):
        pass

    assert model_client._local_extract_status_code(_Int()) == 400
    assert model_client._local_extract_status_code(_String()) == 413
    assert model_client._local_extract_status_code(_Response()) == 422
    assert (
        model_client._local_extract_status_code(
            _Streaming(
                "Streaming response failed: [400] - the input token count "
                "exceeds the maximum number of tokens allowed",
            ),
        )
        == 400
    )


def test_local_classifier_accepts_streaming_wrapped_group_refusal():
    """End-to-end: a streaming ``[400]`` refusal carrying only a group
    phrase must still trip the classifier.  The single-marker fallback in
    ``is_context_length_error`` cannot catch this shape alone, so a green
    here proves the plugin's own status reader is wired up.
    """

    class _Streaming(Exception):
        pass

    refusal = _Streaming(
        "Streaming response failed: [400] - the input token count (290000) "
        "exceeds the maximum number of tokens allowed by the model",
    )
    assert model_client.is_context_overflow_error(refusal)


def test_turning_demotion_off_declines_the_provider_overflow_too(monkeypatch):
    """The escape hatch has to cover the recovery path, not just the local one.

    A deployment that refuses demotion expects the provider's own refusal to
    come back unchanged instead of a quietly rewritten second request.
    """
    monkeypatch.setenv(
        model_context.MEDIA_OBSERVATION_DEGRADE_ENV,
        "0",
    )
    messages, _derived, _human = _overflow_payload()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=1)
        with pytest.raises(RuntimeError, match="maximum context length"):
            await client.complete(
                messages=messages,
                tools=[],
                _context_budget_bytes=_OVERFLOW_BUDGET,
            )
        return provider, asked, forced

    provider, asked, forced = asyncio.run(scenario())

    assert provider.calls == 1
    assert asked == []
    assert forced == []


_TEXT_BUDGET = 40_000
# Six finished reads of 420 repeats each: serialized, the session stays under
# the byte guard, so it is the provider that refuses, and half of its raw size
# is tighter than half of the budget.
_TEXT_EXCHANGES = 6
_TEXT_ROW_REPEATS = 420


def _text_only_history() -> list[dict]:
    """A long session of finished reads: no media anywhere in it."""
    messages = [
        {"role": "system", "content": "项目创作契约"},
        {
            "role": "user",
            "source": "user",
            "content": "把六集分镜做完再交审阅",
        },
    ]
    for index in range(_TEXT_EXCHANGES):
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"call-{index}", "function": {"name": "read"}},
                ],
            },
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call-{index}",
                "name": "read",
                "content": "镜头描述 " * _TEXT_ROW_REPEATS,
            },
        )
    return messages


def _request_read_rows(native_messages) -> int:
    """How many of the session's finished reads a request still held."""
    rows = 0
    for message in native_messages:
        blocks = getattr(message, "content", None)
        for block in blocks if isinstance(blocks, (list, tuple)) else []:
            shape = (
                block.model_dump() if hasattr(block, "model_dump") else block
            )
            if isinstance(shape, dict) and shape.get("type") == "tool_result":
                rows += 1
    return rows


def test_a_text_only_overflow_is_answered_by_retiring_old_tool_exchanges():
    """No media to trade is not the same as nothing left to give up.

    A long plain-text session is the shape that actually broke: the provider
    refused on length, the gentle step found nothing media-shaped, and the
    request then has to be rebuilt at half the budget so compaction retires
    completed tool exchanges. Stopping at the first refusal left that session
    with no second attempt at all.
    """

    async def scenario():
        client, provider, asked, _forced = _overflow_client(failures=1)
        notices: list[RateLimitRetryNotice] = []

        async def on_retry(notice: RateLimitRetryNotice) -> None:
            notices.append(notice)

        turn = await client.complete(
            messages=_text_only_history(),
            tools=[],
            on_rate_limit_retry=on_retry,
            _context_budget_bytes=_TEXT_BUDGET,
        )
        return provider, asked, notices, turn

    provider, asked, notices, turn = asyncio.run(scenario())

    assert turn.content == "降级后的输入仍可用"
    assert provider.calls == 2
    # Nothing traded was a person's: there was no media, and the requirement
    # row still reads the same in the replayed request.
    assert asked == []
    assert len(provider.requests[1]) < len(provider.requests[0])
    assert "把六集分镜做完再交审阅" in _request_text(provider.requests[1])
    assert [n.reason for n in notices] == ["context_recovery"]


def test_an_overflow_that_cannot_be_made_smaller_fails_as_a_model_error():
    """The proven-unfittable input stops the run instead of resuming it.

    Handing back the provider's raw exception made the driver classify the run
    as a generic agent failure with nothing the user could act on, so the text
    stays an AgentModelError family member. What changed is the verdict on a
    retry: every lever this client owns has been pulled, so an automatic
    resume would only re-send bytes the same window already refused.
    """
    messages = [
        {"role": "system", "content": "项目创作契约"},
        {
            "role": "user",
            "source": "user",
            "content": "需求原文。" * 2_000,
        },
    ]

    async def scenario():
        client, provider, asked, _forced = _overflow_client(failures=99)
        with pytest.raises(AgentModelError) as caught:
            await client.complete(
                messages=messages,
                tools=[],
                _context_budget_bytes=_TEXT_BUDGET,
            )
        return provider, asked, caught

    provider, asked, caught = asyncio.run(scenario())

    assert provider.calls == 1
    assert asked == []
    assert "maximum context length" in str(caught.value)
    assert isinstance(caught.value, ModelContextUnfitError)


# ---------------------------------------------------------------------------
# B1: a provider refusal over uploads only still earns the whole ladder.
# ---------------------------------------------------------------------------


def _upload_only_payload() -> tuple[list[dict], str, str]:
    """A contract text and two of a person's uploads, nothing the runtime made.

    This is the shape that stopped at the first refusal: no derived frame for
    the gentle step to trade and no completed tool exchange for compaction to
    retire, so "there is nothing left to rebuild" was read as "there is
    nothing left to give up" and the uploads were never even offered.
    """
    first = _data_url(b"\x33" * _OVERFLOW_BLOCK_BYTES, mime="image/jpeg")
    second = _data_url(b"\x44" * _OVERFLOW_BLOCK_BYTES, mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * _OVERFLOW_CONTRACT_BYTES},
        _attachment(first, seq=5),
        _attachment(second, seq=6),
    ]
    return messages, first, second


def test_a_refusal_over_uploads_only_still_runs_the_ladder():
    """The local guard is not the one that prices a vision window.

    Inline media is charged as vision tokens here and as real tokens by the
    provider, so an oversized upload session almost always reaches the
    provider before it reaches this guard. The refusal then has to be answered
    by the ladder that can move those bytes, not by one burned call and a
    terminal error.
    """
    _unused, first, second = _upload_only_payload()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=1)
        notices: list[RateLimitRetryNotice] = []

        async def on_retry(notice: RateLimitRetryNotice) -> None:
            notices.append(notice)

        turn = await client.complete(
            messages=_unused,
            tools=[],
            on_rate_limit_retry=on_retry,
            _context_budget_bytes=_OVERFLOW_BUDGET,
        )
        return provider, asked, forced, notices, turn

    provider, asked, forced, notices, turn = asyncio.run(scenario())

    assert turn.content == "降级后的输入仍可用"
    assert provider.calls == 2
    # Both uploads were still tradable: the pressure was media-shaped, so the
    # ladder moved them one at a time until the request fitted.
    assert sorted(asked) == sorted([first, second])
    assert forced == [_OVERFLOW_BUDGET // 2]
    assert _request_media(provider.requests[1]) == []
    assert "user attachment moved out of this request" in _request_text(
        provider.requests[1],
    )
    assert [(n.reason, n.delay_seconds) for n in notices] == [
        ("context_recovery", 0),
    ]


def test_the_rewritten_turn_carries_the_shape_that_was_actually_sent():
    """A recovery that hides its own request leaves the next turn to repeat it.

    The demotion ladder rewrites the input, and a turn built from the caller's
    original list would put the refused bytes straight back into the next
    request and pay for the same refusal twice.
    """
    messages, _first, _second = _upload_only_payload()

    async def scenario():
        client, _provider, _asked, _forced = _overflow_client(failures=1)
        return await client.complete(
            messages=messages,
            tools=[],
            _context_budget_bytes=_OVERFLOW_BUDGET,
        )

    turn = asyncio.run(scenario())

    assert turn.sent_messages is not None
    assert turn.sent_messages != list(messages)
    assert ";base64," not in json.dumps(
        turn.sent_messages,
        ensure_ascii=False,
    )
    assert ";base64," in json.dumps(list(messages), ensure_ascii=False)


def test_a_compacted_replay_that_overflows_too_reaches_the_forced_step():
    """Wrapping only the gentle retry left compaction with no second lever.

    A long session that had to be rebuilt at half the budget still carries its
    uploads, and the replay is the same client's request: a refusal there
    belongs to the same boundary as a refusal after gentle relief.
    """
    messages, human = _upload_and_tool_history()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=2)
        notices: list[RateLimitRetryNotice] = []

        async def on_retry(notice: RateLimitRetryNotice) -> None:
            notices.append(notice)

        turn = await client.complete(
            messages=messages,
            tools=[],
            on_rate_limit_retry=on_retry,
            _context_budget_bytes=_OVERFLOW_BUDGET,
        )
        return provider, asked, forced, notices, turn

    provider, asked, forced, notices, turn = asyncio.run(scenario())

    assert turn.content == "降级后的输入仍可用"
    assert provider.calls == 3
    assert asked == [human]
    assert forced == [_OVERFLOW_BUDGET // 2]
    assert _request_media(provider.requests[2]) == []
    # One recovery is one notice, whichever step closed it.
    assert [n.reason for n in notices] == ["context_recovery"]


def _upload_and_tool_history() -> tuple[list[dict], str]:
    """Finished reads plus one upload: compaction has something to retire.

    Sized so the request fits this client's guard on the first attempt, which
    is what makes the provider the one that refuses, and leaves an upload
    behind for the forced step to find.
    """
    messages = [
        {"role": "system", "content": "项目创作契约"},
        {
            "role": "user",
            "source": "user",
            "messageSeq": 1,
            "content": "把六集分镜做完再交审阅",
        },
    ]
    for index in range(3):
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"call-{index}", "function": {"name": "read"}},
                ],
            },
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call-{index}",
                "name": "read",
                "content": "镜头描述 " * 300,
            },
        )
    human = _data_url(b"\x55" * _OVERFLOW_BLOCK_BYTES, mime="image/jpeg")
    messages.append(_attachment(human, seq=9))
    return messages, human


def test_turning_demotion_off_promises_a_retry_it_does_not_make(
    monkeypatch,
):
    """The escape hatch stays terminal for an upload-only refusal too.

    B1 routes this shape through the forced boundary, so the switch has to be
    honoured there: a notice would announce a smaller request the disabled
    ladder is not allowed to build, and a retryable classification would spend
    a second call on bytes no longer permitted to move.
    """
    monkeypatch.setenv(
        model_context.MEDIA_OBSERVATION_DEGRADE_ENV,
        "0",
    )
    messages, _first, _second = _upload_only_payload()

    async def scenario():
        client, provider, asked, forced = _overflow_client(failures=99)
        notices: list[RateLimitRetryNotice] = []

        async def on_retry(notice: RateLimitRetryNotice) -> None:
            notices.append(notice)

        with pytest.raises(AgentModelError) as caught:
            await client.complete(
                messages=messages,
                tools=[],
                on_rate_limit_retry=on_retry,
                _context_budget_bytes=_OVERFLOW_BUDGET,
            )
        return provider, asked, forced, notices, caught

    provider, asked, forced, notices, caught = asyncio.run(scenario())

    assert provider.calls == 1
    assert asked == []
    assert forced == []
    assert notices == []
    assert isinstance(caught.value, ModelContextUnfitError)
    assert "maximum context length" in str(caught.value)


def _provider_refusal() -> ModelContextBudgetError:
    """A refusal a provider wrote down, which carries no local measurement."""
    return ModelContextBudgetError("maximum context length is 8192 tokens")


def _refusal_at(
    messages: list[dict],
    max_bytes: int,
) -> ModelContextBudgetError:
    try:
        prepare_model_messages(messages, [], max_bytes=max_bytes)
    except ModelContextBudgetError as exc:
        return exc
    raise AssertionError("the wire was expected to overflow")


def test_a_provider_refusal_is_not_allowed_to_guess_what_does_not_fit():
    """An empty reading opens the upload gate, so the ladder strips on a hunch.

    Only the accounting behind a refusal says whether the overage is
    media-shaped, and a provider refusal arrives with none of it. The gate read
    that silence as permission and began archiving a person's upload against a
    budget it had never measured for this shape, while the request was
    overflowing on 30KB of contract text no demotion is allowed to shrink.
    """
    data_url = _data_url(b"\x00" * (2 * 1024 * 1024), mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * 5_000},
        {
            "role": "user",
            "source": "user",
            "messageSeq": 7,
            "content": [
                {"type": "text", "text": "T" * 30_000},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    asked: list[str] = []
    client = _ladder_client(lambda url: asked.append(url) or "d" * 64)

    with pytest.raises(ModelContextUnfitError) as unfit:
        client._fit_refused_request(
            messages,
            [],
            max_bytes=20_000,
            failure=_provider_refusal(),
        )

    assert asked == []
    assert [part["type"] for part in messages[1]["content"]] == [
        "text",
        "image_url",
    ]
    # What the caller reads keeps the provider's own words: the probe states a
    # budget the ladder tightened, not the one that refused.
    assert "maximum context length" in str(unfit.value)
    # And the gate closed on a measurement, not on an absent one.
    reading = model_context.budget_diagnostics(messages, [], max_bytes=20_000)
    assert not model_context.media_could_bridge_the_gap(reading)


def test_a_media_shaped_provider_refusal_still_buys_relief_with_an_upload():
    """Measuring the gap must not turn a real media overage into a dead end.

    The same probe that stops the ladder from guessing has to let it work when
    the media really is what does not fit, or a single oversized screenshot
    would end the turn instead of costing the one block that overflowed.
    """
    data_url = _data_url(b"\x00" * (2 * 1024 * 1024), mime="image/jpeg")
    messages = [
        {"role": "system", "content": "A" * 5_000},
        _attachment(data_url, seq=7),
    ]
    asked: list[str] = []
    client = _ladder_client(lambda url: asked.append(url) or "e" * 64)

    prepared, _note = client._fit_refused_request(
        messages,
        [],
        max_bytes=9_000,
        failure=_provider_refusal(),
    )

    assert "image_url" not in json.dumps(prepared[1]["content"])
    assert len(asked) == 1


def _observation_wire() -> list[dict]:
    """A wire as the reader tools leave it: sampled frames on a user row."""
    observed = _data_url(b"\x00" * (2 * 1024 * 1024), mime="image/jpeg")
    uploaded = _data_url(b"\x10" * (64 * 1024), mime="image/jpeg")
    return [
        {"role": "system", "content": "A" * 5_000},
        {
            "role": "tool",
            "tool_call_id": "call-frame",
            "content": [{"type": "image_url", "image_url": {"url": observed}}],
        },
        {
            "role": "user",
            "source": model_context.MEDIA_OBSERVATION_SOURCE,
            "messageSeq": 9,
            "content": [{"type": "image_url", "image_url": {"url": observed}}],
        },
        _attachment(uploaded, seq=11),
    ]


def test_media_the_runtime_observed_is_traded_before_a_person_could_be():
    """An unmarked observation row is archived as though it were an upload.

    The protocol lets inline media ride only the user role, so what tells the
    ladder that a tool can produce those bytes again is the source stamped on
    the row. Without it the first rung leaves a frame in place, the last rung
    moves it as a person's attachment, and the demotion record blames the one
    input nobody may trade for cheap relief the runtime was free to take.
    """
    wire = _observation_wire()

    _demoted, receipt = model_context.demote_derived_inline_media(
        wire,
        budget_bytes=14_000,
        vault=lambda _url: "f" * 64,
    )

    assert receipt["demoted_blocks"] == 2
    # Only the upload a person made counts as theirs, so the last rung is left
    # with one candidate and the frame never reaches it.
    assert receipt["human_attachment_blocks"] == 1

    client = _ladder_client(lambda _url: "f" * 64)
    prepared, note = client._fit_refused_request(
        wire,
        [],
        max_bytes=14_000,
        failure=_refusal_at(wire, 14_000),
    )

    assert "真人附件" not in note
    assert "image_url" in json.dumps(prepared[3]["content"])


def _forced_step_input(client) -> list[list[dict]]:
    """Wrap the forced step so the shape it was handed becomes assertable."""
    handed: list[list[dict]] = []
    original = client._recover_forced_overflow

    async def recording(exc, **kwargs):
        handed.append(list(kwargs["messages"]))
        return await original(exc, **kwargs)

    client._recover_forced_overflow = recording
    return handed


def test_the_forced_step_is_handed_the_request_the_provider_just_refused():
    """Rebuilding from the pre-compaction wire unsays what compaction did.

    The history fallback tightens to half the serialized size whenever that is
    tighter than half the budget, while the forced step halves the *budget* and
    never sees that number. Handed the wire from before compaction it re-runs
    the retirement against the looser budget, so the completed exchanges the
    provider had already been denied come back into the very request built to
    be smaller than the refusal it is answering.
    """

    async def scenario():
        client, provider, _asked, forced = _overflow_client(failures=2)
        handed = _forced_step_input(client)
        with pytest.raises(AgentModelError):
            await client.complete(
                messages=_text_only_history(),
                tools=[],
                _context_budget_bytes=_TEXT_BUDGET,
            )
        return provider, forced, handed

    provider, forced, handed = asyncio.run(scenario())

    # A text-only request has nothing left for the second step to trade, so the
    # recovery stops there; what it was about to rebuild from is the point.
    assert provider.calls == 2
    assert forced == [_TEXT_BUDGET // 2]
    assert len(handed) == 1
    refused = _request_read_rows(provider.requests[1])
    assert 0 < refused < _TEXT_EXCHANGES
    handed_rows = [m for m in handed[0] if m.get("role") == "tool"]
    assert len(handed_rows) == refused


def _string_media_wire() -> tuple[list[dict], str]:
    """A tool answer whose payload rides inside a text part's JSON."""
    observed = _data_url(b"\x00" * (2 * 1024 * 1024), mime="image/jpeg")
    uploaded = _data_url(b"\x10" * (64 * 1024), mime="image/jpeg")
    answer = json.dumps({"resultKind": "frame", "url": observed})
    wire = [
        {"role": "system", "content": "A" * 5_000},
        {
            "role": "tool",
            "tool_call_id": "call-frame",
            "name": "read_frame",
            "content": [{"type": "text", "text": answer}],
        },
        _attachment(uploaded, seq=11),
    ]
    return wire, observed


def test_media_a_tool_answered_as_plain_text_can_still_be_given_up():
    """Media a census cannot find is media the ladder will not trade.

    ``demote_derived_inline_media`` only strips a row its own walk found blocks
    in, so a payload the tool answer serialized into a text part used to pass
    through untouched: the megabytes stayed, and the refusal that followed
    reported no inline media at all - which the entry gate then read as
    pressure no demotion could relieve, so the turn ended instead of giving up
    what had just been measured.
    """
    wire, observed = _string_media_wire()
    asked: list[str] = []
    client = _ladder_client(lambda url: asked.append(url) or "g" * 64)

    prepared, _note = client._fit_refused_request(
        wire,
        [],
        max_bytes=16_000,
        failure=_refusal_at(wire, 16_000),
    )

    dump = json.dumps(prepared, ensure_ascii=False)
    assert observed not in dump
    assert "image/jpeg" in dump
    assert asked == [observed]
    # The frame was the whole overage, so a person's upload never had to move.
    assert "user attachment moved out of this request" not in dump
