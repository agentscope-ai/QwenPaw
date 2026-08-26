# -*- coding: utf-8 -*-
"""Shared fixtures and builders for the media_files test suite."""

from __future__ import annotations

import hashlib
import struct
import zlib

import pytest

from services.media_files import motion_engine
from services.media_files.motion_engine import VendorLib
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
)
from services.project_files.review import ReviewDecisionItem


def make_r2v_element(
    element_id: str,
    *,
    label: str = "猫追老鼠",
    description: str = "猫追逐老鼠",
    narrative: str = "猫发现老鼠后追逐",
    storyboard_prompt: str = "动画分镜：猫发现并追逐老鼠",
    video_prompt: str | None = None,
    start_tick: int = 0,
    duration_tick: int = 4_000,
) -> TimelineElement:
    """One timeline element carrying a single-shot R2V creation."""

    shot = Shot(
        shot_id=f"{element_id}-shot",
        description=description,
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=duration_tick / 1_000,
    )
    extra = {} if video_prompt is None else {"video_prompt": video_prompt}
    return TimelineElement(
        element_id=element_id,
        label=label,
        span=TimelineSpan(start_tick=start_tick, duration_tick=duration_tick),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative=narrative,
            storyboard_prompt=storyboard_prompt,
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
            **extra,
        ),
    )


def r2v_project_services(
    tmp_path,
    monkeypatch,
    *,
    project_id: str,
    name: str,
    elements: tuple[TimelineElement, ...] = (),
) -> CreatorFileServices:
    """CreatorFileServices over one project carrying the given elements."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=project_id, name=name)
    for element in elements:
        project.timelines.items["timeline:main"].elements_by_id[
            element.element_id
        ] = element
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    return services


def accept_pending_reviews(services, project_id: str) -> None:
    """ACCEPT every pending review so downstream dispatches are admitted."""

    for review in services.reviews.all_pending(project_id):
        services.reviews.decide(
            project_id=project_id,
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=operation.operation_id,
                    decision="ACCEPT",
                )
                for operation in review.operations
            ],
        )


def _install_vendor_stub(monkeypatch, tmp_path, *, name, filename, content):
    """Register one stub vendored runtime and install its verified file."""

    stub = VendorLib(
        name=name,
        filename=filename,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        source_url=f"https://example.invalid/{filename}",
        license_note="test stub",
    )
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir(exist_ok=True)
    (vendor_dir / stub.filename).write_bytes(content)
    monkeypatch.setattr(motion_engine, "VENDOR_LIBS", {name: stub})
    monkeypatch.setattr(
        motion_engine,
        "_LIBS_BY_FILENAME",
        {stub.filename: stub},
    )
    monkeypatch.setenv("QWENPAW_CREATOR_MOTION_VENDOR_DIR", str(vendor_dir))
    return stub


@pytest.fixture()
def stub_gsap_vendor(monkeypatch, tmp_path):
    """A verified stand-in for the pinned GSAP runtime."""

    return _install_vendor_stub(
        monkeypatch,
        tmp_path,
        name="gsap",
        filename="gsap.min.js",
        content=b"window.gsap={timeline:function(){return{}}};",
    )


@pytest.fixture()
def stub_vendor(monkeypatch, tmp_path):
    """A generic stub vendored runtime (stub.min.js)."""

    return _install_vendor_stub(
        monkeypatch,
        tmp_path,
        name="stub",
        filename="stub.min.js",
        content=b"window.stubLib = { timeline: function () {} };",
    )


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def write_png(path, width, height, pixel, *, alpha=True):
    """Write one uncompressed-filter PNG without an imaging library.

    ``alpha=False`` writes an RGB PNG without an alpha plane, as Chromium
    does for screenshots whose every pixel ended up fully opaque.
    """

    raw = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height)
    )
    color_type = 6 if alpha else 2
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b""),
    )
