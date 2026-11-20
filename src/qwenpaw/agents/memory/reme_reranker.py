# -*- coding: utf-8 -*-
"""Reranking and search-response reconstruction for ReMe memory."""

import asyncio
import ipaddress
import logging
import math
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ...config.config import (
    RerankerConfig,
    load_agent_config_async,
)

logger = logging.getLogger(__name__)

RerankResults = Callable[[str, Any, RerankerConfig], Awaitable[None]]
CallReranker = Callable[
    [str, list[str], RerankerConfig],
    Awaitable[list[int] | None],
]


async def load_reranker_config(agent_id: str) -> RerankerConfig | None:
    """Load the currently enabled reranker configuration."""
    try:
        agent_config = await load_agent_config_async(agent_id)
        config = getattr(
            agent_config.running.reme_light_memory_config,
            "reranker_config",
            None,
        )
        if (
            config is not None
            and config.enabled
            and config.model_name
            and config.api_key.strip()
        ):
            return config
    except Exception:
        logger.warning("[rerank] failed to load config", exc_info=True)
    return None


async def call_reranker_api(
    query: str,
    documents: list[str],
    config: RerankerConfig,
) -> list[int] | None:
    """Return document indices ordered by an OpenAI-compatible reranker."""
    if not config.base_url:
        logger.warning("[rerank] base_url not configured")
        return None
    if not config.api_key.strip():
        logger.warning("[rerank] api_key not configured")
        return None
    if not query or not documents:
        return None

    url = f"{config.base_url.rstrip('/')}/rerank"
    payload = {
        "model": config.model_name,
        "query": query,
        "documents": documents,
    }
    try:
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        if "results" not in data:
            logger.warning("[rerank] unexpected response format: %s", data)
            return None
        scored = [
            (item["index"], item.get("relevance_score", 0.0))
            for item in data["results"]
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        ordered = [index for index, _score in scored]
        logger.info("[rerank] API responded with %d results", len(ordered))
        return ordered
    except httpx.TimeoutException:
        logger.warning("[rerank] API timed out after %ss", config.timeout)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "[rerank] HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:500],
        )
    except Exception:
        logger.warning("[rerank] unexpected error", exc_info=True)
    return None


@dataclass(frozen=True)
class RerankerCaseResult:
    """Result of one probe case (one query with candidate documents)."""

    query: str
    scores: list[float] | None = None
    correct: bool | None = None


@dataclass(frozen=True)
class RerankerTestResult:
    """Aggregated result of the reranker probe suite."""

    success: bool
    latency_ms: int
    message: str
    total: int = 0
    correct_count: int = 0
    incomplete_count: int = 0
    precision: float | None = None
    cases: list[RerankerCaseResult] | None = None


# Each case is (query, documents, expected_index). The expected most-relevant
# document deliberately sits at a different position in every case
# (0, 1, 2, 0, 1), so a service that merely echoes a fixed order, or returns
# the same score for every document (judged incorrect by the tie rule in
# _extract_scores), cannot score perfect precision.
_TEST_SUITE = [
    (
        "How do I reset my password?",
        [
            "Click 'Forgot password' on the login page to "
            "reset your password.",
            "The quick brown fox jumps over the lazy dog.",
            "Today's lunch special is grilled salmon with rice.",
        ],
        0,
    ),
    (
        "What time is hotel checkout?",
        [
            "The stock market closed higher today.",
            "Checkout is at 11 AM; a late checkout may incur a fee.",
            "The cat slept on the windowsill all afternoon.",
        ],
        1,
    ),
    (
        "How many grams are in a cup of flour?",
        [
            "The train to the airport leaves every 20 minutes.",
            "It rained heavily in the north overnight.",
            "One cup of all-purpose flour weighs about 120 grams.",
        ],
        2,
    ),
    (
        "Which planet is closest to the Sun?",
        [
            "Mercury is the closest planet to the Sun.",
            "The concert was rescheduled to next Friday.",
            "My neighbour's dog barks at the mail carrier.",
        ],
        0,
    ),
    (
        "How do I cancel my subscription?",
        [
            "The recipe calls for two eggs and a cup of milk.",
            "Go to Account > Billing > Cancel subscription to stop "
            "auto-renewal.",
            "Line 3 of the metro is suspended for maintenance.",
        ],
        1,
    ),
]

