"""Private OneBot native loopback; host RPC is a boundary, not Core proof."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import socket
import sys

import aiohttp
from aiohttp import web
import pytest
from g2_shared_response_suite import Peer

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'plugins/channel/onebot'))
from qwenpaw_channel_onebot.platform import OneBotPlatform, OneBotPlatformError
from qwenpaw_channel_onebot.driver import OneBotDriver
from qwenpaw_channel_onebot.media import OneBotInboundMedia
from qwenpaw.channel_protocol.models import IdentityParams, SendParams
from qwenpaw.channel_protocol.shared_worker import DriverContext


async def until(check):
    async def poll():
        while not check():
            await asyncio.sleep(.005)
    await asyncio.wait_for(poll(), 1)


def message(number, *, user=12345, group=None, text='hello'):
    value = {'post_type': 'message', 'message_type': 'group' if group else 'private',
             'message_id': number, 'user_id': user, 'self_id': 99999,
             'message': [{'type': 'text', 'data': {'text': text}}],
             'sender': {'nickname': 'TestUser', 'card': ''}}
    if group:
        value['group_id'] = group
    return value


@asynccontextmanager
async def platform_at(tmp_path, *, handler=None, host='127.0.0.1', token='', **kwargs):
    platform = OneBotPlatform(**kwargs)
    events, endpoints = [], []
    async def receive(value):
        events.append(value)
        if handler:
            await handler(value)
    async def endpoint(operation, value):
        endpoints.append((operation, value))
    await platform.prepare({'ws_host': host, 'ws_port': 0, 'workspace_dir': str(tmp_path)}, {'access_token': token})
    try:
        await platform.start(receive, endpoint)
        yield platform, events, endpoints
    finally:
        await platform.close()


def ws_url(platform, path='/ws'):
    host = platform.endpoint.host
    host = '[' + host + ']' if ':' in host else host
    return f'http://{host}:{platform.listen_port}{path}'


@pytest.mark.parametrize(('host', 'token', 'header', 'allowed'), [
    ('127.0.0.1', '', None, True),
    ('127.0.0.1', 'secret', None, False),
    ('127.0.0.1', 'secret', 'Bearer secret', True),
    ('127.0.0.1', 'secret', 'Token secret', True),
    ('0.0.0.0', '', None, False),
    ('0.0.0.0', 'secret', 'Bearer wrong', False),
])
async def test_native_auth_and_endpoint_readiness(tmp_path, host, token, header, allowed):
    async with platform_at(tmp_path, host=host, token=token) as (platform, events, endpoints):
        assert endpoints[0][0] == 'register'
        assert endpoints[0][1].auth_required == (bool(token) or host == '0.0.0.0')
        assert endpoints[0][1].readiness == ('degraded' if host == '0.0.0.0' and not token else 'ready')
        async with aiohttp.ClientSession() as client:
            url = f'http://127.0.0.1:{platform.listen_port}/ws/'
            headers = {'Authorization': header} if header else {}
            if not allowed:
                with pytest.raises(aiohttp.WSServerHandshakeError) as rejected:
                    await client.ws_connect(url, headers=headers)
                assert rejected.value.status == 401
            else:
                async with client.ws_connect(url, headers=headers) as ws:
                    await ws.send_json(message(1))
                    await until(lambda: len(events) == 1)
                    assert events[0]['message_id'] == 1


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '::1'])
async def test_dynamic_loopback_one_socket_and_port_release(tmp_path, host):
    async with platform_at(tmp_path, host=host) as (platform, _, _):
        server = platform._site._server
        assert len(server.sockets) == 1
        assert {s.getsockname()[1] for s in server.sockets} == {platform.listen_port}
        port = platform.listen_port
        endpoint_host = platform.endpoint.host
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(platform)):
                pass
    assert platform.listen_port is None
    assert platform._inbound_media._session is None or platform._inbound_media._session.closed
    family = socket.AF_INET6 if ':' in endpoint_host else socket.AF_INET
    with socket.socket(family) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((endpoint_host, port))


async def test_echo_reader_continues_while_session_handler_waits(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(_):
        entered.set()
        await release.wait()
    async with platform_at(tmp_path, handler=handler) as (platform, _, _):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(platform)) as ws:
                await ws.send_json(message(1))
                await asyncio.wait_for(entered.wait(), 1)
                call = asyncio.create_task(platform.call_api('get_msg', {'message_id': 42}))
                try:
                    frame = await asyncio.wait_for(ws.receive_json(), 1)
                    assert frame['action'] == 'get_msg'
                    assert frame['params'] == {'message_id': 42}
                    await ws.send_json({'retcode': 0, 'data': {'message': 'quoted'}, 'echo': frame['echo']})
                    result = await asyncio.wait_for(call, 1)
                    assert result['data']['message'] == 'quoted'
                    assert not release.is_set()
                finally:
                    release.set()
                    if not call.done():
                        call.cancel()
                    await asyncio.gather(call, return_exceptions=True)


async def test_session_queue_exact_50_preserves_order_other_session_progresses(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []
    async def handler(value):
        if value['user_id'] == 1:
            entered.set()
            await release.wait()
        delivered.append(value['message_id'])
    async with platform_at(tmp_path, handler=handler) as (platform, _, _):
        try:
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(ws_url(platform)) as ws:
                    await ws.send_json(message(0, user=1))
                    await asyncio.wait_for(entered.wait(), 1)
                    for index in range(1, 52):
                        await ws.send_json(message(index, user=1))
                    await ws.send_json(message(999, user=2))
                    await until(lambda: 999 in delivered)
                    assert platform.health_snapshot()['runner_event_dropped_total'] == 1
                    assert platform.health_snapshot()['session_queued_count'] == 50
                    release.set()
                    await until(lambda: len(delivered) == 52)
                    assert [x for x in delivered if x != 999] == list(range(51))
                    await until(lambda: platform.health_snapshot()['session_queue_count'] == 0)
        finally:
            release.set()


async def test_exact_500_session_workers_bounded_and_stop_awaits(tmp_path):
    entered = set()
    release = asyncio.Event()
    exited = set()
    async def handler(value):
        entered.add(value['user_id'])
        try:
            await release.wait()
        finally:
            exited.add(value['user_id'])
    async with platform_at(tmp_path, handler=handler) as (platform, _, _):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(platform)) as ws:
                for index in range(501):
                    await ws.send_json(message(index, user=index + 1))
                await until(lambda: platform.health_snapshot()['runner_event_dropped_total'] == 1)
                assert len(entered) == 500
                assert platform.health_snapshot()['session_queue_count'] == 500
                tasks = list(platform._session_workers.values())
                await platform.close()
                assert all(task.done() for task in tasks)
                assert exited == entered
                assert not platform._session_workers
                assert not platform._session_queues
                assert not platform._pending_calls
                assert not platform._reader_tasks


@pytest.mark.parametrize(('body', 'mime', 'limit', 'wanted'), [
    (b'\x89PNG\r\n\x1a\nimage', 'image/jpeg', 100, '.png'),
    (b'<html>not image</html>', 'text/html', 100, None),
    (b'123456', 'application/octet-stream', 5, None),
])
async def test_real_http_media_atomic_sniff_and_stream_limit(tmp_path, body, mime, limit, wanted):
    async def serve(request):
        response = web.StreamResponse(headers={'Content-Type': mime})
        await response.prepare(request)
        await response.write(body[:3])
        await response.write(body[3:])
        await response.write_eof()
        return response
    app = web.Application()
    app.router.add_get('/media', serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    async def api(*_):
        raise AssertionError('direct media URL must not call API')
    media = OneBotInboundMedia(media_dir=tmp_path, max_download_bytes=limit, call_api=api)
    try:
        await media.start()
        result = await media.download(f'http://127.0.0.1:{port}/media', 'image' if mime != 'application/octet-stream' else 'file', 0, r'C:\bad:name.jpg')
        if wanted:
            path = Path(result)
            assert path.parent == tmp_path.resolve()
            assert path.suffix == wanted
            assert path.read_bytes() == body
            assert not list(tmp_path.glob('*.part'))
        else:
            assert result is None
            assert not list(tmp_path.iterdir())
    finally:
        await media.close()
        await runner.cleanup()


class HostBoundary(Peer):
    """Only the not-yet-frozen host RPC endpoint, not a Core/Agent replacement."""
    def __init__(self):
        super().__init__()
        self.methods, self.state = {}, {}
        self.batches, self.notifications, self.endpoints = [], [], []
        self.invalid_unregister = False
    def register_method(self, name, handler):
        self.methods[name] = handler
    async def notify(self, method, params):
        self.notifications.append((method, params))
    async def call(self, method, params):
        if method.startswith('host.receipt.'):
            return await super().call(method, params)
        if method == 'host.state.get':
            return {'value': self.state.get(params['key'])}
        if method == 'host.state.put':
            self.state[params['key']] = json.loads(json.dumps(params['value']))
            return {}
        if method.startswith('ingress.endpoint.'):
            self.endpoints.append((method, params))
            operation = method.rsplit('.', 1)[1]
            status = {'register': 'registered', 'update': 'updated', 'unregister': 'unregistered'}[operation]
            if self.invalid_unregister and operation == 'unregister':
                status = 'accepted'
            result = {'status': status, 'generation': params['generation']}
            if operation != 'unregister':
                result['readiness'] = params['readiness']
            return result
        assert method == 'event.batch', method
        self.batches.append(params)
        return {'batch_id': params['batch_id'], 'accepted_event_ids': [e['event_id'] for e in params['events']]}


@asynccontextmanager
async def driver_at(tmp_path, **config):
    driver, peer = OneBotDriver(), HostBoundary()
    identity = IdentityParams('onebot', 'onebot-private-A', 1)
    driver.bind(DriverContext(peer, identity))
    try:
        await driver.start({'enabled': True, 'ws_host': '127.0.0.1', 'ws_port': 0, 'workspace_dir': str(tmp_path), **config})
        yield driver, peer, identity.to_mapping()
    finally:
        peer.invalid_unregister = False
        await driver.stop()


@pytest.mark.parametrize(('group', 'share', 'session'), [(None, False, 'onebot:12345'), (67890, False, 'onebot:67890:12345'), (67890, True, 'onebot:g:67890')])
async def test_real_driver_acl_session_stable_event_and_route(tmp_path, group, share, session):
    async with driver_at(tmp_path, share_session_in_group=share) as (driver, peer, identity):
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(driver._platform)) as ws:
                event = message(101, group=group)
                await ws.send_json(event)
                await until(lambda: len(peer.batches) == 1)
                inbound = peer.batches[0]['events'][0]
                assert inbound['event_id'] == 'onebot:message:101'
                assert inbound['sender_id'] == inbound['acl_sender_id'] == '12345'
                assert inbound['metadata']['session_id'] == session
                assert inbound['metadata']['debounce_key'] == session
                assert inbound['content_parts'] == [{'type': 'text', 'text': 'hello'}]
                await ws.send_json(event)
                await ws.send_json(message(102, group=group))
                await until(lambda: len(peer.batches) == 2)
                assert [row['events'][0]['event_id'] for row in peer.batches] == ['onebot:message:101', 'onebot:message:102']
                assert driver._route_attrs(inbound['response_handle']) == {'to_handle': 'group:67890' if group else '12345'}


async def test_real_driver_unknown_receipt_not_replayed_and_stop_fences_owner(tmp_path):
    async with driver_at(tmp_path) as (driver, peer, identity):
        platform = driver._platform
        platform._api_timeout = .05
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(platform)) as ws:
                route = await peer.methods['channel.response.open']({**identity, 'to_handle': '12345', 'meta': {}}, None)
                params = SendParams.from_mapping({**identity, 'to_handle': route['response_handle'], 'delivery_id': 'unknown-1', 'operation': 'message.create', 'content_parts': [{'type': 'text', 'text': 'hello'}]})
                sending = asyncio.create_task(peer.methods['channel.send'](params, None))
                frame = await asyncio.wait_for(ws.receive_json(), 1)
                assert frame['action'] == 'send_private_msg'
                result = await asyncio.wait_for(sending, 1)
                assert result['state'] == 'unknown'
                assert result['reason_code'] == 'PLATFORM_RESULT_UNKNOWN'
                repeated = await peer.methods['channel.send'](params, None)
                assert repeated['state'] == 'unknown'
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.receive_json(), .05)
                assert not platform._pending_calls
        peer.invalid_unregister = True
        with pytest.raises(RuntimeError, match='ONEBOT_STOP_INCOMPLETE'):
            await driver.stop()
        assert driver._platform is platform
        assert driver._endpoint_maybe_registered
        peer.invalid_unregister = False
        await driver.stop()
        assert driver._platform is None
        assert not driver._endpoint_maybe_registered
        assert peer.endpoints[-1][0] == 'ingress.endpoint.unregister'
        assert peer.endpoints[-1][1] == identity
