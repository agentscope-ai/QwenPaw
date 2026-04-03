# PR: feat(qq): Add rich media support for QQ channel

## Summary

This PR adds comprehensive **rich media support** for the CoPaw QQ channel, enabling the bot to send and receive multimedia files (images, videos, voice messages, and documents).

**This implementation is based on the [openclaw-qqbot](https://github.com/tencent-connect/openclaw-qqbot) plugin**, which provides the reference implementation for QQ official rich media API.

---

## Technical Background

### Reference Implementation

The QQ rich media API requires a complex multi-step upload flow that is documented in the [openclaw-qqbot](https://github.com/tencent-connect/openclaw-qqbot) plugin:

1. **Upload Prepare** - Apply for upload permission, get presigned URLs
2. **Upload to COS** - Direct upload to Tencent Cloud Object Storage
3. **Part Finish** - Notify server each part is complete (for large files)
4. **Complete Upload** - Finalize upload, get `file_info` (encrypted media ID)
5. **Send Message** - Send rich media message with `file_info`

### Why This Was Needed

The original `channel.py` only supported:
- Text messages
- URL-based image sending via `[Image: https://...]` tags

Missing functionality:
- ❌ Local file uploads
- ❌ Audio/video file sending
- ❌ Document (PDF, DOCX) sending
- ❌ Proper chunked upload for large files
- ❌ Audio format conversion (to QQ's SILK format)

---

## Changes

### New Modules Added (8 files, ~50KB total)

| Module | Lines | Description |
|--------|-------|-------------|
| `media_tags.py` | 250 | Parse `<qqimg>`, `<qqvoice>`, `<qqvideo>`, `<qqfile>` XML tags |
| `media_send.py` | 350 | Core upload/send functions: `upload_file_url()`, `upload_local_file()`, `send_media_message()` |
| `file_utils.py` | 180 | File hash (MD5/SHA1), type detection, size limits |
| `chunked_upload.py` | 220 | Multi-part upload with retry logic and progress tracking |
| `audio_convert.py` | 200 | FFmpeg-based audio → SILK conversion for QQ voice messages |
| `image_server.py` | 130 | Local HTTP server for hosting images without public URLs |
| `inbound_attachments.py` | 140 | Process incoming QQ attachments (download & parse) |
| `ssrf_guard.py` | 30 | URL security: blocks localhost, 169.254.*, 127.0.0.1 |

### Integration Changes

**`channel.py`** (modified):
```python
# New imports
from .file_utils import is_local_path
from .media_send import send_media_message, upload_file_url, upload_local_file

# Enhanced _upload_media_async() - supports both local files and URLs
async def _upload_media_async(...):
    is_local = is_local_path(url)
    if is_local:
        return await upload_local_file(session, token, target_type, target_id, url, media_type)
    return await upload_file_url(session, token, target_type, target_id, url, media_type)

# Enhanced _send_media_message_async() - delegates to media_send module
async def _send_media_message_async(...):
    await send_media_message(session, token, target_type, target_id, file_info, msg_id)
```

**`__init__.py`** (updated exports):
```python
from .media_tags import parse_media_tags, SendQueueItem, MediaType
from .media_send import MediaSender, send_media_message, MediaPriority
from .file_utils import get_file_hash, format_file_size, is_local_path
from .chunked_upload import chunked_upload_c2c, chunked_upload_group
from .audio_convert import convert_to_silk, is_audio_file
from .image_server import ImageServer
from .ssrf_guard import is_safe_url, validate_remote_url
```

---

## Technical Details

### Complete Upload Flow (per openclaw-qqbot)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    QQ Rich Media Upload Flow                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. POST /v2/users/{openid}/upload_prepare                         │
│     Body: {file_type, file_name, file_size, md5, sha1, md5_10m}    │
│     ↓                                                               │
│     Returns: {upload_id, block_size, parts: [{index, presigned_url}]}│
│                                                                     │
│  2. For each part:                                                 │
│     PUT {presigned_url}  (upload file chunk to COS)                │
│     ↓                                                               │
│     POST /v2/users/{openid}/upload_part_finish                     │
│     Body: {upload_id, part_index, block_size, md5}                  │
│     ↓                                                               │
│                                                                     │
│  3. POST /v2/users/{openid}/files                                  │
│     Body: {upload_id}                                               │
│     ↓                                                               │
│     Returns: {file_info}  (encrypted media ID)                      │
│                                                                     │
│  4. POST /v2/users/{openid}/messages                               │
│     Body: {msg_type: 7, media: {file_info: "..."}, msg_seq}        │
│     ↓                                                               │
│     Message sent to user!                                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Hash Requirements (Critical for QQ API)

QQ API requires specific hashes for verification:
- `md5`: Full file MD5 (hex)
- `sha1`: Full file SHA1 (hex)  
- `md5_10m`: MD5 of first 10MB (or full file if < 10MB)

```python
def compute_file_hashes(file_content: bytes):
    md5 = hashlib.md5(file_content).hexdigest()
    sha1 = hashlib.sha1(file_content).hexdigest()
    ten_mb = 10 * 1024 * 1024
    if len(file_content) <= ten_mb:
        md5_10m = md5
    else:
        md5_10m = hashlib.md5(file_content[:ten_mb]).hexdigest()
    return {"md5": md5, "sha1": sha1, "md5_10m": md5_10m}
```

### File Type Mapping

| Type | Extensions | QQ `file_type` |
|------|------------|-----------------|
| Image | PNG, JPG, GIF, BMP, WEBP | 1 |
| Video | MP4, AVI, MOV, MKV | 2 |
| Audio | MP3, WAV, OGG, AAC, M4A, SILK | 3 |
| File | PDF, DOCX, XLSX, ZIP, etc. | 4 |

---

## Security Features

### SSRF Protection
Blocks dangerous URL patterns:
```python
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
ALLOWED_SCHEMES = {"http", "https"}

def is_safe_url(url: str) -> bool:
    # Rejects localhost, AWS metadata, internal networks
```

### File Size Limits
- Default max: 50MB
- Configurable per deployment

---

## Testing

### Unit Tests (40 tests, all passing)
```bash
pytest tests/unit/channels/test_qq_media.py -v
```

### End-to-End Verification
Tested with real QQ bot (app ID: 1903753340):

| Test | Result | Notes |
|------|--------|-------|
| Image (PNG) | ✅ | Sent successfully |
| Image (BMP) | ✅ | Sent successfully |
| Audio (WAV) | ✅ | Sent successfully |
| File (TXT) | ✅ | Sent successfully |
| File (JSON) | ✅ | Sent successfully |
| Local path upload | ✅ | Works with absolute paths |
| URL-based upload | ✅ | Existing functionality preserved |

---

## Backward Compatibility

- ✅ Existing `[Image: https://...]` URL-based sending works
- ✅ Text message handling unchanged
- ✅ Markdown support unchanged
- ✅ WebSocket event handling unchanged
- ✅ No breaking changes to existing APIs

---

## References

- **Reference Implementation**: [openclaw-qqbot](https://github.com/tencent-connect/openclaw-qqbot)
- **QQ Open Platform Docs**: [Rich Media API](https://open.qq.com/)
- **Chunked Upload Pattern**: Based on Tencent COS multi-part upload

---

## Checklist

- [x] All modules have docstrings
- [x] Unit tests for core functions
- [x] E2E testing with real QQ bot
- [x] SSRF protection implemented
- [x] Backward compatibility verified
- [x] No secrets/credentials in code
- [x] Code follows project style