# Fixed wall-clock slack for the whole suite: DNS validation of the base URL,
# TLS handshakes and connection setup happen outside the per-request timeout.
_SUITE_OVERHEAD_SECONDS = 10.0


def reranker_suite_deadline_seconds(per_request_timeout: float) -> float:
    """Explicit wall-clock budget for one complete probe run.

    Covers base URL validation plus every sequential request, each bounded by
    ``per_request_timeout``, and a fixed overhead allowance. The console uses
    the same budget (plus a small margin) so the browser never aborts before
    the backend finishes.
    """
    return len(_TEST_SUITE) * per_request_timeout + _SUITE_OVERHEAD_SECONDS


def _strip_html(text: str) -> str:
    """Collapse an HTML error page into a short plain-text snippet."""
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain or "non-JSON response"


def _redact_secret(text: str, secret: str) -> str:
    """Remove a credential from text that may echo request headers.

    The console route masks the key as well, but the background sweep logs
    probe messages directly, so redaction belongs at the probe boundary.
    """
    if secret:
        return text.replace(secret, "***")
    return text


def _extract_scores(
    results: list[Any],
    n_docs: int,
    expected_index: int,
) -> tuple[list[float] | None, bool | None]:
    """Map returned results back to request order and judge the top rank.

    Tied top scores count as incorrect: a service returning the same score for
    every document carries no ranking signal and must not pass as perfect.

    Non-finite scores (``NaN``/``Infinity``) are rejected as an invalid
    response; comparing them would otherwise let a broken service appear to
    win by landing "first" on a NaN.
    """
    score_by_index: dict[int, float] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, int) and isinstance(score, (int, float)):
            value = float(score)
            if not math.isfinite(value):
                raise ValueError(
                    "Reranker service returned non-finite relevance scores",
                )
            score_by_index[index] = value
    if not all(i in score_by_index for i in range(n_docs)):
        return None, None
    scores = [score_by_index[i] for i in range(n_docs)]
    top_score = max(scores)
    if scores.count(top_score) > 1:
        return scores, False
    return scores, scores.index(top_score) == expected_index


@dataclass(frozen=True)
class _ResolvedTarget:
    """A validated probe target, pinned to one resolved address."""

    request_url: str
    host_header: str
    sni_hostname: str
    secure: bool


