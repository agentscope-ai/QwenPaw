# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Model-driven search can only inspect and return retrieved conversations."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats import search_agent
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.search import (
    ChatSearchRequest,
    SearchCorpus,
    TranscriptText,
)


def make_corpus(count=1):
    chats = [
        ChatSpec(
            id=f"chat-{i}",
            name="Auto title",
            session_id=f"s-{i}",
            user_id="u",
        )
        for i in range(count)
    ]
    return SearchCorpus(
        chats=chats,
        messages={
            chat.id: [
                TranscriptText(
                    "The launch deadline is Tuesday",
                    "user",
                    f"m-{i}",
                ),
            ]
            for i, chat in enumerate(chats)
        },
    )


def fake_factory(monkeypatch, actions):
    calls = []

    async def model(messages):
        calls.append(list(messages))
        action = actions[len(calls) - 1]
        if isinstance(action, Exception):
            raise action
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        action
                        if isinstance(action, str)
                        else json.dumps(action)
                    ),
                },
            ],
        }

    async def factory(**kwargs):
        assert kwargs["agent_id"] == "agent-one"
        return model, None

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    return calls


def workspace():
    return SimpleNamespace(agent_id="agent-one", config=object())


async def test_agent_reformulates_reads_then_returns_verified_evidence(
    monkeypatch,
):
    calls = fake_factory(
        monkeypatch,
        [
            {"action": "search", "query": "release"},
            {"action": "search", "query": "deadline"},
            {"action": "read", "chat_id": "chat-0"},
            {"action": "finish", "chat_ids": ["chat-0"]},
        ],
    )
    result = await search_agent.agent_search(
        workspace(),
        make_corpus(),
        ChatSearchRequest(query="When did we plan to launch?", mode="agent"),
    )
    assert result.queries == ["release", "deadline"]
    assert result.results[0].snippet == "The launch deadline is Tuesday"
    assert result.results[0].message_id == "m-0"
    assert result.total == 1 and not result.partial
    observation = json.loads(calls[-1][-1].get_text_content())["observation"]
    assert (
        observation["matched_message"]["text"]
        == "The launch deadline is Tuesday"
    )


async def test_unknown_reads_and_hallucinated_results_are_blocked(
    monkeypatch,
):
    calls = fake_factory(
        monkeypatch,
        [
            {"action": "read", "chat_id": "secret-from-another-agent"},
            {"action": "search", "query": "deadline"},
            {
                "action": "finish",
                "chat_ids": ["chat-0", "secret-from-another-agent", "chat-0"],
            },
        ],
    )
    result = await search_agent.agent_search(
        workspace(),
        make_corpus(),
        ChatSearchRequest(query="deadline", mode="agent"),
    )
    observation = json.loads(calls[1][-1].get_text_content())["observation"]
    assert "error" in observation
    assert [item.chat.id for item in result.results] == ["chat-0"]
    assert result.partial


async def test_agent_can_page_to_older_matches(monkeypatch):
    calls = fake_factory(
        monkeypatch,
        [
            {"action": "search", "query": "deadline"},
            {"action": "search", "query": "deadline", "offset": 20},
            {"action": "finish", "chat_ids": ["chat-24"]},
        ],
    )
    result = await search_agent.agent_search(
        workspace(),
        make_corpus(25),
        ChatSearchRequest(query="deadline", mode="agent"),
    )
    observation = json.loads(calls[1][-1].get_text_content())["observation"]
    assert observation["next_offset"] == 20
    assert result.results[0].chat.id == "chat-24"


async def test_agent_iteration_limit_and_result_limit_are_explicit(
    monkeypatch,
):
    calls = fake_factory(
        monkeypatch,
        [{"action": "search", "query": "deadline"}] * 6,
    )
    result = await search_agent.agent_search(
        workspace(),
        make_corpus(3),
        ChatSearchRequest(query="deadline", mode="agent", limit=1),
    )
    assert len(calls) == 6
    assert len(result.results) == result.total == 1
    assert result.partial
    assert not result.has_more


