# -*- coding: utf-8 -*-
"""DingTalk Markdown normalization helpers."""

import re


def ensure_list_spacing(text: str) -> str:
    """
    Ensure there is a blank line before numbered list items (e.g. "1. ..."),
    to avoid DingTalk merging the list item into the previous paragraph and
    breaking Markdown parsing.

    Example (before):
        Image: `xxx`
        3. **Make sure you are on the latest branch**

    Example (after):
        Image: `xxx`

        3. **Make sure you are on the latest branch**
    """
    lines = text.split("\n")
    out = []

    for i, line in enumerate(lines):
        is_numbered = re.match(r"^\d+\.\s", line.strip()) is not None
        if is_numbered and i > 0:
            prev = lines[i - 1]
            prev_is_empty = prev.strip() == ""
            prev_is_numbered = (
                re.match(
                    r"^\d+\.\s",
                    prev.strip(),
                )
                is not None
            )
            if not prev_is_empty and not prev_is_numbered:
                out.append("")
        out.append(line)

    return "\n".join(out)


_FENCE_RE = re.compile(
    r"^( {0,3}(?:(?:[-+*]|[0-9]{1,9}[.)]) {1,4})?)(`{3,}|~{3,})(.*)$",
)
_TABLE_DELIMITER_RE = re.compile(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?")


def _is_table_delimiter(line: str) -> bool:
    stripped = line.strip()
    return (
        "|" in stripped and _TABLE_DELIMITER_RE.fullmatch(stripped) is not None
    )


def ensure_table_spacing(text: str) -> str:
    """Separate pipe tables from preceding text for DingTalk's renderer."""
    lines = text.split("\n")
    out = []
    fence = ""
    fence_indent = 0
    in_table = False

    for i, line in enumerate(lines):
        fence_line = line.expandtabs(4)
        if (
            fence_indent
            and fence_line.strip()
            and not fence_line.startswith(" " * fence_indent)
        ):
            # Dedenting out of a list item also ends its unclosed fence.
            fence, fence_indent = "", 0
        match = _FENCE_RE.match(fence_line[fence_indent:])
        if match:
            prefix, marker, suffix = match.groups()
            in_table = False
            if not fence:
                if marker[0] != "`" or "`" not in suffix:
                    fence = marker
                    fence_indent = len(prefix) if prefix.strip() else 0
            elif (
                not prefix.strip()
                and marker[0] == fence[0]
                and len(marker) >= len(fence)
                and not suffix.strip()
            ):
                fence, fence_indent = "", 0
        elif not fence:
            if "|" not in line or fence_line.startswith("    "):
                in_table = False
            elif (
                not in_table
                and i + 1 < len(lines)
                and not lines[i + 1].expandtabs(4).startswith("    ")
                and _is_table_delimiter(lines[i + 1])
            ):
                # Delimiter-like rows inside this table are ordinary cells.
                in_table = True
                if i > 0 and lines[i - 1].strip():
                    out.append("")
        out.append(line)

    return "\n".join(out)


def dedent_code_blocks(text: str) -> str:
    """
    Remove unnecessary leading indentation before fenced code blocks.

    DingTalk may render code blocks incorrectly if the opening ``` fence
    is indented. This function detects an indented fenced block and
    removes the same indentation from all lines inside that block.
    """
    pattern = r"^([ \t]*)(```[^\n]*\n.*?\n```)[ \t]*$"

    def _dedent(m: re.Match) -> str:
        indent = m.group(1)
        block = m.group(2)
        if not indent:
            return block

        n = len(indent)
        lines = block.split("\n")
        new_lines = []
        for ln in lines:
            if ln.startswith(indent):
                new_lines.append(ln[n:])
            else:
                new_lines.append(ln)
        return "\n".join(new_lines)

    return re.sub(pattern, _dedent, text, flags=re.MULTILINE | re.DOTALL)


def format_code_blocks(text: str, prefix: str = "·") -> str:
    """
    Prefix each non-empty line inside fenced code blocks with a marker.

    This is sometimes used as a workaround when DingTalk's Markdown parser
    behaves unexpectedly with certain code content.
    """
    pattern = r"```([^\n]*)\n(.*?)\n```"

    def _replace(m: re.Match) -> str:
        lang = m.group(1).strip()
        code = m.group(2)

        prefixed = []
        for ln in code.split("\n"):
            prefixed.append(f"{prefix}{ln}" if ln.strip() else ln)

        fence = f"```{lang}".rstrip()
        return fence + "\n" + "\n".join(prefixed) + "\n```"

    return re.sub(pattern, _replace, text, flags=re.DOTALL)


def normalize_dingtalk_markdown(
    text: str,
    code_prefix: str | None = None,
) -> str:
    """
    Apply DingTalk Markdown normalization steps:
    1) Ensure blank lines before numbered list items
    2) Ensure blank lines before pipe tables
    3) Dedent fenced code blocks
    4) Optionally prefix code lines inside fenced blocks
    """
    text = ensure_list_spacing(text)
    text = ensure_table_spacing(text)
    text = dedent_code_blocks(text)
    if code_prefix is not None:
        text = format_code_blocks(text, prefix=code_prefix)
    return text
