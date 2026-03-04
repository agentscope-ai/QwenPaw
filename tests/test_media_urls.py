# -*- coding: utf-8 -*-
from agentscope.message import Msg

from copaw.app import media as media_module
from copaw.app.media import resolve_public_media_path, to_public_media_url
from copaw.app.runner.utils import agentscope_msg_to_message
from copaw.constant import WORKING_DIR


def test_to_public_media_url_maps_local_media_path() -> None:
    image_path = str((WORKING_DIR / "media" / "feishu" / "img.jpg").resolve())

    assert (
        to_public_media_url(image_path)
        == "/api/media/workspace/feishu/img.jpg"
    )


def test_to_public_media_url_maps_home_media_path_when_enabled(
    monkeypatch,
    tmp_path,
) -> None:
    workspace_root = (tmp_path / "workspace").resolve()
    home_root = (tmp_path / "home").resolve()
    image_path = home_root / "legacy" / "img.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"img")

    monkeypatch.setattr(
        media_module,
        "MEDIA_ROOTS",
        (("workspace", workspace_root), ("home", home_root)),
    )

    assert (
        to_public_media_url(str(image_path))
        == "/api/media/home/legacy/img.jpg"
    )


def test_resolve_public_media_path_supports_alias_and_legacy_paths(
    monkeypatch,
    tmp_path,
) -> None:
    workspace_root = (tmp_path / "workspace").resolve()
    home_root = (tmp_path / "home").resolve()
    image_path = home_root / "legacy" / "img.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"img")

    monkeypatch.setattr(
        media_module,
        "MEDIA_ROOTS",
        (("workspace", workspace_root), ("home", home_root)),
    )

    assert resolve_public_media_path("home/legacy/img.jpg") == image_path
    assert resolve_public_media_path("legacy/img.jpg") == image_path


def test_agentscope_msg_to_message_keeps_image_as_image_content() -> None:
    image_path = str((WORKING_DIR / "media" / "feishu" / "img.jpg").resolve())
    msg = Msg(
        name="user",
        role="user",
        content=[{"type": "image", "image_url": image_path}],
    )

    messages = agentscope_msg_to_message(msg)

    assert len(messages) == 1
    assert len(messages[0].content) == 1
    assert messages[0].content[0].type == "image"
    assert (
        messages[0].content[0].image_url
        == "/api/media/workspace/feishu/img.jpg"
    )


def test_agentscope_msg_to_message_maps_file_urls_for_console() -> None:
    file_path = str(
        (WORKING_DIR / "media" / "feishu" / "report.pdf").resolve(),
    )
    msg = Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "file",
                "file_url": file_path,
                "filename": "report.pdf",
            },
        ],
    )

    messages = agentscope_msg_to_message(msg)

    assert len(messages) == 1
    assert len(messages[0].content) == 1
    assert messages[0].content[0].type == "file"
    assert (
        messages[0].content[0].file_url
        == "/api/media/workspace/feishu/report.pdf"
    )
    assert messages[0].content[0].filename == "report.pdf"
