# -*- coding: utf-8 -*-
import asyncio

from qwenpaw.user_input.schemas import (
    UserInputAnswer,
    UserInputOption,
    UserInputQuestion,
)
from qwenpaw.user_input.service import UserInputService


def _question() -> UserInputQuestion:
    return UserInputQuestion(
        id="date",
        question="请选择出行日期",
        kind="choice_with_custom",
        options=[
            UserInputOption(
                label="使用默认日期",
                value="default",
                recommended=True,
            ),
        ],
    )


def _second_question() -> UserInputQuestion:
    return UserInputQuestion(
        id="style",
        question="请选择行程风格",
        kind="choice_with_custom",
        options=[
            UserInputOption(
                label="经典轻松",
                value="classic",
                recommended=True,
            ),
        ],
    )


async def _create_and_get_pending_by_session():
    svc = UserInputService()
    pending = await svc.create_pending(
        session_id="session-1",
        root_session_id="session-1",
        user_id="default",
        channel="console",
        agent_id="default",
        title="确认信息",
        questions=[_question()],
    )

    found = await svc.get_pending(agent_id="default", session_id="session-1")

    assert found is not None
    assert found.request_id == pending.request_id
    assert found.questions[0].id == "date"


def test_create_and_get_pending_by_session():
    asyncio.run(_create_and_get_pending_by_session())


async def _submit_answer_resolves_waiter():
    svc = UserInputService()
    pending = await svc.create_pending(
        session_id="session-1",
        root_session_id="session-1",
        user_id="default",
        channel="console",
        agent_id="default",
        title=None,
        questions=[_question()],
    )
    waiter = asyncio.create_task(svc.wait_for_result(pending.request_id, 1))
    await asyncio.sleep(0)

    await svc.answer_request(
        pending.request_id,
        UserInputAnswer(action="submit", answers={"date": "2026-05-20"}),
    )
    result = await waiter

    assert result.status == "answered"
    assert result.answers == {"date": "2026-05-20"}
    assert await svc.get_pending(agent_id="default", session_id="session-1") is None


def test_submit_answer_resolves_waiter():
    asyncio.run(_submit_answer_resolves_waiter())


async def _multi_question_request_advances_one_question_at_a_time():
    svc = UserInputService()
    pending = await svc.create_pending(
        session_id="session-1",
        root_session_id="session-1",
        user_id="default",
        channel="console",
        agent_id="default",
        title=None,
        questions=[_question(), _second_question()],
    )
    waiter = asyncio.create_task(svc.wait_for_result(pending.request_id, 1))
    await asyncio.sleep(0)

    first = await svc.answer_request(
        pending.request_id,
        UserInputAnswer(action="submit", answers={"date": "2026-05-20"}),
    )

    assert first is not None
    assert first.status == "pending"
    assert first.question_index == 1
    assert first.total_questions == 2
    assert [q.id for q in first.questions] == ["style"]
    assert waiter.done() is False

    second = await svc.answer_request(
        pending.request_id,
        UserInputAnswer(action="submit", answers={"style": "classic"}),
    )
    result = await waiter

    assert second is not None
    assert second.status == "answered"
    assert result.status == "answered"
    assert result.answers == {
        "date": "2026-05-20",
        "style": "classic",
    }


def test_multi_question_request_advances_one_question_at_a_time():
    asyncio.run(_multi_question_request_advances_one_question_at_a_time())


async def _ignore_answer_resolves_as_ignored():
    svc = UserInputService()
    pending = await svc.create_pending(
        session_id="session-1",
        root_session_id="session-1",
        user_id="default",
        channel="console",
        agent_id="default",
        title=None,
        questions=[_question()],
    )
    waiter = asyncio.create_task(svc.wait_for_result(pending.request_id, 1))
    await asyncio.sleep(0)

    await svc.answer_request(
        pending.request_id,
        UserInputAnswer(action="ignore", answers={}),
    )
    result = await waiter

    assert result.status == "ignored"
    assert result.answers == {}


def test_ignore_answer_resolves_as_ignored():
    asyncio.run(_ignore_answer_resolves_as_ignored())


async def _timeout_cleans_pending():
    svc = UserInputService()
    pending = await svc.create_pending(
        session_id="session-1",
        root_session_id="session-1",
        user_id="default",
        channel="console",
        agent_id="default",
        title=None,
        questions=[_question()],
    )

    result = await svc.wait_for_result(pending.request_id, 0.01)

    assert result.status == "timeout"
    assert await svc.get_pending(agent_id="default", session_id="session-1") is None


def test_timeout_cleans_pending():
    asyncio.run(_timeout_cleans_pending())


async def _other_session_cannot_read_pending():
    svc = UserInputService()
    await svc.create_pending(
        session_id="session-1",
        root_session_id="session-1",
        user_id="default",
        channel="console",
        agent_id="default",
        title=None,
        questions=[_question()],
    )

    assert await svc.get_pending(agent_id="default", session_id="session-2") is None


def test_other_session_cannot_read_pending():
    asyncio.run(_other_session_cannot_read_pending())
