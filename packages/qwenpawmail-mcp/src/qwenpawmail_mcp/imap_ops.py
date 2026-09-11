# -*- coding: utf-8 -*-
"""Shared, data-safe IMAP mutation primitives.

Both the standalone MCP client and QwenPaw's long-lived mail monitor mutate
mailboxes.  Keeping the destructive part of those operations here prevents
their fallback and error-handling semantics from drifting apart.
"""

from __future__ import annotations

import base64
import email
import imaplib
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol, cast

from .errors import CapabilityError, MailError

# Connection-level exceptions must be re-raised before the broader
# ``IMAP4.error`` fallbacks.  The explicit handlers make that safety boundary
# visible even though pylint considers them mechanically redundant.
# pylint: disable=try-except-raise


class MoveCapabilities(Protocol):
    """Subset of provider capabilities needed by the move primitive."""

    @property
    def move(self) -> bool:
        ...

    @property
    def copy(self) -> bool:
        ...

    @property
    def uid_expunge(self) -> bool:
        ...

    @property
    def append(self) -> bool:
        ...


SelectFolder = Callable[[imaplib.IMAP4_SSL, str], Any]


@dataclass(frozen=True)
class UidExpungeResult:
    """Outcome of a UID-scoped expunge attempt."""

    attempted: bool
    expunged: bool
    detail: str = ""


def _encode_imap_utf7(name: str) -> bytes:
    """Encode *name* as IMAP modified UTF-7 (RFC 3501 section 5.1.3)."""
    out = bytearray()
    pending: list[str] = []

    def _flush() -> None:
        if not pending:
            return
        encoded = base64.b64encode("".join(pending).encode("utf-16be"))
        out.extend(b"&" + encoded.rstrip(b"=").replace(b"/", b",") + b"-")
        pending.clear()

    for char in name:
        code = ord(char)
        if 0x20 <= code <= 0x7E:
            _flush()
            out.extend(b"&-" if char == "&" else bytes((code,)))
        else:
            pending.append(char)
    _flush()
    return bytes(out)


def encode_folder(name: str) -> str:
    """Quote and modified-UTF-7 encode an IMAP mailbox name."""
    return '"' + _encode_imap_utf7(name).decode("ascii") + '"'


def response_detail(data: Any) -> str:
    """Return a compact, readable detail string from an IMAP response."""
    values = data if isinstance(data, (list, tuple)) else (data,)
    parts: list[str] = []
    for value in values or ():
        if value is None:
            continue
        if isinstance(value, bytes):
            parts.append(value.decode("utf-8", errors="replace"))
        else:
            parts.append(str(value))
    return " ".join(parts).strip()


def check_response(typ: str, data: Any, action: str) -> None:
    """Raise :class:`MailError` unless an IMAP command returned ``OK``."""
    if str(typ).upper() != "OK":
        raise MailError(
            f"IMAP {action} failed: {typ} {response_detail(data)}".rstrip(),
        )


def ensure_folder(
    conn: imaplib.IMAP4_SSL,
    folder: str,
) -> dict[str, Any]:
    """Create *folder* idempotently and prove it is usable on ``NO``.

    Servers commonly answer ``NO [ALREADYEXISTS]`` for an existing mailbox.
    When the diagnostic is localized or non-standard, ``STATUS`` provides a
    non-selecting existence check.  Any unverified CREATE failure is raised;
    callers must not continue with a destructive move.
    """
    if not folder.strip():
        raise MailError("Target folder must not be empty.")
    target = encode_folder(folder)
    try:
        typ, data = conn.create(target)
    except imaplib.IMAP4.abort:
        raise
    except (ConnectionError, OSError):
        raise
    except imaplib.IMAP4.error as exc:
        typ, data = "NO", [str(exc)]
    if str(typ).upper() == "OK":
        return {"folder": folder, "created": True, "already_exists": False}

    detail = response_detail(data)
    if "exist" in detail.casefold():
        return {"folder": folder, "created": False, "already_exists": True}

    # CREATE error text is not standardized.  Verify an existing target with
    # STATUS without changing the selected source mailbox.
    try:
        status_typ, _ = conn.status(target, "(MESSAGES)")
    except imaplib.IMAP4.abort:
        raise
    except (ConnectionError, OSError):
        raise
    except (AttributeError, imaplib.IMAP4.error):
        status_typ = "NO"
    if str(status_typ).upper() == "OK":
        return {"folder": folder, "created": False, "already_exists": True}

    check_response(typ, data, f"CREATE {folder!r}")
    raise AssertionError("unreachable")


