"""Exact remaining legacy branches at actual private owners; no fake IPC/Agent."""
import json
import pytest
from xiaoyi_native_support import gateway, modules, native_driver, HostBoundary

pytestmark = pytest.mark.asyncio


async def test_primary_failure_backup_success_actual_websockets(gateway, modules, monkeypatch, tmp_path):
    monkeypatch.setattr(modules['platform'], 'DEFAULT_WS_URL', gateway.base + '/missing-ws')
    monkeypatch.setattr(modules['platform'], 'DEFAULT_WS_URL_BACKUP', gateway.backup)
    states = []
    async def state(value):
        states.append(value)
    platform = modules['platform'].XiaoYiPlatform(dict(ak='local-ak', sk='local-sk', agent_id='local-agent', workspace_dir=str(tmp_path)), None, state)
    try:
        await platform.start()
        assert platform._conn_primary is not None and not platform._conn_primary.connected
        assert platform._conn_backup is not None and platform._conn_backup.connected
        assert platform.connected is True
        assert set(gateway.connections) == {'backup'}
        assert states == ['connecting', 'connected']
    finally:
        await platform.stop()
    assert platform._conn_primary is None and platform._conn_backup is None


async def test_empty_backup_constant_starts_only_real_primary(gateway, modules, monkeypatch, tmp_path):
    monkeypatch.setattr(modules['platform'], 'DEFAULT_WS_URL', gateway.primary)
    monkeypatch.setattr(modules['platform'], 'DEFAULT_WS_URL_BACKUP', '')
    async def state(_):
        pass
    platform = modules['platform'].XiaoYiPlatform(dict(ak='local-ak', sk='local-sk', agent_id='local-agent', workspace_dir=str(tmp_path)), None, state)
    try:
        await platform.start()
        assert platform._conn_primary.connected
        assert platform._conn_backup is None
        assert platform.connected is True
        assert set(gateway.connections) == {'primary'}
    finally:
        await platform.stop()


async def test_disabled_driver_empty_credentials_never_constructs_platform_or_network(modules, tmp_path):
    from qwenpaw.channel_protocol.models import IdentityParams
    from qwenpaw.channel_protocol.shared_worker import DriverContext
    from xiaoyi_native_support import SOURCE
    driver, peer = modules['driver'].XiaoYiDriver(), HostBoundary()
    descriptor = json.loads((SOURCE / 'channel.json').read_text())
    driver.bind(DriverContext(peer, IdentityParams('xiaoyi', 'disabled', 1), descriptor['capabilities']))
    media = tmp_path / 'must-not-be-created'
    try:
        await driver.start(dict(enabled=False, ak='', sk='', agent_id='', media_dir=str(media)))
        assert driver._platform is None and driver._connected is False
        assert not media.exists()
        assert peer.batches == []
    finally:
        await driver.stop()


@pytest.mark.parametrize('meta,session,expected', [
    ({'session_id': 'xiaoyi:meta_session', 'task_id': 'meta_task'}, 'sender_123', ('meta_session', 'meta_task')),
    ({'task_id': 'task'}, 'xiaoyi:sender_123', ('sender_123', 'task')),
    ({'session_id': 'xiaoyi:session_123'}, 'ignored', ('session_123', 'task_123')),
])
async def test_native_target_meta_precedence_prefix_and_stored_task(modules, meta, session, expected):
    platform = modules['platform'].XiaoYiPlatform({}, None, None)
    platform._session_task_map['session_123'] = 'task_123'
    route = platform.resolve_target(session, meta)
    assert (route['session_id'], route['task_id']) == expected


async def test_missing_native_task_is_explicit_failure(modules):
    platform = modules['platform'].XiaoYiPlatform({}, None, None)
    with pytest.raises(modules['errors'].XiaoYiDeliveryError, match='XIAOYI_TASK_UNKNOWN'):
        platform.resolve_target('session_123', {})


@pytest.mark.parametrize('source,parts', [('direct', [{'type': 'text', 'text': ''}]), ('media', [{'type': 'unknown', 'url': 'https://unused.invalid/file'}])])
async def test_empty_text_and_unknown_media_have_zero_native_writes(native_driver, monkeypatch, source, parts):
    driver, _, _, _ = native_driver
    platform = driver._platform
    calls = []
    for connection in (platform._conn_primary, platform._conn_backup):
        async def unexpected(frame):
            calls.append(frame)
            raise AssertionError('No external send is allowed for empty/unknown content')
        monkeypatch.setattr(connection, 'send_json', unexpected)
    receipt = await platform.send_parts({'session_id':'session_123','task_id':'task_123','message_id':'message'}, parts, source)
    assert receipt == {'transport_written':'false','frame_count':'0'}
    assert calls == []


async def test_both_real_connection_send_boundaries_reject_in_order(native_driver, monkeypatch):
    driver, _, _, _ = native_driver
    platform = driver._platform
    calls = []
    async def primary(frame):
        calls.append(('primary', frame))
        return False
    async def backup(frame):
        calls.append(('backup', frame))
        return False
    monkeypatch.setattr(platform._conn_primary, 'send_json', primary)
    monkeypatch.setattr(platform._conn_backup, 'send_json', backup)
    from qwenpaw_channel_xiaoyi.errors import XiaoYiDeliveryError
    with pytest.raises(XiaoYiDeliveryError, match='NOT_CONNECTED') as caught:
        await platform.send_parts({'session_id':'session_123','task_id':'task_123','message_id':'message'}, [{'type':'text','text':'Hello'}], 'direct')
    assert [name for name, _ in calls] == ['primary', 'backup']
    assert calls[0][1] == calls[1][1]
    assert caught.value.side_effect_possible is False


async def test_disconnected_driver_refuses_open_before_creating_route(modules):
    driver = modules['driver'].XiaoYiDriver()
    with pytest.raises(ValueError, match='NOT_CONNECTED'):
        driver._require_connected()
    assert driver._platform is None
