"""Only previously unobserved original utility/configuration/lifecycle branches."""
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import json

import pytest

from imessage_native_support import ROOT, import_native, native_fixture, commands
from imessage_closeout_suite import formal_imessage_source,channel_settings

pytest_plugins=['extension_process_suite']


def test_original_image_video_and_extension_oracles():
    import_native()
    from qwenpaw_channel_imessage.media import extract_url_and_filename,file_extension
    assert extract_url_and_filename({'type':'image','image_url':'https://example.com/image.jpg'})==('https://example.com/image.jpg','image','image')
    assert extract_url_and_filename({'type':'video','video_url':'https://example.com/video.mp4'})==('https://example.com/video.mp4','video','video')
    assert file_extension('image','photo.png')=='.png'
    assert [file_extension(kind,name) for kind,name in [('image','photo'),('audio','sound'),('video','movie'),('file','doc')]]==['.jpg','.mp3','.mp4','.bin']


def test_original_config_display_defaults_and_idle_owned_resources(tmp_path):
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.official_channels import bundled_channel_source
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.__version__ import __version__
    from qwenpaw.config.config import IMessageChannelConfig
    with bundled_channel_source('imessage') as source:
        desc=describe_channel(source,PluginManifest.from_dict(json.loads((source/'plugin.json').read_text())))
        display=ChannelDisplayConfig(show_tool_details=False,show_thinking=False,show_tool_calls=False,show_tool_results=False)
        proxy=desc.create_proxy(Runtime.run,IMessageChannelConfig(enabled=True,db_path='~/test/chat.db',poll_sec=2.5,bot_prefix='@test ',max_decoded_size=5*1024*1024,media_dir=str(tmp_path/'media')),python_executable=sys.executable,support_root=ROOT/'src',instance_id='config-original',generation=1,qwenpaw_version=__version__,workspace_dir=tmp_path/'workspace',display_config=display)
        values=proxy._launch_spec.config
        assert proxy.enabled is True
        assert values['db_path']==os.path.expanduser('~/test/chat.db')
        assert values['poll_sec']==2.5 and values['bot_prefix']=='@test ' and values['max_decoded_size']==5*1024*1024
        assert proxy._display_config.show_tool_details is False and proxy._display_config.show_tool_calls is False and proxy._display_config.show_tool_results is False and not proxy._display_config.show_thinking
        assert proxy.channel_process.health_snapshot()['pid'] is None
        assert not (tmp_path/'media').exists()
        default=desc.create_proxy(Runtime.run,IMessageChannelConfig(enabled=False),python_executable=sys.executable,support_root=ROOT/'src',instance_id='default-original',generation=1,qwenpaw_version=__version__,workspace_dir=tmp_path/'workspace')
        assert default._launch_spec.config['db_path']==os.path.expanduser('~/Library/Messages/chat.db')


@pytest.mark.asyncio
async def test_formal_empty_parts_error_reply_and_strict_disabled_zero_effect(runtime,tmp_path,monkeypatch):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.channel_protocol.models import ProtocolValidationError
    directory,config=native_fixture(tmp_path/'native',monkeypatch)
    rt=await runtime('imessage',source_factory=formal_imessage_source,**channel_settings(config))
    assert Path(config['media_dir']).is_dir()
    await rt.channel.send_content_parts('+1234567890',[])
    assert commands(directory)==[]
    with pytest.raises(ProtocolValidationError):
        await rt.channel.send_media('+1234567890',{'type':'image'})
    assert commands(directory)==[]
    await rt.channel._on_consume_error(SimpleNamespace(channel_meta={}),'+1234567890','Error occurred')
    assert [r['argv'] for r in commands(directory)]==[['send','--to','+1234567890','--text','Error occurred']]
    await rt.manager.stop_all()
    with pytest.raises(RuntimeError,match='CHANNEL_NOT_CONNECTED'):
        await rt.channel.send('+1234567890','not initialized after stop')
    assert len(commands(directory))==1
    rt.channel.enabled=False
    await rt.channel.start()
    await rt.channel.stop()
    before=commands(directory)
    for call in (lambda:rt.channel.send('+1234567890','Hello'),lambda:rt.channel.send_media('+1234567890',{'type':'image','image_url':'https://example.com/image.jpg'})):
        with pytest.raises(ChannelDeliveryError) as caught:
            await call()
        assert caught.value.reason_code=='CHANNEL_DISABLED'
    assert commands(directory)==before
    assert rt.process.health_snapshot()['pid'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,expected',[
    ('unsupported','IMESSAGE_MACOS_REQUIRED'),
    ('executable','IMESSAGE_EXECUTABLE_NOT_FOUND'),
    ('database','IMESSAGE_DATABASE_UNREADABLE'),
])
async def test_start_diagnostics_leave_no_watcher_or_command(tmp_path,monkeypatch,failure,expected):
    directory,config=native_fixture(tmp_path/'native',monkeypatch)
    Platform,_,_=import_native()
    async def no_event(value):
        raise AssertionError('Failed startup cannot admit an event')
    states=[]
    async def state(value): states.append(value)
    if failure=='unsupported':
        monkeypatch.setattr('qwenpaw_channel_imessage.platform.sys.platform','linux')
    elif failure=='executable':
        monkeypatch.setenv('PATH',str(tmp_path/'no-executables'))
    else:
        config['db_path']=str(directory/'missing.sqlite')
    platform=Platform(config,no_event,state)
    with pytest.raises(RuntimeError,match=expected):
        await platform.start()
    await platform.stop()
    assert platform._watcher is platform._conn is platform._http is None
    assert not platform._commands and not platform._senders and not platform._spawns and not platform._operations
    assert commands(directory)==[] and 'connected' not in states
