# -*- coding: utf-8 -*-
"""NapCat exceptions."""

from typing import Any, Optional


class NapCatApiError(RuntimeError):
    """HTTP error returned by NapCat API."""

    def __init__(
        self,
        path: str,
        status: int,
        data: Any,
        message: Optional[str] = None,
    ):
        self.path = path
        self.status = status
        self.data = data
        self.message = message
        super().__init__(f"NapCat API {path} {status}: {message or data}")
