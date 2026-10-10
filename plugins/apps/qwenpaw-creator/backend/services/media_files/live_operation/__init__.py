# -*- coding: utf-8 -*-
"""Live operation of real websites, recorded as ordinary Project footage."""

from __future__ import annotations

from .bridge import (
    LiveOperationError,
    LiveOperationRun,
    run_browser_code,
)
from .desktop import (
    computer_use_status,
    run_computer_use_code,
)
from .screen_recorder import (
    ScreenRecorder,
    ffmpeg_available,
    screen_capture_supported,
)
from .ingest import (
    MANIFEST_SCHEMA_NAME,
    PublishedImage,
    PublishedTake,
    build_image_records,
    build_take_records,
    read_take_manifest,
    stable_id,
    stage_and_publish_file,
)
from .manifest import (
    ActionFact,
    BoundingBox,
    TakeManifest,
    Viewport,
    facts_within,
    normalized_location,
    project_location_to_canvas,
)
from .recorder import RecordedTake, RecorderError, TakeRecorder
from .session import LiveBrowserSession, LiveSessionError

__all__ = [
    "ActionFact",
    "BoundingBox",
    "LiveBrowserSession",
    "LiveOperationError",
    "LiveOperationRun",
    "LiveSessionError",
    "MANIFEST_SCHEMA_NAME",
    "PublishedImage",
    "PublishedTake",
    "RecordedTake",
    "RecorderError",
    "ScreenRecorder",
    "TakeManifest",
    "TakeRecorder",
    "Viewport",
    "build_image_records",
    "build_take_records",
    "computer_use_status",
    "facts_within",
    "ffmpeg_available",
    "normalized_location",
    "project_location_to_canvas",
    "read_take_manifest",
    "run_browser_code",
    "run_computer_use_code",
    "screen_capture_supported",
    "stable_id",
    "stage_and_publish_file",
]
