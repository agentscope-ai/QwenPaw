# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.media import extract_media_descriptor


def test_extract_image_descriptor() -> None:
    payload = {
        "msgtype": "image",
        "image": {"md5": "x", "aeskey": "k", "sdkfileid": "f"},
    }

    desc = extract_media_descriptor(payload)

    assert desc is not None
    assert desc.media_type == "image"
    assert desc.sdk_file_id == "f"


def test_extract_file_descriptor() -> None:
    payload = {
        "msgtype": "file",
        "file": {"filename": "note.txt", "aeskey": "k", "sdkfileid": "f2"},
    }

    desc = extract_media_descriptor(payload)

    assert desc is not None
    assert desc.media_type == "file"
    assert desc.file_name == "note.txt"

