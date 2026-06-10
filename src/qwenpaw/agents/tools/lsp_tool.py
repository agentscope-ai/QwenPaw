# -*- coding: utf-8 -*-
"""LSP tool — single ``lsp`` function with operation dispatch.

Built dynamically by :func:`make_lsp_tool` so the agent only sees the
languages whose servers were discovered at toolkit-creation time
(see PROPOSAL §3.2).  Unsupported languages return an error string
that nudges the agent toward ``grep_search`` / ``ast_search``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from . import _lsp_client as lsp_client
from . import _lsp_servers as lsp_servers
from .file_io import _resolve_file_path

# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

_REQUEST_TIMEOUT = 20.0
_MAX_RESULT_CHARS = 80_000

_OPERATIONS_REQUIRING_POSITION = {
    "goToDefinition",
    "findReferences",
    "hover",
    "goToImplementation",
}
_OPERATIONS_REQUIRING_FILE = _OPERATIONS_REQUIRING_POSITION | {
    "documentSymbol",
}
_ALL_OPERATIONS = _OPERATIONS_REQUIRING_FILE | {"workspaceSymbol"}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _make_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _resolve_root() -> Path:
    workspace = get_current_workspace_dir()
    if workspace is not None:
        return workspace
    return WORKING_DIR


def _resolve_file(
    file_path: str,
    root: Path,
) -> "Path | ToolResponse":
    """Resolve ``file_path`` and ensure it lives inside ``root``."""
    if not file_path:
        return _make_response("Error: missing `file_path`.")
    candidate = Path(_resolve_file_path(file_path)).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        return _make_response(
            f"Error: cannot resolve path {candidate} — {exc}",
        )
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return _make_response(
            f"Error: path {file_path} is outside the project root "
            f"{root.resolve()}.",
        )
    if not resolved.exists():
        return _make_response(
            f"Error: path {resolved} does not exist.",
        )
    if not resolved.is_file():
        return _make_response(
            f"Error: path {resolved} is not a regular file.",
        )
    return resolved


def _serialize(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + "\n… (truncated)"
    return text


def _format_languages(language_ids: list[str]) -> str:
    names = [lsp_servers.display_name(lid) for lid in sorted(language_ids)]
    if not names:
        return "(none)"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _build_description(available: dict[str, list[str]]) -> str:
    langs = _format_languages(list(available.keys()))
    return (
        "lsp — Code intelligence via Language Server Protocol.\n\n"
        f"Supported languages in this workspace: {langs}.\n\n"
        "Operations: goToDefinition, findReferences, hover, "
        "documentSymbol, workspaceSymbol, goToImplementation.\n\n"
        "Other languages are not currently available; fall back to "
        "grep_search / ast_search for those files.\n\n"
        "Line and character are 1-based (editor gutter style)."
    )


# ---------------------------------------------------------------------
# Per-operation dispatch
# ---------------------------------------------------------------------


# pylint: disable-next=too-many-return-statements,too-many-arguments
def _call_operation(
    client: lsp_client.LspClient,
    operation: str,
    file_path: Optional[Path],
    line: Optional[int],
    character: Optional[int],
    query: str,
) -> Any:
    # mypy-friendly aliases (callers pre-validate that the required
    # arguments are not None for the chosen operation).
    fp: Path = file_path  # type: ignore[assignment]
    ln: int = line  # type: ignore[assignment]
    ch: int = character  # type: ignore[assignment]
    if operation == "goToDefinition":
        return client.definition(fp, ln, ch)
    if operation == "findReferences":
        return client.references(fp, ln, ch)
    if operation == "hover":
        return client.hover(fp, ln, ch)
    if operation == "goToImplementation":
        return client.implementation(fp, ln, ch)
    if operation == "documentSymbol":
        return client.document_symbol(fp)
    if operation == "workspaceSymbol":
        return client.workspace_symbol(query)
    raise ValueError(f"unknown operation: {operation}")


# ---------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------


def make_lsp_tool(  # noqa: C901  pylint: disable=too-many-statements
    available: dict[str, list[str]],
) -> Callable[..., Any]:
    """Build the async ``lsp`` tool bound to a fixed language map.

    ``available`` maps ``language_id`` → argv (already resolved by
    :func:`_lsp_servers.detect_available_lsp_languages`).  The returned
    coroutine is what gets registered with the toolkit; its docstring
    is the agent-visible description.
    """
    frozen_available = dict(available)

    async def lsp(  # noqa: C901
        operation: str,
        file_path: str = "",
        line: int = 0,
        character: int = 0,
        query: str = "",
    ) -> ToolResponse:
        # pylint: disable=too-many-return-statements,too-many-branches
        if operation not in _ALL_OPERATIONS:
            return _make_response(
                f"Error: unknown operation `{operation}`. Valid: "
                f"{sorted(_ALL_OPERATIONS)}.",
            )

        root = _resolve_root()

        # workspaceSymbol: no file required, but we still need to pick
        # a language since workspace/symbol is server-scoped.
        if operation == "workspaceSymbol":
            if not query:
                return _make_response(
                    "Error: `query` is required for workspaceSymbol.",
                )
            if not frozen_available:
                return _make_response(
                    "Error: no LSP servers available in this workspace.",
                )
            # Prefer Python if discovered, otherwise the first language
            # in the registry order so the choice is deterministic.
            language_id = (
                "python"
                if "python" in frozen_available
                else next(iter(frozen_available))
            )
            target_file: Optional[Path] = None
        else:
            resolved_or_err = _resolve_file(file_path, root)
            if isinstance(resolved_or_err, ToolResponse):
                return resolved_or_err
            target_file = resolved_or_err
            language_id = lsp_servers.language_for_file(target_file) or ""
            if not language_id:
                return _make_response(
                    f"Error: cannot infer language for {target_file.name}. "
                    "Fall back to grep_search / ast_search.",
                )
            if language_id not in frozen_available:
                supported = _format_languages(
                    list(frozen_available.keys()),
                )
                pretty = lsp_servers.display_name(language_id)
                return _make_response(
                    f"Error: LSP for {pretty} is not available in this "
                    f"workspace. Supported: {supported}. Use grep_search "
                    f"/ ast_search for {target_file.name}.",
                )

        if operation in _OPERATIONS_REQUIRING_POSITION:
            if line < 1 or character < 1:
                return _make_response(
                    "Error: `line` and `character` must be 1-based "
                    "integers >= 1.",
                )

        argv = frozen_available[language_id]

        def _run() -> Any:
            client = lsp_client.get_client(root, language_id, argv)
            return _call_operation(
                client,
                operation,
                target_file,
                line if operation in _OPERATIONS_REQUIRING_POSITION else None,
                character
                if operation in _OPERATIONS_REQUIRING_POSITION
                else None,
                query,
            )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=_REQUEST_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return _make_response(
                f"Error: LSP {operation} timed out after "
                f"{_REQUEST_TIMEOUT}s.",
            )
        except lsp_client.LspError as exc:
            return _make_response(f"Error: LSP {operation} failed — {exc}")

        if result is None:
            return _make_response(f"No result for {operation}.")
        return _make_response(_serialize(result))

    lsp.__doc__ = _build_description(frozen_available)
    return lsp