def uid_expunge(
    conn: imaplib.IMAP4_SSL,
    uid: str,
    *,
    supported: bool,
) -> UidExpungeResult:
    """Try RFC 4315 UID EXPUNGE without ever using global EXPUNGE."""
    if not supported:
        return UidExpungeResult(attempted=False, expunged=False)
    try:
        typ, data = conn.uid("EXPUNGE", uid)
    except imaplib.IMAP4.abort:
        raise
    except (ConnectionError, OSError):
        raise
    except imaplib.IMAP4.error as exc:
        return UidExpungeResult(
            attempted=True,
            expunged=False,
            detail=str(exc),
        )
    return UidExpungeResult(
        attempted=True,
        expunged=str(typ).upper() == "OK",
        detail="" if str(typ).upper() == "OK" else response_detail(data),
    )


def _try_uid(
    conn: imaplib.IMAP4_SSL,
    command: str,
    *args: str,
) -> tuple[str, Any]:
    """Run an optional UID command, preserving connection failures."""
    try:
        return cast(tuple[str, Any], conn.uid(command, *args))
    except imaplib.IMAP4.abort:
        raise
    except (ConnectionError, OSError):
        raise
    except imaplib.IMAP4.error as exc:
        return "NO", [str(exc)]


def _fetch_raw(conn: imaplib.IMAP4_SSL, uid: str) -> bytes:
    typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
    check_response(typ, data, "FETCH raw message")
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            payload = item[1]
            if isinstance(payload, bytes) and payload:
                return payload
    raise MailError(
        f"IMAP FETCH raw message returned no payload for UID {uid}",
    )


def _fetch_flags(conn: imaplib.IMAP4_SSL, uid: str) -> str | None:
    """Best-effort original flags for an APPEND fallback."""
    try:
        typ, data = conn.uid("FETCH", uid, "(FLAGS)")
    except imaplib.IMAP4.abort:
        raise
    except (ConnectionError, OSError):
        raise
    except imaplib.IMAP4.error:
        return None
    if str(typ).upper() != "OK":
        return None
    fragments: list[bytes] = []
    for item in data or []:
        if isinstance(item, bytes):
            fragments.append(item)
        elif isinstance(item, tuple) and item and isinstance(item[0], bytes):
            fragments.append(item[0])
    match = re.search(
        r"FLAGS \(([^)]*)\)",
        b" ".join(fragments).decode("ascii", errors="replace"),
    )
    if not match:
        return None
    flags = [
        flag
        for flag in match.group(1).split()
        if flag.casefold() != "\\recent"
    ]
    return f"({' '.join(flags)})" if flags else None


def _escape_imap_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _already_in_target(
    conn: imaplib.IMAP4_SSL,
    *,
    source_folder: str,
    target_folder: str,
    message_id: str,
    select_folder: SelectFolder,
) -> bool:
    """Safely check for an idempotent APPEND retry in the target folder."""
    if not message_id:
        return False
    target_selected = False
    try:
        select_folder(conn, target_folder)
        target_selected = True
        typ, data = conn.uid(
            "SEARCH",
            "HEADER",
            "Message-ID",
            f'"{_escape_imap_string(message_id)}"',
        )
        return str(typ).upper() == "OK" and bool(
            data and data[0] and data[0].split(),
        )
    except imaplib.IMAP4.abort:
        raise
    except (ConnectionError, OSError):
        raise
    except (MailError, imaplib.IMAP4.error):
        return False
    finally:
        # A successful target SELECT must always be undone before STORE.
        # If SELECT target failed, IMAP keeps the previous source selected.
        if target_selected:
            select_folder(conn, source_folder)


def _mark_source_deleted(
    conn: imaplib.IMAP4_SSL,
    uid: str,
    *,
    uid_expunge_supported: bool,
) -> UidExpungeResult:
    typ, data = conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
    check_response(typ, data, "STORE \\Deleted")
    return uid_expunge(
        conn,
        uid,
        supported=uid_expunge_supported,
    )


