"""Private LaunchSpec/Proxy/ChannelRuntime proof; no official Loader/ZIP claim."""
import asyncio
import base64
import importlib.abc
import json
import os
import sys

import psutil
import pytest
import pytest_asyncio

from imessage_native_support import ROOT, SOURCE, native_fixture, insert, commands, eventually


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('qwenpaw_channel_imessage'):
            raise AssertionError('iMessage implementation imported in host: '+fullname)


@pytest_asyncio.fixture
async def private_runtime(tmp_path,monkeypatch):
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.app.channels.process_supervisor import LaunchSpec
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.execution.bootstrap import _hash_code_root
    monkeypatch.setattr('qwenpaw.app.channels.base.load_config',Config)
    guard=ImportGuard(); sys.meta_path.insert(0,guard)
    directory,config=native_fixture(tmp_path/'native',monkeypatch)
    insert(config,'do not replay')
    async def host_process(request):
        raise AssertionError('This private phase captures admission, not actual Agent execution')
        yield
    spec=LaunchSpec(python_executable=sys.executable,support_root=ROOT/'src',code_root=SOURCE,
        descriptor_path=SOURCE/'channel.json',source_revision=_hash_code_root(SOURCE),
        channel_key='imessage',instance_id='private-imessage',generation=1,qwenpaw_version='2.2.2b4',config=config)
    queue=asyncio.Queue()
    async def enqueue(value):
        await queue.put(value)
        return EnqueueResult(True)
    channel=None
    try:
        channel=IsolatedChannelProxy(host_process,launch_spec=spec,workspace_dir=directory)
        channel.set_enqueue_async(enqueue)
        await channel.start()
        yield channel,directory,config,queue
    finally:
        try:
            if channel is not None:
                await channel.stop()
        finally:
            sys.meta_path.remove(guard)


@pytest.mark.asyncio
async def test_private_child_inbound_exact_session_metadata_and_normal_stop(private_runtime):
    channel,directory,config,queue=private_runtime
    row=insert(config,'private native input')
    async with asyncio.timeout(5):
        payload=await queue.get()
    request=channel.build_agent_request_from_native(payload)
    assert request.channel=='imessage' and request.user_id=='+15550001111'
    assert request.session_id=='imessage:+15550001111'
    assert [part.text for message in request.input for part in message.content]==['private native input']
    assert payload['acl_sender_id']=='+15550001111'
    assert payload['meta']['rowid']==row and payload['meta']['chat_rowid']=='1'
    await channel.send('+15550002222',' raw direct ',{'bot_prefix':'IGNORE'})
    await channel.send_content_parts('+15550002222',[{'type':'text','text':'Hello '},{'type':'refusal','refusal':'World'}],{'bot_prefix':'[META]'})
    records=commands(directory)
    assert [record['argv'] for record in records]==[
        ['send','--to','+15550002222','--text',' raw direct '],
        ['send','--to','+15550002222','--text','[META]Hello \nWorld'],
    ]
    pid=channel.channel_process.health_snapshot()['pid']
    assert all(record['ppid']==pid and record['pgid']==pid and record['sid']==pid for record in records)
    assert pid!=os.getpid()
    receipt=await channel.stop()
    assert receipt.exited and not receipt.residual and not psutil.pid_exists(pid)
    assert not any(name.startswith('qwenpaw_channel_imessage') for name in sys.modules)
    print(json.dumps({'worker_pid':pid,'host_pid':os.getpid(),'records':records,'stopped':True}))


@pytest.mark.asyncio
async def test_private_child_failed_command_is_unknown_and_not_replayed(private_runtime):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    channel,directory,config,queue=private_runtime
    (directory/'control.json').write_text(json.dumps({'mode':'fail'}))
    meta={}
    for _ in range(2):
        with pytest.raises(ChannelDeliveryError) as caught:
            await channel.send('+15550002222','possibly executed',meta)
        assert caught.value.state=='unknown' and caught.value.reason_code=='IMESSAGE_COMMAND_FAILED'
    assert len(commands(directory))==1
    journal=list((directory/'channel_state').glob('*.json'))
    assert len(journal)==1
    assert 'IMESSAGE_COMMAND_FAILED' in journal[0].read_text()


@pytest.mark.asyncio
async def test_private_child_same_group_descendant_reaped_after_success(private_runtime):
    channel,directory,config,queue=private_runtime
    (directory/'control.json').write_text(json.dumps({'mode':'descendant'}))
    await channel.send('+15550002222','successful leader')
    record=commands(directory)[0]
    child=record['descendant_pid']
    assert psutil.pid_exists(child)
    assert os.getpgid(child)==record['pgid']
    receipt=await channel.stop()
    assert receipt.exited and not receipt.residual
    await eventually(lambda:not psutil.pid_exists(child))
    print(json.dumps({'descendant_pid':child,'worker_pgid':record['pgid'],'exited':receipt.exited,'forced':receipt.forced}))


@pytest.mark.asyncio
async def test_private_child_data_url_below_and_above_frame_preserves_configured_limit(private_runtime):
    channel,directory,config,queue=private_runtime
    for size in (3,800000):
        data=b'x'*size
        value='data:image/png;base64,'+base64.b64encode(data).decode()
        await channel.send_media('+15550002222',{'type':'image','image_url':value})
        assert base64.b64decode(commands(directory)[-1]['file_bytes'])==data
    assert config['max_decoded_size']==10485760
