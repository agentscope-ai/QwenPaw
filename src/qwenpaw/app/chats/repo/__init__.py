# -*- coding: utf-8 -*-
"""Chat repository implementations."""
from .base import BaseChatRepository
from .json_repo import JsonChatRepository

__all__ = ["BaseChatRepository", "JsonChatRepository"]
