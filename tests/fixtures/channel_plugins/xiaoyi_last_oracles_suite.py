"""Last legacy behaviors at actual replacement owners; lifecycle ruling explicit."""
import asyncio
import json
import os

from aiohttp import web
import pytest
import pytest_asyncio

from xiaoyi_closeout_suite import formal_source, settings, wait_for
from xiaoyi_native_support import Gateway, gateway, inbound, native_driver, modules, open_route, send
from real_host_runtime import bind_real_runtime

pytest_plugins = ['extension_process_suite']


@pytest.mark.asyncio
async def test_unique_backup_inbound_retains_backup_response_route(native_driver):
    driver, peer, identity, external = native_driver
    await external.push(inbound(request='backup-request', message='backup-message', task='backup-task', session='backup-session'), 'backup')
    await wait_for(lambda: len(peer.batches) == 1)
    event = peer.batches[0]['events'][0]
    assert driver._platform._session_server_map['backup-session'] == 'backup'
    assert event['metadata']['session_id'] == 'xiaoyi:backup-session'
    route = driver._route_attrs(event['response_handle'])
    assert route['server_name'] == 'backup'
    assert route['session_id'] == 'backup-session' and route['task_id'] == 'backup-task'
    result = await send(peer, identity, event['response_handle'], text='backup answer')
    assert result['state'] == 'acknowledged'
    await wait_for(lambda: len(external.results()) == 1)
    assert external.results()[0][0] == 'backup'
    assert external.results()[0][1]['artifact']['parts'] == [{'kind':'text','text':'backup answer'}]
    assert not any(server == 'primary' and frame.get('msgType') == 'agent_response' for server, frame in external.frames)


@pytest.mark.asyncio
async def test_formal_native_session_metadata_prefix_sender_fallback_and_enabled_get(runtime, gateway, monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.routers import config as routes
    from qwenpaw.config.config import load_agent_config, save_agent_config
    rt = await runtime('xiaoyi', source_factory=formal_source, **settings(gateway))
    host = await bind_real_runtime(rt, monkeypatch, reply='last session oracle')
    profile = load_agent_config(rt.ws.agent_id)
    profile.channels = rt.ws._config.channels
    save_agent_config(rt.ws.agent_id, profile)
    async def selected_workspace(_):
        return rt.ws
    monkeypatch.setattr('qwenpaw.app.agent_context.get_agent_for_request', selected_workspace)
    app = FastAPI()
    app.state.plugin_loader = rt.loader
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/config/channels/xiaoyi')
    assert response.status_code == 200
    assert response.json()['enabled'] is True
    assert response.json()['ws_url'] == gateway.primary
    assert rt.channel.resolve_session_id('sender_123') == 'xiaoyi:sender_123'
    await wait_for(lambda: 'primary' in gateway.connections and not gateway.connections['primary'].closed)
    await gateway.push(inbound(request='meta-request', message='meta-message', session='meta_session', task='meta-task'))
    await wait_for(lambda: any(row.get('final') is True for _, row in gateway.results()))
    assert len(rt.ws.requests) == 1
    request = rt.ws.requests[0]
    assert request.session_id == 'xiaoyi:meta_session'
    assert request.channel_meta['session_id'] == 'xiaoyi:meta_session'
    assert rt.channel.resolve_session_id('different_sender', request.channel_meta) == 'xiaoyi:meta_session'
    assert host.builds and host.calls
    assert rt.process.health_snapshot()['pid'] != os.getpid()


@pytest_asyncio.fixture
async def gated_gateway():
    class GatedGateway(Gateway):
        accepting = True
        async def gateway(self, request):
            if not self.accepting:
                return web.Response(status=503)
            return await super().gateway(request)
    external = GatedGateway()
    app = web.Application()
    app.router.add_get('/ws/{server}', external.gateway)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    external.primary = f'ws://127.0.0.1:{port}/ws/primary'
    try:
        yield external
    finally:
        for ws in external.connections.values():
            await ws.close()
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['disabled', 'disconnected'])
async def test_lifecycle_fences_api_media_and_ordinary_with_zero_native_effects(runtime, gated_gateway, mode):
    import psutil
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import Message, TextContent
    rt = await runtime('xiaoyi', source_factory=formal_source, **settings(gated_gateway))
    await wait_for(lambda: 'primary' in gated_gateway.connections)
    old_pid = rt.process.health_snapshot()['pid']
    if mode == 'disabled':
        result = await rt.loader.lifecycle.set_enabled(rt.key, False)
        assert result.clean and result.quiescent and not result.leftovers
        assert not psutil.pid_exists(old_pid)
        assert rt.loader.get_loaded_plugin(rt.key) is None
    else:
        gated_gateway.accepting = False
        await gated_gateway.connections['primary'].close()
        await wait_for(lambda: rt.process.health_snapshot()['platform_state'] != 'connected')
        assert rt.process.health_snapshot()['state'] == 'ready'
        assert psutil.pid_exists(old_pid)
    request = rt.channel.build_agent_request_from_native({'sender_id':'session','content_parts':[{'type':'text','text':'question'}],'meta':{'task_id':'task'}})
    event = Message(object='message', type='message', role='assistant', status='completed', content=[TextContent(text='answer')])
    meta = {'task_id':'task'}
    calls = [rt.channel.send('session','answer',{'_api_send':True,'task_id':'task'}), rt.channel.send_media('session',{'type':'image','image_url':'https://unused.invalid/image.png'},{'task_id':'task'}), rt.channel.on_event_message_completed(request,rt.channel.get_to_handle_from_request(request),event,meta)]
    results = await asyncio.gather(*calls, return_exceptions=True)
    if mode == 'disabled':
        assert all(isinstance(result, RuntimeError) and str(result) == 'CHANNEL_NOT_CONNECTED' for result in results), results
    else:
        assert all(isinstance(result, TimeoutError) or isinstance(result, RuntimeError) and str(result) == 'CHANNEL_NOT_CONNECTED' for result in results), results
    assert not meta.get('_reply_failed') and '_continued_event_delivery_error' not in meta
    assert gated_gateway.results() == []
    assert rt.ws.requests == []
    await rt.manager.stop_all()
    await wait_for(lambda: not psutil.pid_exists(old_pid))


