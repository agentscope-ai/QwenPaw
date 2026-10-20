# -*- coding: utf-8 -*-
"""PowerContext HTTP client owned by the memory-powercontext plugin."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import quote

import httpx

MAX_MEMORY_TEXT_BYTES = 8000
MAX_SCOPE_ID_LENGTH = 256
MAX_MEMORY_KIND_LENGTH = 128
MAX_SEARCH_QUERY_LENGTH = 8192
MIN_SEARCH_RESULTS = 1
MAX_SEARCH_RESULTS = 50
TRUNCATION_MARKER = "… [truncated]"


def truncate_utf8_text(
    text: str,
    *,
    max_bytes: int = MAX_MEMORY_TEXT_BYTES,
    marker: str = "",
) -> str:
    """Bound text without splitting a UTF-8 code point.

    PowerContext accepts at most 8192 normalized UTF-8 bytes.  Keep a small
    margin so the client remains valid when the server normalizes whitespace.
    When supplied, ``marker`` is included inside the byte budget so callers
    can make loss of content explicit.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    marker_bytes = marker.encode("utf-8")
    if marker and len(marker_bytes) <= max_bytes:
        prefix = encoded[: max_bytes - len(marker_bytes)].decode(
            "utf-8",
            errors="ignore",
        )
        return prefix + marker
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def bound_search_limit(limit: int) -> int:
    """Clamp a caller-provided result count to the PowerContext contract."""
    return min(MAX_SEARCH_RESULTS, max(MIN_SEARCH_RESULTS, limit))


class PowerContextRequestValidationError(ValueError):
    """Safe local validation error for a PowerContext request field."""


def _validate_scope_id(scope_id: str) -> str:
    normalized = scope_id.strip()
    if not normalized:
        raise PowerContextRequestValidationError(
            "PowerContext scope_id must not be blank.",
        )
    if len(normalized) > MAX_SCOPE_ID_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext scope_id must not exceed 256 characters.",
        )
    return normalized


def _validate_kind(kind: str) -> str:
    normalized = kind.strip()
    if not normalized:
        raise PowerContextRequestValidationError(
            "PowerContext kind must not be blank.",
        )
    if len(normalized) > MAX_MEMORY_KIND_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext kind must not exceed 128 characters.",
        )
    return normalized


def _validate_query(query: str) -> str:
    if not query:
        raise PowerContextRequestValidationError(
            "PowerContext query must not be empty.",
        )
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext query must not exceed 8192 characters.",
        )
    return query


def _validate_memory_text(text: str) -> str:
    if not text.strip():
        raise PowerContextRequestValidationError(
            "PowerContext text must not be blank.",
        )
    if len(text.encode("utf-8")) > MAX_MEMORY_TEXT_BYTES:
        raise PowerContextRequestValidationError(
            "PowerContext text must not exceed 8000 UTF-8 bytes.",
        )
    return text


@dataclass(frozen=True)
class PowerContextConfig:
    base_url: str
    token: str = ""
    scope_id: str = ""
    timeout: float = 10.0


class PowerContextHTTPError(RuntimeError):
    """A safe, operation-scoped error returned by the PowerContext API.

    The response body is reduced to a short server-provided summary.  Headers
    (including the bearer token) and arbitrary response payloads are never
    included in the exception string.
    """

    def __init__(
        self,
        *,
        operation: str,
        response: httpx.Response,
        token: str = "",
    ) -> None:
        self.operation = operation
        self.status_code = response.status_code
        self.summary = _safe_error_summary(response, token=token)
        super().__init__(
            f"PowerContext {operation} failed with HTTP {self.status_code}: "
            f"{self.summary}",
        )


class PowerContextProtocolError(RuntimeError):
    """Safe error for a successful response that violates the API contract."""

    def __init__(self, *, operation: str, summary: str) -> None:
        self.operation = operation
        self.summary = summary
        super().__init__(
            f"PowerContext {operation} returned invalid response: {summary}",
        )


def _safe_error_summary(response: httpx.Response, *, token: str = "") -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), dict):
            # PowerContext envelopes diagnostics under error. Its details and
            # context can contain content, so only read code and message.
            payload = payload["error"]
        code = payload.get("code")
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("detail")
        )
        if (
            isinstance(code, str)
            and code.strip()
            and isinstance(message, str)
            and message.strip()
        ):
            summary = f"{code.strip()}: {message.strip()}"
            return safe_powercontext_exception_summary(summary, token=token)
        for value in (message, code):
            if isinstance(value, str) and value.strip():
                return safe_powercontext_exception_summary(
                    value.strip(),
                    token=token,
                )
    if isinstance(payload, str) and payload.strip():
        return safe_powercontext_exception_summary(
            payload.strip(),
            token=token,
        )
    return safe_powercontext_exception_summary(
        response.reason_phrase or "request failed",
        token=token,
    )


