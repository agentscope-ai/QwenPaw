# -*- coding: utf-8 -*-
"""Base class for loop skill plugins.

Subclasses define LOOP_SKILL_CONFIG and place a SKILL.md
alongside their own plugin.py. This class handles the
boilerplate registration via LoopLoader.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class BaseLoopPlugin:
    """Reusable base for loop skill plugins.

    Subclass and set ``LOOP_SKILL_CONFIG``.  Override
    ``_skill_md_path`` if the SKILL.md is not next to
    the subclass file.
    """

    LOOP_SKILL_CONFIG: ClassVar[dict[str, Any]] = {}

    def register(self, api: Any) -> None:
        """Wire the loop into QwenPaw via LoopLoader."""
        from .loader import LoopLoader

        cfg = dict(self.LOOP_SKILL_CONFIG)
        skill_md = self._skill_md_path()
        if skill_md.exists() and not cfg.get("skill_prompt"):
            cfg["skill_prompt"] = skill_md.read_text(
                encoding="utf-8",
            )

        loader = LoopLoader(api)
        loader.load_from_dict(cfg)
        name = cfg.get("name", "unknown")
        logger.info(f"Registered /{name} loop skill")

    def _skill_md_path(self) -> Path:
        """Return path to SKILL.md next to the subclass."""
        import inspect

        cls_file = inspect.getfile(type(self))
        return Path(cls_file).parent / "SKILL.md"
