"""Real private Driver effects; host RPC double only at the public boundary."""
import asyncio

import aiohttp
import pytest

from onebot_native_suite import driver_at, message, until, ws_url
from qwenpaw.channel_protocol.models import SendParams


@pytest.mark.parametrize('fail_file', [False, True])
async def test_ordered_text_file_text_and_partial_success_is_unknown(tmp_path, fail_file):
    async with driver_at(tmp_path) as (driver, peer, identity):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                route = await peer.methods['channel.response.open']({**identity, 'to_handle': '12345', 'meta': {}}, None)
                params = SendParams.from_mapping({**identity, 'to_handle': route['response_handle'], 'delivery_id': 'ordered-parts', 'operation': 'message.create', 'content_parts': [
                    {'type': 'text', 'text': 'before'},
                    {'type': 'file', 'file_url': 'https://files.test/a.txt', 'filename': 'a.txt'},
                    {'type': 'text', 'text': 'after'},
                ]})
                send = asyncio.create_task(peer.methods['channel.send'](params, None))
                try:
                    before = await asyncio.wait_for(ws.receive_json(), 1)
                    assert before['action'] == 'send_private_msg'
                    assert before['params']['message'] == [{'type': 'text', 'data': {'text': 'before'}}]
                    await ws.send_json({'retcode': 0, 'data': {}, 'echo': before['echo']})
                    file_action = await asyncio.wait_for(ws.receive_json(), 1)
                    assert file_action['action'] == 'upload_private_file'
                    assert file_action['params'] == {'user_id': 12345, 'file': 'https://files.test/a.txt', 'name': 'a.txt'}
                    await ws.send_json({'retcode': 1 if fail_file else 0, 'status': 'failed' if fail_file else 'ok', 'data': {}, 'echo': file_action['echo']})
                    if fail_file:
                        result = await asyncio.wait_for(send, 1)
                        assert result['state'] == 'unknown'
                        assert result['reason_code'] == 'PARTIAL_DELIVERY'
                        assert (await peer.methods['channel.send'](params, None))['state'] == 'unknown'
                        with pytest.raises(asyncio.TimeoutError):
                            await asyncio.wait_for(ws.receive_json(), .05)
                    else:
                        after = await asyncio.wait_for(ws.receive_json(), 1)
                        assert after['action'] == 'send_private_msg'
                        assert after['params']['message'] == [{'type': 'text', 'data': {'text': 'after'}}]
                        await ws.send_json({'retcode': 0, 'data': {}, 'echo': after['echo']})
                        assert (await asyncio.wait_for(send, 1))['state'] == 'acknowledged'
                finally:
                    if not send.done():
                        send.cancel()
                    await asyncio.gather(send, return_exceptions=True)


async def test_link_cleanup_preserves_comments_and_code(tmp_path):
    async with driver_at(tmp_path) as (driver, peer, identity):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                text = ('为你找到了链接：\n**https://example.com/profile**\n'
                        '[profile](https://example.com/card)\n'
                        '`[inline](https://example.com/inline)`\n'
                        '```\n**https://example.com/code**\n```\n'
                        '<!-- internal lookup note -->')
                send = asyncio.create_task(driver._platform.send_message('12345', [{'type': 'text', 'text': text}]))
                try:
                    action = await asyncio.wait_for(ws.receive_json(), 1)
                    assert action['action'] == 'send_private_msg'
                    assert action['params']['message'] == [{'type': 'text', 'data': {'text':
                        '为你找到了链接：\nhttps://example.com/profile\n'
                        'profile: https://example.com/card\n'
                        '`[inline](https://example.com/inline)`\n'
                        '```\n**https://example.com/code**\n```\n'
                        '<!-- internal lookup note -->'}}]
                    await ws.send_json({'retcode': 0, 'data': {}, 'echo': action['echo']})
                    await asyncio.wait_for(send, 1)
                finally:
                    if not send.done():
                        send.cancel()
                    await asyncio.gather(send, return_exceptions=True)


async def test_mention_guard_precedes_quote_lookup_and_quote_echo_does_not_block(tmp_path):
    async with driver_at(tmp_path, require_mention=True) as (driver, peer, identity):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                quoted = message(401, group=777)
                quoted['message'] = [{'type': 'reply', 'data': {'id': '88'}}, {'type': 'text', 'data': {'text': 'current'}}]
                await ws.send_json(quoted)
                await ws.send_json(message(402, user=67890))
                await until(lambda: len(peer.batches) == 1)
                assert peer.batches[0]['events'][0]['event_id'] == 'onebot:message:402'
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.receive_json(), .05)
                quoted['message'].append({'type': 'at', 'data': {'qq': '99999'}})
                await ws.send_json(quoted)
                action = await asyncio.wait_for(ws.receive_json(), 1)
                assert action['action'] == 'get_msg'
                assert action['params'] == {'message_id': 88}
                await ws.send_json(message(403, user=67890))
                await until(lambda: len(peer.batches) == 2)
                await ws.send_json({'retcode': 0, 'data': {'message': 'quoted text'}, 'echo': action['echo']})
                await until(lambda: len(peer.batches) == 3)
                event = peer.batches[-1]['events'][0]
                assert event['event_id'] == 'onebot:message:401'
                assert event['acl_sender_id'] == '12345'
                assert event['content_parts'] == [{'type': 'text', 'text': '[Quoted message]\nquoted text\n\n[Current message]\ncurrent'}]


async def test_shared_admission_retry_preserves_exact_batch_and_event_identity(tmp_path):
    async with driver_at(tmp_path) as (driver, peer, identity):
        call = peer.call
        batches = []
        async def pressure_once(method, params):
            if method == 'event.batch':
                batches.append(params)
                if len(batches) == 1:
                    return {'batch_id': params['batch_id'], 'rejected_events': [{'event_id': params['events'][0]['event_id'], 'reason_code': 'CORE_QUEUE_FULL', 'retryable': True}]}
            return await call(method, params)
        peer.call = pressure_once
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                await ws.send_json(message(303, text='retry'))
                await until(lambda: len(peer.batches) == 1)
                assert len(batches) == 2
                assert batches[0] == batches[1]
                assert batches[0]['events'][0]['event_id'] == 'onebot:message:303'
                assert driver._platform.health_snapshot()['runner_event_dropped_total'] == 0
                # Legacy three Core admission counters remain pending at the
                # public layer; this proves retry identity, not those counters.
