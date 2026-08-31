# -*- coding: utf-8 -*-
"""FastMCP server layer: registers 23 tools over the MailClient core.

All exceptions are caught at the tool boundary and re-raised as ToolError so
MCP clients receive an isError result with an actionable message.
"""

from __future__ import annotations

import asyncio
import functools
import json
from datetime import date, timedelta
from typing import Any, Callable, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .config import Config, load_config
from .errors import (
    CapabilityError,
    ConfigError,
    MailError,
    RegistrationError,
)
from .mail_client import MailClient
from .providers import PROVIDERS, REGISTRATION_SUPPORTED_TYPES
from .registration import (
    build_registration_guide,
    generate_alternatives,
    generate_random_username,
    validate_username,
)
from .thread_store import (
    ThreadStore,
    compute_mailbox_stats,
    detect_special_folders,
    resolve_state_dir,
)

F = TypeVar("F", bound=Callable[..., Any])


def coerce_str_list(value: Any) -> list[str]:
    # pylint: disable=too-many-return-statements
    """Leniently normalize LLM-provided input into a list of strings.

    MCP clients (LLMs) frequently serialize array arguments as JSON strings
    (e.g. '["a","b"]') or plain/comma-separated strings. Rules:

    - None / empty        -> []
    - list / tuple        -> items cast to str, stripped, empties dropped
    - JSON-array string   -> parsed via json.loads, then handled as a list
    - comma-separated     -> split on ',' or '\uff0c' (fullwidth), stripped
    - other non-empty str -> single-element list
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        if "," in text or "\uff0c" in text:
            parts = text.replace("\uff0c", ",").split(",")
            return [p.strip() for p in parts if p.strip()]
        return [text]
    return [str(value)]


def coerce_int(value: Any, default: int, lo: int = 1, hi: int = 100) -> int:
    """Leniently coerce LLM-provided value into a bounded integer.

    LLMs often pass numeric arguments as strings (e.g. "20" instead of 20).
    Returns *default* when the value is None or empty-string; raises ToolError
    with a user-friendly message when the value is completely non-numeric.
    """
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"Invalid integer value: {value!r}") from None
    return max(lo, min(result, hi))


def _tool_errors(func: F) -> F:
    """Convert any exception into ToolError so the client sees isError=true.

    Supports both sync and async decorated functions.
    """
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except MailError as exc:
                raise ToolError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - tool boundary
                raise ToolError(
                    f"Unexpected error ({type(exc).__name__}): {exc}",
                ) from exc

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except MailError as exc:
            raise ToolError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - tool boundary
            raise ToolError(
                f"Unexpected error ({type(exc).__name__}): {exc}",
            ) from exc

    return wrapper  # type: ignore[return-value]


def create_server(
    config: Config | None = None,
    client: MailClient | None = None,
) -> FastMCP:
    # pylint: disable=too-many-statements
    """Build the FastMCP server.

    ``client`` can be injected for testing.  When neither *client* nor valid
    credentials are available, the server still starts so that
    ``create_mailbox`` can be used; credential-requiring tools will return a
    friendly error on demand.
    """
    _client_holder: list[MailClient | None] = [client]
    _config_holder: list[Config | None] = [config]
    # Where the current credentials came from: "runtime" / "env" / "none".
    _config_source: list[str] = ["env" if config is not None else "none"]

    def _get_client() -> MailClient:
        client_obj = _client_holder[0]
        if client_obj is None:
            cfg = _config_holder[0]
            if cfg is None:
                try:
                    cfg = load_config()
                except ConfigError as exc:
                    raise ConfigError(
                        str(exc)
                        + "\n\nCredentials are not configured. Ask the user "
                        "for their email address (for example, xxx@163.com or "
                        "xxx@qq.com) and the provider-specific mailbox "
                        "credential, then call set_credentials.",
                    ) from exc
                _config_holder[0] = cfg
                _config_source[0] = "env"
            client_obj = MailClient(cfg)
            _client_holder[0] = client_obj
        return client_obj

    _store_holder: list[ThreadStore | None] = [None]

    def _get_store() -> ThreadStore:
        """Lazily create the ThreadStore (same pattern as _get_client).

        The state directory comes from the QWENPAWMAIL_STATE_DIR environment
        variable (injected by qwenpaw); when missing it falls back to
        ~/.qwenpawmail-mcp/state/<email>/. Directories are auto-created.
        Uses email-namespaced subdirectories to isolate per-mailbox state.
        """
        if _store_holder[0] is None:
            _get_client()  # ensure config is loaded for the email fallback
            cfg = _config_holder[0]
            email_addr = cfg.email if cfg else None
            state_dir = resolve_state_dir(email_addr)
            if email_addr:
                _store_holder[0] = ThreadStore.for_email(state_dir, email_addr)
            else:
                _store_holder[0] = ThreadStore(state_dir)
        store = _store_holder[0]
        assert store is not None
        return store

    # Every thread-management tool performs a multi-step transaction
    # (mailbox sync/search plus one or more ThreadStore operations).  Serialize
    # that whole boundary for this mailbox; ThreadStore also owns a re-entrant
    # lock so direct callers cannot race its in-memory JSON snapshots.
    _store_operation_lock = asyncio.Lock()

    async def _run_store_operation(
        operation: Callable[[], Any],
        *,
        persistent_transaction: bool = False,
    ) -> Any:
        async with _store_operation_lock:

            def _sync() -> Any:
                if not persistent_transaction:
                    return operation()
                store = _get_store()
                with store.process_transaction():
                    return operation()

            task = asyncio.create_task(asyncio.to_thread(_sync))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Cancelling to_thread does not stop its worker.  Keep the
                # serialization boundary held until the transaction really
                # exits, then propagate cancellation to the MCP caller.
                try:
                    await task
                except BaseException:
                    pass
                raise

    mcp = FastMCP(
        name="qwenpawmail-mcp",
        instructions=(
            "MCP server for NetEase 163/126/yeah.net and QQ mailboxes over "
            "IMAP/SMTP. If you do not yet have an account, call "
            "create_mailbox for registration guidance. Otherwise use "
            "check_auth first to verify credentials. If credentials "
            "are not yet configured, ask the user for their email "
            "address and 16-char authorization code, then call "
            "set_credentials. UIDs are per-folder; refresh them "
            "with list_messages before acting on a message."
        ),
    )

    def _ann(
        title: str,
        *,
        read_only: bool = False,
        destructive: bool = False,
        idempotent: bool = False,
    ) -> ToolAnnotations:
        return ToolAnnotations(
            title=title,
            readOnlyHint=read_only,
            destructiveHint=destructive,
            idempotentHint=idempotent,
            openWorldHint=True,
        )

    @mcp.tool(
        annotations=_ann("List Folders", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def list_folders() -> dict:
        """List all mailbox folders.

        Chinese folder names are decoded from IMAP
        modified UTF-7.
        """
        folders = await asyncio.to_thread(lambda: _get_client().list_folders())
        return {"folders": folders}

    @mcp.tool(
        annotations=_ann("List Messages", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def list_messages(
        folder: str = "INBOX",
        limit: int | str = 20,
        offset: int | str = 0,
    ) -> dict:
        """List messages in a folder, newest first,
        envelope metadata only (no bodies).

        Args:
            folder: Folder name, e.g. 'INBOX' or a Chinese
                folder name.
            limit: Max messages to return (1-100, default 20).
            offset: Number of newest messages to skip,
                for pagination (0-based).
        """
        return await asyncio.to_thread(
            lambda: _get_client().list_messages(
                folder=folder,
                limit=coerce_int(limit, 20),
                offset=coerce_int(offset, 0, lo=0, hi=10000),
            ),
        )

    @mcp.tool(annotations=_ann("Get Message", read_only=True, idempotent=True))
    @_tool_errors
    async def get_message(folder: str, uid: str) -> dict:
        """Fetch one message by UID: text/html bodies plus
        attachment metadata (not attachment content).

        Args:
            folder: Folder containing the message.
            uid: Message UID from list_messages or search_messages.
        """
        return await asyncio.to_thread(
            lambda: _get_client().get_message(folder=folder, uid=uid),
        )

    @mcp.tool(
        annotations=_ann("Get Attachment", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def get_attachment(
        folder: str,
        uid: str,
        attachment: str,
        save_path: str | None = None,
    ) -> dict:
        """Download one attachment by filename or zero-based index.

        Args:
            folder: Folder containing the message.
            uid: Message UID.
            attachment: Attachment filename, or its zero-based
                index as a string (e.g. '0').
            save_path: Optional file or directory path to save
                the attachment to.
                Relative paths are resolved inside the agent workspace (never
                the process CWD); absolute paths must also fall inside the
                workspace or the call is rejected. A trailing '/' marks a
                directory (auto-created). The result includes the final
                absolute path in 'saved_to'.
                When omitted, the content is returned base64-encoded.
        """
        return await asyncio.to_thread(
            lambda: _get_client().get_attachment(
                folder=folder,
                uid=uid,
                attachment=attachment,
                save_path=save_path,
            ),
        )

    @mcp.tool(
        annotations=_ann("Search Messages", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def search_messages(
        folder: str = "INBOX",
        keyword: str | None = None,
        from_address: str | None = None,
        since: str | None = None,
        before: str | None = None,
        limit: int | str = 20,
    ) -> dict:
        """Search messages in a folder by keyword, sender and/or date range.

        Args:
            folder: Folder to search in.
            keyword: Text to match in message content (UTF-8 supported).
            from_address: Sender email address (ASCII).
            since: Only messages on/after this date, format YYYY-MM-DD.
            before: Only messages before this date, format YYYY-MM-DD.
            limit: Max results (1-100, default 20).
        """
        return await asyncio.to_thread(
            lambda: _get_client().search_messages(
                folder=folder,
                keyword=keyword,
                from_address=from_address,
                since=since,
                before=before,
                limit=coerce_int(limit, 20),
            ),
        )

    @mcp.tool(annotations=_ann("Send Message"))
    @_tool_errors
    async def send_message(
        to: list[str] | str,
        subject: str,
        body: str,
        cc: list[str] | str | None = None,
        bcc: list[str] | str | None = None,
    ) -> dict:
        """Send a plain-text email.

        Args:
            to: Recipient email addresses (array, or a comma-separated string).
            subject: Message subject (Chinese supported).
            body: Plain-text message body.
            cc: Optional Cc addresses (array, or a comma-separated string).
            bcc: Optional Bcc addresses (array, or a comma-separated string).
        """
        return await asyncio.to_thread(
            lambda: _get_client().send_message(
                to=coerce_str_list(to),
                subject=subject,
                body=body,
                cc=coerce_str_list(cc),
                bcc=coerce_str_list(bcc),
            ),
        )

    @mcp.tool(annotations=_ann("Reply to Message"))
    @_tool_errors
    async def reply_message(folder: str, uid: str, body: str) -> dict:
        """Reply to a message. Sets In-Reply-To/References
        headers and the 'Re:' subject prefix.

        Args:
            folder: Folder containing the original message.
            uid: UID of the original message.
            body: Plain-text reply body.
        """
        return await asyncio.to_thread(
            lambda: _get_client().reply_message(
                folder=folder,
                uid=uid,
                body=body,
            ),
        )

    @mcp.tool(annotations=_ann("Forward Message"))
    @_tool_errors
    async def forward_message(
        folder: str,
        uid: str,
        to: list[str] | str,
        body: str = "",
    ) -> dict:
        """Forward a message (attached as message/rfc822)
        with a 'Fwd:' subject prefix.

        Args:
            folder: Folder containing the original message.
            uid: UID of the original message.
            to: Recipient email addresses (array, or a comma-separated string).
            body: Optional note to include above the forwarded message.
        """
        return await asyncio.to_thread(
            lambda: _get_client().forward_message(
                folder=folder,
                uid=uid,
                to=coerce_str_list(to),
                body=body,
            ),
        )

    @mcp.tool(annotations=_ann("Mark Messages", idempotent=True))
    @_tool_errors
    async def mark_messages(
        folder: str,
        uids: list[str] | str,
        mark: str,
    ) -> dict:
        """Mark messages as read/unread or flag/unflag (star) them.

        Args:
            folder: Folder containing the messages.
            uids: Message UIDs to mark (array, or a comma-separated string).
            mark: One of 'read', 'unread', 'flagged', 'unflagged'.
        """
        return await asyncio.to_thread(
            lambda: _get_client().mark_messages(
                folder=folder,
                uids=coerce_str_list(uids),
                mark=mark,
            ),
        )

    @mcp.tool(annotations=_ann("Move Message"))
    @_tool_errors
    async def move_message(folder: str, uid: str, target_folder: str) -> dict:
        """Move a message to another folder.

        Args:
            folder: Source folder.
            uid: Message UID in the source folder.
            target_folder: Destination folder name.
        """
        return await asyncio.to_thread(
            lambda: _get_client().move_message(
                folder=folder,
                uid=uid,
                target_folder=target_folder,
            ),
        )

    @mcp.tool(annotations=_ann("Delete Message", destructive=True))
    @_tool_errors
    async def delete_message(folder: str, uid: str) -> dict:
        """Mark a message \\Deleted and UID-expunge it when supported.

        Cleanup is always scoped to the requested UID. On servers without
        UIDPLUS, the marked message remains pending server/client cleanup;
        global EXPUNGE is never used.

        Args:
            folder: Folder containing the message.
            uid: Message UID to delete.
        """
        return await asyncio.to_thread(
            lambda: _get_client().delete_message(folder=folder, uid=uid),
        )

    @mcp.tool(annotations=_ann("Create Folder", idempotent=True))
    @_tool_errors
    async def create_folder(name: str) -> dict:
        """Create a new mailbox folder. Chinese names are
        encoded to IMAP modified UTF-7.

        Args:
            name: New folder name.
        """
        return await asyncio.to_thread(
            lambda: _get_client().create_folder(name=name),
        )

    @mcp.tool(
        annotations=_ann(
            "Check Authentication",
            read_only=True,
            idempotent=True,
        ),
    )
    @_tool_errors
    async def check_auth() -> dict:
        """Diagnose credentials: performs a fresh IMAP
        login (with the RFC 2971 ID command) and SMTP
        login."""
        return await asyncio.to_thread(lambda: _get_client().check_auth())

    @mcp.tool(
        annotations=_ann("Create Mailbox", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def create_mailbox(domain: str, username: str | None = None) -> dict:
        """Guide registration for a new mailbox account:
        validate username format, generate a random username
        (if not specified), and return a direct link to the
        registration page with step-by-step instructions.
        Registration must be completed manually by the user
        in a browser (requires SMS verification). After
        registration, use check_auth to verify connectivity.

        Args:
            domain: Target email domain
                (163.com / 126.com / yeah.net / qq.com /
                foxmail.com).
            username: Desired email username (the part
                before @). Randomly generated if not
                provided.
        """
        domain = domain.lower()
        provider = PROVIDERS.get(domain)
        if provider is None:
            raise RegistrationError(
                f"Unsupported domain: {domain}. Supported domains are "
                "163.com/126.com/yeah.net/qq.com/foxmail.com",
            )
        if provider.provider_type not in REGISTRATION_SUPPORTED_TYPES:
            raise RegistrationError(
                f"The {domain} domain supports sending and receiving mail, "
                "but create_mailbox cannot guide its registration. Register "
                "on the provider's website, enable IMAP/SMTP, and then use "
                "set_credentials.",
            )
        if username is None:
            username = generate_random_username(domain)
        is_valid, format_errors = validate_username(username, domain)
        alternatives = generate_alternatives(username, domain=domain)
        guide = build_registration_guide(username, domain, provider)
        return {
            "username": username,
            "domain": domain,
            "username_format_valid": is_valid,
            "format_errors": format_errors,
            "alternatives": alternatives,
            "username_taken_guidance": (
                f"If the registration page says {username} is taken, call "
                "create_mailbox again with username set to one of the names "
                "in alternatives, or try an alternative directly on the "
                "registration page."
            ),
            "manual_actions_required": [
                "phone_number",
                "sms_verification_code",
                "authorization_code",
            ],
            "can_be_automated": False,
            **guide,
        }

    @mcp.tool(annotations=_ann("Set Credentials"))
    @_tool_errors
    async def set_credentials(
        email: str,
        auth_code: str,
        imap_host: str | None = None,
        smtp_host: str | None = None,
    ) -> dict:
        """Set or update mailbox credentials at runtime.

        Call this tool when the user provides an email
        address and auth code during the conversation —
        no need to configure env in the MCP client;
        overrides environment variables or previously set
        credentials. auth_code is the 16-character
        authorization code generated in the provider's web
        settings (NOT the login password).
        163.com/126.com/yeah.net/qq.com/foxmail.com are
        auto-routed to IMAP/SMTP servers; other domains
        require both imap_host and smtp_host. After
        success, call check_auth to verify.

        Args:
            email: Full email address,
                e.g. xxx@163.com or xxx@qq.com.
            auth_code: 16-character authorization code
                (not the login password).
            imap_host: Optional IMAP server address
                (required for non-built-in domains).
            smtp_host: Optional SMTP server address
                (required for non-built-in domains).
        """

        def _sync() -> dict:
            env = {
                "QWENPAWMAIL_EMAIL": email,
                "QWENPAWMAIL_AUTH_CODE": auth_code,
            }
            if imap_host:
                env["QWENPAWMAIL_IMAP_HOST"] = imap_host
            if smtp_host:
                env["QWENPAWMAIL_SMTP_HOST"] = smtp_host
            cfg = load_config(env=env)
            _config_holder[0] = cfg
            _client_holder[0] = None
            _config_source[0] = "runtime"
            # Rebuild ThreadStore with the new email namespace while no
            # thread-management operation can still hold the previous store.
            state_dir = resolve_state_dir(cfg.email)
            _store_holder[0] = ThreadStore.for_email(state_dir, cfg.email)
            return {
                "configured": True,
                "email": cfg.email,
                "imap_host": cfg.imap_host,
                "imap_port": cfg.imap_port,
                "smtp_host": cfg.smtp_host,
                "smtp_port": cfg.smtp_port,
                "next_action": (
                    "Call check_auth to verify that the credentials can log "
                    "in to both IMAP and SMTP."
                ),
            }

        return await _run_store_operation(_sync)

    @mcp.tool(annotations=_ann("Clear Credentials", idempotent=True))
    @_tool_errors
    async def clear_credentials() -> dict:
        """Clear runtime credentials. Mail tools will fall back to environment
        variables (if set), or set_credentials must be called again."""

        def _sync() -> dict:
            _config_holder[0] = None
            _client_holder[0] = None
            _config_source[0] = "none"
            _store_holder[0] = None
            return {
                "cleared": True,
                "note": (
                    "Runtime credentials were cleared. The next mail tool "
                    "call will fall back to environment variables if they "
                    "are set; otherwise, call set_credentials again."
                ),
            }

        return await _run_store_operation(_sync)

    # -- thread management & statistics tools ---------------------------------

    @mcp.tool(
        annotations=_ann("List Threads", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def list_threads(
        labels: list[str] | str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        subject: str | None = None,
        before: str | None = None,
        after: str | None = None,
        limit: int | str = 20,
        offset: int | str = 0,
    ) -> dict:
        """List conversation threads (newest activity first)
        after an incremental sync.

        Threads group messages from INBOX and the sent folder
        by their References/In-Reply-To chain (falling back to
        normalized subject + participants). Labels include
        system labels (inbox/sent/spam/trash, derived from
        folders, read-only) and custom labels set via
        update_thread.

        Args:
            labels: Only threads carrying ALL of these labels
                (system or custom). Accepts an array or a
                comma-separated string.
            sender: Substring match against the From header
                of any message.
            recipient: Substring match against the To header
                of any message.
            subject: Substring match against the thread
                subject.
            before: Only threads whose latest message is
                before this date (YYYY-MM-DD).
            after: Only threads whose latest message is
                on/after this date (YYYY-MM-DD).
            limit: Max threads to return (1-100, default 20).
            offset: Number of threads to skip, for pagination.
        """

        def _sync():
            store = _get_store()
            store.sync(_get_client())
            return store.list_threads(
                labels=coerce_str_list(labels),
                sender=sender,
                recipient=recipient,
                subject=subject,
                before=before,
                after=after,
                limit=coerce_int(limit, 20),
                offset=coerce_int(offset, 0, lo=0, hi=10000),
            )

        return await _run_store_operation(
            _sync,
            persistent_transaction=True,
        )

    @mcp.tool(
        annotations=_ann("Search Threads", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def search_threads(keyword: str, limit: int | str = 20) -> dict:
        """Search INBOX and the sent folder by keyword
        and return matching threads.

        Matched message UIDs are mapped to threads; results are ranked by hit
        count then recency. Spam and trash folders are explicitly excluded.

        Args:
            keyword: Text to match in message content (UTF-8 supported).
            limit: Max threads to return (1-100, default 20).
        """

        def _sync():
            _limit = coerce_int(limit, 20)
            client = _get_client()
            store = _get_store()
            sync_info = store.sync(client)
            folders = ["INBOX"] + sync_info[
                "sent_folders"
            ]  # spam/trash excluded
            hits: dict[str, int] = {}
            for folder in folders:
                try:
                    result = client.search_messages(
                        folder=folder,
                        keyword=keyword,
                        limit=100,
                    )
                except CapabilityError:
                    # Server lacks IMAP full-text search: degrade to
                    # local thread-subject matching over the synced index.
                    local = store.list_threads(
                        subject=keyword,
                        limit=_limit,
                    )
                    return {
                        "keyword": keyword,
                        "threads": local["threads"],
                        "total": local["total"],
                        "note": (
                            "The provider does not support IMAP full-text "
                            "search. Results use local thread subject "
                            "matching and cover only synchronized message "
                            "headers."
                        ),
                    }
                for msg in result["messages"]:
                    tid = store.thread_for_uid(folder, msg["uid"])
                    if tid is None and msg.get("message_id"):
                        tid = store.thread_for_message_id(msg["message_id"])
                    if tid is not None:
                        hits[tid] = hits.get(tid, 0) + 1
            summaries = [
                {**store.thread_summary(tid), "hits": count}
                for tid, count in hits.items()
            ]
            summaries.sort(
                key=lambda s: (s["hits"], s.get("latest_timestamp") or 0.0),
                reverse=True,
            )
            for s in summaries:
                s.pop("latest_timestamp", None)
            return {
                "keyword": keyword,
                "threads": summaries[:_limit],
                "total": len(summaries),
            }

        return await _run_store_operation(
            _sync,
            persistent_transaction=True,
        )

    @mcp.tool(annotations=_ann("Get Thread", read_only=True, idempotent=True))
    @_tool_errors
    async def get_thread(thread_id: str) -> dict:
        """Get all messages of a thread as envelopes, oldest first.

        Envelopes carry folder + uid; call get_message(folder, uid) to read a
        message body.

        Args:
            thread_id: Thread id from list_threads or search_threads.
        """

        def _sync():
            result = _get_store().get_thread(thread_id)
            result["hint"] = (
                "Envelopes only. Use get_message(folder, uid)"
                " to fetch the body of any message in this "
                "thread."
            )
            return result

        return await _run_store_operation(
            _sync,
            persistent_transaction=True,
        )

    @mcp.tool(annotations=_ann("Update Thread", idempotent=True))
    @_tool_errors
    async def update_thread(
        thread_id: str,
        add_labels: list[str] | str | None = None,
        remove_labels: list[str] | str | None = None,
    ) -> dict:
        """Add/remove custom labels on a thread.

        System labels (inbox/sent/spam/trash) are derived from message folders
        and cannot be modified; passing one raises an error.

        Args:
            thread_id: Thread id from list_threads or search_threads.
            add_labels: Custom labels to add (array, or a
                comma-separated string).
            remove_labels: Custom labels to remove (array,
                or a comma-separated string).
        """

        def _sync():
            store = _get_store()
            custom = store.update_labels(
                thread_id,
                add=coerce_str_list(add_labels),
                remove=coerce_str_list(remove_labels),
            )
            return {
                "thread_id": thread_id,
                "custom_labels": custom,
                "labels": store.thread_summary(thread_id)["labels"],
            }

        return await _run_store_operation(
            _sync,
            persistent_transaction=True,
        )

    @mcp.tool(annotations=_ann("Delete Thread", destructive=True))
    @_tool_errors
    async def delete_thread(thread_id: str) -> dict:
        """Move every message of a thread into the trash folder.

        The trash folder is auto-detected from provider flags and known
        localized folder names. Messages already in trash are left untouched.
        If only some moves succeed, failed messages remain indexed and
        ``partial`` is true.

        Args:
            thread_id: Thread id from list_threads or search_threads.
        """

        def _sync():
            client = _get_client()
            store = _get_store()
            messages = store.thread_messages(thread_id)
            special = detect_special_folders(client.list_folders())
            trash = special["trash"]
            if not trash:
                raise ToolError(
                    "No trash folder was found among the provider's known "
                    "trash folder names. Use list_folders to inspect the "
                    "available folders.",
                )
            moved, errors = [], []
            for m in messages:
                if m["folder"] == trash:
                    continue
                try:
                    client.move_message(
                        folder=m["folder"],
                        uid=m["uid"],
                        target_folder=trash,
                    )
                    moved.append({"folder": m["folder"], "uid": m["uid"]})
                except Exception as exc:  # pylint: disable=broad-except
                    errors.append(
                        {
                            "folder": m["folder"],
                            "uid": m["uid"],
                            "error": str(exc),
                        },
                    )
            if messages and not moved and errors:
                raise ToolError(
                    "delete_thread failed: "
                    f"All {len(errors)} messages failed to move to the trash "
                    f"folder. First error: {errors[0]['error']}\nTry deleting "
                    "the messages individually with delete_message or move "
                    "them manually in webmail.",
                )
            if errors:
                # Trash is intentionally excluded from the active thread
                # index. Drop only the messages that were actually moved and
                # retain failed messages so they remain addressable/retryable.
                store.remove_messages(thread_id, moved)
                return {
                    "thread_id": thread_id,
                    "deleted": False,
                    "partial": True,
                    "trash_folder": trash,
                    "moved_count": len(moved),
                    "moved": moved,
                    "errors": errors,
                }
            store.remove_thread(thread_id)
            result = {
                "thread_id": thread_id,
                "deleted": True,
                "trash_folder": trash,
                "moved_count": len(moved),
                "moved": moved,
            }
            return result

        return await _run_store_operation(
            _sync,
            persistent_transaction=True,
        )

    @mcp.tool(
        annotations=_ann("Get Mailbox Stats", read_only=True, idempotent=True),
    )
    @_tool_errors
    async def get_mailbox_stats(days: int | str = 30) -> dict:
        """Mailbox statistics over the last N days from
        INBOX + the sent folder.

        Includes received/sent totals, unread/flagged counts, top 10 senders
        and recipients, daily send/receive trend, response-time mean/median
        (sent messages with In-Reply-To vs. the original date), pending
        replies (inbox threads still unread/flagged), attachment count and the
        5 largest messages. Scans at most 1000 messages per folder; sets
        truncated=true when the window exceeds that.

        Args:
            days: Statistics window in days (1-365, default 30).
        """

        def _sync():
            _days = coerce_int(days, 30, lo=1, hi=365)
            client = _get_client()
            store = _get_store()
            store.sync(client)
            since = (date.today() - timedelta(days=_days)).isoformat()
            special = detect_special_folders(client.list_folders())
            inbox_envs, truncated = client.scan_folder_stats(
                "INBOX",
                since=since,
            )
            sent_envs: list[dict] = []
            for folder in special["sent"]:
                envs, trunc = client.scan_folder_stats(folder, since=since)
                sent_envs.extend(envs)
                truncated = truncated or trunc
            return compute_mailbox_stats(
                inbox_envs,
                sent_envs,
                days=_days,
                store=store,
                truncated=truncated,
            )

        return await _run_store_operation(
            _sync,
            persistent_transaction=True,
        )

    return mcp
