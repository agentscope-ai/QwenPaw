# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
import codecs
import os
import secrets
import shutil
from codecs import BOM_UTF8
from io import FileIO
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .utils import (
    build_truncation_metadata,
    truncate_text_output,
    read_file_safe,
    read_file_bytes_safe,
    DEFAULT_MAX_BYTES,
    TRUNCATION_METADATA_KEY,
)
from ...config.context import (
    get_all_project_dir_paths,
    get_current_recent_max_bytes,
    get_tool_base_dir,
)
from ...runtime.tool_registry import tool_descriptor
from ...utils.io_utils import (
    get_path_lock,
    run_sync_io,
    write_text_atomic_async,
)

_USER_FILE_MODE = 0o644


def _decode_lossless(raw: bytes) -> tuple[str, str]:
    """Decode a byte snapshot without losing information, returning the text
    and the encoding to write it back with (#8415).

    UTF-8 (BOM-aware) first; anything that is not valid UTF-8 falls back to
    latin-1, which maps every byte to one code point, so
    ``text.encode(encoding)`` rebuilds the exact input bytes and nothing is
    destroyed. The old path decoded with ``errors='ignore'`` and rewrote the
    lossy text as UTF-8, silently dropping the non-UTF-8 bytes of an
    ISO-8859-1 file while reporting success.
    """
    if raw.startswith(codecs.BOM_UTF8):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _detect_newline(text: str) -> str:
    """The file's line ending, so an edit can be written back unchanged (#8414).

    ``edit_file`` matches on a ``\\n``-normalized copy — the model sees the file
    through ``read_file``, which normalizes — but writes the result back with
    the ending the file already uses.
    """
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Atomically replace a file with raw bytes, preserving its mode.

    ``edit_file`` writes the snapshot back byte for byte (#8414, #8415): a
    text-mode write with ``newline='\\n'`` would translate every line ending
    on Windows and re-encode non-UTF-8 files, so this writes binary through a
    sibling temp file, the same shape as io_utils' atomic text writer.
    """
    target = Path(path)
    has_target = target.exists()
    temp_path: Path | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        for _ in range(100):
            candidate = target.with_name(
                f".{target.name}.{secrets.token_hex(8)}.tmp",
            )
            try:
                fd = os.open(candidate, flags, 0o600)
                temp_path = candidate
                break
            except FileExistsError:
                continue
        if temp_path is None:
            raise OSError(
                f"Unable to allocate an atomic temp file for {target}"
            )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if has_target:
            # Keep the original permission bits: an editor must not silently
            # change who can read the file it edits. copymode() copies the
            # source's mode rather than re-applying a 0o777-masked value.
            shutil.copymode(target, temp_path)
        else:
            os.chmod(temp_path, _USER_FILE_MODE)
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _path_to_file_url(path: str) -> str:
    """Convert a local file path to a ``file://`` URL.

    Does NOT percent-encode non-ASCII characters because agentscope's
    DashScope formatter extracts the local path from the URL without
    ``unquote()``, causing ``FileNotFoundError`` for files with
    non-ASCII names (e.g. Chinese characters).
    """
    abs_path = os.path.abspath(path)
    if os.name == "nt":
        abs_path = abs_path.replace("\\", "/")

    if os.name == "nt":
        if abs_path.startswith("//"):
            return f"file:{abs_path}"
        return f"file:///{abs_path}"
    return f"file://{abs_path}"


def _effective_project_roots() -> list[Path]:
    """Return the granted project roots for this turn, primary first.

    Falls back to the tool base dir (project → workspace → WORKING_DIR)
    when the per-turn list was never populated.
    """
    roots = get_all_project_dir_paths()
    if roots:
        return roots
    return [get_tool_base_dir()]


def _resolve_file_path(file_path: str) -> str:
    """Resolve a tool-supplied file path against the project roots.

    Relative paths resolve from the PRIMARY project directory (never an
    extra root). Absolute paths are used as given.

    Deliberately NOT a permission boundary: the tool layer only decides
    what a path *means*, and a path outside the bound directories is not
    an error here. Access is gated by the governance rules and the guard
    chain (and, when enabled, the OS sandbox), which is where the user's
    approval prompts come from. Enforcing containment here as well made
    ordinary absolute-path edits fail that had always worked.

    Args:
        file_path: The input file path (absolute or relative).

    Returns:
        The resolved absolute file path as string.
    """
    path = Path(file_path).expanduser()
    if path.is_absolute():
        return str(path)
    return str(_effective_project_roots()[0] / file_path)


def _get_encoding_for_file(file_path: str) -> str:
    """Preserve an existing BOM; default only new tabular files to BOM."""
    try:
        with FileIO(file_path) as handle:
            has_bom = handle.read(len(BOM_UTF8)) == BOM_UTF8
    except FileNotFoundError:
        has_bom = Path(file_path).suffix.lower() in {
            f".csv",
            f".tsv",
            f".tab",
        }
    return f"utf-8-sig" if has_bom else f"utf-8"


def _append_file(file_path: str, content: str) -> None:
    """Select encoding and append within one offloaded transaction."""
    encoding = _get_encoding_for_file(file_path)
    with open(file_path, f"a", encoding=encoding) as handle:
        handle.write(content)


@tool_descriptor(
    requires_sandbox=("file_read",),
    async_execution=True,
    tool_type="file",
    target_param="file_path",
    policy_name="Read",
    default_policy="allow",
    policy_reason="Read-only file access (global)",
    decision_model_local_read=True,
    ui_description="Read file contents",
    ui_icon="📄",
)
# Keep numeric strings in the public type: AgentScope validates the generated
# schema before entering this function, where they are normalized to integers.
async def read_file(  # pylint: disable=too-many-return-statements
    file_path: str,
    start_line: Optional[int | str] = None,
    end_line: Optional[int | str] = None,
) -> ToolChunk:
    """Read a text file. Relative paths resolve from the project directory.

    Use start_line/end_line to read a specific line range (output includes
    line numbers). Omit both to read from the start. If output is truncated,
    the tail says which start_line to resume from. Images, PDFs and other
    binaries come back as unusable bytes rather than an error. Use view_image
    for images.

    Args:
        file_path (`str`):
            Path to the file.
        start_line (`int | str`, optional):
            First line to read (1-based, inclusive). Decimal strings are
            accepted for tool-call compatibility.
        end_line (`int | str`, optional):
            Last line to read (1-based, inclusive). Decimal strings are
            accepted for tool-call compatibility.
    """

    # Convert start_line/end_line to int if they are strings
    if start_line is not None:
        try:
            start_line = int(start_line)
        except (ValueError, TypeError):
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line must be an integer, got {start_line!r}.",
                    ),
                ],
            )

    if end_line is not None:
        try:
            end_line = int(end_line)
        except (ValueError, TypeError):
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: end_line must be an integer, got {end_line!r}.",
                    ),
                ],
            )

    file_path = _resolve_file_path(file_path)

    try:
        content = await read_file_safe(file_path)
        all_lines = content.split("\n")
        total = len(all_lines)

        # Determine read range
        s = max(1, start_line if start_line is not None else 1)
        e = min(total, end_line if end_line is not None else total)

        if s > total:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line {s} exceeds file length ({total} lines).",
                    ),
                ],
            )

        if s > e:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line ({s}) > end_line ({e}).",
                    ),
                ],
            )

        # Extract selected lines
        selected_content = "\n".join(all_lines[s - 1 : e])

        # Apply smart truncation (consistent with shell output format)
        max_bytes = get_current_recent_max_bytes() or DEFAULT_MAX_BYTES
        text, metadata = truncate_text_output(
            selected_content,
            start_line=s,
            total_lines=total,
            file_path=file_path,
            file_size_bytes=len(content.encode("utf-8")),
            max_bytes=max_bytes,
        )

        # Add continuation hint if partial read without truncation.
        # Use TRUNCATION_NOTICE_MARKER format so ToolResultPruningMiddleware can
        # re-truncate with the correct start_line when pruning old messages.
        if text == selected_content and e < total:
            content_bytes = len(text.encode("utf-8"))
            metadata = build_truncation_metadata(
                file_path=file_path,
                file_size_bytes=len(content.encode("utf-8")),
                total_lines=total,
                start_line=s,
                max_bytes=content_bytes,
                excerpt_bytes=content_bytes,
                read_from=e + 1,
            )
            text += metadata[TRUNCATION_METADATA_KEY]["0"]["notice"]

        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text=text)],
            metadata=metadata,
        )

    except FileNotFoundError:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )
    except IsADirectoryError:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )
    except Exception as e:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Read file failed due to \n{e}",
                ),
            ],
        )


@tool_descriptor(
    requires_sandbox=("file_write",),
    async_execution=True,
    tool_type="file",
    target_param="file_path",
    policy_name="Write",
    ui_description="Write content to file",
    ui_icon="✍️",
)
async def write_file(
    file_path: str,
    content: str,
) -> ToolChunk:
    """Create or overwrite a file. Relative paths resolve from the
    project directory. New text files use UTF-8 without a BOM; new
    CSV/TSV/TAB files use a BOM. Existing files retain their BOM state.

    Args:
        file_path (`str`):
            Path to the file.
        content (`str`):
            Content to write.
    """

    if not file_path:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    file_path = _resolve_file_path(file_path)
    try:
        async with get_path_lock(file_path):
            encoding = await run_sync_io(_get_encoding_for_file, file_path)
            await write_text_atomic_async(
                file_path,
                content,
                encoding=encoding,
                new_file_mode=_USER_FILE_MODE,
            )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"Wrote {len(content)} bytes to {file_path}.",
                ),
            ],
        )
    except Exception as e:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Write file failed due to \n{e}",
                ),
            ],
        )


# pylint: disable=too-many-return-statements
@tool_descriptor(
    requires_sandbox=("file_write",),
    async_execution=True,
    tool_type="file",
    target_param="file_path",
    policy_name="Edit",
    ui_description="Edit file using find-and-replace",
    ui_icon="🖊️",
)
async def edit_file(
    file_path: str,
    old_text: str,
    new_text: str,
) -> ToolChunk:
    """Find-and-replace text in a file. All occurrences of old_text are
    replaced with new_text. Relative paths resolve from the project
    directory.

    Args:
        file_path (`str`):
            Path to the file.
        old_text (`str`):
            Exact text to find.
        new_text (`str`):
            Replacement text.
    """

    if not file_path:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    resolved_path = _resolve_file_path(file_path)

    async with get_path_lock(resolved_path):
        try:
            raw = await read_file_bytes_safe(resolved_path)
        except FileNotFoundError:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: The file {resolved_path} "
                            f"does not exist."
                        ),
                    ),
                ],
            )
        except IsADirectoryError:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: The path {resolved_path} "
                            f"is not a file."
                        ),
                    ),
                ],
            )
        except Exception as e:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Read file failed due to \n{e}",
                    ),
                ],
            )

        # Lossless round trip (#8414, #8415): match and replace on a
        # \n-normalized copy — the model sees the file through read_file, which
        # normalizes — then write the replacement back with the file's own
        # line endings and encoding, so a one-line edit destroys neither.
        content, used_encoding = _decode_lossless(raw)
        newline = _detect_newline(content)
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")

        if old_text not in normalized:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: The text to replace was not found in {file_path}.",
                    ),
                ],
            )

        try:
            new_content = normalized.replace(old_text, new_text)
            if newline != "\n":
                new_content = new_content.replace("\n", newline)
            await run_sync_io(
                _write_bytes_atomic,
                Path(resolved_path),
                new_content.encode(used_encoding),
            )
        except Exception as e:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Write file failed due to \n{e}",
                    ),
                ],
            )

    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=f"Successfully replaced text in {file_path}.",
            ),
        ],
    )


@tool_descriptor(
    requires_sandbox=("file_write",),
    async_execution=True,
    enabled_by_default=False,
    tool_type="file",
    target_param="file_path",
    policy_name="Append",
    ui_description="Append content to a file",
    ui_icon="📎",
)
async def append_file(
    file_path: str,
    content: str,
) -> ToolChunk:
    """Append content to the end of a file. Relative paths resolve from
    WORKING_DIR.

    Args:
        file_path (`str`):
            Path to the file.
        content (`str`):
            Content to append.
    """

    if not file_path:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    file_path = _resolve_file_path(file_path)
    try:
        async with get_path_lock(file_path):
            await run_sync_io(_append_file, file_path, content)
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"Appended {len(content)} bytes to {file_path}.",
                ),
            ],
        )
    except Exception as e:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Append file failed due to \n{e}",
                ),
            ],
        )