def safe_powercontext_exception_summary(
    error: BaseException | str,
    *,
    token: str = "",
) -> str:
    """Return a bounded diagnostic with the configured bearer token removed."""
    summary = str(error).strip() or type(error).__name__
    if token:
        summary = summary.replace(token, "<redacted>")
    return summary[:300]


def _invalid_search_hit(index: int, field: str) -> PowerContextProtocolError:
    return PowerContextProtocolError(
        operation="memory search",
        summary=f"hit {index} has an invalid {field}",
    )


def _is_visible_ascii(value: Any, *, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= max_length
        and all("!" <= character <= "~" for character in value)
    )


def _validate_search_hit(hit: Any, *, index: int) -> dict[str, Any]:
    """Validate one successful hit without echoing server-provided values."""
    if not isinstance(hit, dict):
        raise PowerContextProtocolError(
            operation="memory search",
            summary=f"hit {index} must be an object",
        )
    if "memory" in hit:
        return _validate_atomic_search_hit(hit, index=index)
    text = hit.get("text")
    if not isinstance(text, str):
        raise _invalid_search_hit(index, "text")
    if set(hit) != {"citation", "text", "score", "matched_by"}:
        raise _invalid_search_hit(index, "fields")

    score = hit.get("score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
        or not 0.0 <= float(score) <= 1.0
    ):
        raise _invalid_search_hit(index, "score")

    citation = hit.get("citation")
    if not isinstance(citation, dict):
        raise _invalid_search_hit(index, "citation")
    if set(citation) != {"memory_ref", "entry_id", "entry_version_id"}:
        raise _invalid_search_hit(index, "citation")
    memory_ref = citation.get("memory_ref")
    if not isinstance(memory_ref, dict):
        raise _invalid_search_hit(index, "citation")
    if set(memory_ref) != {"family", "artifact_id", "revision"}:
        raise _invalid_search_hit(index, "citation")
    revision = memory_ref.get("revision")
    reference_values = (
        memory_ref.get("family"),
        memory_ref.get("artifact_id"),
        citation.get("entry_id"),
        citation.get("entry_version_id"),
    )
    if not all(
        _is_visible_ascii(value, max_length=128) for value in reference_values
    ):
        raise _invalid_search_hit(index, "citation")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
    ):
        raise _invalid_search_hit(index, "citation")

    matched_by = hit.get("matched_by")
    if not isinstance(matched_by, list) or any(
        not isinstance(value, str) or value not in {"fts", "vector"}
        for value in matched_by
    ):
        raise _invalid_search_hit(index, "matched_by")

    validated = dict(hit)
    validated["score"] = float(score)
    return validated


