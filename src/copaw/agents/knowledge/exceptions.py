# -*- coding: utf-8 -*-
"""Knowledge import domain exceptions."""


class KnowledgeError(Exception):
    """Base exception for knowledge import errors."""


class UploadNotFoundError(KnowledgeError):
    """Raised when an upload_id cannot be resolved to a local file."""


class UnsupportedFileTypeError(KnowledgeError):
    """Raised when uploaded file type is not supported for import."""


class EmptyParsedContentError(KnowledgeError):
    """Raised when parser can open file but cannot extract textual content."""
