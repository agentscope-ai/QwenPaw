"""Generic target-open controls through actual sample worker; no XiaoYi branch."""
import asyncio
import json
import os

import pytest
from extension_sample import sample_source
from extension_process_suite import eventually

pytest_plugins = ['extension_process_suite']


def target_failure_source(directory, key, *, capabilities=None):
    source = sample_source(directory, key, capabilities=capabilities)
    path = source / key / 'driver.py'
    with path.open('a') as stream:
        stream.write('''
from qwenpaw.channel_protocol.errors import RPC_RESPONSE_OPEN_FAILED
from qwenpaw.channel_protocol.response_policy import ResponsePolicy

_OriginalDriver = Driver
class Driver(_OriginalDriver):
    def __init__(self):
        super().__init__()
        self.open_attempts = []
        self.open_active = 0
        self.open_cancelled = 0
        self.release = asyncio.Event()

    def response_open_policy(self):
        if self.fault == "default":
            return super().response_open_policy()
        return ResponsePolicy(continue_on_delivery_error=True)

    async def inspect(self, params, request):
        state = await super().inspect(params, request)
        state.update(open_attempts=self.open_attempts, open_active=self.open_active, open_cancelled=self.open_cancelled)
        return state

    async def set_fault(self, params, request):
        if params["mode"] == "release":
            self.release.set()
            return {}
        return await super().set_fault(params, request)

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        self.open_attempts.append({"pid": os.getpid(), "mode": self.fault})
        if self.fault.startswith("malformed-"):
            data = {"operation":"channel.response.open", "result":{"delivery_id":"unroutable","state":"failed","reason_code":"TARGET_ABSENT","retryable":False}, "continue_on_delivery_error":True}
            if self.fault == "malformed-extra":
                data["unexpected"] = True
            elif self.fault == "malformed-unknown":
                data["result"]["state"] = "unknown"
            elif self.fault == "malformed-bool":
                data["continue_on_delivery_error"] = 1
            raise RpcError(RPC_RESPONSE_OPEN_FAILED, "controlled malformed target result", data=data)
        self.open_active += 1
        try:
            with self.target_resolution():
                if self.fault == "blocked":
                    await self.release.wait()
                if self.fault == "internal":
                    raise RuntimeError("UNEXPECTED_INTERNAL_FAILURE")
                raise DeliveryError("TARGET_ABSENT", side_effect_possible=self.fault == "unknown")
        except asyncio.CancelledError:
            self.open_cancelled += 1
            raise
        finally:
            self.open_active -= 1
''')
    return source


def completed_call(channel, *, approval=False):
    from qwenpaw.schemas import Message, TextContent
    request = channel.build_agent_request_from_native({'sender_id':'member','session_id':'room-A','content_parts':[{'type':'text','text':'question'}],'meta':{}})
    event = Message(object='message', type='message', role='assistant', status='completed', content=[TextContent(text='answer')])
    if approval:
        event.metadata = {'message_type':'tool_guard_approval','approval_request_id':'approval-A','tool_name':'controlled-tool','severity':'medium'}
    target = channel.get_to_handle_from_request(request)
    metadata = {}
    return channel.on_event_message_completed(request, target, event, metadata), metadata


async def inspect_no_effects(rt):
    state = await rt.process.call('fixture.inspect', {})
    assert state['pid'] == rt.process.health_snapshot()['pid'] != os.getpid()
    assert state['effects'] == [] and state['routes'] == []
    assert state['finish_calls'] == []
    assert all(row['pid'] == state['pid'] for row in state['open_attempts'])
    return state


