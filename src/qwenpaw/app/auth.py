# -*- coding: utf-8 -*-
"""Authentication module: password hashing, JWT tokens, and FastAPI middleware.

Login is disabled by default and only enabled when the environment
variable ``QWENPAW_AUTH_ENABLED`` is set to a truthy value (``true``,
``1``, ``yes``).  Credentials are created through a web-based
registration flow rather than environment variables, so that agents
running inside the process cannot read plaintext passwords.

Single-user design: only one account can be registered.  If the user
forgets their password, delete ``auth.json`` from ``SECRET_DIR`` and
restart the service to re-register.

Uses only Python stdlib (hashlib, hmac, secrets) to avoid adding new
dependencies.  The password is stored as a salted SHA-256 hash in
``auth.json`` under ``SECRET_DIR``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..constant import SECRET_DIR, EnvVarLoader
from ..security.secret_store import (
    AUTH_SECRET_FIELDS,
    decrypt_dict_fields,
    encrypt_dict_fields,
    is_encrypted,
)

logger = logging.getLogger(__name__)

AUTH_FILE = SECRET_DIR / "auth.json"

# Token validity: 7 days (default)
TOKEN_EXPIRY_SECONDS = 7 * 24 * 3600

# Maximum token validity: 100 years (for "permanent" tokens)
TOKEN_EXPIRY_MAX = 100 * 365 * 24 * 3600

# Paths that do NOT require authentication
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/auth/login",
        "/api/auth/status",
        "/api/auth/register",
        "/api/version",
        "/api/settings/language",
        "/api/plugins",
    },
)

# Prefixes that do NOT require authentication (static assets)
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/assets/",
    "/logo.png",
    "/qwenpaw-symbol.svg",
    "/api/plugins/",  # plugin JS bundles served to unauthenticated login page
)


# ---------------------------------------------------------------------------
# Helpers (reuse SECRET_DIR patterns from envs/store.py)
# ---------------------------------------------------------------------------


def _chmod_best_effort(path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _prepare_secret_parent(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)


# ---------------------------------------------------------------------------
# Password hashing (salted SHA-256, no external deps)
# ---------------------------------------------------------------------------


def _hash_password(
    password: str,
    salt: Optional[str] = None,
) -> tuple[str, str]:
    """Hash *password* with *salt*.  Returns ``(hash_hex, salt_hex)``."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify *password* against a stored hash."""
    h, _ = _hash_password(password, salt)
    return hmac.compare_digest(h, stored_hash)


# ---------------------------------------------------------------------------
# Token generation / verification (HMAC-SHA256, no PyJWT needed)
# ---------------------------------------------------------------------------


