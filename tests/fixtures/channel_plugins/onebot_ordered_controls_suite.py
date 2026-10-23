"""Narrow opt-in ordered-parts behavior through the actual generic worker."""
import json
from pathlib import Path
import sys

import pytest

from onebot_host_order_suite import ordered_source, ordered_policy
from semantic_event_host_suite import semantic_source
from qwenpaw.channel_protocol.response_policy import SendFormatPolicy
from qwenpaw.channel_protocol.errors import ProtocolValidationError

pytest_plugins = ['extension_process_suite']
FILE = {'type': 'file', 'file_url': 'https://files.test/a.txt', 'filename': 'a.txt'}
IMAGE = {'type': 'image', 'image_url': 'https://files.test/a.png'}
MIXED = [{'type': 'text', 'text': 'before'}, FILE, {'type': 'text', 'text': 'after'}]


@pytest.mark.parametrize('value', [0, 1, None, 'true', []])
def test_ordered_policy_is_strict_boolean(value):
    with pytest.raises(ProtocolValidationError):
        SendFormatPolicy(parts_preserve_order=value)
    with pytest.raises(ProtocolValidationError):
        SendFormatPolicy.from_mapping({'direct_prefix': True, 'parts_configured_prefix': True, 'parts_preserve_order': value})


def test_policy_unknown_field_rejected_and_legacy_wire_unchanged():
    legacy = {'direct_prefix': True, 'parts_configured_prefix': True}
    assert SendFormatPolicy().to_mapping() == legacy
    assert SendFormatPolicy.from_mapping(legacy).parts_preserve_order is False
    explicit = {**legacy, 'parts_preserve_order': True}
    assert SendFormatPolicy.from_mapping(explicit).to_mapping() == explicit
    old_false = {**legacy, 'parts_metadata_prefix': False, 'stream_prefix': False, 'parts_strip_text': False}
    assert SendFormatPolicy.from_mapping(old_false).to_mapping() == old_false
    with pytest.raises(ProtocolValidationError):
        SendFormatPolicy.from_mapping({**legacy, 'preserve_order': True})


def test_real_onebot_driver_opts_in_without_changing_other_format_flags():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'plugins/channel/onebot'))
    from qwenpaw_channel_onebot.driver import OneBotDriver
    policy = OneBotDriver().response_policy('unused').send_format
    assert policy.to_mapping() == {'direct_prefix': False, 'parts_configured_prefix': False,
                                   'stream_prefix': False, 'parts_preserve_order': True}
    assert policy.parts_metadata_prefix is True
    assert policy.parts_strip_text is True


async def effects(rt):
    return [row for row in (await rt.process.call('fixture.inspect', {}))['effects'] if row['operation'] == 'message.create']


def target(rt):
    return rt.channel.to_handle_from_target(user_id='member', session_id='room-A')


@pytest.mark.asyncio
async def test_default_route_keeps_legacy_flattening(runtime):
    rt = await runtime(source_factory=semantic_source)
    await rt.channel.send_content_parts(target(rt), MIXED, {})
    rows = await effects(rt)
    assert len(rows) == 1
    assert rows[0]['content_source'] == 'content_parts'
    assert rows[0]['content_parts'] == [{'type': 'text', 'text': 'before\nafter'}, FILE]


@pytest.mark.asyncio
@pytest.mark.parametrize(('strip', 'meta_prefix', 'first', 'last'), [
    (True, 'META', 'META  before\nrefusal', 'after'),
    (True, None, 'CFG  before\nrefusal', 'after'),
    (False, 'META', 'META    before\nrefusal  ', ' after '),
])
async def test_adjacent_runs_strip_and_media_first_prefix_only_once(runtime, strip, meta_prefix, first, last):
    rt = await runtime(source_factory=ordered_source, bot_prefix='CFG', route_policies={'room-A': ordered_policy(parts_strip_text=strip)})
    parts = [{'type': 'text', 'text': ''}, IMAGE, {'type': 'text', 'text': '  before'},
             {'type': 'refusal', 'refusal': 'refusal  '}, FILE,
             {'type': 'text', 'text': ' after '}]
    await rt.channel.send_content_parts(target(rt), parts, {'bot_prefix': meta_prefix} if meta_prefix else {})
    rows = await effects(rt)
    assert len(rows) == 1
    assert rows[0]['content_parts'] == [IMAGE, {'type': 'text', 'text': first}, FILE, {'type': 'text', 'text': last}]


def merge_source(directory, key, *, capabilities=None):
    source = ordered_source(directory, key, capabilities=capabilities)
    path = source / 'channel.json'
    descriptor = json.loads(path.read_text())
    descriptor['capabilities'] = sorted(set(descriptor['capabilities']) | {'channel.text_merge.v1'})
    descriptor['config_schema']['properties']['route_policies']['additionalProperties']['properties']['text_merge_delay_ms'] = {'type': 'integer', 'minimum': 0}
    path.write_text(json.dumps(descriptor))
    return source


