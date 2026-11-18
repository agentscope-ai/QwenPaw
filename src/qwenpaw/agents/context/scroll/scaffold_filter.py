# -*- coding: utf-8 -*-
"""Single-pass filter for model-facing scaffolding in assistant text.

Why a scanner and not a set of regexes: the previous implementation paired
``<thinking>…</thinking>`` with ``.*?``, which rescans the remainder of the
text for every candidate opener (quadratic in the number of unclosed tags),
and it could not tell a tag inside a code block from a real one. Both problems
come from trying to recognise Markdown structure with deeply nested patterns.

The scanner tracks Markdown structure as it goes, so literal tags inside
quoted material are preserved. It holds incomplete syntax until it can be
classified and buffers parameter shells until a closing tag confirms them.

The same object also carries state across chunk boundaries and across the text
blocks of one message, which is what the streaming and rendering paths need.
"""

from __future__ import annotations

import re

_REASONING_TAGS = ("thinking", "think", "analysis", "reasoning")
_OPEN_TAGS = tuple(f"<{name}>" for name in _REASONING_TAGS)
_CLOSE_TAGS = tuple(f"</{name}>" for name in _REASONING_TAGS)
_TAG_LITERALS = _OPEN_TAGS + _CLOSE_TAGS

# Framework-injected context notes travel as ordinary assistant text. They are
# hidden the same way reasoning blocks are, but their names are open-ended
# (``system-*``) and their closers may use a different suffix, so they are
# matched with patterns instead of literals.
_SYSTEM_NAME = r"system-[a-z0-9_-]+"
_INJECT_OPEN_RE = re.compile(rf"<({_SYSTEM_NAME})\s*(/?)>", re.IGNORECASE)
_SHORT_INJECT_NAMES = {"notification", "info", "warning", "reminder", "error"}
_INJECT_CLOSE_NAME = "|".join((_SYSTEM_NAME, *sorted(_SHORT_INJECT_NAMES)))
_INJECT_CLOSE_RE = re.compile(rf"</({_INJECT_CLOSE_NAME})\s*>", re.IGNORECASE)
_INJECT_CLOSE_PREFIX_RE = re.compile(
    rf"</(?:{_INJECT_CLOSE_NAME}|system-[a-z0-9_-]*)\s*\Z",
    re.IGNORECASE,
)
_INJECT_OPEN_PREFIX_RE = re.compile(
    r"<system-[a-z0-9_-]*\s*/?\Z",
    re.IGNORECASE,
)
_PARAMETER_OPEN_RE = re.compile(r"<parameter(?:\s[^<>]*)?>", re.IGNORECASE)
_PARAMETER_PREFIX_RE = re.compile(r"<parameter\s[^<>]*\Z", re.IGNORECASE)
_PARAMETER_CLOSE = "</parameter>"
_PARAMETER_CLOSE_RE = re.compile(_PARAMETER_CLOSE, re.IGNORECASE)
_FENCE_CLOSE_TAIL_RE = re.compile(r"[ \t\r]*(?:\n|\Z)")
_TAG_HEADS = _TAG_LITERALS + ("<system-", "<parameter")
_HIDDEN_TAG_HEADS = (
    _TAG_HEADS
    + ("</system-",)
    + tuple(f"</{name}>" for name in sorted(_SHORT_INJECT_NAMES))
)
_MAX_TAG_LEN = max(map(len, _TAG_LITERALS))
_PARAGRAPH_BREAK_RE = re.compile(r"\r?\n[ \t]*\r?\n")


def _match_tag(text: str, index: int, literals: tuple[str, ...]) -> int:
    """Length of the tag literal starting at *index*, or 0."""
    if text[index] != "<":
        return 0
    head = text[index : index + _MAX_TAG_LEN].lower()
    for literal in literals:
        if head.startswith(literal):
            return len(literal)
    return 0