def _get_jwt_secret() -> str:
    """Return the signing secret, creating one if absent."""
    data = _load_auth_data()
    secret = data.get("jwt_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        data["jwt_secret"] = secret
        _save_auth_data(data)
    return secret


def create_token(username: str, expiry_seconds: Optional[int] = None) -> str:
    """Create an HMAC-signed token: ``base64(payload).signature``.

    Args:
        username: The username to encode in the token.
        expiry_seconds: Custom expiry time in seconds.
            Use -1 or 0 for permanent tokens.
            Defaults to TOKEN_EXPIRY_SECONDS (7 days).
    """
    import base64

    if expiry_seconds is None:
        expiry_seconds = TOKEN_EXPIRY_SECONDS
    elif expiry_seconds <= 0:
        # Permanent token: 100 years
        expiry_seconds = TOKEN_EXPIRY_MAX
    else:
        # Cap at maximum allowed expiry
        expiry_seconds = min(expiry_seconds, TOKEN_EXPIRY_MAX)

    secret = _get_jwt_secret()
    # Generate unique token ID (jti) for revocation support
    token_id = secrets.token_hex(16)
    payload = json.dumps(
        {
            "sub": username,
            "exp": int(time.time()) + expiry_seconds,
            "iat": int(time.time()),
            "jti": token_id,  # JWT ID for individual revocation
        },
    )
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(
        secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """Verify *token*, return username if valid, ``None`` otherwise.

    Also checks if the token has been revoked (appears in the revocation list).
    """
    import base64

    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        secret = _get_jwt_secret()
        expected_sig = hmac.new(
            secret.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None

        # Check if token is revoked
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti):
            return None

        return payload.get("sub")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.debug("Token verification failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Auth data persistence (auth.json in SECRET_DIR)
# ---------------------------------------------------------------------------


def _load_auth_data() -> dict:
    """Load ``auth.json`` from ``SECRET_DIR``.

    Returns the parsed dict, or a sentinel with ``_auth_load_error``
    set to ``True`` when the file exists but cannot be read/parsed so
    that callers can fail closed instead of silently bypassing auth.

    Encrypted fields (``jwt_secret``) are transparently decrypted.
    Legacy plaintext values trigger an automatic re-encryption.
    """
    if AUTH_FILE.is_file():
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            needs_rewrite = any(
                isinstance(data.get(field), str)
                and data.get(field)
                and not is_encrypted(data[field])
                for field in AUTH_SECRET_FIELDS
            )
            data = decrypt_dict_fields(data, AUTH_SECRET_FIELDS)
            if needs_rewrite:
                try:
                    _save_auth_data(data)
                except Exception as enc_err:
                    logger.debug(
                        "Deferred plaintext→encrypted migration for"
                        " auth.json: %s",
                        enc_err,
                    )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load auth file %s: %s", AUTH_FILE, exc)
            return {"_auth_load_error": True}
    return {}


def _save_auth_data(data: dict) -> None:
    """Save ``auth.json`` to ``SECRET_DIR`` with restrictive permissions.

    Sensitive fields (``jwt_secret``) are encrypted before writing.
    """
    _prepare_secret_parent(AUTH_FILE)
    encrypted_data = encrypt_dict_fields(data, AUTH_SECRET_FIELDS)
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(encrypted_data, f, indent=2, ensure_ascii=False)
    _chmod_best_effort(AUTH_FILE, 0o600)


# ---------------------------------------------------------------------------
# Token revocation (blacklist management)
# ---------------------------------------------------------------------------


def _is_token_revoked(jti: str) -> bool:
    """Check if a token ID (jti) is in the revocation list.

    Uses O(1) dict lookup via revoked_tokens_meta for performance.
    """
    data = _load_auth_data()
    meta = data.get("revoked_tokens_meta", {})
    return jti in meta


def _add_to_revocation_list(jti: str, exp: int) -> None:
    """Add a token ID to the revocation list with its expiry time.

    Uses revoked_tokens_meta dict for O(1) lookups. The revoked_tokens list
    is kept for backwards compatibility but not used for membership checks.
    """
    data = _load_auth_data()
    if data.get("_auth_load_error"):
        return

    # Initialize revoked_tokens_meta if not present
    if "revoked_tokens_meta" not in data:
        data["revoked_tokens_meta"] = {}

    # O(1) check using dict
    if jti not in data["revoked_tokens_meta"]:
        data["revoked_tokens_meta"][jti] = exp

        # Also add to list for backwards compatibility
        if "revoked_tokens" not in data:
            data["revoked_tokens"] = []
        data["revoked_tokens"].append(jti)

    _save_auth_data(data)


def _clean_expired_revocations() -> None:
    """
    Remove expired tokens from the revocation list to prevent unbounded growth.
    """
    data = _load_auth_data()
    if data.get("_auth_load_error"):
        return

    revoked = data.get("revoked_tokens", [])
    meta = data.get("revoked_tokens_meta", {})
    current_time = int(time.time())

    # Remove expired tokens
    cleaned_revoked = []
    cleaned_meta = {}

    for jti in revoked:
        exp = meta.get(jti, 0)
        if exp > current_time:
            cleaned_revoked.append(jti)
            cleaned_meta[jti] = exp

    if len(cleaned_revoked) < len(revoked):
        data["revoked_tokens"] = cleaned_revoked
        data["revoked_tokens_meta"] = cleaned_meta
        _save_auth_data(data)
        logger.info(
            "Cleaned %d expired tokens from revocation list",
            len(revoked) - len(cleaned_revoked),
        )


def is_auth_enabled() -> bool:
    """Check whether authentication is enabled via environment variable.

    Returns ``True`` when ``QWENPAW_AUTH_ENABLED`` is set to a truthy
    value (``true``, ``1``, ``yes``).  The presence of a registered
    user is checked separately by the middleware so that the first
    user can still reach the registration page.
    """
    env_flag = EnvVarLoader.get_str("QWENPAW_AUTH_ENABLED", "").strip().lower()
    return env_flag in ("true", "1", "yes")


def has_registered_users() -> bool:
    """Return ``True`` if a user has been registered."""
    data = _load_auth_data()
    return bool(data.get("user"))


# ---------------------------------------------------------------------------
# Registration (single-user)
# ---------------------------------------------------------------------------


def register_user(
    username: str,
    password: str,
    expiry_seconds: Optional[int] = None,
) -> Optional[str]:
    """Register the single user account.

    Args:
        username: The username to register.
        password: The password to register.
        expiry_seconds: Custom token expiry time in seconds.

    Returns a token on success, ``None`` if a user already exists.
    """
    data = _load_auth_data()

    # Only one user allowed
    if data.get("user"):
        return None

    pw_hash, salt = _hash_password(password)
    data["user"] = {
        "username": username,
        "password_hash": pw_hash,
        "password_salt": salt,
    }

    # Ensure jwt_secret exists
    if not data.get("jwt_secret"):
        data["jwt_secret"] = secrets.token_hex(32)

    _save_auth_data(data)
    logger.info("User '%s' registered", username)
    return create_token(username, expiry_seconds)


def auto_register_from_env() -> None:
    """Auto-register admin user from environment variables.

    Called once during application startup.  If ``QWENPAW_AUTH_ENABLED``
    is truthy and both ``QWENPAW_AUTH_USERNAME`` and ``QWENPAW_AUTH_PASSWORD``
    are set, the admin account is created automatically — useful for
    Docker, Kubernetes, server-panel, and other automated deployments
    where interactive web registration is not practical.

    Skips silently when:
    - authentication is not enabled
    - a user has already been registered
    - either env var is missing or empty
    """
    if not is_auth_enabled():
        return
    if has_registered_users():
        return

    username = EnvVarLoader.get_str("QWENPAW_AUTH_USERNAME", "").strip()
    password = EnvVarLoader.get_str("QWENPAW_AUTH_PASSWORD", "").strip()
    if not username or not password:
        return

    token = register_user(username, password)
    if token:
        logger.info(
            "Auto-registered user '%s' from environment variables",
            username,
        )


def update_credentials(
    current_password: str,
    new_username: Optional[str] = None,
    new_password: Optional[str] = None,
    expiry_seconds: Optional[int] = None,
) -> Optional[str]:
    """Update the registered user's username and/or password.

    Requires the current password for verification.  Returns a new
    token on success (because the username may have changed), or
    ``None`` if verification fails.

    Args:
        current_password: The current password for verification.
        new_username: The new username (optional).
        new_password: The new password (optional).
        expiry_seconds: Custom token expiry time in seconds.
    """
    data = _load_auth_data()
    user = data.get("user")
    if not user:
        return None

    stored_hash = user.get("password_hash", "")
    stored_salt = user.get("password_salt", "")
    if not verify_password(current_password, stored_hash, stored_salt):
        return None

    if new_username and new_username.strip():
        user["username"] = new_username.strip()

    if new_password:
        pw_hash, salt = _hash_password(new_password)
        user["password_hash"] = pw_hash
        user["password_salt"] = salt
        # Rotate JWT secret to invalidate all existing sessions
        data["jwt_secret"] = secrets.token_hex(32)

    data["user"] = user
    _save_auth_data(data)
    logger.info("Credentials updated for user '%s'", user["username"])
    return create_token(user["username"], expiry_seconds)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def authenticate(
    username: str,
    password: str,
    expiry_seconds: Optional[int] = None,
) -> Optional[str]:
    """Authenticate *username* / *password*.  Returns a token if valid.

    Args:
        username: The username to authenticate.
        password: The password to verify.
        expiry_seconds: Custom token expiry time in seconds.
    """
    data = _load_auth_data()
    user = data.get("user")
    if not user:
        return None
    if user.get("username") != username:
        return None
    stored_hash = user.get("password_hash", "")
    stored_salt = user.get("password_salt", "")
    if (
        stored_hash
        and stored_salt
        and verify_password(password, stored_hash, stored_salt)
    ):
        return create_token(username, expiry_seconds)
    return None


def revoke_token(token: str) -> bool:
    """Revoke a single token by adding its jti to the blacklist.

    Args:
        token: The token string to revoke.

    Returns True on success, False on failure.
    """
    import base64

    try:
        # Extract jti and exp from token
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False

        payload_b64 = parts[0]
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        jti = payload.get("jti")
        exp = payload.get("exp", 0)

        if not jti:
            logger.warning("Token has no jti, cannot revoke individually")
            return False

        _add_to_revocation_list(jti, exp)
        logger.info("Token %s revoked", jti[:8])

        # Clean up expired tokens periodically
        _clean_expired_revocations()

        return True
    except Exception as exc:
        logger.error("Failed to revoke token: %s", exc)
        return False


def revoke_all_tokens() -> bool:
    """Revoke all existing tokens by rotating the JWT secret.

    This will invalidate all tokens that were issued before this call.
    Also clears the revocation list since all tokens are invalid anyway.
    Returns True on success, False on failure.
    """
    try:
        data = _load_auth_data()
        if data.get("_auth_load_error"):
            return False

        # Rotate JWT secret to invalidate all existing tokens
        data["jwt_secret"] = secrets.token_hex(32)

        # Clear revocation list since all tokens are now invalid
        data["revoked_tokens"] = []
        data["revoked_tokens_meta"] = {}

        _save_auth_data(data)
        logger.info("All tokens revoked (JWT secret rotated)")
        return True
    except Exception as exc:
        logger.error("Failed to revoke tokens: %s", exc)
        return False


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks Bearer token on protected routes."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """Check Bearer token on protected API routes; skip public paths."""
        if self._should_skip_auth(request):
            return await call_next(request)

        token = self._extract_token(request)
        if not token:
            return Response(
                content=json.dumps({"detail": "Not authenticated"}),
                status_code=401,
                media_type="application/json",
            )

        user = verify_token(token)
        if user is None:
            return Response(
                content=json.dumps(
                    {"detail": "Invalid or expired token"},
                ),
                status_code=401,
                media_type="application/json",
            )

        request.state.user = user
        return await call_next(request)

    @staticmethod
    def _should_skip_auth(request: Request) -> bool:
        """Return ``True`` when the request does not require auth."""
        if not is_auth_enabled() or not has_registered_users():
            return True

        path = request.url.path

        if request.method == "OPTIONS":
            return True

        if path in _PUBLIC_PATHS or any(
            path.startswith(p) for p in _PUBLIC_PREFIXES
        ):
            return True

        # Only protect /api/ routes
        if not path.startswith("/api/"):
            return True

        # Allow localhost requests without auth (CLI runs locally)
        client_host = request.client.host if request.client else ""
        return client_host in ("127.0.0.1", "::1")

    @staticmethod
    def _extract_token(request: Request) -> Optional[str]:
        """Extract Bearer token from header or WebSocket query param."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        if "upgrade" in request.headers.get("connection", "").lower():
            return request.query_params.get("token")

        token = request.query_params.get("token")
        if token:
            return token
        return None
