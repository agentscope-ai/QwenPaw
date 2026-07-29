# -*- coding: utf-8 -*-
"""OMP Workflows plugin — registers five workflow AgentModes."""

import logging
from pathlib import Path

logger = logging.getLogger("qwenpaw").getChild("plugin.omp_workflows")

_PLUGIN_DIR = Path(__file__).parent


class OMPWorkflowsPlugin:
    """Plugin entry point for Oh My Paw workflow modes."""

    def register(self, api) -> None:
        from .autopilot.mode import AutopilotMode
        from .ralph.mode import RalphMode
        from .team.mode import TeamMode
        from .ultraqa.mode import UltraQAMode
        from .ultrawork.mode import UltraworkMode

        for mode_cls in (
            UltraQAMode,
            RalphMode,
            UltraworkMode,
            AutopilotMode,
            TeamMode,
        ):
            api.register_mode(mode_cls)
            logger.info("Registered OMP mode: %s", mode_cls.name)

        api.register_skill_provider(
            skills_dir=_PLUGIN_DIR / "skills",
            enabled_by_default=True,
        )


plugin = OMPWorkflowsPlugin()