async def _validate_reranker_base_url(
    base_url: str,
    *,
    allow_private: bool = False,
) -> list[_ResolvedTarget]:
    """Validate a user-supplied reranker base URL before probing it.

    Only http/https, no embedded credentials. By default every resolved address
    must be globally routable so an untrusted caller cannot use the probe to
    reach internal services.

    ``allow_private`` reflects the runtime deployment model: the rest of
    QwenPaw talks to whatever base URL the operator configured, including a
    reranker on localhost or a private network. The console-only probe endpoint
    derives this flag from the existing trust boundary
    (``security.allow_no_auth_hosts`` plus the loopback peer check), so only a
    caller the server already treats as trusted can probe a local endpoint —
    there is no extra configuration switch.

    The returned targets pin the request to one of the validated addresses
    (with ``Host`` header and TLS SNI preserved), so a hostname cannot
    re-resolve to a different address between validation and the request.
    One target is returned per validated address, letting the probe fall back
    when a dual-stack hostname has only one family listening.
    """
    base = (base_url or "").strip()
    if not base:
        raise ValueError("Reranker base URL is required")
    try:
        parsed = urlsplit(base)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Reranker base URL is invalid") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Reranker base URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Reranker base URL must not contain credentials")

    host = parsed.hostname.rstrip(".")
    if host.lower() == "localhost" and not allow_private:
        raise ValueError("Reranker base URL targets a non-public address")

    async def _resolve() -> tuple[str, ...]:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            # The event-loop resolver is cancellable, so the suite deadline
            # stays a hard wall-clock bound rather than waiting out a stuck
            # synchronous DNS call.
            infos = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
            return tuple(
                dict.fromkeys(
                    str(info[4][0]).split("%", maxsplit=1)[0]
                    for info in infos
                    if info[4]
                ),
            )
        return (str(literal),)

    try:
        addresses = await _resolve()
    except OSError as exc:
        raise ValueError(
            "Reranker base URL host could not be resolved",
        ) from exc
    if not addresses:
        raise ValueError("Reranker base URL host could not be resolved")

    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(
                "Reranker base URL host resolved to an invalid address",
            ) from exc
        if address.is_global:
            continue
        if not allow_private:
            raise ValueError("Reranker base URL targets a non-public address")
        # Even when local targets are allowed, reject addresses that cannot
        # name a real service. Only unspecified and multicast qualify:
        # is_reserved also flags ::1 on newer Pythons, which would break
        # IPv6 loopback rerankers.
        if address.is_unspecified or address.is_multicast:
            raise ValueError("Reranker base URL targets a non-public address")

    try:
        ipaddress.ip_address(host)
        sni_hostname = host
    except ValueError:
        try:
            sni_hostname = host.encode("idna").decode("ascii")
        except UnicodeError:
            sni_hostname = host

    request_path = f"{parsed.path.rstrip('/')}/rerank"
    targets: list[_ResolvedTarget] = []
    for value in addresses:
        address = ipaddress.ip_address(value)
        if address.version == 6:
            netloc = f"[{value}]"
        else:
            netloc = value
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        targets.append(
            _ResolvedTarget(
                request_url=urlunsplit(
                    (parsed.scheme, netloc, request_path, "", ""),
                ),
                # Credentials were rejected above, so netloc is host[:port].
                host_header=parsed.netloc,
                sni_hostname=sni_hostname,
                secure=parsed.scheme == "https",
            ),
        )
    return targets


