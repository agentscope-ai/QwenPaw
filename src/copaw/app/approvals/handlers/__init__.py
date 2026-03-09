# -*- coding: utf-8 -*-
"""Channel-specific approval handlers."""

from .console import ConsoleApprovalHandler
from .dingtalk import DingTalkApprovalHandler

__all__ = [
    "ConsoleApprovalHandler",
    "DingTalkApprovalHandler",
]
