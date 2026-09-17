# -*- coding: utf-8 -*-
"""Content-addressed blob storage retained for web grounding staging."""

from .content_store import ContentStore, StoredContent, atomic_replace_bytes

__all__ = [
    "ContentStore",
    "StoredContent",
    "atomic_replace_bytes",
]
