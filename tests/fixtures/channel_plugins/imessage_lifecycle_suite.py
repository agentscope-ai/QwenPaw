"""Real formal plugin lifecycle; only copied candidate code induces failure."""
import json
import os
import shutil

import pytest

from imessage_closeout_suite import formal_imessage_source, channel_settings, eventually
from imessage_native_support import native_fixture, insert, commands
from real_host_runtime import bind_real_runtime

pytest_plugins = ['extension_process_suite']


@pytest.mark.asyncio
async def test_formal_two_workspaces_isolate_same_sender_and_stale_generation(runtime, tmp_path, monkeypatch):
    import psutil
    from qwenpaw.channel_protocol.errors import RpcError
    from extension_process_suite import identity

    directory, config = native_fixture(tmp_path/'native', monkeypatch)
    second_db = tmp_path/'second.sqlite'
    shutil.copyfile(config['db_path'], second_db)
    second_config = {**config, 'db_path':str(second_db), 'media_dir':str(tmp_path/'second-media')}
    first = await runtime('imessage',source_factory=formal_imessage_source,workspace_name='first',**channel_settings(config))
    host_first = await bind_real_runtime(first,monkeypatch,reply='workspace isolated answer')
    second = await runtime('imessage',existing_loader=first.loader,workspace_name='second',**channel_settings(second_config))
    old = identity(second)
    host_second = await bind_real_runtime(second,monkeypatch,reply='workspace isolated answer')
    first.channel = await first.manager.get_channel('imessage')
    first.process = first.channel.channel_process
    first_pid, second_pid = first.process.health_snapshot()['pid'], second.process.health_snapshot()['pid']
    assert len({first_pid,second_pid,os.getpid()}) == 3
    assert identity(second) != old
    with pytest.raises(RpcError):
        await second.process.call('channel.response.open',{**old,'to_handle':'imessage:+15550001111','meta':{}})
    assert commands(directory) == []
    insert(config,'first workspace question')
    insert(second_config,'second workspace question')
    await eventually(lambda:len(commands(directory)) == 2)
    assert len(first.ws.requests) == len(second.ws.requests) == 1
    assert first.ws.requests[0].session_id == second.ws.requests[0].session_id == 'imessage:+15550001111'
    assert first.ws.requests[0].input[0].content[0].text == 'first workspace question'
    assert second.ws.requests[0].input[0].content[0].text == 'second workspace question'
    assert {r['ppid'] for r in commands(directory)} == {first_pid,second_pid}
    assert host_first.builds and host_second.builds
    for rt, own, foreign in ((first,'first workspace question','second workspace question'),(second,'second workspace question','first workspace question')):
        sessions=list((rt.ws.workspace_dir/'sessions').rglob('*.json'))
        assert sessions and any(own in p.read_text() for p in sessions)
        assert all(foreign not in p.read_text() for p in sessions)
    await first.manager.stop_all()
    await eventually(lambda:not psutil.pid_exists(first_pid))
    assert psutil.pid_exists(second_pid)
    insert(second_config,'second survives other workspace stop')
    await eventually(lambda:len(commands(directory)) == 3)
    assert commands(directory)[-1]['ppid'] == second_pid
    assert len(first.ws.requests) == 1 and len(second.ws.requests) == 2


@pytest.mark.asyncio
async def test_enabled_candidate_failure_restores_original_and_agent_delivery(runtime, tmp_path, monkeypatch):
    directory, config = native_fixture(tmp_path/'native',monkeypatch)
    rt=await runtime('imessage',source_factory=formal_imessage_source,**channel_settings(config))
    host=await bind_real_runtime(rt,monkeypatch,reply='after rollback answer')
    installed=rt.source/'qwenpaw_channel_imessage/driver.py'
    original=installed.read_bytes()
    db_before=open(config['db_path'],'rb').read()
    candidate=formal_imessage_source(tmp_path/'update','imessage')
    manifest_path=candidate/'plugin.json'
    manifest=json.loads(manifest_path.read_text());manifest['version']='2.0.0';manifest_path.write_text(json.dumps(manifest))
    with (candidate/'qwenpaw_channel_imessage/driver.py').open('a') as stream:
        stream.write('\n_OriginalDriver = IMessageDriver\nclass IMessageDriver(_OriginalDriver):\n    async def start(self, config):\n        if config.get("enabled"):\n            raise RuntimeError("CONTROLLED_ENABLED_CANDIDATE_FAILURE")\n        return await super().start(config)\n')
    report=await rt.loader.lifecycle.reload('imessage',new_source=candidate)
    assert not report.ok and report.errors
    assert installed.read_bytes()==original
    assert open(config['db_path'],'rb').read()==db_before
    current=await rt.manager.get_channel('imessage')
    assert current is not None and current.enabled
    assert current._launch_spec.config['db_path']==config['db_path']
    insert(config,'question after rollback')
    await eventually(lambda:len(commands(directory))==1)
    assert commands(directory)[0]['argv']==['send','--to','+15550001111','--text','after rollback answer']
    assert len(rt.ws.requests)==1 and host.builds and host.calls