def _is_tag_prefix(text: str, index: int, tags: tuple[str, ...]) -> bool:
    """Check a partial fixed-length tag without slicing the whole suffix."""
    if len(text) - index > max(map(len, tags)):
        return False
    tail = text[index:].lower()
    return any(tag.startswith(tail) for tag in tags)


def _drop_trailing_paragraph(text: str) -> str:
    """Keep everything before the last blank-line separated paragraph."""
    matches = list(_PARAGRAPH_BREAK_RE.finditer(text))
    if not matches:
        return ""
    return text[: matches[-1].start()]


class ScaffoldFilter:
    """Incremental remover for reasoning blocks and tool-call shells.

    ``feed`` may be called with arbitrary fragments (streaming deltas) or with
    whole text blocks; the result is the same as feeding the concatenation once,
    except that text already returned cannot be recalled.
    """

    __slots__ = (
        "hidden_tags",
        "pending",
        "parameter",
        "at_line_start",
        "fence_char",
        "fence_len",
        "line_literal",
        "line_has_text",
        "ticks",
        "unclosed_opens_are_prose",
    )

    def __init__(self, *, unclosed_opens_are_prose: bool = False) -> None:
        self.hidden_tags: list[str] = []
        self.pending = ""
        self.parameter: list[str] | None = None
        self.at_line_start = True
        self.fence_char: str | None = None
        self.fence_len = 0
        self.line_literal = False
        self.line_has_text = False
        self.ticks = 0
        # Whole-text scans can tell that no closing tag exists at all. Prose
        # that merely mentions an opener mid-sentence must then survive.
        self.unclosed_opens_are_prose = unclosed_opens_are_prose

    # -- helpers ---------------------------------------------------------
    def _classify_line(self, text: str, index: int) -> tuple[int, bool]:
        """Return (index after the line prefix, literal-line flag)."""
        length = len(text)
        cursor = index
        spaces = 0
        quoted = False
        while cursor < length and text[cursor] in " \t>":
            if text[cursor] == ">":
                quoted = True
            elif text[cursor] == "\t":
                spaces += 4
            else:
                spaces += 1
            cursor += 1
            if cursor - index > 12:
                break

        if quoted:
            return cursor, True
        if spaces >= 4:
            return cursor, True
        return cursor, False

    # -- public API ------------------------------------------------------
    def feed(self, text: str, *, bare_closes: list[int] | None = None) -> str:
        """Scan a fragment, optionally reporting bare closes in the output."""
        text = self.pending + text
        self.pending = ""
        out: list[str] = []
        segments: list[str] = []
        emitted = 0
        index = 0
        length = len(text)

        while index < length:
            char = text[index]

            # A parameter shell is literal only if it eventually closes.
            if self.parameter is not None:
                match = _PARAMETER_CLOSE_RE.search(text, index)
                if match:
                    self.parameter.append(text[index : match.end()])
                    out.extend(self.parameter)
                    self.parameter = None
                    self.line_has_text = True
                    index = match.end()
                    continue
                start = text.rfind(
                    "<",
                    max(index, length - len(_PARAMETER_CLOSE)),
                )
                if start != -1 and _is_tag_prefix(
                    text,
                    start,
                    (_PARAMETER_CLOSE,),
                ):
                    self.pending = text[start:]
                    length = start
                self.parameter.append(text[index:length])
                break

            # Classify Markdown even inside hidden blocks: a quoted closer
            # is not the end of the hidden block.
            if self.at_line_start:
                if index + 1 >= length and text[index] in " \t>":
                    self.pending = text[index:]
                    break
                cursor, literal = self._classify_line(text, index)
                if cursor == length and cursor > index:
                    self.pending = text[index:]
                    break
                if not literal and cursor < length:
                    marker = text[cursor]
                    if marker in "`~":
                        run = 1
                        while (
                            cursor + run < length
                            and text[cursor + run] == marker
                        ):
                            run += 1
                        if cursor + run == length:
                            self.pending = text[index:]
                            break
                        if run >= 3:
                            if self.fence_char is None:
                                self.fence_char = marker
                                self.fence_len = run
                            elif (
                                marker == self.fence_char
                                and run >= self.fence_len
                                and (
                                    tail := _FENCE_CLOSE_TAIL_RE.match(
                                        text,
                                        cursor + run,
                                    )
                                )
                            ):
                                if text[tail.end() - 1] != "\n":
                                    self.pending = text[index:]
                                    break
                                self.fence_char = None
                                self.fence_len = 0
                            # Both the opening and the closing fence line are
                            # literal; only the closing one clears the state.
                            literal = True
                self.at_line_start = False
                self.line_literal = literal or self.fence_char is not None
                continue

            # 3. Literal contexts: emit verbatim.
            if self.line_literal or self.fence_char is not None:
                if char == "\n":
                    if not self.hidden_tags:
                        out.append(char)
                    index += 1
                    self.at_line_start = True
                    self.line_literal = False
                    self.line_has_text = False
                    continue
                if not self.hidden_tags:
                    out.append(char)
                index += 1
                continue

            # 4. Inline code spans keep their content literal.
            if char == "`":
                run = 1
                while index + run < length and text[index + run] == "`":
                    run += 1
                if index + run == length:
                    self.pending = text[index:]
                    break
                if self.ticks == 0:
                    self.ticks = run
                elif run == self.ticks:
                    self.ticks = 0
                if not self.hidden_tags:
                    out.append(text[index : index + run])
                index += run
                continue
            if self.ticks:
                if not self.hidden_tags:
                    out.append(char)
                index += 1
                continue

            # 5. Tags.
            if char == "<":
                match = _INJECT_OPEN_RE.match(text, index)
                if match:
                    index = match.end()
                    if not match.group(2):
                        self.hidden_tags.append(match.group(1).lower())
                    continue

                size = _match_tag(text, index, _OPEN_TAGS)
                if size and not (
                    not self.hidden_tags
                    and self.unclosed_opens_are_prose
                    and self.line_has_text
                ):
                    self.hidden_tags.append(
                        text[index + 1 : index + size - 1].lower(),
                    )
                    index += size
                    continue

                size = _match_tag(text, index, _CLOSE_TAGS)
                if self.hidden_tags:
                    match = _INJECT_CLOSE_RE.match(text, index)
                    if match or size:
                        end = match.end() if match else index + size
                        name = text[index + 2 : end - 1].strip().lower()
                        if match and name in _SHORT_INJECT_NAMES:
                            name = f"system-{name}"
                        if name == self.hidden_tags[-1]:
                            self.hidden_tags.pop()
                        index = end
                        continue
                    if _is_tag_prefix(text, index, _HIDDEN_TAG_HEADS) or (
                        _INJECT_OPEN_PREFIX_RE.match(text, index)
                        or _INJECT_CLOSE_PREFIX_RE.match(text, index)
                    ):
                        self.pending = text[index:]
                        break
                    index += 1
                    continue

                if size:
                    if bare_closes is not None:
                        segment = "".join(out)
                        emitted += len(segment)
                        segments.append(segment)
                        bare_closes.append(emitted)
                        out.clear()
                    elif text[index + size :].strip():
                        # Reasoning head already dropped upstream: only the
                        # reply after the marker belongs to the user.
                        out.clear()
                    else:
                        kept = _drop_trailing_paragraph("".join(out))
                        out = [kept.rstrip()] if kept.strip() else []
                    index += size
                    continue

                if not self.line_has_text:
                    match = _PARAMETER_OPEN_RE.match(text, index)
                    if match:
                        self.parameter = [match.group()]
                        index = match.end()
                        continue
                    if _PARAMETER_PREFIX_RE.match(text, index):
                        self.pending = text[index:]
                        break

                if _is_tag_prefix(
                    text,
                    index,
                    _TAG_HEADS,
                ) or _INJECT_OPEN_PREFIX_RE.match(text, index):
                    self.pending = text[index:]
                    break

            if not self.hidden_tags:
                out.append(char)
                if char not in " \t\r\n":
                    self.line_has_text = True
            if char == "\n":
                self.at_line_start = True
                self.line_literal = False
                self.line_has_text = False
                self.ticks = 0
            index += 1

        segments.append("".join(out))
        return "".join(segments)

    def flush(self) -> str:
        """Release buffered text when the stream ends."""
        hidden = self.hidden_tags or self.parameter is not None
        visible = "" if hidden else self.pending
        self.pending = ""
        self.parameter = None
        self.hidden_tags.clear()
        self.at_line_start = True
        self.line_literal = False
        self.line_has_text = False
        self.fence_char = None
        self.fence_len = 0
        self.ticks = 0
        return visible


