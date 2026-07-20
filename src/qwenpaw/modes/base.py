# -*- coding: utf-8 -*-
"""``AgentMode`` and ``ModeGatedHook`` base classes.

An ``AgentMode`` is a *bundle* of behavior: commands, tools, hooks and
prompt contributors that should appear together. ``setup(workspace)`` is
the single entry point that pushes those four pieces into the host
workspace's plugins / service_manager — there is no other registration
path, which keeps "which mode owns what" trivially derivable from
``mode.commands()`` / ``.tools()`` / ``.hooks()`` /
``.prompt_contributors()``.

``ModeGatedHook`` is the base every mode-scoped hook should inherit
from: it auto-skips when the owning mode's ``is_active(ctx)`` returns
``False``, so subclasses never need to repeat the gate themselves
(forgetting it was a recurring bug in the old code).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..runtime.hooks import HookBase, HookContext, HookResult

if TYPE_CHECKING:
    from ..runtime.prompt_manager import PromptContributor
    from ..runtime.slash_command_registry import CommandSpec
    from ..runtime.tool_registry import ToolDescriptor


class AgentMode:
    """Base class for one named runtime mode.

    Subclasses set ``name`` (must be unique within a workspace) and
    override ``is_active`` plus any of the four content methods they
    actually contribute to.
    """

    name: str

    def setup(self, workspace: object) -> None:
        """Register every contribution into ``workspace``'s plugins.

        ``workspace`` is typed as ``object`` because the concrete
        ``Workspace`` class is defined in a higher layer — by duck-typing
        on ``workspace.plugins`` subclasses stay stable.
        """
        for spec in self.commands():
            workspace.plugins.slash_command_registry.register(spec)
        for desc in self.tools():
            workspace.plugins.tool_registry.register(desc)
        for hook in self.hooks():
            workspace.plugins.hook_registry.register(hook)
        for contributor in self.prompt_contributors():
            workspace.plugins.prompt_manager.register(contributor)

    def commands(self) -> list["CommandSpec"]:
        return []

    def tools(self) -> list["ToolDescriptor"]:
        return []

    def hooks(self) -> list[HookBase]:
        return []

    def prompt_contributors(self) -> list["PromptContributor"]:
        return []

    async def on_turn_start(
        self,
        ctx: HookContext,  # noqa: ARG002
    ) -> None:
        """Prepare mode-owned state for a new user turn."""

    def on_conversation_reset(
        self,
        ctx: HookContext,  # noqa: ARG002
    ) -> None:
        """Called on /new and /clear to reset mode state.

        Subclasses override to clear sessions, gate state,
        or any mode-specific data. Default is no-op.
        """

    def is_active(  # noqa: ARG002
        self,
        ctx: HookContext,  # pylint: disable=unused-argument
    ) -> bool:
        """Whether this mode applies to the current request.

        Default is ``False`` — subclasses MUST override and read
        something concrete (e.g. ``ctx.agent_config.mode``) so an
        unconfigured mode never silently leaks into requests.
        """
        return False


class ModeGatedHook(HookBase):
    """``HookBase`` variant that auto-skips when its owner mode is inactive.

    Subclasses implement ``_run`` instead of ``run``. The base ``run``
    runs the mode gate first, returning a no-op ``HookResult`` (CONTINUE
    + no payload) when ``owner_mode.is_active(ctx)`` is ``False``.
    """

    def __init__(self, owner_mode: AgentMode) -> None:
        self.owner_mode = owner_mode

    async def run(self, ctx: HookContext) -> HookResult:
        if not self.owner_mode.is_active(ctx):
            return HookResult()
        return await self._run(ctx)

    async def _run(self, ctx: HookContext) -> HookResult:  # noqa: D401, ARG002
        raise NotImplementedError


__all__ = ["AgentMode", "ModeGatedHook"]
