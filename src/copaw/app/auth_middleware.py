# -*- coding: utf-8 -*-
"""HTTP Basic Auth middleware for FastAPI."""

import secrets
from typing import Optional

from fastapi import Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce HTTP Basic Auth on all routes
    except excluded paths."""

    def __init__(
        self,
        app,
        username: str,
        password: str,
        excluded_paths: Optional[list] = None,
    ):
        super().__init__(app)
        self.username = username
        self.password = password
        self.excluded_paths = excluded_paths or []
        self.security = HTTPBasic(auto_error=False)

    def _is_excluded(self, path: str) -> bool:
        """Check if path is excluded from auth."""
        for excluded in self.excluded_paths:
            if path == excluded or path.startswith(excluded + "/"):
                return True
        return False

    def _verify_credentials(self, credentials: HTTPBasicCredentials) -> bool:
        """Verify username and password using constant-time comparison."""
        if not credentials:
            return False
        is_username_ok = secrets.compare_digest(
            credentials.username,
            self.username,
        )
        is_password_ok = secrets.compare_digest(
            credentials.password,
            self.password,
        )
        return is_username_ok and is_password_ok

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip auth if password is not set
        if not self.password:
            return await call_next(request)

        path = request.url.path

        # Skip excluded paths
        if self._is_excluded(path):
            return await call_next(request)

        # Check for basic auth credentials
        credentials = await self.security(request)

        if not credentials or not self._verify_credentials(credentials):
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
                content="Unauthorized",
            )

        return await call_next(request)
