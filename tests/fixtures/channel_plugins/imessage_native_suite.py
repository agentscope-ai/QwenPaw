"""Real SQLite/executable platform observations; callbacks here are unit boundaries."""
import asyncio
import base64
from pathlib import Path
import sqlite3

import pytest

from imessage_native_support import native_fixture, insert, commands, eventually, import_native


@pytest.mark.parametrize('name,want',[
    ('../../../etc/passwd','passwd'),('test_file-name.123.jpg','test_file-name.123.jpg'),
    ('','media_file'),('!@#$%','media_file'),('test.jpg','test.jpg'),('test.png','test.png'),
    ('/path/to/file.txt','file.txt'),('../secret.txt','secret.txt'),('file with spaces.pdf','file_with_spaces.pdf'),
])
def test_literal_filename_oracles(name,want):
    import_native()
    from qwenpaw_channel_imessage.media import sanitize_filename
    assert sanitize_filename(name)==want


def test_media_bytes_strict_limit_and_authorized_paths(tmp_path,monkeypatch):
    directory,config=native_fixture(tmp_path/'native',monkeypatch)
    _,error,Media=import_native()
    media=Media({**config,'max_decoded_size':3},error)
    media.start()
    value=media.data_url('data:image/png;base64,YWJj','image','../photo')
    assert Path(value).read_bytes()==b'abc'
    assert Path(value).name=='photo_f4c0128178a6a21b.png'
    assert media.data_url('data:image/png;base64,YWJjZA==','image','photo') is None
    assert media.data_url('data:image/png;base64,YW Jj','image','photo') is None
    assert media.data_url('data:image/png;base64,!!!invalid!!!','image','photo') is None
    assert media.data_url('data:text/plain,hello','image','photo') is None
    assert Path(media.data_url('data:image/png;base64,','image','photo')).read_bytes()==b''
    local=directory/'document.txt'; local.write_bytes(b'authorized bytes')
    for locator in (str(local),local.as_uri()):
        assert Path(media.local_file(locator)).read_bytes()==b'authorized bytes'
    assert media.local_file(str(directory/'missing')) is None
    outside=tmp_path/'outside'; outside.write_bytes(b'never sent')
    link=directory/'escape'; link.symlink_to(outside)
    with pytest.raises(error,match='MEDIA_PATH_UNAUTHORIZED'):
        media.local_file(str(link))
    assert outside.read_bytes()==b'never sent'


@pytest.mark.asyncio
async def test_real_sqlite_no_replay_filters_retry_and_closed_connection(tmp_path,monkeypatch):
    directory,config=native_fixture(tmp_path/'native',monkeypatch)
    Platform,_,_=import_native()
    insert(config,'historical row')
    seen=[]; states=[]; accepted=asyncio.Event()
    async def state(value): states.append(value)
    async def event(value):
        seen.append(dict(value))
        if len(seen)==1:
            raise RuntimeError('controlled unit admission rejection')
        accepted.set()
    platform=Platform(config,event,state)
    await platform.start()
    connection=platform._conn
    try:
        insert(config,'self',own=1); insert(config,''); insert(config,'missing',sender=' ')
        row=insert(config,'ordinary text with empty configured prefix')
        await eventually(accepted.is_set)
        assert seen==[{'sender':'+15550001111','text':'ordinary text with empty configured prefix','rowid':row,'chat_rowid':'1','event_id':f'imessage:row:{row}:1'}]*2
        assert platform._last_rowid==row and platform._pending is None
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            connection.execute("INSERT INTO chat VALUES ('forbidden')")
        assert states[0]=='connected' and commands(directory)==[]
    finally:
        await platform.stop()
    assert platform._watcher is platform._conn is platform._http is None
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        connection.execute('SELECT 1')


@pytest.mark.asyncio
async def test_nonempty_prefix_filter_and_exact_command_formats(tmp_path,monkeypatch):
    directory,config=native_fixture(tmp_path/'native',monkeypatch)
    Platform,_,_=import_native()
    seen=[]
    async def event(value): seen.append(value)
    async def state(value): pass
    platform=Platform({**config,'bot_prefix':'[BOT]'},event,state)
    await platform.start()
    try:
        insert(config,'[BOT] echoed'); row=insert(config,'receive this')
        await eventually(lambda:len(seen)==1)
        assert seen[0]['rowid']==row and seen[0]['text']=='receive this'
        await platform.send_parts('+15550002222',[{'type':'text','text':'  raw\n text  '}],'direct','IGNORED')
        await platform.send_parts('+15550002222',[{'type':'text','text':'Hello '},{'type':'text','text':'World'}],'parts','[META]')
        assert [record['argv'] for record in commands(directory)]==[
            ['send','--to','+15550002222','--text','  raw\n text  '],
            ['send','--to','+15550002222','--text','[META]Hello \nWorld'],
        ]
    finally:
        await platform.stop()
    assert platform._commands=={} and not platform._senders and not platform._spawns and not platform._operations
