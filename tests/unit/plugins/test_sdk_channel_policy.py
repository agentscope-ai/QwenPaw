# -*- coding: utf-8 -*-
"""Public response policy through real workers and the production Runtime."""

import json

import pytest

from qwenpaw.app.channels import manager as channel_manager
from qwenpaw.plugins.channel_workers import ChannelDefinition, ResponsePolicy
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.testing import PluginTestHost
from tests.channel_support.sdk import make_channel, workspace_store
from tests.channel_support.process import alive, eventually
from .sdk_author_fixture import make_plugin

MODEL = """
import asyncio
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.tools import ToolSpec, ToolResult
class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            count = ctx.storage.read_json("calls.json", 0) + 1
            ctx.storage.write_json("calls.json", count)
            if count == 2 and ctx.config.get("cancel"):
                ctx.storage.write_json("waiting.json", True)
                try:
                    await asyncio.Event().wait()
                finally:
                    ctx.storage.write_json("cancelled.json", True)
            blocks = (ContentBlock(text="part-" + str(count)),)
            if count == 1:
                blocks += (ContentBlock("tool_call", id="policy-call", name="policy_echo", arguments="{}"),)
            yield ModelChunk(blocks, is_last=True)
        def echo(call, arguments):
            ctx.storage.write_json("tool.json", True)
            return ToolResult.text("tool-result")
        ctx.register_provider(ProviderSpec("policy-model", "Policy model", generate,
            models=(ModelInfo("model", "Model"),), require_api_key=False))
        ctx.register_tool(ToolSpec("policy_echo", "Return a fixed local value", {"type": "object"}, echo, enabled=True))
plugin = Plugin()
"""

DRIVER = """
import os
import asyncio
import json
from qwenpaw.plugins.channel_workers import (
    ChannelDriver,
    ChannelSendResult,
    ChannelDeliveryError,
    ResponsePolicy,
)
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock


class Driver(ChannelDriver):
    response_policy = ResponsePolicy(
        text_merge_delay_ms=DELAY, continue_on_delivery_error=CONTINUE
    )

    async def start(self, ch):
        self.cases = ch.config.get("cases", {})
        await ch.storage.awrite_json("pid.json", os.getpid())
        await ch.report_status("connected")
        if ch.config.get("manual"):
            return
        await ch.receive(
            ChannelMessage(
                "alice",
                (ContentBlock(text="Run two turns"),),
                session_id="room",
                message_id="message-one",
            )
        )

    def response_policy_for(self, target):
        case = self.cases.get(target.session_id)
        if case is None:
            return self.response_policy
        delay, continued, _ = case
        return ResponsePolicy(
            text_merge_delay_ms=delay, continue_on_delivery_error=continued
        )

    def record(self, session, filename):
        return f"{session}/{filename}" if session in self.cases else filename

    async def send(self, ch, response):
        text = "\\n".join(block.text for block in response.content)
        if text.startswith("request-start:"):
            data = json.loads(text.removeprefix("request-start:"))
            await ch.receive(
                ChannelMessage(
                    data["user"],
                    (ContentBlock(text="hello"),),
                    session_id=data["session"],
                    message_id=data["message"],
                    is_group=data.get("group", False),
                    mentioned=data.get("group", False),
                    session_scope="group" if data.get("group") else "default",
                )
            )
            return ChannelSendResult("start-submitted")
        if text.strip() == "request-cancel":
            await ch.receive(
                ChannelMessage(
                    "alice",
                    (ContentBlock(text="/stop"),),
                    session_id="room",
                    message_id="cancel-one",
                    metadata={"has_bot_command": True},
                )
            )
            return ChannelSendResult("cancel-submitted")
        session = response.target.session_id
        sent = self.record(session, "sent.json")
        calls = await ch.storage.aread_json(sent, [])
        calls.append(text)
        await ch.storage.awrite_json(sent, calls)
        _, _, failure = self.cases.get(session, (None, False, ""))
        if failure and len(calls) == 1:
            raise ChannelDeliveryError(
                "PLATFORM_TEST_FAILURE",
                side_effect_possible=failure == "unknown",
            )
        return ChannelSendResult(str(len(calls)))

    async def finish_response(self, ch, target, outcome):
        await ch.storage.awrite_json(self.record(target.session_id, "finished.json"), outcome)

    async def stop(self, ch):
        await ch.storage.awrite_json("stopped.json", True)

    async def on_run(self, ch, event):
        assert ch.deadline is not None and ch.remaining_timeout() > 0
        if ch.config.get("failure") == "slow-end" and event.phase == "end":
            await ch.storage.awrite_json("run-ending.json", True)
            while True:
                try:
                    if await ch.storage.aread_json("release.json", False):
                        break
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    continue
        runs = self.record(event.session_id, "runs.json")
        values = await ch.storage.aread_json(runs, [])
        values.append(
            {
                "id": event.run_id,
                "phase": event.phase,
                "status": event.status,
                "user": event.user_id,
                "session": event.session_id,
                "sender": event.sender_id,
                "acl": event.acl_sender_id,
                "messages": list(event.message_ids),
                "target": event.target,
                "workspace": ch.workspace_id,
            }
        )
        await ch.storage.awrite_json(runs, values)
"""


