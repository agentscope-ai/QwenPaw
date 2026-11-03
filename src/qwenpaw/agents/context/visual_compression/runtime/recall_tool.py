# -*- coding: utf-8 -*-
"""Current-context recall: tool contract, message text and ReMe retrieval.

Reads host-owned messages independently of visual rendering and durable
history. The runtime builder owns feature gating and tool registration.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .....config.context import get_current_agent_state
from .....utils.io_utils import run_async_to_completion
from ....utils.tool_message_utils import flatten_output

logger = logging.getLogger(__name__)
_RECALL_TOOLS = {
    "recall_context",
    "recall_history",
    "recall_history_python",
}


MAX_QUERIES = 4
MAX_QUERY_CHARS = 1_000
CHUNK_BYTES = 2_048
CHUNK_OVERLAP_BYTES = 256
CANDIDATES_PER_QUERY = 10
PASSAGE_CONTEXT_CHARS = 32

RECALL_DESCRIPTION = (
    "Search conversation messages and tool interactions currently retained "
    "in this session context "
    "and return relevant passages with source-role prefixes. "
    'Pass queries as objects, for example [{"query":"release port"}]. '
    "Use short queries with distinctive source terms. "
    "Refine queries when evidence is insufficient; "
    "stop when it is sufficient."
)
RECALL_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "queries": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_QUERIES,
            "description": (
                "Independent searches over the current session context."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_QUERY_CHARS,
                        "description": (
                            "A short query with distinctive terms likely "
                            "to appear in the source."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    "required": ["queries"],
}


class RecallRequestError(ValueError):
    """A model-correctable recovery error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def serialize_result(
    rows: list[dict[str, str]],
    status: str,
    error: dict[str, str] | None = None,
) -> str:
    return json.dumps(
        {"status": status, "results": rows, "error": error},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def make_tokenizer() -> Any:
    from reme.components.tokenizer.regex_tokenizer import RegexTokenizer

    return RegexTokenizer(filter_stopwords=False)


def normalize_queries(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_QUERIES:
        raise RecallRequestError(
            "invalid_queries",
            "Use queries: one to four objects containing query.",
        )
    tokenizer = make_tokenizer()
    queries: list[str] = []
    signatures: set[tuple[str, ...]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"query"}:
            raise RecallRequestError(
                "invalid_query",
                "Expected exactly one query field.",
            )
        query = item["query"]
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > MAX_QUERY_CHARS
        ):
            raise RecallRequestError(
                "invalid_query",
                "Query must contain 1–1000 characters.",
            )
        query = query.strip()
        # ReMe deduplicates query terms before scoring, including repetitions.
        signature = tuple(sorted(set(tokenizer.tokenize([query])[0])))
        if not signature:
            raise RecallRequestError(
                "invalid_query",
                "Use distinctive searchable words.",
            )
        if signature in signatures:
            continue
        signatures.add(signature)
        queries.append(query)
    return tuple(queries)


@dataclass(frozen=True)
class TextSource:
    """Text and attribution; neither field is a persisted conversation."""

    text: str
    prefix: str


def message_sources(message: Any) -> list[TextSource]:
    """Project native blocks without visual whitespace or role rewriting."""
    sources = []
    role = message.role
    for block in message.content:
        kind = block.type
        name = getattr(block, "name", "")
        if kind in {"tool_call", "tool_result"}:
            if name.casefold() in _RECALL_TOOLS:
                continue
            text = (
                block.input
                if kind == "tool_call"
                else flatten_output(block.output)
            )
            prefix = f"{role} [{kind} name={name}]: "
        elif kind == "text":
            text, prefix = block.text, f"{role}: "
        elif kind == "hint":
            text = flatten_output(block.hint)
            prefix = f"{role} [hint]: "
        else:
            continue
        if text:
            sources.append(TextSource(text, prefix))
    return sources


def context_sources(state: Any) -> tuple[TextSource, ...]:
    """Snapshot live conversation text without retaining request state."""
    if state is None:
        raise RecallRequestError(
            "context_unavailable",
            "Current agent context is unavailable.",
        )
    return tuple(
        source
        for message in state.context
        if message.role != "system"
        for source in message_sources(message)
    )


def _bounded_passage(
    rows: list[dict[str, str]],
    source: TextSource,
    query: str,
    tokenizer: Any,
    max_bytes: int,
) -> tuple[int, int]:
    """Return the source span fitting around a match in the JSON budget."""

    def fits(body: str) -> bool:
        row = {"passage": source.prefix + body}
        result = serialize_result([*rows, row], "success")
        return len(result.encode("utf-8")) <= max_bytes

    if fits(source.text):
        return 0, len(source.text)
    terms = tokenizer.tokenize([query])[0]
    matches = [
        match
        for term in terms
        if (match := re.search(re.escape(term), source.text, re.IGNORECASE))
    ]
    start = max(
        0,
        min((m.start() for m in matches), default=0) - PASSAGE_CONTEXT_CHARS,
    )
    body = source.text[start:]
    lo, hi = 0, len(body)
    while lo < hi:
        middle = (lo + hi + 1) // 2
        if fits(body[:middle]):
            lo = middle
        else:
            hi = middle - 1
    return start, start + lo


async def search_sources(
    sources: tuple[TextSource, ...],
    queries: tuple[str, ...],
    max_bytes: int,
) -> str:
    """Build one disposable ReMe index shared by this call's query lanes."""
    from reme.components.file_chunker.default_file_chunker import (
        DefaultFileChunker,
    )
    from reme.components.keyword_index.bm25_index import BM25Index

    chunker = DefaultFileChunker(
        chunk_byte_size=CHUNK_BYTES,
        overlap_byte_size=CHUNK_OVERLAP_BYTES,
    )
    # Repeated reads add no new passage evidence and must not consume top-k.
    # TextSource equality includes attribution, preserving different speakers.
    chunks = [
        TextSource(chunk.text, source.prefix)
        for number, source in enumerate(dict.fromkeys(sources))
        for chunk in chunker.chunk_content(
            source.text,
            str(number),
            parse_links=False,
        )
        if chunk.text
    ]
    backend = BM25Index(tokenizer="")
    backend.tokenizer = make_tokenizer()
    # Explicit tokenizer injection allows these public in-memory operations
    # without start/reset/close, which load or persist file-backed indexes.
    await backend.add_docs(
        {
            str(number): chunk.prefix + chunk.text
            for number, chunk in enumerate(chunks)
        },
    )
    lanes = [
        list(await backend.retrieve(query, limit=CANDIDATES_PER_QUERY))
        for query in queries
    ]
    rows: list[dict[str, str]] = []
    covered: dict[str, list[tuple[int, int]]] = {}
    for rank in range(max(map(len, lanes), default=0)):
        for query_index, (query, lane) in enumerate(zip(queries, lanes)):
            if rank >= len(lane):
                continue
            key = lane[rank]
            chunk = chunks[int(key)]
            candidate_budget = max_bytes
            if rank == 0:
                # Share the remaining serialized budget among queries still
                # awaiting their first candidate; unused shares carry forward.
                pending = sum(bool(lane) for lane in lanes[query_index:])
                used = len(serialize_result(rows, "success").encode("utf-8"))
                candidate_budget = used + max(0, max_bytes - used) // pending
            start, end = _bounded_passage(
                rows,
                chunk,
                query,
                backend.tokenizer,
                candidate_budget,
            )
            if start == end:
                continue
            spans = covered.setdefault(key, [])
            if any(lo <= start and end <= hi for lo, hi in spans):
                continue
            rows.append({"passage": chunk.prefix + chunk.text[start:end]})
            # Merge returned coverage only; a partial excerpt does not consume
            # the whole chunk for subsequent independent queries.
            merged: list[tuple[int, int]] = []
            for lo, hi in sorted([*spans, (start, end)]):
                if merged and lo <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
                else:
                    merged.append((lo, hi))
            covered[key] = merged
    if any(lanes) and not rows:
        raise RecallRequestError(
            "result_budget",
            "No passage fits the output budget.",
        )
    return serialize_result(rows, "success" if rows else "no_match")


def make_recall_context_tool(
    max_bytes: int = 50_000,
):
    """Bind a plain guarded function to the existing current-state accessor."""

    async def recall_context(
        queries: list[dict[str, str]] | None = None,
        **unexpected: Any,
    ) -> ToolChunk:
        """Search current context with one to four independent queries."""
        state = ToolResultState.SUCCESS
        try:
            if unexpected:
                raise RecallRequestError(
                    "invalid_queries",
                    "Use only queries.",
                )
            normalized = normalize_queries(queries)
            agent_state = get_current_agent_state()
            sources = context_sources(agent_state)
            text = await run_async_to_completion(
                asyncio.to_thread(
                    lambda: asyncio.run(
                        search_sources(sources, normalized, max_bytes),
                    ),
                ),
            )
            if sources != context_sources(agent_state):
                raise RecallRequestError(
                    "context_changed",
                    "Context changed; retry the query.",
                )
        except RecallRequestError as error:
            text = serialize_result(
                [],
                "error",
                {"code": error.code, "message": str(error)},
            )
            state = ToolResultState.ERROR
        except Exception:
            logger.exception("Context recall failed")
            text = serialize_result(
                [],
                "error",
                {"code": "recall_failed", "message": "Context recall failed."},
            )
            state = ToolResultState.ERROR
        return ToolChunk(
            is_last=True,
            state=state,
            content=[TextBlock(text=text)],
        )

    recall_context.__doc__ = RECALL_DESCRIPTION
    return recall_context


def configure_recall_tool(tool: Any) -> Any:
    """Preserve the small explicit schema through both permission wrappers."""
    tool.input_schema = deepcopy(RECALL_INPUT_SCHEMA)
    tool.description = RECALL_DESCRIPTION
    tool.is_read_only = True
    return tool
