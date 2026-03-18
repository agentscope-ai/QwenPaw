# -*- coding: utf-8 -*-
"""Content parsing utilities for Nextcloud Talk channel."""


import json
import logging
import os
import base64
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote

from .constants import (
    ACTIVITY_TYPE_CREATE,
    ACTIVITY_TYPE_JOIN,
    ACTIVITY_TYPE_LEAVE,
    ACTIVITY_TYPE_LIKE,
    ACTIVITY_TYPE_UNDO,
    ACTIVITY_TYPE_SYSTEM,
    ACTIVITY_TYPE_ACTIVITY,
    ACTOR_TYPE_PERSON,
    ACTOR_TYPE_APPLICATION,
    MESSAGE_NAME_NORMAL,
    SESSION_ID_SUFFIX_LEN,
)

logger = logging.getLogger(__name__)


class NextcloudTalkContentParser:
    """Parser for Nextcloud Talk Activity Streams 2.0 messages."""

    @classmethod
    def _find_file_data(
        cls,
        payload: Dict[str, Any],
        obj: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find file data using multiple approaches."""
        object_name = obj.get("name", "")
        file_data = None

        # Approach 1: Direct file_shared event
        if object_name == "file_shared":
            parameters = obj.get("parameters", {})
            file_data = parameters.get("file", {}) or parameters.get(
                "share",
                {},
            )
            cls._log_file_shared_debug(file_data)

        # Approach 2: File in content.parameters (mixed message)
        elif object_name == "message":
            file_data = cls._extract_file_from_message(obj)

        # Approach 3: Embedded file data in object properties
        if not file_data:
            file_data = cls._find_embedded_file(obj)

        # Approach 4: Meta fallback
        if not file_data:
            file_data = cls._find_file_in_meta(payload)

        # Final fallback: actor parameters
        if not file_data:
            file_data = cls._find_file_in_actor(payload)

        return file_data if file_data and isinstance(file_data, dict) else None

    @classmethod
    def _log_file_shared_debug(cls, file_data: Dict[str, Any]) -> None:
        """Log debug information for file_shared events."""
        logger.debug(
            f"Found file_shared event with file data: {bool(file_data)}",
        )
        if file_data:
            logger.debug(
                f"file_shared file_data keys: {list(file_data.keys())}",
            )
            logger.debug(
                "file_shared file_data path: %s, name: %s",
                file_data.get("path"),
                file_data.get("name"),
            )

    @classmethod
    def _extract_file_from_message(
        cls,
        obj: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract file data from message content parameters."""
        content_str = obj.get("content", "")
        if not content_str:
            return None

        try:
            content_json = json.loads(content_str)
            parameters = content_json.get("parameters", {})
            file_data = (
                parameters.get("file", {})
                or parameters.get("attachment", {})
                or parameters.get("upload", {})
            )
            if file_data:
                logger.debug(
                    "Found file in content.parameters: %s",
                    file_data.get("name"),
                )
            return file_data
        except Exception as e:
            logger.debug(f"Failed to parse content JSON: {e}")
            return None

    @classmethod
    def _find_embedded_file(
        cls,
        obj: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Look for embedded file data in object properties."""
        logger.debug("Checking object fields for file data")
        potential_file_fields = ["file", "attachment", "upload", "media"]

        for field in potential_file_fields:
            candidate = obj.get(field, {})
            if isinstance(candidate, dict) and candidate.get("name"):
                logger.debug(
                    f"Found file in object.{field}: {candidate.get('name')}",
                )
                logger.debug(f"object.{field} keys: {list(candidate.keys())}")
                logger.debug(
                    "object.%s path: %s, name: %s",
                    field,
                    candidate.get("path"),
                    candidate.get("name"),
                )
                return candidate
        return None

    @classmethod
    def _find_file_in_meta(
        cls,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find file data in meta section."""
        meta = payload.get("meta", {})
        file_data = meta.get("file", {}) or meta.get("attachment", {})
        if file_data:
            logger.debug(f"Found file in meta: {file_data.get('name')}")
        return file_data

    @classmethod
    def _find_file_in_actor(
        cls,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find file data in actor parameters."""
        actor = payload.get("actor", {})
        actor_params = (
            actor.get("parameters", {}) if isinstance(actor, dict) else {}
        )
        file_data = actor_params.get("file", {})
        if file_data:
            logger.debug(
                f"Found file in actor parameters: {file_data.get('name')}",
            )
        return file_data

    @classmethod
    def _extract_file_metadata(
        cls,
        file_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Extract basic file metadata with fallbacks."""
        file_name = (
            file_data.get("name")
            or file_data.get("filename")
            or file_data.get("displayName")
            or "unknown_file"
        )

        file_path = (
            file_data.get("path")
            or file_data.get("filepath")
            or file_data.get("location")
            or file_name
        )

        # Handle Talk directory assumption
        if file_path and "/" not in file_path:
            logger.debug(
                f"file_path is just filename: {file_path}, "
                "assuming Talk/ directory",
            )
            file_path = f"Talk/{file_path}"

        # Handle size parsing
        file_size = cls._parse_file_size(file_data.get("size"))

        mime_type = (
            file_data.get("mimetype")
            or file_data.get("mime-type")
            or file_data.get("contentType")
            or "application/octet-stream"
        )

        return {
            "name": file_name,
            "path": file_path,
            "size": file_size,
            "mime_type": mime_type,
        }

    @classmethod
    def _parse_file_size(cls, size_value: Any) -> int:
        """Parse file size with error handling."""
        try:
            if isinstance(size_value, str):
                return int(size_value)
            return int(size_value or 0)
        except (ValueError, TypeError):
            return 0

    @classmethod
    def _determine_media_type(
        cls,
        mime_type: str,
        file_name: str,
    ) -> Optional[str]:
        """Determine media type from MIME type or file extension."""
        mime_type_lower = mime_type.lower()
        media_type = None

        # Check MIME type first
        if mime_type_lower.startswith("image/"):
            media_type = "image"
        elif mime_type_lower.startswith("video/"):
            media_type = "video"
        elif mime_type_lower.startswith("audio/"):
            media_type = "audio"
        else:
            # Fallback to file extension
            _, ext = os.path.splitext(file_name.lower())
            if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]:
                media_type = "image"
            elif ext in [".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv"]:
                media_type = "video"
            elif ext in [".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"]:
                media_type = "audio"
            else:
                logger.debug(
                    f"Unknown file mime type and extension: {mime_type}, "
                    f"{ext}",
                )

        return media_type

    @classmethod
    def _check_preview_available(
        cls,
        file_data: Dict[str, Any],
        mime_type: str,
    ) -> bool:
        """Check if preview is available for the file."""
        mime_type_lower = mime_type.lower()
        return bool(
            file_data.get("preview-available")
            or file_data.get("has-preview")
            or file_data.get("preview")
            or mime_type_lower.startswith("image/")
            or file_data.get("thumbnail"),
        )

    @classmethod
    def _extract_additional_metadata(
        cls,
        file_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Extract additional metadata fields."""
        return {
            "id": file_data.get("id", ""),
            "etag": file_data.get("etag", ""),
            "permissions": file_data.get("permissions", ""),
            "width": file_data.get("width", ""),
            "height": file_data.get("height", ""),
            "duration": file_data.get("duration", ""),
            "share-token": (
                file_data.get("share-token")
                or file_data.get("token")
                or file_data.get("link", "")
            ),
            "hide-download": file_data.get("hide-download", "no"),
        }

    @staticmethod
    def parse_actor(actor: Dict[str, Any]) -> Tuple[str, str, str]:
        """
        Parse actor from Activity Streams payload.

        Returns:
            Tuple of (actor_id, actor_name, actor_type)
            - actor_id: "users/username" or "bots/bot-id"
            - actor_name: Display name
            - actor_type: "user", "guest", "bot"
        """
        actor_id = actor.get("id", "")
        actor_name = actor.get("name", "")
        actor_type_raw = actor.get("type", "")

        # Extract agent type from ID
        if actor_type_raw == ACTOR_TYPE_APPLICATION:
            actor_type = "bot"
        elif actor_type_raw == ACTOR_TYPE_PERSON:
            if actor_id.startswith("users/"):
                actor_type = "user"
            elif actor_id.startswith("guests/"):
                actor_type = "guest"
            else:
                actor_type = "unknown"
        else:
            actor_type = "unknown"

        # Extract username from ID (not used but keep logic for reference)
        # if "/" in actor_id:
        #     username = actor_id.split("/", 1)[1]
        # else:
        #     username = actor_id

        logger.debug(
            f"parsed actor: id={actor_id} name={actor_name} type={actor_type}",
        )

        return (actor_id, actor_name, actor_type)

    @staticmethod
    def parse_message_content(
        content_str: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Parse message content string.

        The content is a JSON-encoded string with "message" and "parameters" keys.  # noqa: E501
        Parameters contain rich object data for mentions, calls, files, etc.

        Returns:
            Tuple of (message_text, parameters_dict)
        """
        try:
            content_data = json.loads(content_str)
            message = content_data.get("message", "")
            parameters = content_data.get("parameters", {})

            # Ensure parameters is a dict
            if not isinstance(parameters, dict):
                logger.debug(
                    f"parameters is not dict, converting from {type(parameters)}",  # noqa: E501
                )
                parameters = {}

        except json.JSONDecodeError:
            # If not JSON, use content string directly
            message = content_str
            parameters = {}

        logger.debug(
            "parsed msg content: msg_len=%s params_type=%s keys=%s",
            len(message),
            type(parameters).__name__,
            list(parameters.keys()) if isinstance(parameters, dict) else "N/A",
        )

        return (message, parameters)

    @staticmethod
    def replace_mentions(text: str, parameters: Dict[str, Any]) -> str:
        """
        Replace placeholders in message text with actual mentions.

        Example: "hi {mention-call1}!" -> "hi @world!"
        """
        # Safely handle parameters, ensuring it is a dictionary
        if not isinstance(parameters, dict):
            logger.debug(
                f"replace_mentions: parameters is not dict, type={type(parameters)}",  # noqa: E501
            )
            return text

        for key, value in parameters.items():
            placeholder = "{" + key + "}"
            if placeholder in text:
                if isinstance(value, dict):
                    name = value.get("name", "")
                    mention_type = value.get("type", "")
                    if mention_type == "call":
                        text = text.replace(placeholder, f"@{name}")
                    elif mention_type == "user":
                        text = text.replace(placeholder, f"@{name}")
                    elif mention_type == "guest":
                        text = text.replace(placeholder, f"@{name}")
                    else:
                        # Generic fallback
                        text = text.replace(placeholder, name)
                else:
                    text = text.replace(placeholder, str(value))

        return text

    @staticmethod
    def parse_conversation(target: Dict[str, Any]) -> Tuple[str, str]:
        """
        Parse conversation/target from payload.

        Returns:
            Tuple of (conversation_token, conversation_name)
        """
        conversation_token = target.get("id", "")
        conversation_name = target.get("name", "")

        return (conversation_token, conversation_name)

    @staticmethod
    def is_regular_message(object_data: Dict[str, Any]) -> bool:
        """
        Check if the object represents a regular user message (not system message).  # noqa: E501
        """
        object_name = object_data.get("name", "")

        # Handle bug fix: empty string for attachments before Nextcloud 33
        if object_name == MESSAGE_NAME_NORMAL:
            return True

        # Some system messages have specific names
        system_names = [
            "message_deleted",
            "message_modified",
            "conversation_renamed",
            "conversation_avatar_changed",
            "user_joined",
            "user_left",
            "password_set",
            "call_started",
            "call_ended",
        ]

        # If object_name is empty or matches system name pattern, it's not
        # regular
        if not object_name or object_name in system_names:
            return False

        # If it's not explicitly a system message, assume it's regular
        return True

    @staticmethod
    def extract_message_text(payload: Dict[str, Any]) -> Optional[str]:
        """
        Extract message text from Activity Streams payload.

        Returns None if payload doesn't contain a regular message.
        """
        activity_type = payload.get("type")
        actor = payload.get("actor", {})
        obj = payload.get("object", {})

        # Only handle Create activities from persons (users)
        if activity_type != ACTIVITY_TYPE_CREATE:
            return None

        actor_type_raw = actor.get("type", "")
        if actor_type_raw != ACTOR_TYPE_PERSON:
            return None

        # Check if it's a regular message
        if not NextcloudTalkContentParser.is_regular_message(obj):
            return None

        # Extract content
        content_str = obj.get("content", "")

        message, parameters = NextcloudTalkContentParser.parse_message_content(
            content_str,
        )

        # Replace mentions
        message = NextcloudTalkContentParser.replace_mentions(
            message,
            parameters,
        )

        return message if message else None

    @staticmethod
    def _extract_file_data_direct(
        payload: Dict[str, Any],
        object_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Extract file data from direct file_shared event."""
        if object_name == "file_shared":
            obj = payload.get("object", {})
            parameters = obj.get("parameters", {})
            file_data = parameters.get("file", {}) or parameters.get(
                "share",
                {},
            )
            logger.debug(
                f"Found file_shared event with file data: {bool(file_data)}",
            )
            # Log file_data structure for debugging
            if file_data:
                logger.debug(
                    f"file_shared file_data keys: {list(file_data.keys())}",
                )
                logger.debug(
                    "file_shared file_data path: %s, name: %s",
                    file_data.get("path"),
                    file_data.get("name"),
                )
            return file_data
        return None

    @staticmethod
    def extract_media_file(
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Extract media file information from Activity Streams payload.

        Handles file_shared events for images, videos, and audio files.
        Supports multiple Nextcloud versions and payload formats.

        Returns:
            Dictionary with file information or None
        """
        activity_type = payload.get("type")
        obj = payload.get("object", {})

        # Log activity type for debugging
        logger.debug(
            "extract_media_file: activity_type=%s, object_name=%s",
            activity_type,
            obj.get("name", ""),
        )
        logger.debug(f"extract_media_file: object keys={list(obj.keys())}")

        # Validate activity type
        valid_activity_types = [
            ACTIVITY_TYPE_CREATE,
            ACTIVITY_TYPE_SYSTEM,
            ACTIVITY_TYPE_ACTIVITY,
        ]
        if activity_type not in valid_activity_types:
            logger.debug(
                f"Skipping unsupported activity type: {activity_type}",
            )
            return None

        # Find file data using multiple approaches
        file_data = NextcloudTalkContentParser._find_file_data(payload, obj)
        if not file_data:
            logger.debug("No valid file data found in payload")
            return None

        # Extract basic metadata
        metadata = NextcloudTalkContentParser._extract_file_metadata(file_data)

        # Determine media type
        media_type = NextcloudTalkContentParser._determine_media_type(
            metadata["mime_type"],
            metadata["name"],
        )
        if not media_type:
            return None

        # Check preview availability
        preview_available = (
            NextcloudTalkContentParser._check_preview_available(
                file_data,
                metadata["mime_type"],
            )
        )

        # Extract additional metadata
        additional_metadata = (
            NextcloudTalkContentParser._extract_additional_metadata(file_data)
        )
        complete_metadata = {**file_data, **additional_metadata}

        result = {
            "type": media_type,
            "name": metadata["name"],
            "path": metadata["path"],
            "size": metadata["size"],
            "mime_type": metadata["mime_type"],
            "preview_available": preview_available,
            "metadata": complete_metadata,
        }

        logger.debug(
            f"Successfully extracted media file: {result['name']} "
            f"({result['type']})",
        )
        return result

    @staticmethod
    def extract_reaction(payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """
        Extract reaction from Activity Streams payload.

        Returns:
            Tuple of (reaction_emoji, message_id) or None
        """
        activity_type = payload.get("type")

        if activity_type == ACTIVITY_TYPE_LIKE:
            # Reaction added
            emoji = payload.get("content", "")
            obj = payload.get("object", {})
            message_id = obj.get("id", "")
            return (emoji, message_id) if emoji and message_id else None
        elif activity_type == ACTIVITY_TYPE_UNDO:
            # Reaction removed
            obj = payload.get("object", {})
            if obj.get("type") == ACTIVITY_TYPE_LIKE:
                # The object being undone is a Like
                emoji = obj.get("content", "")
                target = obj.get("target", {})
                # In Undo, the original object is nested
                message_id = target.get("id", "") or obj.get("id", "")
                return (emoji, message_id) if emoji and message_id else None

        return None

    @staticmethod
    def extract_conversation_event(payload: Dict[str, Any]) -> Optional[str]:
        """
        Extract conversation event type (bot added/removed).

        Returns:
            "added" or "removed" or None
        """
        activity_type = payload.get("type")
        actor = payload.get("actor", {})

        # Check if actor is a bot (Application type with bots/ prefix)
        actor_type_raw = actor.get("type", "")
        actor_id = actor.get("id", "")

        if actor_type_raw != ACTOR_TYPE_APPLICATION:
            return None

        if not actor_id.startswith("bots/"):
            return None

        if activity_type == ACTIVITY_TYPE_JOIN:
            return "added"
        elif activity_type == ACTIVITY_TYPE_LEAVE:
            return "removed"

        return None


def parse_data_url(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Parse data URL (data:mime/type;base64,encoded_data)."""
    if not url.startswith("data:"):
        return (None, None)

    try:
        # Parse data URL
        header, data = url.split(",", 1)
        # Remove "data:" prefix
        header = header[5:]

        # Extract mime type and encoding
        parts = header.split(";")
        mime_type = parts[0] if parts else "application/octet-stream"

        # Check if base64
        is_base64 = any(p.strip() == "base64" for p in parts)

        if is_base64:
            decoded = base64.b64decode(data)
            return (decoded, mime_type)
        else:
            # URL encoded
            decoded = unquote(data).encode("utf-8")
            return (decoded, mime_type)
    except Exception:
        logger.exception("Failed to parse data URL")
        return (None, None)


def session_param_from_token(token: str) -> str:
    """Extract session identifier from conversation token."""
    # token is typically an alphanumeric string, use suffix for session
    if len(token) > SESSION_ID_SUFFIX_LEN:
        return token[-SESSION_ID_SUFFIX_LEN:]
    return token


def nextcloud_content_from_type(
    media_type: str,
    local_path: str,
    filename: str = "",
) -> dict:
    """
    Build content part from Nextcloud media type and local path.

    Args:
        media_type: "image", "video", "audio", or "file"
        local_path: Local file path (already downloaded)
        filename: Filename for the file

    Returns:
        Dict compatible with content_parts format
    """
    base = {
        "type": "file",
        "filename": filename or f"file_{media_type}",
        "file_url": local_path,  # Local path, not remote URL!
    }

    if media_type == "image":
        base["file_type"] = "image"
    elif media_type == "video":
        base["file_type"] = "video"
    elif media_type == "audio":
        base["file_type"] = "audio"
    else:
        base["file_type"] = "file"

    return base


def is_public_url(url: Optional[str]) -> bool:
    """Check if URL is a public HTTP/HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return url.startswith("http://") or url.startswith("https://")


def guess_suffix_from_content(data: bytes) -> str:
    """Guess file suffix from content using magic bytes."""
    if not data:
        return ".bin"

    # Define magic byte patterns and their corresponding suffixes
    magic_patterns = [
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"RIFF", ".webp"),  # Special case handled below
        (b"%PDF", ".pdf"),
        (b"PK\x03\x04", ".zip"),
        (b"\x1f\x8b", ".gz"),
    ]

    # Check standard magic bytes
    for magic, suffix in magic_patterns:
        if data.startswith(magic):
            # Special handling for WebP (RIFF container)
            if magic == b"RIFF" and len(data) > 8 and data[8:12] == b"WEBP":
                return ".webp"
            return suffix

    return ".bin"
