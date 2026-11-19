import asyncio
from uuid import uuid4

import pytest

from qwenpaw.artifacts.repository import PostgresArtifactRepository
from qwenpaw.user_input.schemas import UserInputAnswer, UserInputQuestion
from qwenpaw.user_input.service import UserInputService


@pytest.mark.asyncio
async def test_same_sample_shares_human_answer_and_changed_sample_needs_new_answer(monkeypatch):
    store = {}

    async def sample_answer(self, *, answer=None, **scope):
        key = tuple(sorted(scope.items()))
        if answer is not None:
            store[key] = answer
        return store.get(key)

    monkeypatch.setattr(PostgresArtifactRepository, "sample_answer", sample_answer)
    owner = uuid4()
    scope = dict(owner=owner, agent=uuid4(), chat=uuid4(), artifact=uuid4())
    args = dict(session_id="chat", root_session_id="chat", user_id=str(owner),
                recipient_user_id=str(owner), agent_id="ppt", channel="console",
                title="确认样稿", questions=[UserInputQuestion(id="sample_approval", question="确认样稿？")],
                timeout_seconds=3)

    async def answer(service, value):
        for _ in range(20):
            pending = await service.get_pending(agent_id="ppt", session_id="chat", user_id=str(owner))
            if pending:
                await service.answer_request(pending.request_id,
                    UserInputAnswer(answers={"sample_approval": value}), agent_id="ppt", user_id=str(owner))
                return
            await asyncio.sleep(.005)
        pytest.fail("sample question was not presented")

    service = UserInputService()
    first, duplicate, _ = await asyncio.gather(
        service.ask_about_sample(scope, **args), service.ask_about_sample(scope, **args),
        answer(service, "确认并生成"),
    )
    assert first == duplicate
    restarted = UserInputService()
    assert (await restarted.ask_about_sample(scope, **args))["reused"]
    changed = {**scope, "artifact": uuid4()}
    for _ in range(2):
        response, _ = await asyncio.gather(restarted.ask_about_sample(changed, **args), answer(restarted, "调整样稿"))
        assert "reused" not in response
