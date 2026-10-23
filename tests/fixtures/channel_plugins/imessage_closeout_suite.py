"""Formal iMessage owner through actual Core/Agent; temporary SQLite/imsg only."""
import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from imessage_native_support import ROOT, native_fixture, insert, commands
from real_host_runtime import bind_real_runtime

pytest_plugins = ['extension_process_suite']


def formal_imessage_source(directory, key, **_):
    from qwenpaw.plugins.official_channels import bundled_channel_source
    assert key == 'imessage'
    with bundled_channel_source(key) as source:
        target = directory / key
        shutil.copytree(source, target)
        assert {str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()} == {str(p.relative_to(target)):p.read_bytes() for p in target.rglob('*') if p.is_file()}
    return target


def channel_settings(config):
    return {key:value for key,value in config.items() if key not in {'enabled','workspace_dir'}}


async def eventually(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_formal_zip_sqlite_acl_actual_agent_safe_session_and_native_reply(runtime, tmp_path, monkeypatch):
    import psutil
    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith('qwenpaw_channel_imessage'):
                raise AssertionError('Private iMessage imported in host: '+fullname)
    guard = Guard()
    assert not any(n.startswith('qwenpaw_channel_imessage') for n in sys.modules)
    sys.meta_path.insert(0,guard)
    started = time.monotonic()
    directory, config = native_fixture(tmp_path/'native', monkeypatch)
    insert(config, 'history must not replay')
    config['bot_prefix'] = '[BOT]'
    try:
        rt = await runtime('imessage', source_factory=formal_imessage_source, access_control_dm=True, **channel_settings(config))
        host = await bind_real_runtime(rt, monkeypatch, reply='formal iMessage answer')
        store = rt.channel._get_acl_store()
        store.add_to_whitelist('imessage','+15550001111')
        assert rt.channel.access_control_dm is True
        assert rt.ws.requests == [] and commands(directory) == []
        insert(config, 'denied question', sender='+15550009999')
        await eventually(lambda:any(row['user_id']=='+15550009999' for row in store.get_all_pending()))
        assert rt.ws.requests == [] and host.calls == []
        rowid = insert(config, 'new formal question')
        await eventually(lambda:any(row.get('object')=='response' and row.get('status')=='completed' for row in host.events))
        await eventually(lambda:any(record['argv'][2]=='+15550001111' for record in commands(directory)))
        assert len(rt.ws.requests) == 1
        request = rt.ws.requests[0]
        assert request.channel == 'imessage' and request.user_id == '+15550001111'
        assert request.session_id == 'imessage:+15550001111'
        assert request.channel_meta['rowid'] == rowid and request.channel_meta['chat_rowid'] == '1'
        assert [part.text for message in request.input for part in message.content] == ['new formal question']
        actual = [record for record in commands(directory) if record['argv'][2]=='+15550001111']
        assert len(actual) == 1
        assert actual[0]['argv'] == ['send','--to','+15550001111','--text','[BOT]formal iMessage answer']
        pid = rt.process.health_snapshot()['pid']
        assert actual[0]['ppid'] == actual[0]['pgid'] == actual[0]['sid'] == pid != os.getpid()
        assert host.builds and all(row['agent']=='QwenPawAgent' for row in host.builds)
        session_files = list((rt.ws.workspace_dir/'sessions').rglob('*.json'))
        assert session_files and any('new formal question' in path.read_text() and 'formal iMessage answer' in path.read_text() for path in session_files)
        assert not any(n.startswith('qwenpaw_channel_imessage') for n in sys.modules)
        current = {'host_pid':os.getpid(),'worker_pid':pid,'elapsed_seconds':time.monotonic()-started,'host_rss':psutil.Process().memory_info().rss,'worker_rss':psutil.Process(pid).memory_info().rss,'host_threads':psutil.Process().num_threads(),'worker_threads':psutil.Process(pid).num_threads(),'observation_only':True}
        print('IMESSAGE_CURRENT '+json.dumps(current),flush=True)
        await rt.manager.stop_all()
        await eventually(lambda:not psutil.pid_exists(pid))
    finally:
        sys.meta_path.remove(guard)


def test_legacy_environment_and_official_unstarted_configuration(tmp_path):
    from qwenpaw.config.channel_env import read_channel_env
    from qwenpaw.config.config import IMessageChannelConfig
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.official_channels import bundled_channel_source
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.__version__ import __version__
    env = read_channel_env('imessage',{'IMESSAGE_CHANNEL_ENABLED':'0','IMESSAGE_DB_PATH':'/custom/path/chat.db','IMESSAGE_POLL_SEC':'2.0','IMESSAGE_BOT_PREFIX':'@assistant '})
    assert env['enabled'] is False and env['db_path']=='/custom/path/chat.db'
    assert env['poll_sec']==2.0 and env['bot_prefix']=='@assistant '
    defaults=read_channel_env('imessage',{})
    assert defaults['enabled'] is True and defaults['db_path']=='~/Library/Messages/chat.db'
    assert defaults['poll_sec']==1.0 and defaults['bot_prefix']==''
    config=IMessageChannelConfig(enabled=False,db_path='/tmp/test/db.sqlite',poll_sec=3.0,bot_prefix='@ai ',media_dir=str(tmp_path/'media'),max_decoded_size=20*1024*1024)
    with bundled_channel_source('imessage') as source:
        desc=describe_channel(source,PluginManifest.from_dict(json.loads((source/'plugin.json').read_bytes())))
        proxy=desc.create_proxy(Runtime.run,config,python_executable=sys.executable,support_root=ROOT/'src',instance_id='imessage-passive',generation=1,qwenpaw_version=__version__,workspace_dir=tmp_path/'workspace')
        values=proxy._launch_spec.config
        assert proxy.channel=='imessage' and proxy.enabled is False
        assert values['db_path']=='/tmp/test/db.sqlite' and values['poll_sec']==3.0
        assert values['bot_prefix']=='@ai ' and values['max_decoded_size']==20*1024*1024
        assert values['media_dir']==str(tmp_path/'media') and not (tmp_path/'media').exists()
        empty=proxy.build_agent_request_from_native({})
        assert empty.channel=='imessage' and empty.user_id==''
        assert proxy.channel_process.health_snapshot()['pid'] is None
