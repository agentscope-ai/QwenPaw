# -*- coding: utf-8 -*-
"""Nextcloud Talk channel constants."""

# HTTP header names for incoming webhook requests
HEADER_SIGNATURE = "X-Nextcloud-Talk-Signature"
HEADER_RANDOM = "X-Nextcloud-Talk-Random"
HEADER_BACKEND = "X-Nextcloud-Talk-Backend"

# Signature length (SHA256 hex digest)
SIGNATURE_LENGTH = 64

# Random string length
RANDOM_LENGTH = 64

# Time debounce (300ms)
NEXTCLOUD_TALK_DEBOUNCE_SECONDS = 0.3

# Session ID suffix length (for cron compatibility)
SESSION_ID_SUFFIX_LEN = 8

# Activity Streams types
ACTIVITY_TYPE_CREATE = "Create"
ACTIVITY_TYPE_JOIN = "Join"
ACTIVITY_TYPE_LEAVE = "Leave"
ACTIVITY_TYPE_LIKE = "Like"
ACTIVITY_TYPE_UNDO = "Undo"
ACTIVITY_TYPE_SYSTEM = "system"
ACTIVITY_TYPE_ACTIVITY = "Activity"

# Actor types
ACTOR_TYPE_PERSON = "Person"
ACTOR_TYPE_APPLICATION = "Application"
ACTOR_TYPE_BOT = "Application"  # Bots actor type in Nextcloud Talk

# Message object types
OBJECT_TYPE_NOTE = "Note"
OBJECT_TYPE_COLLECTION = "Collection"

# Message name for regular messages
MESSAGE_NAME_NORMAL = "message"

# Media types
MEDIA_TYPE_MARKDOWN = "text/markdown"
MEDIA_TYPE_PLAIN = "text/plain"

# Bot signature headers for outgoing requests
BOT_HEADER_RANDOM = "X-Nextcloud-Talk-Bot-Random"
BOT_HEADER_SIGNATURE = "X-Nextcloud-Talk-Bot-Signature"
OCS_API_REQUEST_HEADER = "OCS-APIRequest"

# Message length limits
MAX_MESSAGE_LENGTH = 4000  # Maximum characters for chat messages
