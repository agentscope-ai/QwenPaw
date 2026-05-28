# -*- coding: utf-8 -*-
"""Temporary compatibility shims for the agentscope 1.x → 2.x migration.

These modules exist only to let the qwenpaw codebase import and run while
we incrementally rewrite call sites against the agentscope 2.0 API.

Each shim is documented with the equivalent 2.0 API it should eventually be
replaced by; once all call sites are migrated, the shim file is deleted.

Side-effect on import: legacy ``Msg.to_dict`` / ``Msg.from_dict`` helpers
are reattached to :class:`agentscope.message.Msg`.  agentscope 2.0 only
exposes the pydantic ``model_dump`` / ``model_validate`` API; many qwenpaw
call sites (and saved session files) still depend on the 1.x shape.
TODO(as2-migration): drop this monkey-patch once every consumer has been
ported to the new API.
"""
from __future__ import annotations


def _install_msg_dict_shim() -> None:
    try:
        from agentscope.message import Msg
    except Exception:  # pragma: no cover - keep imports tolerant
        return

    if not hasattr(Msg, "to_dict"):

        def _to_dict(self):  # type: ignore[no-untyped-def]
            return self.model_dump()

        Msg.to_dict = _to_dict  # type: ignore[attr-defined]

    if not hasattr(Msg, "from_dict"):

        def _from_dict(cls, data):  # type: ignore[no-untyped-def]
            from .message import msg_from_dict

            return msg_from_dict(data)

        Msg.from_dict = classmethod(_from_dict)  # type: ignore[attr-defined]

    # ``Msg.timestamp`` (1.x format ``"YYYY-mm-dd HH:MM:SS.fff"``) was
    # renamed to ``Msg.created_at`` (ISO-8601 ``"YYYY-mm-ddTHH:MM:SS.fff"``)
    # in 2.0.  Keep a read-only alias so legacy call sites (notably the
    # context store which does ``msg.timestamp.split()[0]``) keep working.
    if not hasattr(Msg, "timestamp"):

        def _timestamp(self):  # type: ignore[no-untyped-def]
            value = getattr(self, "created_at", None)
            if not value:
                return ""
            return str(value).replace("T", " ")

        Msg.timestamp = property(_timestamp)  # type: ignore[attr-defined]


_install_msg_dict_shim()


# Toolkit + Agent hook shims live in their own modules; install side-effects
# happen here so the patches are in place before any qwenpaw module imports
# ``Toolkit`` or constructs an ``Agent`` subclass.
from .toolkit import install_toolkit_shim  # noqa: E402
from .hooks import install_hook_shim  # noqa: E402

install_toolkit_shim()
install_hook_shim()
