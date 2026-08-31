# -*- coding: utf-8 -*-
"""Stateful conversion of captured terminal bytes into public text."""

from __future__ import annotations

import codecs

_ESC = 0x1B
_BEL = 0x07
_MAX_PENDING_ESCAPE_BYTES = 4096


class TerminalTextStream:
    """Incrementally decode UTF-8 and remove complete ANSI sequences.

    Capture cursors are byte based and may split both UTF-8 code points and
    terminal escape sequences.  Keeping those two pieces of parser state at
    session scope lets callers concatenate output chunks without corruption.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Start a fresh command text stream."""
        decoder = codecs.getincrementaldecoder("utf-8")
        self._decoder = decoder(errors="replace")
        self._pending_escape = b""
        self._finalized = False

    def discard_pending(self) -> None:
        """Reset parser state after capture eviction breaks continuity."""
        decoder = codecs.getincrementaldecoder("utf-8")
        self._decoder = decoder(errors="replace")
        self._pending_escape = b""

    def feed(self, data: bytes, *, final: bool = False) -> str:
        """Format the next contiguous byte chunk."""
        if self._finalized:
            if data:
                raise RuntimeError("terminal text stream is already final")
            return ""
        visible = self._strip_ansi(self._pending_escape + data, final=final)
        text = self._decoder.decode(visible, final=final)
        if final:
            self._finalized = True
        return text

    def _strip_ansi(self, data: bytes, *, final: bool) -> bytes:
        visible = bytearray()
        self._pending_escape = b""
        index = 0
        while index < len(data):
            escape_at = data.find(b"\x1b", index)
            if escape_at < 0:
                visible.extend(data[index:])
                break
            visible.extend(data[index:escape_at])
            sequence_end = self._sequence_end(data, escape_at)
            if sequence_end is not None:
                index = sequence_end
                continue
            remaining = data[escape_at:]
            if not final and self._could_be_incomplete(remaining):
                if len(remaining) <= _MAX_PENDING_ESCAPE_BYTES:
                    self._pending_escape = remaining
                    break
            # Unknown, malformed, overlong, or final incomplete escapes are
            # ordinary output. Emit ESC and continue parsing the suffix.
            visible.append(_ESC)
            index = escape_at + 1
        return bytes(visible)

    @staticmethod
    def _sequence_end(data: bytes, start: int) -> int | None:
        if start + 1 >= len(data):
            return None
        kind = data[start + 1]
        if kind == ord("["):
            index = start + 2
            while index < len(data) and 0x30 <= data[index] <= 0x3F:
                index += 1
            while index < len(data) and 0x20 <= data[index] <= 0x2F:
                index += 1
            if index < len(data) and 0x40 <= data[index] <= 0x7E:
                return index + 1
            return None
        if kind == ord("]"):
            index = start + 2
            while index < len(data):
                if data[index] == _BEL:
                    return index + 1
                if (
                    data[index] == _ESC
                    and index + 1 < len(data)
                    and data[index + 1] == ord("\\")
                ):
                    return index + 2
                index += 1
        return None

    @staticmethod
    def _could_be_incomplete(data: bytes) -> bool:
        if data == b"\x1b":
            return True
        if len(data) < 2 or data[0] != _ESC:
            return False
        return data[1] in {ord("["), ord("]")}
