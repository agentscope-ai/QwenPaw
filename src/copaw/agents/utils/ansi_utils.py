# -*- coding: utf-8 -*-
"""ANSI escape sequence utilities for cleaning terminal output."""

import re

# Regex pattern to match ANSI escape sequences
# Matches ESC followed by any number of parameter bytes and final byte
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]")


def strip_ansi_sequences(text: str) -> str:
    """Remove ANSI escape sequences from text.

    This cleans terminal output that contains color codes, cursor movements,
    and other control sequences that bloat the output when stored in memory.

    Args:
        text: Text potentially containing ANSI escape sequences

    Returns:
        Cleaned text with all ANSI sequences removed

    Example:
        >>> strip_ansi_sequences("\\x1b[32mHello\\x1b[0m World")
        'Hello World'
    """
    if not text:
        return text
    return _ANSI_ESCAPE_PATTERN.sub("", text)