def false_socket_source(directory, key, **kwargs):
    source = formal_source(directory, key, **kwargs)
    # Test artifact changes only external socket-write boundary, after real connect.
    path = source / 'qwenpaw_channel_xiaoyi/driver.py'
    with path.open('a') as stream:
        stream.write('''
_ActualDriver = XiaoYiDriver
class XiaoYiDriver(_ActualDriver):
    def __init__(self):
        super().__init__()
        self.socket_attempts = []
    def bind(self, context):
        super().bind(context)
        context.peer.register_method('fixture.false_sockets', self.false_sockets)
        context.peer.register_method('fixture.socket_attempts', self.inspect_socket_attempts)
    async def false_sockets(self, params, request):
        import os
        for name, conn in (('primary',self._platform._conn_primary),('backup',self._platform._conn_backup)):
            if conn is None:
                raise AssertionError('Both real connections required')
            async def refuse(frame, server=name):
                self.socket_attempts.append({'server':server,'pid':os.getpid(),'frame':frame})
                return False
            conn.send_json = refuse
        return {}
    async def inspect_socket_attempts(self, params, request):
        return {'attempts':self.socket_attempts}
''')
    return source


@pytest.mark.asyncio
@pytest.mark.parametrize('ordinary', [False, True])
async def test_actual_host_dual_socket_refusal_strict_api_tolerant_ordinary(runtime, gateway, ordinary):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import Message, TextContent
    def source_factory(directory, key, **kwargs):
        source = false_socket_source(directory, key, **kwargs)
        constants = source / 'qwenpaw_channel_xiaoyi/constants.py'
        with constants.open('a') as stream:
            stream.write(f'\nDEFAULT_WS_URL = {gateway.primary!r}\nDEFAULT_WS_URL_BACKUP = {gateway.backup!r}\n')
        return source
    cfg = settings(gateway)
    cfg['ws_url'] = ''
    rt = await runtime('xiaoyi', source_factory=source_factory, **cfg)
    await wait_for(lambda: set(gateway.connections) == {'primary','backup'})
    await rt.process.call('fixture.false_sockets', {})
    meta = {'task_id':'task_123','message_id':'message_123','server_name':'primary'}
    if ordinary:
        request = rt.channel.build_agent_request_from_native({'sender_id':'session_123','content_parts':[{'type':'text','text':'question'}],'meta':dict(meta)})
        event = Message(object='message', type='message', role='assistant', status='completed', content=[TextContent(text='Hello')])
        await rt.channel.on_event_message_completed(request,rt.channel.get_to_handle_from_request(request),event,meta)
        assert meta['_reply_failed'] is True
        assert meta['_continued_event_delivery_error'] == {'state':'failed','reason_code':'NOT_CONNECTED'}
    else:
        with pytest.raises(ChannelDeliveryError) as refused:
            await rt.channel.send('session_123','Hello',meta)
        assert refused.value.state == 'failed' and refused.value.reason_code == 'NOT_CONNECTED'
        assert refused.value.side_effect_possible is False
    rows = (await rt.process.call('fixture.socket_attempts', {}))['attempts']
    expected_servers = ['primary','backup'] if ordinary else ['primary','backup','primary','backup']
    assert [row['server'] for row in rows] == expected_servers
    assert all(row['pid'] == rt.process.health_snapshot()['pid'] != os.getpid() for row in rows)
    assert rows[0]['frame'] == rows[1]['frame']
    assert rows[0]['frame']['sessionId'] == 'session_123'
    results = [json.loads(row['frame']['msgDetail'])['result'] for row in rows]
    assert results[0]['kind'] == results[1]['kind'] == 'artifact-update'
    expected_text = '\n\nHello' if ordinary else 'Hello'
    assert results[0]['artifact']['parts'] == [{'kind':'text','text':expected_text}]
    if not ordinary:
        assert rows[2]['frame'] == rows[3]['frame']
        assert all(row['kind'] == 'status-update' and row['status']['state'] == 'completed' and row['final'] is False for row in results[2:])
    assert gateway.results() == []
