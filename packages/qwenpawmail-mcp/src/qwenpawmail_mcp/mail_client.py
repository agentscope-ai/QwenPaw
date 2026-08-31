# -*- coding: utf-8 -*-
"""Core IMAP/SMTP logic for NetEase (163/126/yeah.net) and QQ mailboxes.

This module deliberately does NOT import anything from the ``mcp`` package so
it can be unit-tested (and reused) independently of the MCP server layer.

Connection strategy: every operation opens a fresh connection and closes it in
``try/finally`` to avoid NetEase server-side state / concurrency issues.
"""

from __future__ import annotations

import base64
import email
import email.utils
import imaplib
import os
import re
import smtplib
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Iterator

from imap_tools import imap_utf7
from imap_tools.message import MailMessage

from .config import CLIENT_NAME, CLIENT_VENDOR, CLIENT_VERSION, Config
from .errors import (
    AuthError,
    CapabilityError,
    MailError,
    PermanentSendError,
    RateLimitError,
    UnsafeLoginError,
)
from .imap_ops import (
    check_response as _check,
    encode_folder,
    ensure_folder,
    move_message as move_message_on_connection,
    uid_expunge,
)

# Register the RFC 2971 ID command so imaplib accepts it
# in AUTH/SELECTED state.
imaplib.Commands["ID"] = ("AUTH", "SELECTED")

ID_COMMAND_ARGS = (  # noqa: E501
    f'("name" "{CLIENT_NAME}" "version" "{CLIENT_VERSION}"'
    f' "vendor" "{CLIENT_VENDOR}")'
)

