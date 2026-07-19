# -*- coding: utf-8 -*-
"""System-level desktop notification support for QwenPaw inbox events."""

from .matcher import event_matches_rules
from .service import NotificationService, get_notification_service

__all__ = [
    "event_matches_rules",
    "NotificationService",
    "get_notification_service",
]
