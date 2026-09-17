# -*- coding: utf-8 -*-
"""Assemble system prompt from host anchors and plugin sections."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from ..plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


@dataclass
class PromptSection:
    """A named block of system prompt text."""

    name: str
    content: str


class PromptBuilder:
    """Assemble system prompt from host anchors and plugin sections.

    Host anchors are emitted in :pyattr:`HOST_ANCHORS` order.
    Plugin sections are inserted immediately after their declared anchor.
    """

    HOST_ANCHORS = ("workspace", "multimodal", "env_context")

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def build(
        self,
        *,
        agent: Any = None,
        agent_id: Optional[str] = None,
        workspace: str = "",
        multimodal: str = "",
        env_context: str = "",
    ) -> str:
        """Return the assembled system prompt string."""
        host = {
            "workspace": workspace,
            "multimodal": multimodal,
            "env_context": env_context,
        }

        sections: List[PromptSection] = []
        for anchor in self.HOST_ANCHORS:
            content = host.get(anchor, "")
            if content:
                sections.append(PromptSection(anchor, content))
            for reg in self._get_plugin_sections(anchor, agent_id):
                rendered = self._render(reg, agent)
                if rendered:
                    sections.append(PromptSection(reg.name, rendered))

        return "\n\n".join(s.content for s in sections)

    def _get_plugin_sections(self, anchor: str, agent_id: Optional[str]):
        """Filter registered sections by anchor and agent_id."""
        return [
            s
            for s in self._registry.get_prompt_sections()
            if s.after == anchor
            and (s.agent_id is None or s.agent_id == agent_id)
        ]

    # SECURITY: plugin text is concatenated verbatim into the
    # system prompt. Only trusted plugins can reach this path.
    @staticmethod
    def _render(registration: Any, agent: Any) -> str:
        """Call provider; swallow and log failures."""
        try:
            return registration.provider(agent)
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Prompt section '%s' provider failed",
                registration.name,
            )
            return ""