async def test_reranker_model(
    config: RerankerConfig,
    *,
    timeout: float | None = None,
    allow_private: bool = False,
) -> RerankerTestResult:
    """Send real rerank requests for the probe suite and aggregate quality."""
    timeout = config.timeout if timeout is None else timeout
    deadline = reranker_suite_deadline_seconds(timeout)
    started = time.monotonic()
    try:
        cases: list[RerankerCaseResult] = []
        correct_count = 0
        # One HTTP client for the whole suite keeps DNS/TLS setup out of every
        # case, and one suite-wide deadline bounds URL validation (including
        # DNS) plus all five sequential requests. Per-request httpx timeouts
        # only bound a single operation, so a slow-drip server could otherwise
        # hold the suite open forever.
        async with asyncio.timeout(deadline):
            targets = await _validate_reranker_base_url(
                config.base_url,
                allow_private=allow_private,
            )
            if not config.model_name or not config.model_name.strip():
                raise ValueError("Reranker model name is required")
            # Match the runtime reranker, which refuses to call without a key;
            # never send an empty "Bearer " header.
            if not config.api_key or not config.api_key.strip():
                raise ValueError("Reranker API key is not configured")

            async with httpx.AsyncClient(timeout=timeout) as client:

                async def _probe(target: _ResolvedTarget) -> None:
                    nonlocal correct_count
                    headers = {
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                        # The request dials the validated address; the Host
                        # header and TLS SNI keep the configured origin.
                        "Host": target.host_header,
                    }
                    extensions = (
                        {"sni_hostname": target.sni_hostname}
                        if target.secure
                        else None
                    )
                    for query, documents, expected_index in _TEST_SUITE:
                        payload = {
                            "model": config.model_name.strip(),
                            "query": query,
                            "documents": documents,
                        }
                        # codeql[py/partial-ssrf] pinned to a validated address
                        response = await client.post(
                            target.request_url,
                            headers=headers,
                            json=payload,
                            extensions=extensions,
                        )
                        response.raise_for_status()
                        data = response.json()
                        results = (
                            data.get("results")
                            if isinstance(data, dict)
                            else None
                        )
                        if not isinstance(results, list) or not results:
                            raise RuntimeError(
                                "Reranker service returned an unexpected "
                                "response format",
                            )
                        indices: list[int] = []
                        for item in results:
                            if not isinstance(item, dict):
                                raise RuntimeError(
                                    "Reranker service returned invalid "
                                    "document indices",
                                )
                            index = item.get("index")
                            if not isinstance(index, int) or isinstance(
                                index, bool
                            ):
                                raise RuntimeError(
                                    "Reranker service returned invalid "
                                    "document indices",
                                )
                            indices.append(index)
                        # Same index contract as the runtime path: every
                        # document exactly once. Duplicate indices must not be
                        # scored as if they were distinct rankings.
                        if sorted(indices) != list(range(len(documents))):
                            raise RuntimeError(
                                "Reranker service returned invalid document "
                                "indices",
                            )
                        scores, correct = _extract_scores(
                            results,
                            len(documents),
                            expected_index,
                        )
                        cases.append(
                            RerankerCaseResult(
                                query=query,
                                scores=scores,
                                correct=correct,
                            ),
                        )
                        if correct is True:
                            correct_count += 1

                # A dual-stack hostname may resolve to a family the service
                # does not listen on (commonly ::1 for an IPv4-only service).
                # Retry the next validated address on connection failures,
                # all within the same suite deadline.
                last_connect_error: Exception | None = None
                for target in targets:
                    try:
                        await _probe(target)
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                        last_connect_error = exc
                        cases.clear()
                        correct_count = 0
                else:
                    raise last_connect_error or RuntimeError(
                        "Reranker service connection failed",
                    )

        incomplete_count = sum(1 for case in cases if case.correct is None)
        total = len(cases)
        precision = (
            correct_count / total
            if total and incomplete_count < total
            else None
        )
        latency_ms = round((time.monotonic() - started) * 1000)
        return RerankerTestResult(
            success=True,
            latency_ms=latency_ms,
            message="Reranker service is available",
            total=total,
            correct_count=correct_count,
            incomplete_count=incomplete_count,
            precision=precision,
            cases=cases,
        )
    except (TimeoutError, httpx.TimeoutException):
        latency_ms = round((time.monotonic() - started) * 1000)
        return RerankerTestResult(
            success=False,
            latency_ms=latency_ms,
            message=(
                f"Reranker API timed out after {timeout}s "
                f"per request ({deadline:g}s suite deadline)"
            ),
        )
    except httpx.HTTPStatusError as exc:
        latency_ms = round((time.monotonic() - started) * 1000)
        detail = _redact_secret(
            _strip_html(exc.response.text[:300]),
            config.api_key,
        )
        return RerankerTestResult(
            success=False,
            latency_ms=latency_ms,
            message=(
                f"Reranker API returned HTTP {exc.response.status_code}: "
                f"{detail}"
            ),
        )
    except Exception as exc:
        latency_ms = round((time.monotonic() - started) * 1000)
        message = _redact_secret(
            str(exc) or type(exc).__name__,
            config.api_key,
        )
        return RerankerTestResult(
            success=False,
            latency_ms=latency_ms,
            message=message,
        )


async def rerank_search_results(
    query: str,
    response: Any,
    config: RerankerConfig,
    call_reranker: CallReranker = call_reranker_api,
) -> None:
    """Reorder response metadata using validated reranker indices."""
    results = response.metadata.get("results")
    if not results or len(results) <= 1:
        return
    documents = [result.get("text", "")[:500] for result in results]
    new_order = await call_reranker(query, documents, config)
    if not new_order or len(new_order) != len(results):
        return
    if set(new_order) != set(range(len(results))):
        logger.warning(
            "[rerank] API returned invalid indices: %s for %d results",
            new_order,
            len(results),
        )
        return
    response.metadata["results"] = [results[index] for index in new_order]
    logger.info(
        "[rerank] reordered %d results with model=%s",
        len(results),
        config.model_name,
    )


