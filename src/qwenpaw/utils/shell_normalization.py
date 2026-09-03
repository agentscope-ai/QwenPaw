# -*- coding: utf-8 -*-
"""Normalization shared by shell security checks and execution."""
from __future__ import annotations


def normalize_posix_line_continuations(command: str) -> str:
    r"""Remove POSIX ``\\`` + newline continuations from *command*.

    POSIX shells remove an unquoted backslash followed by a newline before
    tokenization.  A security check that examines the pre-removal spelling can
    therefore see a different path or command from the one the shell executes.

    Backslash-newline pairs inside single quotes are literal and must remain.
    The pairs are continuations both outside quotes and inside double quotes.
    CRLF is accepted as a continuation as well so callers cannot create the
    same parser differential with JSON/text produced on Windows.
    """
    if "\\\n" not in command and "\\\r\n" not in command:
        return command

    result: list[str] = []
    quote: str | None = None
    index = 0
    length = len(command)

    while index < length:
        char = command[index]

        if quote == "'":
            result.append(char)
            if char == "'":
                quote = None
            index += 1
            continue

        if char == "\\":
            if index + 1 < length and command[index + 1] == "\n":
                index += 2
                continue
            if (
                index + 2 < length
                and command[index + 1] == "\r"
                and command[index + 2] == "\n"
            ):
                index += 3
                continue

            # Preserve the escaped character and prevent an escaped quote from
            # changing the quote state tracked below.
            result.append(char)
            if index + 1 < length:
                result.append(command[index + 1])
                index += 2
            else:
                index += 1
            continue

        result.append(char)
        if char == '"':
            quote = None if quote == '"' else '"'
        elif char == "'" and quote is None:
            quote = "'"
        index += 1

    return "".join(result)
