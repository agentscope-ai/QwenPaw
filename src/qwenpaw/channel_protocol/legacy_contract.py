# -*- coding: utf-8 -*-
"""Closed compatibility window for previously released official Drivers."""


def accepts_legacy_contract(channel_key: str) -> bool:
    return channel_key in {"feishu", "dingtalk"}
