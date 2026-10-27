# -*- coding: utf-8 -*-
"""Lightweight HTML -> Markdown converter built on the stdlib.

Used by ``web_fetch`` to turn fetched pages into readable text for the
model. Fidelity is intentionally modest: links are kept, images and
non-content elements (scripts, styles, ...) are dropped.
"""

import re
from html.parser import HTMLParser


def _tags(names: str) -> frozenset[str]:
    return frozenset(names.split())


# Dropped with their content. HTMLParser, like browsers, reads these as
# raw text, so no tags can nest inside them.
_SKIP = _tags("script style title iframe")
_BLOCK = _tags(
    "p div section article main header footer nav aside form figure "
    "figcaption details summary dl dt dd table caption pre blockquote",
)
_INLINE = {
    "strong": "**",
    "b": "**",
    "em": "*",
    "i": "*",
    "del": "~~",
    "s": "~~",
    "strike": "~~",
    "code": "`",
}
# tag -> (markup on open, markup on close). Leading/trailing "\n"s are
# line breaks requested around the markup text (see _emit).
_MARKUP = {
    **{t: ("\n\n", "\n\n") for t in _BLOCK},
    **{f"h{n}": ("\n\n" + "#" * n + " ", "\n\n") for n in range(1, 7)},
    "hr": ("\n\n---\n\n", ""),
    "tr": ("\n|", ""),
    "td": (" ", ""),
    "th": (" ", ""),
    "option": ("\n", ""),
}
# Elements whose rendered content is captured and wrapped on close.
_CAPTURE = {"a", "pre", "blockquote", *_INLINE}
_FAKE_LINK_PREFIXES = ("#", "javascript:", "vbscript:", "data:")
# Characters that would end a Markdown link destination early.
_LINK_ESCAPES = str.maketrans({"(": "\\(", ")": "\\)", " ": "%20"})


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip: str | None = None
        self.pre = 0
        # One entry per open <table>: whether a cell is open in it. Line
        # breaks become spaces inside cells.
        self.tables: list[bool] = []
        # Line breaks owed before the next text. Written lazily, so empty
        # elements leave no blank lines behind.
        self.newlines = 0
        # One entry per open ul/ol: None for ul, item counter for ol.
        self.lists: list[int | None] = []
        # An <li> started; its marker is written along with its first
        # text, so items without text vanish.
        self.item_pending = False
        # (tag, start index in self.out, href) for open _CAPTURE tags.
        self.marks: list[tuple[str, int, str | None]] = []

    def handle_starttag(self, tag, attrs):
        if self.skip:
            return
        if tag in _SKIP:
            self.skip = tag
            return
        if tag in ("tr", "td", "th"):
            self._end_cell()  # </td> and </th> are optional in HTML.
        if tag in _MARKUP:
            self._emit(_MARKUP[tag][0])
        if tag in _CAPTURE:
            self.pre += tag == "pre"
            self.marks.append((tag, len(self.out), dict(attrs).get("href")))
        elif tag in ("ul", "ol"):
            self._newline(1 if self.lists else 2)
            self.lists.append(_ol_counter(attrs) if tag == "ol" else None)
        elif tag == "li":
            self._newline(1)
            self.item_pending = True
        elif tag == "br":
            # Unlike block breaks, consecutive <br>s add up.
            self.newlines = min(self.newlines + 1, 2)
        elif tag == "table":
            self.tables.append(False)
        elif tag in ("td", "th") and self.tables:
            self.tables[-1] = True

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip:
                self.skip = None
            return
        if any(mark[0] == tag for mark in self.marks):
            # Also closes anything left open inside it (bad nesting).
            while self._close_mark() != tag:
                pass
        if tag in ("tr", "td", "th", "table"):
            self._end_cell()
        if tag == "table" and self.tables:
            self.tables.pop()
        if tag in _MARKUP:
            self._emit(_MARKUP[tag][1])
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self._newline(1 if self.lists else 2)
            self.item_pending = False
        elif tag == "li":
            self.item_pending = False

    def handle_data(self, data):
        if self.skip:
            return
        if not self.pre:
            data = re.sub(r"\s+", " ", data)
            at_line_start = (
                self.newlines
                or self.item_pending
                or not self.out
                or self.out[-1].endswith((" ", "\n"))
            )
            if at_line_start:
                data = data.lstrip()
        self._write(data)

    def _newline(self, count):
        self.newlines = max(self.newlines, count)

    def _emit(self, markup):
        text = markup.strip("\n")
        self._newline(len(markup) - len(markup.lstrip("\n")))
        self._write(text)
        self._newline(len(markup) - len(markup.rstrip("\n")))

    def _write(self, text):
        if not text:
            return
        prefix = ""
        if self.newlines and self.out:
            self.out[-1] = self.out[-1].rstrip(" ")
            if not self._in_cell():
                prefix = "\n" * self.newlines
            elif not text[0].isspace():
                prefix = " "  # Keep the cell's paragraphs on its row.
        if self.item_pending:
            prefix += self._list_marker()
        self.newlines, self.item_pending = 0, False
        if prefix:
            # Line breaks and markers go outside captures that have not
            # received any text yet, so wrapping doesn't swallow them.
            n = len(self.out)
            self.marks = [(t, s + (s == n), h) for t, s, h in self.marks]
            self.out.append(prefix)
        self.out.append(text)

    def _in_cell(self) -> bool:
        return bool(self.tables) and self.tables[-1]

    def _end_cell(self):
        if self._in_cell():
            self._write(" |")  # Written while still in the cell.
            self.tables[-1] = False

    def _list_marker(self) -> str:
        indent = "  " * (len(self.lists) - 1)
        if self.lists and self.lists[-1] is not None:
            self.lists[-1] += 1
            return f"{indent}{self.lists[-1]}. "
        return f"{indent}* "

    def _close_mark(self) -> str:
        tag, start, href = self.marks.pop()
        text = "".join(self.out[start:])
        del self.out[start:]
        if tag == "pre":
            self.pre -= 1
            code = text.strip("\n")
            fence = _fence(code, 3)
            text = f"{fence}\n{code}\n{fence}" if code else ""
        elif not self.pre:  # Markup inside <pre> would corrupt the code.
            text = _wrap(tag, href, text)
        self.out.append(text)
        return tag

    def result(self) -> str:
        while self.marks:
            self._close_mark()
        return "".join(self.out).strip()


