# -*- coding: utf-8 -*-
"""Token-based authentication for CoPaw API.

Provides a TokenStore for managing API tokens with three scope levels
(owner > collaborator > viewer), a FastAPI middleware for Bearer token
validation, and dependency helpers for route-level scope enforcement.
"""

from .models import TokenScope, TokenRecord
from .store import TokenStore

__all__ = [
    "TokenScope",
    "TokenRecord",
    "TokenStore",
]
