# -*- coding: utf-8 -*-
"""
Agent utilities package.

This package provides utilities for agent operations:
- file_handling: File download and management
- message_processing: Message content manipulation and validation
- tool_message_utils: Tool message validation and sanitization
- token_counting: Token counting for context window management
- setup_utils: Setup and initialization utilities
"""

# File handling
from .file_handling import (
    download_file_from_base64,
    download_file_from_url,
)

# Message processing
from .message_processing import (
    is_first_user_interaction,
    prepend_to_message_content,
    process_file_and_media_blocks_in_message,
)

# Setup utilities
from .setup_utils import copy_md_files

# Token counting
from .token_counting import (
    _get_token_counter,
    count_message_tokens,
    safe_count_message_tokens,
    safe_count_str_tokens,
)

# Tool message utilities
from .tool_message_utils import (
    _dedup_tool_blocks,
    _remove_invalid_tool_blocks,
    _repair_empty_tool_inputs,
    _sanitize_tool_messages,
    check_valid_messages,
    extract_tool_ids,
)

__all__ = [
    # File handling
    "download_file_from_base64",
    "download_file_from_url",
    # Message processing
    "process_file_and_media_blocks_in_message",
    "is_first_user_interaction",
    "prepend_to_message_content",
    # Setup utilities
    "copy_md_files",
    # Token counting
    "_get_token_counter",
    "count_message_tokens",
    "safe_count_message_tokens",
    "safe_count_str_tokens",
    # Tool message utilities
    "_dedup_tool_blocks",
    "_remove_invalid_tool_blocks",
    "_repair_empty_tool_inputs",
    "_sanitize_tool_messages",
    "check_valid_messages",
    "extract_tool_ids",
]
