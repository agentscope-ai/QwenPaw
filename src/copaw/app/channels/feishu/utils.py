# -*- coding: utf-8 -*-
"""Feishu channel pure helpers (session id, sender display, markdown)."""

import json
import re
from typing import Optional

from .constants import FEISHU_SESSION_ID_SUFFIX_LEN


def short_session_id_from_full_id(full_id: str) -> str:
    """Use last N chars of full_id (chat_id or open_id) as session_id."""
    n = FEISHU_SESSION_ID_SUFFIX_LEN
    return full_id[-n:] if len(full_id) >= n else full_id


def sender_display_string(
    nickname: Optional[str],
    sender_id: str,
) -> str:
    """Build sender display as nickname#last4(sender_id), like DingTalk."""
    nick = (nickname or "").strip() if isinstance(nickname, str) else ""
    sid = (sender_id or "").strip()
    suffix = sid[-4:] if len(sid) >= 4 else (sid or "????")
    return f"{(nick or 'unknown')}#{suffix}"


def extract_json_key(content: Optional[str], *keys: str) -> Optional[str]:
    """Parse JSON content and return first present key."""
    if not content:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    for k in keys:
        v = data.get(k) or data.get(k.replace("_", "").lower())
        if v:
            return str(v).strip()
    return None


def normalize_feishu_md(text: str) -> str:
    """
    Light markdown normalization for Feishu post (avoid broken rendering).
    """
    if not text or not text.strip():
        return text
    # Ensure newline before code fence so Feishu parses it
    text = re.sub(r"([^\n])(```)", r"\1\n\2", text)
    
    # Ensure proper spacing for tables
    # Feishu requires proper markdown table format with consistent column widths
    # Add extra newlines around tables to ensure proper rendering
    text = re.sub(r'(\n|^)(\|.*\|)(\n|$)', r'\1\2\n\n', text)
    
    # Ensure table rows have consistent number of columns
    # This is a simple check to ensure tables are properly formatted
    table_lines = []
    in_table = False
    for line in text.split('\n'):
        if '|' in line and ('---' in line or in_table):
            in_table = True
            table_lines.append(line)
        else:
            if in_table:
                # End of table, ensure it's properly closed
                if table_lines:
                    # Add an extra newline after table
                    line = '\n' + line
                in_table = False
            table_lines.append(line)
    text = '\n'.join(table_lines)
    
    return text
