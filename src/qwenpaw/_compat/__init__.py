# -*- coding: utf-8 -*-
"""Compatibility shims for agentscope 1.x APIs.

Remaining contents:
- ``Msg.to_dict`` / ``Msg.from_dict`` / ``Msg.timestamp`` monkey-patches
  (session files and some call sites still use the 1.x shape)
- ``memory.py``: InMemoryMemory for legacy session deserialization
- ``message.py``: ImageBlock/VideoBlock/ToolUseBlock factory aliases
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

        def _from_dict(cls, data):  # pylint: disable=unused-argument
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


# The hook shim (hooks.py) has been replaced by native 2.0 Middleware
# classes in ``qwenpaw.agents.middlewares``.
# The toolkit shim (toolkit.py) has been replaced by direct use of
# ``Toolkit(tools=[...])`` and ``qwenpaw.agents.tool_compat``.