@pytest.mark.asyncio
async def test_generic_safe_target_failure_is_truthful_ordinary_failure_but_api_stays_rpc_error(runtime):
    from qwenpaw.channel_protocol.errors import RpcError, RPC_RESPONSE_OPEN_FAILED
    rt = await runtime(source_factory=target_failure_source)
    await rt.process.call('fixture.fault', {'mode':'safe'})
    with pytest.raises(RpcError) as api:
        await rt.channel.send('room-A', 'answer', {})
    assert api.value.code == RPC_RESPONSE_OPEN_FAILED
    assert api.value.data == {'operation':'channel.response.open','result':{'delivery_id':'unroutable','state':'failed','reason_code':'TARGET_ABSENT','retryable':False},'continue_on_delivery_error':True}
    call, meta = completed_call(rt.channel)
    await call
    assert meta['_reply_failed'] is True
    assert meta['_continued_event_delivery_error'] == {'state':'failed','reason_code':'TARGET_ABSENT'}
    state = await inspect_no_effects(rt)
    assert len(state['open_attempts']) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['default','unknown','internal','malformed-extra','malformed-unknown','malformed-bool'])
async def test_non_optin_uncertain_internal_or_malformed_open_failure_never_becomes_success(runtime, mode):
    from qwenpaw.channel_protocol.errors import RpcError, ProtocolValidationError
    rt = await runtime(source_factory=target_failure_source)
    await rt.process.call('fixture.fault', {'mode':mode})
    call, meta = completed_call(rt.channel)
    expected_error = ProtocolValidationError if mode.startswith('malformed-') else RpcError
    with pytest.raises(expected_error):
        await call
    assert not meta.get('_reply_failed') and '_continued_event_delivery_error' not in meta
    state = await inspect_no_effects(rt)
    assert len(state['open_attempts']) == 1


@pytest.mark.asyncio
async def test_approval_target_failure_never_uses_ordinary_tolerance(runtime):
    from qwenpaw.channel_protocol.errors import RpcError
    rt = await runtime(source_factory=target_failure_source)
    await rt.process.call('fixture.fault', {'mode':'safe'})
    call, meta = completed_call(rt.channel, approval=True)
    with pytest.raises(RpcError):
        await call
    assert '_continued_event_delivery_error' not in meta
    assert len((await inspect_no_effects(rt))['open_attempts']) == 1


async def wait_open_entered(rt):
    async with asyncio.timeout(8):
        while True:
            state = await rt.process.call('fixture.inspect', {})
            if state['open_active'] == 1:
                return state
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancel_actual_pending_open_preserves_cancellation_and_no_effect(runtime):
    rt = await runtime(source_factory=target_failure_source)
    await rt.process.call('fixture.fault', {'mode':'blocked'})
    call, meta = completed_call(rt.channel)
    task = asyncio.create_task(call)
    try:
        await wait_open_entered(rt)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await rt.process.call('fixture.fault', {'mode':'release'})
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    state = await inspect_no_effects(rt)
    assert state['open_active'] == 0
    assert not meta.get('_reply_failed') and '_continued_event_delivery_error' not in meta


@pytest.mark.asyncio
async def test_real_disable_retires_pending_open_without_tolerated_success(runtime):
    from qwenpaw.plugins.execution.process import CallUnknown
    rt = await runtime(source_factory=target_failure_source)
    await rt.process.call('fixture.fault', {'mode':'blocked'})
    old_identity = rt.channel._identity().to_mapping()
    call, meta = completed_call(rt.channel)
    task = asyncio.create_task(call)
    try:
        await wait_open_entered(rt)
        report = await rt.loader.lifecycle.set_enabled(rt.key, False)
        assert report.clean and report.quiescent
        assert report.errors == [] and report.leftovers == [] and report.workspace_leaks == []
        with pytest.raises(CallUnknown) as retired:
            await task
        assert retired.value.reason_code == 'PLATFORM_RESULT_UNKNOWN'
        assert retired.value.method == 'channel.response.open'
        assert retired.value.generation == old_identity['generation']
        assert not meta.get('_reply_failed') and '_continued_event_delivery_error' not in meta
        report = await rt.loader.lifecycle.set_enabled(rt.key, True)
        assert report.status == 'active' and report.enabled
        current = await rt.manager.get_channel(rt.key)
        assert current._identity().to_mapping() != old_identity
        state = await current.channel_process.call('fixture.inspect', {})
        assert state['effects'] == [] and state['routes'] == []
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
