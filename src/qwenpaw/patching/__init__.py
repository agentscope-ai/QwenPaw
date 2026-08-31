# -*- coding: utf-8 -*-
"""Transactional patch parsing and application primitives."""

from .errors import PatchError
from .executor import apply_patch_document
from .models import PatchDocument, PatchResult
from .parser import parse_patch

__all__ = [
    "PatchDocument",
    "PatchError",
    "PatchResult",
    "apply_patch_document",
    "parse_patch",
]