def strip_scaffold_blocks(blocks: list[str]) -> list[str]:
    """Filter a complete message, preserving the order and slots of blocks."""
    if not blocks:
        return []
    lowered = "".join(blocks).lower()
    has_close = any(tag in lowered for tag in _CLOSE_TAGS)
    scanner = ScaffoldFilter(unclosed_opens_are_prose=not has_close)
    visible = []
    offset = 0
    closes: list[int] = []
    for block in blocks:
        local_closes: list[int] = []
        piece = scanner.feed(block, bare_closes=local_closes)
        visible.append(piece)
        closes.extend(offset + pos for pos in local_closes)
        offset += len(piece)
    visible[-1] += scanner.flush()

    cleaned = "".join(visible)
    if not closes and cleaned == "".join(blocks):
        # Don't shift an unchanged Markdown delimiter into another slot.
        return blocks.copy()

    start, end = 0, len(cleaned)
    if closes:
        last = closes[-1]
        if cleaned[last:].strip():
            start = last
        else:
            start = closes[-2] if len(closes) > 1 else 0
            end = start + len(
                _drop_trailing_paragraph(cleaned[start:last]).rstrip(),
            )
    kept = cleaned[start:end]
    start += len(kept) - len(kept.lstrip("\r\n"))
    end = min(end, start + len(kept.strip("\r\n")))

    offset = 0
    for index, piece in enumerate(visible):
        left, right = max(start - offset, 0), max(end - offset, 0)
        visible[index] = piece[left:right]
        offset += len(piece)
    return visible


