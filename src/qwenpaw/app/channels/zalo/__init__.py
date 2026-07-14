# -*- coding: utf-8 -*-
"""Zalo Bot channel package.

Connects to the Zalo Bot Platform (https://bot.zalo.me/) via long-polling
of the ``getUpdates`` endpoint. No public URL / webhook is required,
making the channel suitable for personal bots running behind NAT.

Group chats are routed with a per-group session id
(``zalo:group:<chat_id>``) so the agent keeps one conversation context
per group, while each private chat retains its own per-sender session
(``zalo:<user_id>``).
"""

from .channel import ZaloChannel

__all__ = ["ZaloChannel"]
