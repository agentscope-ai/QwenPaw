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
ARTIFACT_SCHEMA_NAMES = {
    "atomic-memory": "AtomicMemory",
    "experience": "Experience",
    "skill": "Skill",
    "topic-memory": "TopicMemory",
    "handoff": "Handoff",
    "profile": "Profile",
    "prompt": "Prompt",
}
SEARCHABLE_ARTIFACT_FAMILIES = {
    "atomic-memory",
    "experience",
    "skill",
    "topic-memory",
}


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
    if not isinstance(scope_id, str):
        raise PowerContextRequestValidationError(
            "PowerContext scope_id must be a string.",
        )
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
    if not isinstance(query, str) or not query.strip():
        raise PowerContextRequestValidationError(
            "PowerContext query must not be empty.",
        )
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext query must not exceed 8192 characters.",
        )
    return query


def _validate_integer(
    value: int,
    *,
    field: str,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise PowerContextRequestValidationError(
            f"PowerContext {field} is outside its integer range.",
        )
    return value


def _validate_object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PowerContextRequestValidationError(
            f"PowerContext {field} must be an object.",
        )
    return value


def _validate_artifact_family(family: str) -> str:
    if not isinstance(family, str) or family not in ARTIFACT_SCHEMA_NAMES:
        raise PowerContextRequestValidationError(
            "PowerContext family must be a supported Artifact family.",
        )
    return family


def _validate_artifact_id(artifact_id: str) -> str:
    if not _is_visible_ascii(artifact_id, max_length=128) or artifact_id in {
        ".",
        "..",
    }:
        raise PowerContextRequestValidationError(
            "PowerContext artifact_id must be a non-dot visible ASCII ID "
            "of at most 128 characters.",
        )
    return artifact_id


def _artifact_paging(limit: int, cursor: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": _validate_integer(limit, field="limit", maximum=100),
    }
    if cursor is not None:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
            raise PowerContextRequestValidationError(
                "PowerContext cursor must contain 1 to 4096 characters.",
            )
        params["cursor"] = cursor
    return params


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

    def _json_response(
        self,
        response: httpx.Response,
        *,
        operation: str,
        status: int = 200,
    ) -> dict[str, Any]:
        self._raise_for_status(operation, response)
        if response.status_code != status:
            raise PowerContextProtocolError(
                operation=operation,
                summary="response has an unexpected HTTP status",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PowerContextProtocolError(
                operation=operation,
                summary="response body is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise PowerContextProtocolError(
                operation=operation,
                summary="response body must be an object",
            )
        return payload

    async def prepare_context(
        self,
        *,
        query: str,
        max_bytes: int,
        assembly: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return complete bounded context without rewriting its content."""
        request: dict[str, Any] = {
            "scope_id": _validate_scope_id(self.config.scope_id),
            "query": _validate_query(query),
            "max_bytes": _validate_integer(
                max_bytes,
                field="max_bytes",
                minimum=512,
                maximum=32768,
            ),
        }
        if assembly is not None:
            request["assembly"] = _validate_object(assembly, field="assembly")
        response = await self._http.post("/v1/context/prepare", json=request)
        operation = "context prepare"
        payload = self._json_response(response, operation=operation)
        content = payload.get("content")
        content_bytes = payload.get("content_bytes")
        valid = (
            set(payload) == {"schema", "status", "content", "content_bytes"}
            and payload["schema"] == "powercontext.prepared-context.v1"
            and isinstance(content_bytes, int)
            and not isinstance(content_bytes, bool)
            and 0 <= content_bytes <= max_bytes
        )
        if valid and payload["status"] == "empty":
            valid = content is None and content_bytes == 0
        elif valid and payload["status"] == "ready":
            try:
                valid = (
                    isinstance(content, str)
                    and bool(content.strip())
                    and len(content.encode("utf-8")) == content_bytes
                )
            except UnicodeEncodeError:
                valid = False
        else:
            valid = False
        if not valid:
            raise PowerContextProtocolError(
                operation=operation,
                summary="prepared context envelope or byte count is invalid",
            )
        return payload

    def _artifact_path(
        self,
        *,
        family: str | None = None,
        artifact_id: str | None = None,
    ) -> str:
        scope_id = _validate_scope_id(self.config.scope_id)
        if scope_id in {".", ".."}:
            raise PowerContextRequestValidationError(
                "PowerContext scope_id must not be a dot path segment.",
            )
        path = f"/v1/scopes/{quote(scope_id, safe='')}/artifacts"
        if family is not None:
            path += "/" + quote(_validate_artifact_family(family), safe="")
        if artifact_id is not None:
            path += "/" + quote(_validate_artifact_id(artifact_id), safe="")
        return path

    def _validate_artifact_identity(
        self,
        payload: Any,
        *,
        operation: str,
        family: str,
        artifact_id: str | None = None,
        revision: int | None = None,
        require_scope: bool = True,
    ) -> None:
        if not isinstance(payload, dict):
            raise PowerContextProtocolError(
                operation=operation,
                summary="Artifact must be an object",
            )
        actual_id = payload.get("artifact_id")
        actual_revision = payload.get("revision")
        valid_id = (
            _is_visible_ascii(actual_id, max_length=128)
            and actual_id not in {".", ".."}
            and (artifact_id is None or actual_id == artifact_id)
        )
        valid_revision = (
            not isinstance(actual_revision, bool)
            and isinstance(actual_revision, int)
            and actual_revision >= 1
            and (revision is None or actual_revision == revision)
        )
        valid_scope = (
            not require_scope and "scope_id" not in payload
        ) or payload.get("scope_id") == _validate_scope_id(
            self.config.scope_id,
        )
        if not all(
            (
                payload.get("family") == family,
                valid_id,
                valid_revision,
                valid_scope,
            ),
        ):
            raise PowerContextProtocolError(
                operation=operation,
                summary="Artifact identity is invalid",
            )

    def _validate_artifact_record(
        self,
        payload: Any,
        *,
        operation: str,
        family: str,
        artifact_id: str | None = None,
        revision: int | None = None,
        require_content: bool = False,
    ) -> None:
        self._validate_artifact_identity(
            payload,
            operation=operation,
            family=family,
            artifact_id=artifact_id,
            revision=revision,
        )
        if (
            not isinstance(payload.get("sources"), list)
            or not isinstance(payload.get("artifacts"), list)
            or (
                require_content
                and not isinstance(payload.get("content"), dict)
            )
        ):
            raise PowerContextProtocolError(
                operation=operation,
                summary="Artifact content or references have invalid shape",
            )

    @staticmethod
    def _with_etag(
        payload: dict[str, Any],
        response: httpx.Response,
        *,
        operation: str,
    ) -> dict[str, Any]:
        etag = response.headers.get("ETag")
        if not etag or not etag.strip() or etag.strip() == "*":
            raise PowerContextProtocolError(
                operation=operation,
                summary="response is missing a usable ETag",
            )
        return {**payload, "etag": etag}

    async def artifact_search(
        self,
        *,
        family: str,
        query: str,
        limit: int = 5,
        mode: str | None = None,
        filters: dict[str, Any] | None = None,
        min_score: float | None = None,
        include_scores: bool = False,
    ) -> dict[str, Any]:
        """Search one supported family and preserve exact revision results."""
        path = self._artifact_path(family=family) + "/search"
        if family not in SEARCHABLE_ARTIFACT_FAMILIES:
            raise PowerContextRequestValidationError(
                "PowerContext family does not support Artifact search.",
            )
        if not isinstance(include_scores, bool):
            raise PowerContextRequestValidationError(
                "PowerContext include_scores must be a boolean.",
            )
        request: dict[str, Any] = {
            "query": _validate_query(query),
            "limit": _validate_integer(limit, field="limit", maximum=200),
            "include_scores": include_scores,
        }
        if mode is not None:
            if not isinstance(mode, str) or not mode.strip():
                raise PowerContextRequestValidationError(
                    "PowerContext mode must be a nonblank string.",
                )
            request["mode"] = mode
        if filters is not None:
            request["filters"] = _validate_object(filters, field="filters")
        if min_score is not None:
            if (
                isinstance(min_score, bool)
                or not isinstance(min_score, (float, int))
                or not 0 <= min_score <= 1
            ):
                raise PowerContextRequestValidationError(
                    "PowerContext min_score must be between 0 and 1.",
                )
            request["min_score"] = min_score
        response = await self._http.post(path, json=request)
        operation = "Artifact search"
        payload = self._json_response(response, operation=operation)
        if not isinstance(payload.get("results"), list):
            raise PowerContextProtocolError(
                operation=operation,
                summary="response needs a results list",
            )
        for result in payload["results"]:
            self._validate_artifact_identity(
                result,
                operation=operation,
                family=family,
                require_scope=False,
            )
            if not isinstance(result.get("content"), dict) or not isinstance(
                result.get("lineage"),
                dict,
            ):
                raise PowerContextProtocolError(
                    operation=operation,
                    summary="search content or lineage has invalid shape",
                )
        return payload

    def _artifact_page(
        self,
        response: httpx.Response,
        *,
        operation: str,
        family: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        payload = self._json_response(response, operation=operation)
        if (
            not isinstance(payload.get("items"), list)
            or "next_cursor" not in payload
            or (
                payload["next_cursor"] is not None
                and not isinstance(payload["next_cursor"], str)
            )
        ):
            raise PowerContextProtocolError(
                operation=operation,
                summary="invalid Artifact page shape",
            )
        for item in payload["items"]:
            self._validate_artifact_record(
                item,
                operation=operation,
                family=family,
                artifact_id=artifact_id,
            )
        return payload

    async def artifact_list(
        self,
        *,
        family: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        response = await self._http.get(
            self._artifact_path(family=family),
            params=_artifact_paging(limit, cursor),
        )
        return self._artifact_page(
            response,
            operation="Artifact list",
            family=family,
        )

    async def artifact_history(
        self,
        *,
        family: str,
        artifact_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        response = await self._http.get(
            self._artifact_path(family=family, artifact_id=artifact_id)
            + "/revisions",
            params=_artifact_paging(limit, cursor),
        )
        return self._artifact_page(
            response,
            operation="Artifact history",
            family=family,
            artifact_id=artifact_id,
        )

    async def artifact_get(
        self,
        *,
        family: str,
        artifact_id: str,
        revision: int | None = None,
    ) -> dict[str, Any]:
        path = self._artifact_path(family=family, artifact_id=artifact_id)
        if revision is not None:
            path += "/revisions/" + str(
                _validate_integer(revision, field="revision"),
            )
        response = await self._http.get(path)
        operation = "Artifact get"
        payload = self._json_response(response, operation=operation)
        self._validate_artifact_record(
            payload,
            operation=operation,
            family=family,
            artifact_id=artifact_id,
            revision=revision,
            require_content=True,
        )
        if revision is not None:
            return payload
        return self._with_etag(payload, response, operation=operation)

    async def artifact_create(
        self,
        *,
        family: str,
        content: dict[str, Any],
        prompt_key: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "family": _validate_artifact_family(family),
            "content": _validate_object(content, field="content"),
        }
        if family == "prompt":
            if not isinstance(prompt_key, str) or not prompt_key.strip():
                raise PowerContextRequestValidationError(
                    "PowerContext Prompt creation requires prompt_key.",
                )
            request["prompt_key"] = prompt_key
        elif prompt_key is not None:
            raise PowerContextRequestValidationError(
                "PowerContext prompt_key is only valid for Prompt creation.",
            )
        response = await self._http.post(self._artifact_path(), json=request)
        operation = "Artifact create"
        payload = self._json_response(
            response,
            operation=operation,
            status=201,
        )
        self._validate_artifact_record(
            payload,
            operation=operation,
            family=family,
            revision=1,
        )
        return self._with_etag(payload, response, operation=operation)

    async def artifact_replace(
        self,
        *,
        family: str,
        artifact_id: str,
        content: dict[str, Any],
        expected_etag: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected_etag, str)
            or not expected_etag.strip()
            or expected_etag.strip() == "*"
            or "\r" in expected_etag
            or "\n" in expected_etag
        ):
            raise PowerContextRequestValidationError(
                "PowerContext expected_etag must be a non-wildcard ETag.",
            )
        response = await self._http.put(
            self._artifact_path(family=family, artifact_id=artifact_id),
            json={"content": _validate_object(content, field="content")},
            headers={"If-Match": expected_etag},
        )
        operation = "Artifact replace"
        payload = self._json_response(response, operation=operation)
        self._validate_artifact_record(
            payload,
            operation=operation,
            family=family,
            artifact_id=artifact_id,
            require_content=True,
        )
        return self._with_etag(payload, response, operation=operation)

    async def artifact_schema(self, *, family: str) -> dict[str, Any]:
        """Discover the server's exact write schemas and local references."""
        stem = ARTIFACT_SCHEMA_NAMES[_validate_artifact_family(family)]
        response = await self._http.get("/openapi.json")
        operation = "Artifact schema"
        document = self._json_response(response, operation=operation)
        return _artifact_schema_bundle(document, stem=stem)

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


def _artifact_schema_bundle(
    document: dict[str, Any],
    *,
    stem: str,
) -> dict[str, Any]:
    """Collect bounded local schema references, retaining cycles as refs."""
    operation = "Artifact schema"

    def invalid() -> PowerContextProtocolError:
        return PowerContextProtocolError(
            operation=operation,
            summary="OpenAPI write schemas or local references are invalid",
        )

    components = document.get("components")
    schemas = (
        components.get("schemas") if isinstance(components, dict) else None
    )
    if not isinstance(schemas, dict):
        raise invalid()
    create_name = f"Create{stem}ArtifactRequest"
    replace_name = f"Replace{stem}ArtifactRequest"
    selected: dict[str, Any] = {}
    pending = [create_name, replace_name]
    visited_nodes = 0
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        schema = schemas.get(name)
        if not isinstance(schema, dict) or len(selected) >= 256:
            raise invalid()
        selected[name] = schema
        nodes: list[Any] = [schema]
        while nodes:
            node = nodes.pop()
            visited_nodes += 1
            if visited_nodes > 20000:
                raise invalid()
            if isinstance(node, dict):
                pending.extend(
                    name
                    for name in _local_schema_names(node)
                    if name not in selected
                )
                nodes.extend(node.values())
            elif isinstance(node, list):
                nodes.extend(node)
    return {
        "create": selected[create_name],
        "replace": selected[replace_name],
        "components": {"schemas": selected},
    }


def _local_schema_names(node: dict[str, Any]) -> list[str]:
    """Resolve JSON pointers without accepting external schema fetches."""
    references = []
    if "$ref" in node:
        references.append(node["$ref"])
    discriminator = node.get("discriminator")
    if isinstance(discriminator, dict):
        mapping = discriminator.get("mapping", {})
        if isinstance(mapping, dict):
            references.extend(mapping.values())
    names = []
    prefix = "#/components/schemas/"
    for reference in references:
        if (
            not isinstance(reference, str)
            or not reference.startswith(prefix)
            or "/" in reference[len(prefix) :]
        ):
            raise PowerContextProtocolError(
                operation="Artifact schema",
                summary="OpenAPI schema has an unsupported reference",
            )
        names.append(
            reference[len(prefix) :].replace("~1", "/").replace("~0", "~"),
        )
    return names