def strip_scaffold_text(text: str | None) -> str | None:
    """Remove reasoning scaffolding from a complete text block."""
    return strip_scaffold_blocks([text])[0] if text else text


class ScaffoldDeltaState:
    """Cross-chunk, cross-block state for :class:`ScaffoldFilter`."""

    __slots__ = ("filter",)

    def __init__(self) -> None:
        self.filter = ScaffoldFilter()

    def feed(self, text: str) -> str:
        """Run one fragment through the same scanner, keeping its state."""
        return self.filter.feed(text)

    def flush(self) -> str:
        """Release whatever the scanner still holds once the stream ends."""
        return self.filter.flush()

    # Backwards-compatible views used by the SSE helpers.
    @property
    def pending(self) -> str:
        return self.filter.pending

    @property
    def suppressing(self) -> bool:
        return bool(self.filter.hidden_tags)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScaffoldDeltaState):
            return NotImplemented
        return (
            self.filter.pending == other.filter.pending
            and self.filter.hidden_tags == other.filter.hidden_tags
        )


def strip_scaffold_delta(
    text: str,
    *,
    state: ScaffoldDeltaState | None = None,
) -> tuple[str, ScaffoldDeltaState]:
    """Remove one streamed scaffolding fragment and return its state."""
    state = state or ScaffoldDeltaState()
    return state.filter.feed(text), state


def flush_scaffold_delta(state: ScaffoldDeltaState) -> str:
    """Finalize one stream, releasing only an unconfirmed tag prefix."""
    return state.filter.flush()