@pytest.mark.parametrize("delay", [-1, True, 1.5, "10", 2**63])
def test_merge_delay_is_a_bounded_integer(delay):
    with pytest.raises(ValueError):
        ResponsePolicy(text_merge_delay_ms=delay)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["delivery", "cancel", "cancel-after-idle", "slow-end"],
)
async def test_policy_controls_actual_runtime_delivery(
    tmp_path,
    monkeypatch,
    scenario,
):
    source = tmp_path / "channel"
    key = "sdk-policy"
    definition = ChannelDefinition(
        key,
        {"en": "Policy", "zh": "策略验证"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        (
            "channel.generic.v1",
            "channel.run_events.v1",
            "channel.text_merge.v1",
        ),
    )
    delay = {"cancel": 10000, "cancel-after-idle": 30}.get(scenario)
    make_channel(
        source,
        DRIVER.replace("DELAY", repr(delay)).replace("CONTINUE", "False"),
        definition,
        capabilities=["channels", "storage"],
    )
    provider_source = make_plugin(
        tmp_path,
        MODEL,
        ["providers", "storage", "tools"],
        sdk_version="1.2.0",
    )
    root = tmp_path / "host"
    async with PluginTestHost(root, process_channels=(key,)) as host:
        assert (await host.install(source)).ok
        provider = await host.load(
            provider_source,
            config={"cancel": scenario.startswith("cancel")},
        )
        await host.configure_chat_model("policy-model", "model")
        cases = (
            {
                "no-timer": (0, False, ""),
                "delayed": (10000, False, ""),
                "failed-stop": (None, False, "failed"),
                "failed-continue": (None, True, "failed"),
                "unknown": (None, True, "unknown"),
            }
            if scenario == "delivery"
            else {}
        )
        await host.start_channel(
            key,
            {"failure": scenario, "manual": bool(cases), "cases": cases},
        )
        storage = workspace_store(root, key, "test")
        if scenario == "slow-end":
            await eventually((storage / "run-ending.json").exists, timeout=15)
            pid = json.loads((storage / "pid.json").read_text())
            try:
                with monkeypatch.context() as deadlines:
                    deadlines.setattr(
                        channel_manager,
                        "_CHANNEL_DRAIN_TIMEOUT",
                        1.0,
                    )
                    with pytest.raises(
                        SDKError,
                        match="CHANNEL_DRAIN_TIMEOUT",
                    ):
                        await host.stop_channel(key)
                assert alive(pid)
                assert not (storage / "finished.json").exists()
                assert not (storage / "stopped.json").exists()
            finally:
                (storage / "release.json").write_text("true")
            await host.stop_channel(key)
            assert not alive(pid)
            assert (
                json.loads((storage / "finished.json").read_text())
                == "completed"
            )
            assert json.loads((storage / "stopped.json").read_text()) is True
            events = json.loads((storage / "runs.json").read_text())
            assert [(event["phase"], event["status"]) for event in events] == [
                ("start", "running"),
                ("end", "completed"),
            ]
            assert events[0]["id"] == events[1]["id"]
            assert (await host.uninstall(key)).quiescent
            return
        if scenario.startswith("cancel"):
            await eventually(
                lambda: provider.storage.read_json("waiting.json", False),
                timeout=15,
            )
            pid = json.loads((storage / "pid.json").read_text())
            before = []
            if scenario == "cancel-after-idle":

                def sent_tool_result():
                    if not (storage / "sent.json").exists():
                        return False
                    return any(
                        "tool-result" in text
                        for text in json.loads(
                            (storage / "sent.json").read_text(),
                        )
                    )

                await eventually(sent_tool_result, timeout=5)
                before = json.loads((storage / "sent.json").read_text())
                assert not provider.storage.read_json("cancelled.json", False)
                assert not (storage / "finished.json").exists()
                assert "policy_echo" in before[0]
            await host.send_channel(
                key,
                "request-cancel",
                user_id="alice",
                session_id="room",
            )
            await eventually(
                lambda: provider.storage.read_json("cancelled.json", False),
                timeout=10,
            )
            await host.stop_channel(key)
            assert provider.storage.read_json("cancelled.json") is True
            assert not alive(pid)
            sent = json.loads((storage / "sent.json").read_text())
            assert sent[:-1] == before and "Task Stopped" in sent[-1]
            assert "policy_echo" not in sent[-1]
            assert all("part-" not in text for text in sent)
            assert provider.storage.read_json("calls.json") == 2
            events = json.loads((storage / "runs.json").read_text())
            original = [
                event
                for event in events
                if event["messages"] == ["message-one"]
            ]
            assert [
                (event["phase"], event["status"]) for event in original
            ] == [
                ("start", "running"),
                ("end", "cancelled"),
            ]
            assert original[0]["id"] == original[1]["id"]
            assert (await host.uninstall(key)).quiescent
            return
        for session, (_, continued, failure) in cases.items():
            provider.storage.delete("calls.json")
            provider.storage.delete("tool.json")
            await host.send_channel(
                key,
                "request-start:"
                + json.dumps(
                    {"user": "alice", "session": session, "message": session},
                ),
                user_id="alice",
                session_id="policy-test-control",
            )
            case_storage = storage / session
            await eventually(
                (case_storage / "finished.json").exists,
                timeout=15,
            )
            sent = json.loads((case_storage / "sent.json").read_text())
            outcome = json.loads((case_storage / "finished.json").read_text())
            calls = provider.storage.read_json("calls.json")
            events = json.loads((case_storage / "runs.json").read_text())
            assert [(event["phase"], event["status"]) for event in events] == [
                ("start", "running"),
                ("end", "failed" if failure else "completed"),
            ], session
            assert events[0]["id"] == events[1]["id"]
            assert all(
                event["user"] == event["sender"] == event["acl"] == "alice"
                and event["session"] == event["target"] == session
                and event["messages"] == [session]
                and event["workspace"] == "test"
                for event in events
            )
            if not failure:
                assert calls == 2 and outcome == "completed", session
                assert provider.storage.read_json("tool.json") is True
                assert len(sent) == 1
                assert (
                    sent[0].index("policy_echo")
                    < sent[0].index("tool-result")
                    < sent[0].index("part-2")
                )
            else:
                assert outcome == "failed", session
                assert calls == (2 if continued else 1), session
                assert sent.count(sent[0]) == 1
                if failure == "unknown":
                    assert len(sent) == 1
                assert any("part-2" in text for text in sent) == (
                    continued and failure != "unknown"
                )
        pid = json.loads((storage / "pid.json").read_text())
        assert alive(pid)
        result = await host.uninstall(key)
        assert result.clean and result.quiescent and not alive(pid)