def format_scores_for_header(
    score: float,
    scores: dict[str, float],
) -> str:
    """Format a ReMe-compatible score header."""
    parts = [f"score={score:.4f}"]
    if "vector" in scores and "keyword" in scores:
        for key in ("vector", "keyword"):
            value = scores.get(key)
            if value is not None:
                parts.append(f"{key}={value:.4f}")
    return " ".join(parts)


def extract_score(result: dict) -> float:
    """Extract a fused score from serialized ReMe chunk data."""
    scores = result.get("scores", {})
    if isinstance(scores, dict) and "score" in scores:
        return scores["score"]
    return result.get("score", 0.0)


def rebuild_search_answer_with_expansions(
    results: list[dict],
    link_expansion: dict[str, dict],
) -> str:
    """Rebuild a ReMe answer from result and expansion metadata."""
    from reme.utils import render_expansion_lines

    answer: list[str] = []
    for result in results:
        path = result.get("path", "")
        start_line = result.get("start_line", 0)
        end_line = result.get("end_line", 0)
        score = extract_score(result)
        score_text = format_scores_for_header(
            score,
            result.get("scores", {}),
        )
        header = (
            f"========== {path}:{start_line}-{end_line} "
            f"[{score_text}] =========="
        )
        answer.append(f"{header}\n{result.get('text', '')}")
        expansion = link_expansion.get(path, {})
        if expansion:
            answer.extend(render_expansion_lines(expansion))
    return "\n".join(answer)


def parse_answer_into_sections(answer: str) -> dict[str, str]:
    """Parse a ReMe answer into path-and-line keyed sections."""
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in answer.split("\n"):
        if line.startswith("=========="):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines)
            rest = line.removeprefix("==========").strip()
            bracket_index = rest.find("[")
            current_key = (
                rest[:bracket_index].strip()
                if bracket_index > 0
                else (rest.split()[0] if rest else None)
            )
            current_lines = [line]
        elif current_key is not None:
            current_lines.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines)
    return sections


def reconstruct_answer_from_sections(
    sections: dict[str, str],
    results: list[dict],
) -> str:
    """Reconstruct an answer in result order, preserving known sections."""
    answer: list[str] = []
    for result in results:
        path = result.get("path", "")
        start_line = result.get("start_line", 0)
        end_line = result.get("end_line", 0)
        key = f"{path}:{start_line}-{end_line}"
        section = sections.get(key)
        if section is None:
            score_text = format_scores_for_header(
                extract_score(result),
                result.get("scores", {}),
            )
            header = f"========== {key} [{score_text}] =========="
            section = f"{header}\n{result.get('text', '')}"
        answer.append(section)
    return "\n".join(answer)


async def rerank_and_cap_response(
    query: str,
    response: Any,
    cap: int,
    config: RerankerConfig | None,
    rerank_results: RerankResults,
) -> None:
    """Rerank, cap and rebuild one mutable ReMe search response."""
    metadata = getattr(response, "metadata", None)
    results = (
        metadata.get("results") if response.success and metadata else None
    )
    if not results:
        return
    link_expansion = metadata.get("link_expansion", {})
    original_answer = str(response.answer or "")
    sections = (
        parse_answer_into_sections(original_answer) if original_answer else {}
    )
    reordered = False
    if config and len(results) > 1:
        try:
            before = list(results)
            await rerank_results(query, response, config)
            results = response.metadata["results"]
            reordered = results != before
        except Exception:
            logger.warning(
                "[rerank] failed, using original order",
                exc_info=True,
            )
    truncated = len(results) > cap
    if truncated:
        results = results[:cap]
        response.metadata["results"] = results
    if reordered or truncated:
        response.answer = (
            reconstruct_answer_from_sections(sections, results)
            if sections
            else rebuild_search_answer_with_expansions(results, link_expansion)
        )
