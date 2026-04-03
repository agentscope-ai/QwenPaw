# -*- coding: utf-8 -*-
"""QQ channel package."""
from .channel import QQChannel
from .media_tags import SendQueueItem, parse_media_tags, fix_path_encoding
from .media_send import (
    MediaTargetContext,
    MediaSendResult,
    send_photo,
    send_video_msg,
    send_voice,
    send_document,
    execute_send_queue,
)
from .file_utils import (
    is_local_path,
    get_file_hash,
    get_file_size,
    file_exists,
    format_file_size,
    get_max_upload_size,
)
from .audio_convert import is_audio_file, should_transcode_voice, audio_to_silk
from .chunked_upload import (
    chunked_upload_c2c,
    chunked_upload_group,
    get_media_file_type,
)
from .inbound_attachments import (
    process_attachments,
    ProcessedAttachments,
    RawAttachment,
)
from .image_server import save_image, get_image_url, start_server
from .ssrf_guard import is_safe_url, validate_remote_url

__all__ = [
    "QQChannel",
    "SendQueueItem",
    "parse_media_tags",
    "fix_path_encoding",
    "MediaTargetContext",
    "MediaSendResult",
    "send_photo",
    "send_video_msg",
    "send_voice",
    "send_document",
    "execute_send_queue",
    "is_local_path",
    "get_file_hash",
    "get_file_size",
    "file_exists",
    "format_file_size",
    "get_max_upload_size",
    "is_audio_file",
    "should_transcode_voice",
    "audio_to_silk",
    "chunked_upload_c2c",
    "chunked_upload_group",
    "get_media_file_type",
    "process_attachments",
    "ProcessedAttachments",
    "RawAttachment",
    "save_image",
    "get_image_url",
    "start_server",
    "is_safe_url",
    "validate_remote_url",
]
