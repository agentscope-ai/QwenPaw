# -*- coding: utf-8 -*-
"""NapCat constants and configuration."""

from pathlib import Path

# Reconnect settings
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 100
QUICK_DISCONNECT_THRESHOLD = 5
MAX_QUICK_DISCONNECT_COUNT = 3

# Default paths
DEFAULT_MEDIA_DIR = Path("~/.copaw/media/napcat").expanduser()

# Markdown detection regex patterns
MARKDOWN_PATTERNS = [
    r"^#{1,6}\s+.+",  # Headers (# to ######)
    r"\*\*[^*]+\*\*",  # Bold (**text**)
    r"(?<!\*)\*[^*\n]+\*(?!\*)",  # Italic (*text*)
    r"__[^_]+__",  # Bold underline
    r"_[^_\n]+_",  # Italic underline
    r"~~[^~]+~~",  # Strikethrough
    r"`[^`]+`",  # Inline code
    r"```[\s\S]+```",  # Code block
    r"^\s*[-*+]\s",  # Unordered list
    r"^\s*\d+\.\s",  # Ordered list
    r"^\s*>\s+",  # Quote
    r"\|.+\|",  # Table
    r"\[.+\]\(.+\)",  # Link
    r"!\[.+\]\(.+\)",  # Image
]
