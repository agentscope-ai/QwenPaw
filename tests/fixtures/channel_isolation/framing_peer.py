# -*- coding: utf-8 -*-
"""Small stdio peer used by CH-0-003 cross-platform pipe tests."""

from __future__ import annotations

import sys
import time


def _read_message() -> bytes:
    """Read one strict frame from binary stdin."""
    header = bytearray()
    while not header.endswith(b"\r\n\r\n"):
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            raise EOFError
        header.extend(chunk)
    line = bytes(header[:-4])
    prefix = b"Content-Length: "
    if not line.startswith(prefix):
        raise ValueError("invalid test frame")
    length = int(line[len(prefix) :])
    body = sys.stdin.buffer.read(length)
    if len(body) != length:
        raise EOFError
    return body


def _write_fragmented(body: bytes) -> None:
    """Write one frame across deliberately awkward chunk boundaries."""
    frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    for boundary in (1, 5, 13, len(frame)):
        chunk, frame = frame[:boundary], frame[boundary:]
        if chunk:
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            time.sleep(0.002)
    if frame:
        sys.stdout.buffer.write(frame)
        sys.stdout.buffer.flush()


def main() -> None:
    """Echo two messages or close stdout immediately."""
    if len(sys.argv) == 2 and sys.argv[1] == "close_stdout":
        return
    for _ in range(2):
        _write_fragmented(_read_message())


if __name__ == "__main__":
    main()
