# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Web search and fetch tools powered by Tavily."""

import logging

import httpx

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_RESULTS = 5

_FALLBACK_HINT = (
    "This tool uses a free API with rate limits. "
    "Try again later, or fall back to "
    "execute_shell_command with curl, or browser_use "
    "with action='open' as a last resort."
)


async def _post(
    url: str,
    headers: dict,
    payload: dict,
) -> dict:
    """Async HTTP POST with SSL-verification fallback."""
    try:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
        ) as client:
            resp = await client.post(
                url,
                headers=headers,
                json=payload,
            )
    except Exception as first_exc:
        if "SSL" not in str(type(first_exc).__name__):
            raise
        logger.warning(
            f"SSL verify failed for {url}, retrying",
        )
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            verify=False,
        ) as client:
            resp = await client.post(
                url,
                headers=headers,
                json=payload,
            )
    resp.raise_for_status()
    return resp.json()


def _format_search_results(results: list[dict]) -> str:
    """Format Tavily search results into readable text."""
    if not results:
        return "No results found."
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        lines.append(f"[{i}] {title}")
        lines.append(f"    URL: {url}")
        if content:
            lines.append(f"    {content}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_extract_results(results: list[dict]) -> str:
    """Format Tavily extract results into readable text."""
    if not results:
        return "No content extracted."
    parts: list[str] = []
    for r in results:
        url = r.get("url", "")
        raw = r.get("raw_content", "")
        parts.append(f"URL: {url}\n\n{raw}")
    return "\n\n---\n\n".join(parts)


@tool_descriptor(async_execution=True)
async def web_search(search_term: str) -> ToolChunk:
    """Search the web for real-time information about any topic. Returns summarized information from search results and relevant URLs.

    Use this tool when you need up-to-date information that might not be available or correct in your training data, or when you need to verify current facts.
    This includes queries about:
    - Libraries, frameworks, and tools whose APIs, best practices, or usage instructions are frequently updated.
    - Current events or technology news.
    - Informational queries similar to what you might search on the web.

    IMPORTANT - Prefer this tool over browser_use for simple information retrieval. browser_use should only be used when you need to interact with a page (click, fill forms, navigate through multi-step flows).

    FALLBACK - This tool uses a free API with rate limits. If it returns an error due to network issues or quota limits, fall back to execute_shell_command with curl, or browser_use with action='open' as a last resort.

    Args:
        search_term: The search term to look up on the web. Be specific and include relevant keywords for better results. For technical queries, include version numbers or dates if relevant.

    Returns:
        `ToolChunk`: Search results with titles, URLs, and content snippets.
    """
    query = (search_term or "").strip()
    if not query:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text="Error: search_term is empty.",
                ),
            ],
        )

    try:
        data = await _post(
            _TAVILY_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Tavily-Access-Mode": "keyless",
            },
            payload={
                "query": query,
                "max_results": _DEFAULT_MAX_RESULTS,
                "search_depth": "basic",
            },
        )
        results = data.get("results", [])
        text = _format_search_results(results)
    except Exception as exc:
        logger.warning(f"web_search failed: {exc}")
        text = f"web_search failed: {exc}\n\n" f"{_FALLBACK_HINT}"

    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


@tool_descriptor(async_execution=True)
async def web_fetch(url: str) -> ToolChunk:
    """Fetch content from a specified URL and return its contents in a readable format. Use this tool when you need to retrieve and analyze webpage content.

    - The URL must be a fully-formed, valid URL.
    - This tool is read-only and will not work for requests intended to have side effects.
    - Authentication is not supported, and an error will be returned if the URL requires authentication.
    - This tool does not support fetching binary content, e.g. media or PDFs.
    - For static assets and non-webpage URLs, use execute_shell_command with curl instead.

    IMPORTANT - Prefer this tool over browser_use when you have a direct URL and only need to read its content. Use browser_use only when the page requires JavaScript rendering or interactive operations.

    FALLBACK - This tool uses a free API with rate limits. If it returns an error, fall back to execute_shell_command with curl, or browser_use with action='open' as a last resort.

    Args:
        url: The URL to fetch. The content will be converted to a readable text format.

    Returns:
        `ToolChunk`: The extracted text content of the page.
    """
    target = (url or "").strip()
    if not target:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text="Error: url is empty.",
                ),
            ],
        )

    try:
        data = await _post(
            _TAVILY_EXTRACT_URL,
            headers={
                "Content-Type": "application/json",
                "X-Tavily-Access-Mode": "keyless",
            },
            payload={"urls": [target]},
        )
        results = data.get("results", [])
        text = _format_extract_results(results)
    except Exception as exc:
        logger.warning(f"web_fetch failed: {exc}")
        text = f"web_fetch failed: {exc}\n\n" f"{_FALLBACK_HINT}"

    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )
