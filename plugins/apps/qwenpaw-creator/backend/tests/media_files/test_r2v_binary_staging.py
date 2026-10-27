# -*- coding: utf-8 -*-
"""Video staging must not apply Windows text-mode byte translations."""

import hashlib

import pytest

from domain.errors import StorageIntegrityError
from services.media_files.r2v_execution import _stage_materialized_video
from services.media_files.secure_video_stream import MaterializedVideo
from services.project_files.assets import AssetFileStore


@pytest.mark.parametrize("changed", [False, True])
def test_video_staging_preserves_binary_bytes(tmp_path, changed):
    content = b"\x00\x00\x00\x18ftypisom\r\n\x1a" + bytes(range(256)) * 8
    source = tmp_path / "generated.mp4"
    source.write_bytes(content + (b"changed" if changed else b""))
    video = MaterializedVideo(
        path=source,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        media_type="video/mp4",
        container="mp4",
        source_kind="local",
    )
    store = AssetFileStore(tmp_path)
    if changed:
        with pytest.raises(StorageIntegrityError, match="scratch changed"):
            _stage_materialized_video(store, video, staging_id="binary-test")
    else:
        staged = _stage_materialized_video(
            store,
            video,
            staging_id="binary-test",
        )
        assert staged.sha256 == video.sha256
        assert staged.size_bytes == len(content)
