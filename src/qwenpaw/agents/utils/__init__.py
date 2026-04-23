# -*- coding: utf-8 -*-
"""
Agent utilities package.

This package provides utilities for agent operations:
- audio_transcription: Audio file transcription
- estimate_token_counter: Estimated token counting
- file_handling: File download and management
- message_processing: Message content manipulation and validation
- message_request_normalizer: Normalize messages for model requests
- registry: Generic registry for implementations
- tool_message_utils: Tool message validation and sanitization
- setup_utils: Setup and initialization utilities
"""

# Audio transcription
from .audio_transcription import (
    check_local_whisper_available,
    get_configured_transcription_provider_id,
    list_transcription_providers,
    transcribe_audio,
)

# Estimated token counter
from .estimate_token_counter import EstimatedTokenCounter

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

# Message request normalizer
from .message_request_normalizer import normalize_messages_for_model_request

# Registry
from .registry import Registry

# Setup utilities
from .setup_utils import (
    copy_builtin_qa_md_files,
    copy_md_files,
    copy_template_md_files,
    copy_workspace_md_files,
)

# Token counting
from .token_counter import get_token_counter

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
    # Audio transcription
    "check_local_whisper_available",
    "get_configured_transcription_provider_id",
    "list_transcription_providers",
    "transcribe_audio",
    # Estimated token counter
    "EstimatedTokenCounter",
    # File handling
    "download_file_from_base64",
    "download_file_from_url",
    # Message processing
    "process_file_and_media_blocks_in_message",
    "is_first_user_interaction",
    "prepend_to_message_content",
    # Message request normalizer
    "normalize_messages_for_model_request",
    # Registry
    "Registry",
    # Setup utilities
    "copy_builtin_qa_md_files",
    "copy_md_files",
    "copy_template_md_files",
    "copy_workspace_md_files",
    # Token counting
    "get_token_counter",
    # Tool message utilities
    "_dedup_tool_blocks",
    "_remove_invalid_tool_blocks",
    "_repair_empty_tool_inputs",
    "_sanitize_tool_messages",
    "check_valid_messages",
    "extract_tool_ids",
]
