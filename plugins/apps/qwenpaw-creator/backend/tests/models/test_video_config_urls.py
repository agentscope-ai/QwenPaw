# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from models import config


def test_wan_video_urls_accept_api_root(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "get_video_base_url",
        lambda: "https://workspace.example/api/v1",
    )
    monkeypatch.setattr(config, "get_video_backend", lambda: "wan")
    assert config.get_video_submit_url() == (
        "https://workspace.example/api/v1/services/aigc/video-generation/video-synthesis"
    )
    assert config.get_video_task_url("task-1") == (
        "https://workspace.example/api/v1/tasks/task-1"
    )


def test_wan_video_urls_accept_full_submit_endpoint_without_duplication(
    monkeypatch,
) -> None:
    endpoint = (
        "https://workspace.example/api/v1/services/aigc/"
        "video-generation/video-synthesis"
    )
    monkeypatch.setattr(config, "get_video_base_url", lambda: endpoint)
    monkeypatch.setattr(config, "get_video_backend", lambda: "wan")
    assert config.get_video_submit_url() == endpoint
    assert config.get_video_task_url("task-2") == (
        "https://workspace.example/api/v1/tasks/task-2"
    )


def test_video_provider_poll_interval_is_request_configurable() -> None:
    token = config.set_request_tool_configs(
        {
            config.CREATOR_VIDEO_CONFIG_TOOL: {
                "poll_interval_seconds": 2.5,
            },
        },
    )
    try:
        assert config.get_video_poll_interval_seconds() == 2.5
    finally:
        config.reset_request_tool_configs(token)