def _move_result(
    *,
    uid: str,
    source_folder: str,
    target_folder: str,
    via: str,
    expunge: UidExpungeResult | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "moved": True,
        "uid": uid,
        "from": source_folder,
        "to": target_folder,
        "via": via,
    }
    if expunge is None:
        return result
    result.update(
        {
            "source_marked_deleted": True,
            "expunged": expunge.expunged,
        },
    )
    if not expunge.expunged:
        result["cleanup_pending"] = True
        if not expunge.attempted:
            result["note"] = (
                "copied to target and marked \\Deleted in source; the server "
                "does not support UID EXPUNGE, so cleanup is deferred"
            )
        else:
            result["note"] = (
                "copied to target and marked \\Deleted in source; UID "
                "EXPUNGE did not complete, so cleanup is deferred"
            )
            if expunge.detail:
                result["expunge_error"] = expunge.detail
    return result


def move_message(
    conn: imaplib.IMAP4_SSL,
    *,
    source_folder: str,
    uid: str,
    target_folder: str,
    capabilities: MoveCapabilities,
    select_folder: SelectFolder,
    provider_name: str,
    create_target: bool = True,
) -> dict[str, Any]:
    """Move one UID using a shared, data-safe three-level fallback.

    The source is never marked ``\\Deleted`` until MOVE, COPY, or APPEND has
    proved that a target copy exists.  Cleanup is UID-scoped only; this
    function never calls global ``EXPUNGE``.
    """
    # pylint: disable=too-many-branches
    source_folder = source_folder.strip()
    target_folder = target_folder.strip()
    uid = str(uid)
    if not source_folder or not target_folder:
        raise MailError("Source and target folders must not be empty.")
    if source_folder.casefold() == target_folder.casefold():
        raise MailError("Source and target folders must be different.")
    if create_target:
        ensure_folder(conn, target_folder)

    target = encode_folder(target_folder)

    # Level 1: RFC 6851 UID MOVE is atomic from the client's perspective.
    if capabilities.move:
        typ, _data = _try_uid(conn, "MOVE", uid, target)
        if str(typ).upper() == "OK":
            return _move_result(
                uid=uid,
                source_folder=source_folder,
                target_folder=target_folder,
                via="uid_move",
            )

    # Level 2: only mark the source after COPY explicitly succeeded.
    if capabilities.copy:
        typ, _data = _try_uid(conn, "COPY", uid, target)
        if str(typ).upper() == "OK":
            expunge = _mark_source_deleted(
                conn,
                uid,
                uid_expunge_supported=capabilities.uid_expunge,
            )
            return _move_result(
                uid=uid,
                source_folder=source_folder,
                target_folder=target_folder,
                via="uid_copy",
                expunge=expunge,
            )

    # Level 3: RFC 3501 requires APPEND.  This covers providers whose UID
    # MOVE/COPY implementations are absent or deliberately disabled.
    if not capabilities.append:
        raise CapabilityError(
            operation="move_message",
            provider_name=provider_name,
            alternatives=[
                "Use `mark_messages` to mark the message",
                "Move the message manually in webmail",
            ],
        )
    raw = _fetch_raw(conn, uid)
    flags = _fetch_flags(conn, uid)
    try:
        message_id = (
            email.message_from_bytes(raw).get("Message-ID") or ""
        ).strip()
    except Exception:  # header parsing is best-effort
        message_id = ""
    already_in_target = _already_in_target(
        conn,
        source_folder=source_folder,
        target_folder=target_folder,
        message_id=message_id,
        select_folder=select_folder,
    )
    if not already_in_target:
        try:
            typ, _ = cast(Any, conn.append)(target, flags, None, raw)
        except imaplib.IMAP4.abort:
            raise
        except (ConnectionError, OSError):
            raise
        except imaplib.IMAP4.error:
            typ = "NO"
        if str(typ).upper() != "OK":
            raise CapabilityError(
                operation="move_message",
                provider_name=provider_name,
                alternatives=[
                    "Use `mark_messages` to mark the message",
                    "Move the message manually in webmail",
                ],
            )

    # APPEND and duplicate detection may have changed selected state.
    select_folder(conn, source_folder)
    expunge = _mark_source_deleted(
        conn,
        uid,
        uid_expunge_supported=capabilities.uid_expunge,
    )
    return _move_result(
        uid=uid,
        source_folder=source_folder,
        target_folder=target_folder,
        via="fetch_append_delete",
        expunge=expunge,
    )