async def test_invalid_model_actions_fail_after_one_repair_attempt(
    monkeypatch,
):
    calls = fake_factory(
        monkeypatch,
        ["not JSON", {"action": "execute_shell", "command": "echo forbidden"}],
    )
    with pytest.raises(HTTPException) as raised:
        await search_agent.agent_search(
            workspace(),
            make_corpus(),
            ChatSearchRequest(query="deadline", mode="agent"),
        )
    assert raised.value.status_code == 502
    assert len(calls) == 2


async def test_missing_model_is_explicit(monkeypatch):
    async def factory(**_kwargs):
        raise ValueError("No configured model")

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    with pytest.raises(HTTPException) as raised:
        await search_agent.agent_search(
            workspace(),
            make_corpus(),
            ChatSearchRequest(query="deadline", mode="agent"),
        )
    assert raised.value.status_code == 503


async def test_provider_failure_is_explicit(monkeypatch):
    fake_factory(monkeypatch, [RuntimeError("API failure")])
    with pytest.raises(HTTPException) as raised:
        await search_agent.agent_search(
            workspace(),
            make_corpus(),
            ChatSearchRequest(query="deadline", mode="agent"),
        )
    assert raised.value.status_code == 502


async def test_timeout_without_candidates_is_explicit(monkeypatch):
    async def model(_messages):
        await asyncio.Event().wait()

    async def factory(**_kwargs):
        return model, None

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    monkeypatch.setattr(search_agent, "AGENT_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(HTTPException) as raised:
        await search_agent.agent_search(
            workspace(),
            make_corpus(),
            ChatSearchRequest(query="deadline", mode="agent"),
        )
    assert raised.value.status_code == 504


async def test_oversized_model_stream_is_closed_early(monkeypatch):
    monkeypatch.setattr(search_agent, "MAX_ACTION_CHARS", 20)
    consumed = []
    closed = []

    async def chunks():
        try:
            for text in ["x" * 21, "must never consume this"]:
                consumed.append(text)
                yield {"content": [{"type": "text", "text": text}]}
        finally:
            closed.append(True)

    async def model(_messages):
        return chunks()

    with pytest.raises(ValueError, match="response limit"):
        await search_agent._consume_action(model, [])
    assert len(consumed) == 1 and closed == [True]


async def test_cancellation_propagates(monkeypatch):
    async def factory(**_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    with pytest.raises(asyncio.CancelledError):
        await search_agent.agent_search(
            workspace(),
            make_corpus(),
            ChatSearchRequest(query="deadline", mode="agent"),
        )


@pytest.mark.parametrize("offset", [-1, True, "20"])
def test_agent_rejects_invalid_pagination(offset):
    with pytest.raises(ValueError):
        search_agent._parse_action(
            json.dumps({"action": "search", "query": "x", "offset": offset}),
        )


def test_read_context_caps_message_count_and_marks_omitted_history():
    corpus = make_corpus()
    result = corpus.search("deadline")[0]
    corpus.messages["chat-0"].extend(
        TranscriptText("ok", "assistant") for _ in range(1000)
    )
    observation = search_agent._read_candidate(corpus, result)
    assert len(observation["messages"]) <= search_agent.MAX_READ_MESSAGES
    assert observation["truncated"]
    assert len(json.dumps(observation)) < 12000


@pytest.mark.parametrize("message_ids", [True, False])
def test_read_prioritizes_the_matching_turn_over_an_older_shared_excerpt(
    message_ids,
):
    corpus = make_corpus()
    prefix = "deadline " + "details " * 40
    corpus.messages["chat-0"] = [
        TranscriptText(
            prefix + "OLD DECISION: canceled",
            "user",
            "older" if message_ids else None,
        ),
        TranscriptText(
            prefix + "LATEST DECISION: approved",
            "assistant",
            "latest" if message_ids else None,
        ),
    ]
    result = corpus.search("deadline")[0]
    observation = search_agent._read_candidate(corpus, result)
    assert observation["matched_message"]["role"] == "assistant"
    assert observation["matched_message"]["text"].endswith(
        "LATEST DECISION: approved",
    )