#: Env vars injected by qwenpaw into the MCP stdio subprocess.
WORKSPACE_DIR_ENV = "QWENPAWMAIL_WORKSPACE_DIR"
STATE_DIR_ENV = "QWENPAWMAIL_STATE_DIR"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def resolve_attachments_base(
    email_address: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve the base directory that confines attachment saves.

    The MCP stdio subprocess inherits its CWD from the qwenpaw backend
    (the source repo root), so relative save paths must NOT be resolved
    against the CWD.  Priority:

    1. QWENPAWMAIL_WORKSPACE_DIR - agent workspace root (newer cards);
    2. parent of QWENPAWMAIL_STATE_DIR - STATE_DIR points at
       <workspace>/mail_state, so its parent is the workspace root
       (works for existing driver cards without regeneration);
    3. ~/.qwenpawmail-mcp/state/<email>/attachments - default, matching
       the thread-store state directory convention.
    """
    env = dict(os.environ) if env is None else env
    raw = (env.get(WORKSPACE_DIR_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    raw = (env.get(STATE_DIR_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().parent
    safe = re.sub(r"[^A-Za-z0-9@._+-]", "_", email_address or "default")
    return Path.home() / ".qwenpawmail-mcp" / "state" / safe / "attachments"


def resolve_save_path(save_path: str, base: Path) -> Path:
    """Resolve *save_path* against *base* and reject any escape from it.

    Relative paths are interpreted relative to *base*.  Absolute paths are
    accepted only when they fall inside *base*.  ``..`` traversal (and
    symlink tricks, via realpath) escaping *base* is rejected.
    """
    base_real = base.expanduser().resolve()
    candidate = Path(save_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_real / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base_real):
        raise MailError(
            f"save_path {save_path!r} resolves to '{resolved}', which is "
            f"outside the allowed workspace directory '{base_real}'. "
            "Attachments can only be saved inside the agent workspace: pass "
            "a relative path (e.g. 'finance/attachments/') or an absolute "
            "path under the workspace.",
        )
    return resolved


def decode_mime_header(value: str | bytes | None) -> str:
    """Decode an RFC 2047 encoded header (e.g. Chinese Subject/From) to str."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def decode_folder(raw: str | bytes) -> str:
    """Decode an IMAP modified UTF-7 folder name to a readable str."""
    if isinstance(raw, str):
        raw = raw.encode("ascii", errors="replace")
    return imap_utf7.utf7_decode(raw)


# Layered, provider-agnostic SMTP error classification: rules are matched in
# order. Provider-specific diagnostic prefixes (NetEase MI:STC etc.) come
# first, then standard SMTP reply-code rules (QQ Mail and other providers).
# Each rule: (predicate(code, upper_text), error class, actionable advice).
_SMTP_RULES: tuple[
    tuple[Callable[[int, str], bool], type[MailError], str],
    ...,
] = (
    # -- NetEase-specific diagnostic prefixes -----------------------------
    (
        lambda code, text: code == 554
        and ("MI:STC" in text or "HL:IHU" in text),
        RateLimitError,
        "temporary sending limit or IP/account flagged. This is usually a "
        "daily quota or temporary blacklist. Wait a few hours (or until the "
        "next day) and retry; reduce sending frequency.",
    ),
    (
        lambda code, text: code == 451 and "MI:SFQ" in text,
        RateLimitError,
        "sending frequency limit reached. The server throttles per 15-minute "
        "window. Wait 15+ minutes and retry.",
    ),
    (
        lambda code, text: code == 550 and "DT:SPM" in text,
        PermanentSendError,
        "message rejected as spam-like. Review the subject/body content, "
        "avoid promotional wording and mass identical messages, then send a "
        "revised message.",
    ),
    # -- standard SMTP reply codes ----------------------------------------
    (
        lambda code, text: "AUTH" in text
        and ("FAIL" in text or "INVALID" in text),
        AuthError,
        "authentication failed. Verify QWENPAWMAIL_AUTH_CODE is the correct "
        "credential for your provider (authorization code / app-specific "
        "password / login password); regenerate it in your provider's webmail "
        "settings and confirm SMTP service is enabled.",
    ),
    (
        lambda code, text: code in (421, 450, 451, 452),
        RateLimitError,
        "temporary failure or throttling. Wait a while (15+ minutes is a safe "
        "default) and retry; reduce sending frequency.",
    ),
    (
        lambda code, text: code in (550, 554)
        and any(k in text for k in ("SPAM", "CONTENT", "REJECT")),
        PermanentSendError,
        "message permanently rejected. Review the subject/body content and "
        "recipients, then send a revised message.",
    ),
    (
        lambda code, text: code == 554,
        RateLimitError,
        "message refused, likely a temporary restriction. Wait and retry, or "
        "check your provider's webmail for notices.",
    ),
)


def classify_smtp_error(code: int, message: str) -> MailError:
    """Map SMTP reply codes to actionable, user-readable errors.

    Provider-agnostic: NetEase diagnostic prefixes are matched first, then
    standard SMTP reply-code rules used by QQ Mail and other providers.
    """
    text = message.upper()
    for predicate, err_cls, advice in _SMTP_RULES:
        if predicate(code, text):
            return err_cls(f"SMTP {code}: {advice} ({message})")
    return MailError(f"SMTP {code}: {message}")


def _map_imap_login_error(exc: Exception) -> MailError:
    text = str(exc)
    lowered = text.lower()
    if "unsafe login" in lowered:
        return UnsafeLoginError(
            f"NetEase rejected the login as 'Unsafe Login' ({text}). The RFC "
            "2971 ID command was not accepted before SELECT. Make sure IMAP "
            "is enabled for this account in NetEase webmail settings.",
        )
    if any(
        k in lowered
        for k in (
            "authenticat",
            "login fail",
            "password",
            "invalid credentials",
        )
    ):
        return AuthError(
            f"IMAP authentication failed ({text}). Verify QWENPAWMAIL_EMAIL "
            "and QWENPAWMAIL_AUTH_CODE. Depending on your provider, "
            "the credential may be an authorization code, an "
            "app-specific password, or your login password. Please "
            "confirm IMAP/SMTP service is enabled in your "
            "provider's webmail settings and regenerate the "
            "credential if needed.",
        )
    return MailError(f"IMAP login error: {text}")


def _imap_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to the IMAP date format DD-Mon-YYYY."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return f"{dt.day:02d}-{months[dt.month - 1]}-{dt.year}"


def _escape_imap_string(value: str) -> str:
    """Escape backslashes and double quotes for an IMAP quoted string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def read_uidvalidity(conn: imaplib.IMAP4_SSL) -> int | None:
    """Return the UIDVALIDITY of the currently selected folder.

    Must be called right after SELECT. Returns None when the server did
    not report UIDVALIDITY or the value cannot be parsed.
    """
    try:
        _typ, data = conn.response("UIDVALIDITY")
    except (imaplib.IMAP4.error, OSError, AttributeError):
        return None
    if not data or data[0] is None:
        return None
    raw = data[0]
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


_FETCH_META_RE = {
    "uid": re.compile(rb"UID (\d+)"),
    "size": re.compile(rb"RFC822\.SIZE (\d+)"),
    "flags": re.compile(rb"FLAGS \(([^)]*)\)"),
}


def _iter_fetch_items(data: list[Any]) -> Iterator[tuple[bytes, bytes]]:
    """Yield (meta, payload) pairs from an imaplib FETCH response."""
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            meta = (
                item[0]
                if isinstance(item[0], bytes)
                else bytes(str(item[0]), "ascii")
            )
            payload = item[1] if isinstance(item[1], bytes) else b""
            yield meta, payload


class MailClient:
    """Stateless mail client: one fresh IMAP/SMTP connection per operation."""

    # Class-level connection throttle: track last connect time per IMAP host.
    _last_connect_time: dict[str, float] = {}
    _throttle_lock = threading.Lock()
    _THROTTLE_INTERVAL = 0.5  # seconds between connections to the same host

    def __init__(self, config: Config) -> None:
        self.config = config

    # -- connection management ---------------------------------------------

    def _throttle(self) -> None:
        """Ensure at least _THROTTLE_INTERVAL seconds
        between connections to the same IMAP host."""
        host = self.config.imap_host
        with self._throttle_lock:
            now = time.monotonic()
            last = self._last_connect_time.get(host, 0.0)
            wait = self._THROTTLE_INTERVAL - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_connect_time[host] = time.monotonic()

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        """Connect, login and (for NetEase) send the RFC 2971 ID command.

        The ID command MUST be sent after LOGIN and before any SELECT,
        otherwise NetEase replies 'Unsafe Login'.
        """
        self._throttle()
        conn = imaplib.IMAP4_SSL(
            self.config.imap_host,
            self.config.imap_port,
            timeout=30,
        )
        try:
            try:
                conn.login(self.config.email, self.config.auth_code)
            except imaplib.IMAP4.error as exc:
                raise _map_imap_login_error(exc) from exc
            if self.config.requires_id_command:
                # pylint: disable-next=protected-access
                conn._simple_command("ID", ID_COMMAND_ARGS)
        except BaseException:
            try:
                conn.shutdown()
            except Exception:
                pass
            raise
        return conn

    @contextmanager
    def _imap(self) -> Iterator[imaplib.IMAP4_SSL]:
        conn = self._imap_connect()
        try:
            yield conn
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _select(
        self,
        conn: imaplib.IMAP4_SSL,
        folder: str,
        readonly: bool = False,
    ) -> int:
        typ, data = conn.select(encode_folder(folder), readonly=readonly)
        if typ != "OK":
            raw_detail = data[0] if data else b""
            detail = (
                raw_detail.decode("utf-8", errors="replace")
                if isinstance(raw_detail, bytes)
                else str(raw_detail)
            )
            if "unsafe login" in detail.lower():
                raise UnsafeLoginError(
                    f"NetEase 'Unsafe Login' on SELECT ({detail}). The ID "
                    "command was rejected or IMAP access is not enabled for "
                    "this account. Enable IMAP in NetEase webmail settings.",
                )
            raise MailError(
                f"Cannot open folder {folder!r}: {detail}. "
                "Use list_folders to see available folder names.",
            )
        try:
            return int(data[0] or 0)
        except (TypeError, ValueError, IndexError):
            return 0

    @contextmanager
    def _smtp(self) -> Iterator[smtplib.SMTP_SSL]:
        try:
            conn = smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=30,
            )
        except OSError as exc:
            raise MailError(f"Cannot connect to SMTP server: {exc}") from exc
        try:
            try:
                conn.login(self.config.email, self.config.auth_code)
            except smtplib.SMTPAuthenticationError as exc:
                raise AuthError(
                    f"SMTP authentication failed ({exc.smtp_code} "
                    f"{exc.smtp_error!r}). Depending on your provider, the "
                    "credential may be an authorization code, an app-specific "
                    "password, or your login password. Please confirm SMTP "
                    "service is enabled in your provider's webmail settings "
                    "and regenerate the credential if needed.",
                ) from exc
            yield conn
        finally:
            try:
                conn.quit()
            except Exception:
                pass

    def _smtp_send(self, msg: EmailMessage, recipients: list[str]) -> None:
        with self._smtp() as conn:
            try:
                conn.send_message(
                    msg,
                    from_addr=self.config.email,
                    to_addrs=recipients,
                )
            except smtplib.SMTPRecipientsRefused as exc:
                first = next(iter(exc.recipients.values()))
                code, raw = first[0], first[1]
                detail = (
                    raw.decode("utf-8", errors="replace")
                    if isinstance(raw, bytes)
                    else raw
                )
                raise classify_smtp_error(code, detail) from exc
            except smtplib.SMTPResponseException as exc:
                raw_err = exc.smtp_error
                detail = (
                    raw_err.decode("utf-8", errors="replace")
                    if isinstance(raw_err, bytes)
                    else raw_err
                )
                raise classify_smtp_error(exc.smtp_code, detail) from exc

    # -- folder operations ---------------------------------------------------

    def list_folders(self) -> list[dict[str, Any]]:
        with self._imap() as conn:
            typ, data = conn.list()
            _check(typ, data, "LIST")
            folders: list[dict[str, Any]] = []
            for item in data or []:
                if not item:
                    continue
                # pylint: disable-next=unsubscriptable-object
                raw_line = item[0] if isinstance(item, tuple) else item
                text = (
                    raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes)
                    else str(raw_line)
                )
                m = re.match(
                    r"\((?P<flags>[^)]*)"
                    r'\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)',
                    text,
                )
                if not m:
                    continue
                raw_name = m.group("name").strip().strip('"')
                folders.append(
                    {
                        "name": decode_folder(raw_name),
                        "raw_name": raw_name,
                        "flags": m.group("flags").split(),
                    },
                )
            return folders

    def create_folder(self, name: str) -> dict[str, Any]:
        with self._imap() as conn:
            result = ensure_folder(conn, name)
            return {
                "created": name,
                "already_exists": result["already_exists"],
            }

    # -- message listing / reading -------------------------------------------

    def list_messages(
        self,
        folder: str = "INBOX",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return envelope metadata only (no bodies), newest first."""
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            typ, data = conn.uid("SEARCH", "ALL")
            _check(typ, data, "SEARCH")
            uids = (data[0] or b"").split()
            uids.reverse()  # newest first
            total = len(uids)
            page = uids[offset : offset + limit]
            messages = [self._fetch_envelope(conn, uid) for uid in page]
            return {
                "folder": folder,
                "total": total,
                "offset": offset,
                "limit": limit,
                "messages": messages,
            }

    _ENVELOPE_FIELDS = "FROM TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES"

    def _fetch_envelope(
        self,
        conn: imaplib.IMAP4_SSL,
        uid: bytes,
        with_structure: bool = False,
    ) -> dict[str, Any]:
        items = (
            "UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS"
            f" ({self._ENVELOPE_FIELDS})]"
        )
        if with_structure:
            items += " BODYSTRUCTURE"
        typ, data = conn.uid("FETCH", uid.decode("ascii"), f"({items})")
        _check(typ, data, "FETCH envelope")
        meta = b""
        header_bytes = b""
        for m, payload in _iter_fetch_items(data or []):
            meta, header_bytes = m, payload
            break
        headers = email.message_from_bytes(header_bytes)
        flags_m = _FETCH_META_RE["flags"].search(meta)
        size_m = _FETCH_META_RE["size"].search(meta)
        flags = (
            flags_m.group(1).decode("ascii", errors="replace").split()
            if flags_m
            else []
        )
        result = {
            "uid": uid.decode("ascii", errors="replace"),
            "subject": decode_mime_header(headers.get("Subject")),
            "from": decode_mime_header(headers.get("From")),
            "to": decode_mime_header(headers.get("To")),
            "date": headers.get("Date", ""),
            "message_id": (headers.get("Message-ID") or "").strip(),
            "in_reply_to": (headers.get("In-Reply-To") or "").strip(),
            "references": (headers.get("References") or "").strip(),
            "size": int(size_m.group(1)) if size_m else None,
            "flags": flags,
            "seen": "\\Seen" in flags,
            "flagged": "\\Flagged" in flags,
        }
        if with_structure:
            # Heuristic: BODYSTRUCTURE mentioning attachment/filename params.
            blob = b" ".join(
                part
                for part in (
                    [meta] + [p for p in (data or []) if isinstance(p, bytes)]
                )
            ).upper()
            result["has_attachment"] = (
                b"ATTACHMENT" in blob or b"FILENAME" in blob
            )
        return result

    def _fetch_raw(self, conn: imaplib.IMAP4_SSL, uid: str) -> bytes:
        typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        _check(typ, data, "FETCH body")
        for _, payload in _iter_fetch_items(data or []):
            if payload:
                return payload
        raise MailError(
            f"Message UID {uid} not found. It may have been moved or deleted; "
            "run list_messages to refresh UIDs.",
        )

    def get_message(self, folder: str, uid: str) -> dict[str, Any]:
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            raw = self._fetch_raw(conn, uid)
            msg = MailMessage.from_bytes(raw)
            attachments = [
                {
                    "index": i,
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "size": len(att.payload or b""),
                }
                for i, att in enumerate(msg.attachments)
            ]
            return {
                "uid": uid,
                "folder": folder,
                "subject": msg.subject,
                "from": msg.from_,
                "to": list(msg.to),
                "cc": list(msg.cc),
                "date": msg.date_str,
                "message_id": msg.headers.get("message-id", ("",))[0].strip(),
                "text": msg.text,
                "html": msg.html,
                "attachments": attachments,
            }

    def get_attachment(
        self,
        folder: str,
        uid: str,
        attachment: str | int,
        save_path: str | None = None,
    ) -> dict[str, Any]:
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            raw = self._fetch_raw(conn, uid)
            msg = MailMessage.from_bytes(raw)
            atts = list(msg.attachments)
            target = None
            if isinstance(attachment, int) or (
                isinstance(attachment, str) and attachment.isdigit()
            ):
                idx = int(attachment)
                if 0 <= idx < len(atts):
                    target = atts[idx]
            else:
                for att in atts:
                    if att.filename == attachment:
                        target = att
                        break
            if target is None:
                names = [a.filename for a in atts]
                raise MailError(
                    f"Attachment {attachment!r} not found in "
                    f"message UID {uid}. "
                    f"Available attachments: {names}.",
                )
            payload = target.payload or b""
            result: dict[str, Any] = {
                "filename": target.filename,
                "content_type": target.content_type,
                "size": len(payload),
            }
            if save_path:
                base = resolve_attachments_base(self.config.email)
                # A trailing separator means "directory" even if it does
                # not exist yet (it is auto-created below).
                treat_as_dir = str(save_path).rstrip().endswith(("/", os.sep))
                path = resolve_save_path(str(save_path), base)
                if path.is_dir() or treat_as_dir:
                    # basename() guards against path traversal in hostile
                    # attachment names like "../../.ssh/authorized_keys".
                    safe_name = (
                        os.path.basename(target.filename or "")
                        or f"attachment-{uid}"
                    )
                    path = path / safe_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                # Absolute path so the agent can reference it in ledgers.
                result["saved_to"] = str(path)
            else:
                result["content_base64"] = base64.b64encode(payload).decode(
                    "ascii",
                )
            return result

    def search_messages(
        self,
        folder: str = "INBOX",
        keyword: str | None = None,
        from_address: str | None = None,
        since: str | None = None,
        before: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        caps = self.config.capabilities
        provider_name = self.config.email.rpartition("@")[2]
        if keyword and not caps.search_text:
            raise CapabilityError(
                operation="search_messages(keyword)",
                provider_name=provider_name,
                alternatives=[
                    "Narrow the date range with since/before, then browse "
                    "with `list_messages`",
                    "Perform a full-text search in webmail",
                ],
            )
        if from_address and not caps.search_from:
            raise CapabilityError(
                operation="search_messages(from_address)",
                provider_name=provider_name,
                alternatives=[
                    "Fetch messages with `list_messages`, then filter locally "
                    "by sender",
                    "Search by date with since/before",
                ],
            )
        criteria: list[str] = []
        literal: bytes | None = None
        if keyword:
            if keyword.isascii():
                criteria += ["TEXT", f'"{_escape_imap_string(keyword)}"']
            else:
                literal = keyword.encode("utf-8")
                criteria += ["TEXT"]
        if from_address:
            if not from_address.isascii():
                raise MailError(
                    "Non-ASCII from_address is not supported; use the ASCII "
                    "email address instead of a display name.",
                )
            criteria += ["FROM", f'"{_escape_imap_string(from_address)}"']
        if since:
            criteria += ["SINCE", _imap_date(since)]
        if before:
            criteria += ["BEFORE", _imap_date(before)]
        if not criteria:
            criteria = ["ALL"]
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            if literal is not None:
                conn.literal = literal
                typ, data = conn.uid("SEARCH", "CHARSET", "UTF-8", *criteria)
            else:
                typ, data = conn.uid("SEARCH", *criteria)
            _check(typ, data, "SEARCH")
            uids = (data[0] or b"").split()
            uids.reverse()
            matched = len(uids)
            messages = [
                self._fetch_envelope(conn, uid) for uid in uids[:limit]
            ]
            return {"folder": folder, "matched": matched, "messages": messages}

    # -- thread / stats support ----------------------------------------

    def fetch_envelopes_after(
        self,
        folder: str,
        last_seen_uid: int | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Fetch envelopes for incremental thread sync.

        With *last_seen_uid* only strictly newer UIDs are fetched. Otherwise
        an initial scan bounded by *since* (YYYY-MM-DD) and *limit* (newest
        first, but returned oldest-first) is performed.

        Returns ``(envelopes, uidvalidity)``. *uidvalidity* is the folder's
        UIDVALIDITY reported at SELECT time (None when unavailable). Callers
        persisting UID state must discard it when UIDVALIDITY changes: after
        a folder rebuild/migration new UIDs restart from small values and a
        ``UID last+1:*`` window would silently miss all new mail forever.
        """
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            uidvalidity = read_uidvalidity(conn)
            if last_seen_uid is not None:
                typ, data = conn.uid(
                    "SEARCH",
                    "UID",
                    f"{last_seen_uid + 1}:*",
                )
            elif since:
                typ, data = conn.uid(
                    "SEARCH",
                    "SINCE",
                    _imap_date(since),
                )
            else:
                typ, data = conn.uid("SEARCH", "ALL")
            _check(typ, data, "SEARCH")
            uids = list((data[0] or b"").split())
            if last_seen_uid is not None:
                # Servers may echo the last existing UID for a n:* range.
                uids = [u for u in uids if int(u) > last_seen_uid]
            uids.sort(key=int)
            if limit is not None and len(uids) > limit:
                # pylint: disable-next=invalid-unary-operand-type
                uids = uids[-limit:]  # keep the newest N, oldest-first order
            envelopes = []
            for uid in uids:
                env = self._fetch_envelope(conn, uid)
                env["folder"] = folder
                envelopes.append(env)
            return envelopes, uidvalidity

    def scan_folder_stats(
        self,
        folder: str,
        since: str,
        max_scan: int = 1000,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Scan a folder for stats: envelopes
        (with attachment flag) since a date.

        Returns (envelopes, truncated). At most *max_scan* newest messages are
        fetched; *truncated* is True when the folder had more matches.
        """
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            typ, data = conn.uid("SEARCH", "SINCE", _imap_date(since))
            _check(typ, data, "SEARCH")
            uids = sorted((data[0] or b"").split(), key=int)
            truncated = len(uids) > max_scan
            if truncated:
                uids = uids[-max_scan:]
            envelopes = []
            for uid in uids:
                env = self._fetch_envelope(conn, uid, with_structure=True)
                env["folder"] = folder
                envelopes.append(env)
            return envelopes, truncated

    # -- sending -----------------------------------------------------------

    def _build_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.config.email
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(
            domain=self.config.email.rpartition("@")[2],
        )
        for key, value in (extra_headers or {}).items():
            msg[key] = value
        msg.set_content(body)
        return msg

    def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        if not to:
            raise MailError("At least one recipient is required in 'to'.")
        msg = self._build_message(to, subject, body, cc=cc)
        recipients = list(to) + list(cc or []) + list(bcc or [])
        self._smtp_send(msg, recipients)
        return {
            "sent": True,
            "to": to,
            "cc": cc or [],
            "bcc": bcc or [],
            "subject": subject,
            "message_id": msg["Message-ID"],
        }

    def reply_message(
        self,
        folder: str,
        uid: str,
        body: str,
    ) -> dict[str, Any]:
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            raw = self._fetch_raw(conn, uid)
        original = email.message_from_bytes(raw)
        orig_id = (original.get("Message-ID") or "").strip()
        orig_refs = (original.get("References") or "").strip()
        reply_to = decode_mime_header(
            original.get("Reply-To") or original.get("From"),
        )
        _, addr = email.utils.parseaddr(reply_to)
        if not addr:
            raise MailError(
                "Cannot determine reply address from the original message.",
            )
        subject = decode_mime_header(original.get("Subject"))
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        headers: dict[str, str] = {}
        if orig_id:
            headers["In-Reply-To"] = orig_id
            headers["References"] = f"{orig_refs} {orig_id}".strip()
        msg = self._build_message([addr], subject, body, extra_headers=headers)
        self._smtp_send(msg, [addr])
        return {
            "sent": True,
            "to": [addr],
            "subject": subject,
            "in_reply_to": orig_id,
            "message_id": msg["Message-ID"],
        }

    def forward_message(
        self,
        folder: str,
        uid: str,
        to: list[str],
        body: str = "",
    ) -> dict[str, Any]:
        if not to:
            raise MailError("At least one recipient is required in 'to'.")
        with self._imap() as conn:
            self._select(conn, folder, readonly=True)
            raw = self._fetch_raw(conn, uid)
        original = email.message_from_bytes(raw)
        subject = decode_mime_header(original.get("Subject"))
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"
        msg = self._build_message(
            to,
            subject,
            body or f"Forwarded message: {subject}",
        )
        msg.add_attachment(
            raw,
            maintype="message",
            subtype="rfc822",
            filename="forwarded-message.eml",
        )
        self._smtp_send(msg, list(to))
        return {
            "sent": True,
            "to": to,
            "subject": subject,
            "message_id": msg["Message-ID"],
        }

    # -- flags / move / delete ---------------------------------------------

    _MARKS = {
        "read": ("+FLAGS", "\\Seen"),
        "unread": ("-FLAGS", "\\Seen"),
        "flagged": ("+FLAGS", "\\Flagged"),
        "unflagged": ("-FLAGS", "\\Flagged"),
    }

    def mark_messages(
        self,
        folder: str,
        uids: list[str],
        mark: str,
    ) -> dict[str, Any]:
        mark = mark.lower()
        if mark not in self._MARKS:
            raise MailError(
                f"Unknown mark {mark!r}. Use one of: {sorted(self._MARKS)}.",
            )
        op, flag = self._MARKS[mark]
        uid_set = ",".join(str(u) for u in uids)
        with self._imap() as conn:
            self._select(conn, folder)
            typ, data = conn.uid("STORE", uid_set, op, f"({flag})")
            _check(typ, data, "STORE")
            return {"folder": folder, "uids": list(uids), "mark": mark}

    def move_message(
        self,
        folder: str,
        uid: str,
        target_folder: str,
    ) -> dict[str, Any]:
        with self._imap() as conn:
            self._select(conn, folder)
            return move_message_on_connection(
                conn,
                source_folder=folder,
                uid=uid,
                target_folder=target_folder,
                capabilities=self.config.capabilities,
                select_folder=self._select,
                provider_name=self.config.email.rpartition("@")[2],
            )

    def delete_message(self, folder: str, uid: str) -> dict[str, Any]:
        with self._imap() as conn:
            self._select(conn, folder)
            typ, data = conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            _check(typ, data, "STORE \\Deleted")
            expunge = uid_expunge(
                conn,
                uid,
                supported=self.config.capabilities.uid_expunge,
            )
            result: dict[str, Any] = {
                "deleted": True,
                "uid": uid,
                "folder": folder,
                "expunged": expunge.expunged,
            }
            if not expunge.expunged:
                if not self.config.capabilities.uid_expunge:
                    result["note"] = (
                        "This provider does not support immediate cleanup "
                        "with UID EXPUNGE. The message was marked "
                        "for deletion and will be cleaned up by the server "
                        "or another client."
                    )
                else:
                    result[
                        "note"
                    ] = "marked \\Deleted; UID EXPUNGE did not complete"
                    if expunge.detail:
                        result["expunge_error"] = expunge.detail
            return result

    # -- diagnostics -------------------------------------------------------

    def check_auth(self) -> dict[str, Any]:
        """Verify both IMAP and SMTP credentials with fresh connections."""
        result: dict[str, Any] = {
            "email": self.config.email,
            "imap_host": self.config.imap_host,
            "smtp_host": self.config.smtp_host,
        }
        with self._imap() as conn:
            self._select(conn, "INBOX", readonly=True)
            result["imap_ok"] = True
        with self._smtp():
            result["smtp_ok"] = True
        return result
