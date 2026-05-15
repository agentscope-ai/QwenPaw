# -*- coding: utf-8 -*-
"""Gateway adapter: URL /rpc suffix + A2A-Version header override.

The Alibaba Cloud intelligent gateway requires:
1. JSON-RPC endpoint at {base_url}/rpc (not the card's URL directly)
2. A2A-Version header = "1.0.0" (SDK default is "1.0")
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

GATEWAY_A2A_VERSION = "1.0.0"


def patch_card_url(card: dict) -> dict:
    """Append /rpc suffix to the card's URL field."""
    url = card.get("url", "")
    if url and not url.endswith("/rpc"):
        card = {**card, "url": url.rstrip("/") + "/rpc"}
        logger.debug("Patched card URL: %s", card["url"])
    return card


def normalize_gateway_card(card_data: dict) -> dict:
    """Fix gateway AgentCard fields that may cause parsing issues.

    Known issues: some gateway cards have ``tags: null`` in skills.
    """
    for skill in card_data.get("skills", []):
        if skill.get("tags") is None:
            skill["tags"] = []
    return card_data