@pytest.mark.asyncio
async def test_pending_text_flushes_before_one_ordered_mixed_operation(runtime):
    policy = {**ordered_policy(), 'text_merge_delay_ms': 10000}
    rt = await runtime(source_factory=merge_source, route_policies={'room-A': policy})
    meta = {}
    async with rt.channel._response_scope(meta):
        await rt.channel.send_content_parts(target(rt), [{'type': 'text', 'text': 'pending'}], meta)
        assert await effects(rt) == []
        await rt.channel.send_content_parts(target(rt), MIXED, meta)
        rows = await effects(rt)
        assert len(rows) == 2
        assert [row['content_parts'] for row in rows] == [[{'type': 'text', 'text': 'pending'}], MIXED]
        assert [row['content_source'] for row in rows] == ['content_parts', 'content_parts']


@pytest.mark.asyncio
async def test_unknown_ordered_operation_is_not_replayed(runtime):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    rt = await runtime(source_factory=ordered_source, route_policies={'room-A': ordered_policy()})
    await rt.process.call('fixture.fault', {'mode': 'unknown'})
    meta = {}
    for _ in range(2):
        with pytest.raises(ChannelDeliveryError) as caught:
            await rt.channel.send_content_parts(target(rt), MIXED, meta)
        assert caught.value.state == 'unknown' and caught.value.side_effect_possible
    assert meta['_reply_unknown'] is True
    rows = await effects(rt)
    assert len(rows) == 1
    assert rows[0]['content_parts'] == MIXED


def trace_source(directory, key, *, capabilities=None):
    source = ordered_source(directory, key, capabilities=capabilities)
    path = source / key / 'driver.py'
    body = path.read_text()
    needle = '"content_parts": list(getattr(params, "content_parts", ())),'
    assert body.count(needle) == 1
    body = body.replace(needle, needle + '\n                "accumulated_text": getattr(params, "accumulated_text", None),')
    path.write_text(body)
    return source


@pytest.mark.asyncio
async def test_optin_leaves_direct_stream_and_completed_semantic_roles_intact(runtime):
    from qwenpaw.schemas import Message, TextContent
    policy = {**ordered_policy(), 'streaming': True}
    rt = await runtime(source_factory=trace_source, bot_prefix='CFG', streaming_enabled=True, route_policies={'room-A': policy})
    handle = target(rt)
    await rt.channel.send(handle, ' direct ', {})
    rows = await effects(rt)
    assert rows[0]['content_parts'] == [{'type': 'text', 'text': 'CFG direct '}]
    assert rows[0]['content_source'] == 'direct'
    request = rt.channel.build_agent_request_from_native({'sender_id': 'member', 'session_id': 'room-A', 'content_parts': [{'type': 'text', 'text': 'question'}], 'meta': {}})
    event = Message(object='message', type='reasoning', role='assistant', status='completed', content=[TextContent(text='analysis')])
    await rt.channel.on_event_message_completed(request, handle, event, {})
    rows = await effects(rt)
    assert rows[-1]['content_parts'] == [{'type': 'text', 'text': 'analysis', 'role': 'reasoning'}]
    assert rows[-1]['content_source'] == 'event'
    meta = {}
    async with rt.channel._response_scope(meta):
        await rt.channel.on_streaming_start(request, handle, event, meta, 'message')
        await rt.channel.on_streaming_delta(request, handle, event, meta, 'message', accumulated_text='stream')
        await rt.channel.on_streaming_end(request, handle, event, meta, 'message', accumulated_text='stream end')
    all_rows = (await rt.process.call('fixture.inspect', {}))['effects']
    streams = [row for row in all_rows if row['operation'].startswith('stream.')]
    assert [row['operation'] for row in streams] == ['stream.start', 'stream.delta', 'stream.end']
    assert [row['accumulated_text'] for row in streams] == ['CFG  ...', 'CFG  stream', 'CFG  stream end']


@pytest.mark.asyncio
async def test_whitespace_run_does_not_consume_first_real_text_prefix(runtime):
    rt = await runtime(source_factory=ordered_source, bot_prefix='CFG', route_policies={'room-A': ordered_policy()})
    await rt.channel.send_content_parts(target(rt), [
        {'type': 'text', 'text': '   '}, IMAGE,
        {'type': 'text', 'text': ' first '}, FILE,
        {'type': 'text', 'text': ' second '},
    ], {})
    rows = await effects(rt)
    assert len(rows) == 1
    assert rows[0]['content_parts'] == [IMAGE, {'type': 'text', 'text': 'CFG  first'}, FILE, {'type': 'text', 'text': 'second'}]
