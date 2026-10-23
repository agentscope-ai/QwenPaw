"""Temporary Messages schema and real external imsg stand-in; no plugin RPC seam."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'plugins/channel/imessage'


def native_fixture(directory, monkeypatch):
    directory.mkdir(parents=True, exist_ok=True)
    db = directory / 'messages.sqlite'
    connection = sqlite3.connect(db)
    connection.executescript('''
    CREATE TABLE message (text TEXT, is_from_me INTEGER, handle_id INTEGER);
    CREATE TABLE chat (label TEXT);
    CREATE TABLE handle (id TEXT);
    CREATE TABLE chat_message_join (message_id INTEGER, chat_id INTEGER);
    INSERT INTO chat VALUES ('fixture chat');
    INSERT INTO handle VALUES ('+15550001111');
    ''')
    connection.commit()
    connection.close()
    executable = directory / 'imsg'
    executable.write_text('#!' + sys.executable + '\n' + '''
import base64, json, os, pathlib, subprocess, sys, time
root = pathlib.Path(__file__).resolve().parent
control = json.loads((root / 'control.json').read_text())
record = {'argv':sys.argv[1:], 'pid':os.getpid(), 'ppid':os.getppid(), 'pgid':os.getpgrp(), 'sid':os.getsid(0)}
if '--file' in sys.argv:
    record['file_bytes'] = base64.b64encode(pathlib.Path(sys.argv[sys.argv.index('--file')+1]).read_bytes()).decode()
if control['mode'] == 'descendant':
    child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(120)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record['descendant_pid'] = child.pid
fd = os.open(root / 'commands.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (json.dumps(record)+'\\n').encode()); os.close(fd)
if control['mode'] == 'block':
    time.sleep(120)
if control['mode'] == 'fail':
    sys.stderr.write('controlled platform failure')
    sys.exit(7)
print('controlled sent')
''')
    executable.chmod(0o700)
    (directory / 'control.json').write_text(json.dumps({'mode':'ok'}))
    monkeypatch.setenv('PATH', str(directory) + os.pathsep + os.environ.get('PATH',''))
    return directory, {'enabled':True, 'db_path':str(db), 'poll_sec':0.01,
                       'workspace_dir':str(directory), 'media_dir':str(directory/'media'),
                       'max_decoded_size':10485760, 'bot_prefix':''}


def insert(config, text, *, own=0, sender='+15550001111'):
    with sqlite3.connect(config['db_path']) as connection:
        handle = connection.execute('INSERT INTO handle VALUES (?)',(sender,)).lastrowid
        rowid = connection.execute('INSERT INTO message VALUES (?,?,?)',(text,own,handle)).lastrowid
        connection.execute('INSERT INTO chat_message_join VALUES (?,1)',(rowid,))
    return rowid


def commands(directory):
    path=directory/'commands.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


def import_native():
    sys.path.insert(0,str(SOURCE))
    from qwenpaw_channel_imessage.platform import IMessagePlatform, IMessageDeliveryError
    from qwenpaw_channel_imessage.media import IMessageMedia
    return IMessagePlatform, IMessageDeliveryError, IMessageMedia