def _wrap(tag: str, href: str | None, text: str) -> str:
    """Render the captured *text* of a ``_CAPTURE`` element."""
    core = text.strip()
    if not core:
        return text
    # Keep surrounding spaces outside: "<b> x </b>" -> " **x** ".
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    if tag == "blockquote":
        core = "\n".join(f"> {line}".rstrip() for line in core.split("\n"))
    elif "```" in core:
        pass  # Don't wrap code blocks in links or emphasis.
    elif tag in _INLINE:
        mark = _INLINE[tag]
        if tag == "code":
            mark = _fence(core, 1)
            if len(mark) > 1:
                core = f" {core} "  # So edge backticks aren't fused.
        core = f"{mark}{core}{mark}"
    elif href and not href.strip().lower().startswith(_FAKE_LINK_PREFIXES):
        # Card-style links wrap headings/paragraphs; flatten them.
        label = re.sub(r"(?m)^#{1,6} ", "", core)
        label = re.sub(r"\s+", " ", label)
        core = f"[{label}]({href.strip().translate(_LINK_ESCAPES)})"
    return lead + core + trail


def _fence(code: str, minimum: int) -> str:
    """Backtick fence longer than any backtick run inside *code*."""
    longest = max((len(run) for run in re.findall("`+", code)), default=0)
    return "`" * max(minimum, longest + 1)


def _ol_counter(attrs: list[tuple[str, str | None]]) -> int:
    """Counter before the first item of an <ol>, honoring ``start``."""
    try:
        return int(dict(attrs).get("start") or 1) - 1
    except ValueError:
        return 0


def html_to_markdown(html_content: str) -> str:
    """Convert *html_content* to Markdown (links kept, images dropped)."""
    converter = _Converter()
    converter.feed(html_content)
    converter.close()
    return converter.result()