def _validate_atomic_search_hit(
    hit: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    """Preserve Atomic identity and state without inventing entry IDs."""
    if set(hit) != {"memory", "score", "matched_by"}:
        raise _invalid_search_hit(index, "fields")
    memory = hit["memory"]
    if not isinstance(memory, dict) or set(memory) != {
        "artifact",
        "state_version",
        "kind",
        "text",
        "state",
        "merged_into_id",
    }:
        raise _invalid_search_hit(index, "memory")
    for field in ("kind", "text"):
        if not isinstance(memory[field], str) or not memory[field]:
            raise _invalid_search_hit(index, f"memory {field}")
    if memory["state"] != "active" or memory["merged_into_id"] is not None:
        raise _invalid_search_hit(index, "memory state")

    artifact = memory["artifact"]
    if not isinstance(artifact, dict) or set(artifact) != {
        "family",
        "artifact_id",
        "revision",
    }:
        raise _invalid_search_hit(index, "artifact")
    revision = artifact["revision"]
    if (
        artifact["family"] != "atomic-memory"
        or not _is_visible_ascii(artifact["artifact_id"], max_length=128)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
    ):
        raise _invalid_search_hit(index, "artifact")
    state_version = memory["state_version"]
    if (
        isinstance(state_version, bool)
        or not isinstance(state_version, int)
        or state_version < 0
    ):
        raise _invalid_search_hit(index, "state_version")

    score = hit["score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
    ):
        raise _invalid_search_hit(index, "score")
    matched_by = hit["matched_by"]
    if not isinstance(matched_by, list) or any(
        not isinstance(value, str) or value not in {"text", "vector"}
        for value in matched_by
    ):
        raise _invalid_search_hit(index, "matched_by")
    return {
        "text": memory["text"],
        "score": float(score),
        "matched_by": matched_by,
        "citation": {
            "artifact": dict(artifact),
            "state_version": state_version,
        },
    }


class PowerContextMemoryClient:
    def __init__(self, config: PowerContextConfig) -> None:
        self.config = config
        headers = (
            {"Authorization": f"Bearer {config.token}"} if config.token else {}
        )
        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=config.timeout,
        )

    async def resolve_scope(self, *, create_default: bool = False) -> str:
        """Reuse an existing scope, or idempotently create a host default."""
        requested_id = _validate_scope_id(self.config.scope_id)
        response = await self._http.get(
            f"/v1/scopes/{quote(requested_id, safe='')}",
        )
        missing_scope = False
        if response.status_code == 404:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            error = payload.get("error") if isinstance(payload, dict) else None
            missing_scope = (
                isinstance(error, dict)
                and error.get("code") == "scope_not_found"
            )
        if create_default and missing_scope:
            # Keep both the key and payload stable across restarts: changing
            # either would break the server's persisted idempotency contract.
            response = await self._http.post(
                "/v1/scopes",
                json={
                    "title": "QwenPaw agent memory",
                    "summary": (
                        "Long-term memory for one QwenPaw installation "
                        "and agent."
                    ),
                    "idempotency_key": "qwenpaw-memory:"
                    + hashlib.sha256(requested_id.encode("utf-8")).hexdigest(),
                },
            )
            self._raise_for_status("scope creation", response)
            resolved_id = self._scope_response_id(response)
        else:
            self._raise_for_status("scope lookup", response)
            resolved_id = self._scope_response_id(
                response,
                expected_id=requested_id,
            )
        self.config = replace(self.config, scope_id=resolved_id)
        return resolved_id

    @staticmethod
    def _scope_response_id(
        response: httpx.Response,
        *,
        expected_id: str | None = None,
    ) -> str:
        success_statuses = {200} if expected_id is not None else {200, 201}
        if response.status_code not in success_statuses:
            raise PowerContextProtocolError(
                operation="scope resolution",
                summary="response has an unexpected HTTP status",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PowerContextProtocolError(
                operation="scope resolution",
                summary="response body is not valid JSON",
            ) from exc
        scope_id = (
            payload.get("scope_id") if isinstance(payload, dict) else None
        )
        if (
            not isinstance(scope_id, str)
            or not scope_id.strip()
            or len(scope_id) > MAX_SCOPE_ID_LENGTH
            or (expected_id is not None and scope_id != expected_id)
        ):
            raise PowerContextProtocolError(
                operation="scope resolution",
                summary="response has an invalid scope_id",
            )
        return scope_id

    async def remember(
        self,
        *,
        kind: str,
        text: str,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_scope_id = _validate_scope_id(
            scope_id or self.config.scope_id,
        )
        response = await self._http.post(
            "/v1/memory/remember",
            json={
                "scope_id": resolved_scope_id,
                "kind": _validate_kind(kind),
                "text": _validate_memory_text(text),
            },
        )
        self._raise_for_status("memory remember", response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PowerContextProtocolError(
                operation="memory remember",
                summary="response body is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise PowerContextProtocolError(
                operation="memory remember",
                summary="response body must be an object",
            )
        return payload

    async def search(
        self,
        *,
        query: str,
        limit: int = 5,
        scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        resolved_scope_id = _validate_scope_id(
            scope_id or self.config.scope_id,
        )
        response = await self._http.post(
            "/v1/memory/search",
            json={
                "scope_id": resolved_scope_id,
                "query": _validate_query(query),
                "limit": bound_search_limit(limit),
            },
        )
        self._raise_for_status("memory search", response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PowerContextProtocolError(
                operation="memory search",
                summary="response body is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise PowerContextProtocolError(
                operation="memory search",
                summary="response body must be an object",
            )
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise PowerContextProtocolError(
                operation="memory search",
                summary="response does not contain a hits list",
            )
        return [
            _validate_search_hit(hit, index=index)
            for index, hit in enumerate(hits)
        ]

    async def close(self) -> None:
        await self._http.aclose()

    def _raise_for_status(
        self,
        operation: str,
        response: httpx.Response,
    ) -> None:
        if response.is_error:
            raise PowerContextHTTPError(
                operation=operation,
                response=response,
                token=self.config.token,
            )
