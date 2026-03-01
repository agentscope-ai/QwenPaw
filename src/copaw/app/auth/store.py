# -*- coding: utf-8 -*-
"""Token store — create, verify, revoke, list API tokens.

Tokens are stored as SHA-256 hashes in a JSON file.  The plaintext
token is returned only once at creation time and never persisted.
"""

import hashlib
import json
import logging
import secrets
from pathlib import Path
from typing import List, Optional

from .models import TokenRecord, TokenScope

logger = logging.getLogger(__name__)

# Token prefix makes it easy to identify CoPaw tokens in logs / configs.
_TOKEN_PREFIX = "cpw_"


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of *token*."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    """JSON-file-backed token store.

    Usage::

        store = TokenStore(Path("~/.copaw/tokens.json"))
        plaintext = store.create(scope=TokenScope.OWNER, label="my-app")
        # plaintext is shown once; only the hash is stored.

        scope = store.verify(plaintext)
        # Returns TokenScope if valid, None otherwise.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[TokenRecord] = []
        self._load()

    # -- public API -----------------------------------------------------------

    def create(
        self,
        scope: TokenScope = TokenScope.OWNER,
        label: str = "",
    ) -> str:
        """Create a new token. Returns the plaintext token (shown once)."""
        plaintext = _TOKEN_PREFIX + secrets.token_hex(24)
        record = TokenRecord(
            hash=_hash_token(plaintext),
            scope=scope,
            label=label,
        )
        self._records.append(record)
        self._save()
        logger.info("Created token [%s] scope=%s label=%s", record.id, scope.value, label)
        return plaintext

    def verify(self, token: str) -> Optional[TokenScope]:
        """Verify a plaintext token. Returns scope if valid, None otherwise."""
        h = _hash_token(token)
        for record in self._records:
            if record.hash == h:
                return record.scope
        return None

    def get_record_by_token(self, token: str) -> Optional[TokenRecord]:
        """Look up the full record for a plaintext token."""
        h = _hash_token(token)
        for record in self._records:
            if record.hash == h:
                return record
        return None

    def revoke(self, token_id: str) -> bool:
        """Revoke (delete) a token by its id. Returns True if found."""
        before = len(self._records)
        self._records = [r for r in self._records if r.id != token_id]
        if len(self._records) < before:
            self._save()
            logger.info("Revoked token [%s]", token_id)
            return True
        return False

    def list_tokens(self) -> List[TokenRecord]:
        """Return all token records (hashes included for internal use)."""
        return list(self._records)

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._records = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._records = [TokenRecord.model_validate(r) for r in data]
        except Exception:
            logger.exception("Failed to load token store")
            self._records = []

    def _save(self) -> None:
        try:
            data = [r.model_dump() for r in self._records]
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save token store")
