"""Legacy OneBot assertions mechanically retargeted to private dict protocol.
No legacy Channel/BaseChannel is imported or emulated.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/onebot"))
from qwenpaw_channel_onebot.codec import parse_segments, _normalize_segments, session_id, _normalize_media_ref_sync

def test_text_only():
    self_id = None
    share_session = False
    parts, mentioned, media_segments = parse_segments([{'type': 'text', 'data': {'text': 'hello world'}}], self_id)
    assert len(parts) == 1
    assert parts[0]['type'] == 'text'
    assert parts[0]['text'] == 'hello world'
    assert mentioned is False
    assert not media_segments

def test_empty_text_skipped():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'text', 'data': {'text': '  '}}], self_id)
    assert len(parts) == 0

def test_image_segment():
    self_id = None
    share_session = False
    parts, _, media_segments = parse_segments([{'type': 'image', 'data': {'url': 'https://img.example.com/1.jpg'}}], self_id)
    assert len(parts) == 1
    assert parts[0]['type'] == 'image'
    assert parts[0]['image_url'] == 'https://img.example.com/1.jpg'
    assert media_segments[0]['type'] == 'image'

def test_image_file_fallback():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'image', 'data': {'file': 'file:///tmp/1.jpg'}}], self_id)
    assert len(parts) == 1
    assert parts[0]['image_url'] == 'file:///tmp/1.jpg'

def test_record_segment():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'record', 'data': {'url': 'https://audio.example.com/a.mp3'}}], self_id)
    assert len(parts) == 1
    assert parts[0]['type'] == 'audio'

def test_video_segment():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'video', 'data': {'url': 'https://video.example.com/v.mp4'}}], self_id)
    assert len(parts) == 1
    assert parts[0]['type'] == 'video'

def test_file_segment():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'file', 'data': {'url': 'https://files.example.com/doc.pdf', 'name': 'doc.pdf'}}], self_id)
    assert len(parts) == 1
    assert parts[0]['type'] == 'file'

def test_at_bot_detected():
    self_id = None
    share_session = False
    self_id = 99999
    parts, mentioned, _ = parse_segments([{'type': 'at', 'data': {'qq': '99999'}}, {'type': 'text', 'data': {'text': 'hello bot'}}], self_id)
    assert mentioned is True
    assert len(parts) == 1
    assert parts[0]['text'] == 'hello bot'

def test_at_other_user_not_mentioned():
    self_id = None
    share_session = False
    self_id = 99999
    _, mentioned, _ = parse_segments([{'type': 'at', 'data': {'qq': '11111'}}, {'type': 'text', 'data': {'text': 'hello'}}], self_id)
    assert mentioned is False

def test_mixed_segments():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'text', 'data': {'text': 'look at this'}}, {'type': 'image', 'data': {'url': 'https://img.example.com/pic.png'}}, {'type': 'reply', 'data': {'id': '123'}}, {'type': 'face', 'data': {'id': '178'}}], self_id)
    assert len(parts) == 2
    assert parts[0]['type'] == 'text'
    assert parts[1]['type'] == 'image'

def test_unknown_segment_ignored():
    self_id = None
    share_session = False
    parts, _, _ = parse_segments([{'type': 'unknown_type', 'data': {}}], self_id)
    assert len(parts) == 0

def test_media_segments_only_include_created_parts():
    self_id = None
    share_session = False
    valid_file = {'type': 'file', 'data': {'file': 'report.pdf', 'file_id': 'file-id'}}
    parts, _, media_segments = parse_segments([{'type': 'image', 'data': {}}, valid_file], self_id)
    assert len(parts) == 1
    assert parts[0]['type'] == 'file'
    assert media_segments == [valid_file]

def test_normalize_cq_code_message():
    segments = _normalize_segments('hello [CQ:image,file=pic.jpg,url=https://img.example.com/pic.jpg]')
    assert segments == [{'type': 'text', 'data': {'text': 'hello'}}, {'type': 'image', 'data': {'file': 'pic.jpg', 'url': 'https://img.example.com/pic.jpg'}}]

def test_normalize_cq_code_decodes_escaped_parameters():
    segments = _normalize_segments('[CQ:image,file=a&#44;b&#91;c&#93;.jpg,title=&lt;literal&gt;,url=https://cdn.example/a?x=1&#38;y=2]')
    assert segments == [{'type': 'image', 'data': {'file': 'a,b[c].jpg', 'title': '&lt;literal&gt;', 'url': 'https://cdn.example/a?x=1&y=2'}}]

def test_private_session():
    self_id = None
    share_session = False
    sid = session_id('12345', {'is_group': False}, share_session)
    assert sid == 'onebot:12345'

def test_group_per_user():
    self_id = None
    share_session = False
    sid = session_id('12345', {'is_group': True, 'group_id': '67890'}, share_session)
    assert sid == 'onebot:67890:12345'

def test_group_shared():
    self_id = None
    share_session = True
    sid = session_id('12345', {'is_group': True, 'group_id': '67890'}, share_session)
    assert sid == 'onebot:g:67890'

def test_normalize_media_ref_policy(tmp_path):
    image = tmp_path / 'pic.png'
    image.write_bytes(b'fake')
    assert _normalize_media_ref_sync(image.as_uri(), media_base64_max_bytes=10 * 1024 * 1024) == image.as_uri()
    assert _normalize_media_ref_sync(image.as_uri(), media_base64=True, media_base64_max_bytes=10 * 1024 * 1024) == 'base64://ZmFrZQ=='
    assert _normalize_media_ref_sync(image.as_uri(), media_base64=True, media_base64_max_bytes=1) == image.as_uri()
    assert _normalize_media_ref_sync('data:image/png;base64,ZmFrZQ==', media_base64_max_bytes=10 * 1024 * 1024) == 'base64://ZmFrZQ=='
