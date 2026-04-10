# -*- coding: utf-8 -*-
"""XiaoYi channel module.

XiaoYi (小艺) is Huawei's voice assistant platform.
This module implements A2A (Agent-to-Agent) protocol support.
"""

from .channel import XiaoYiChannel
from .auth import generate_auth_headers
from .constants import DEFAULT_WS_URL

__all__ = [
    "XiaoYiChannel",
    "generate_auth_headers",
    "DEFAULT_WS_URL",
]
