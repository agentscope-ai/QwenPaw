# -*- coding: utf-8 -*-
"""DriverHandler template method base class."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from .approval import ApprovalGate
from .capabilities import (
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
)
from .constants import (
    CREDENTIAL_ALIAS_DEFAULT,
    DRIVER_OPERATION_INVOKE,
    POLICY_EFFECT_ALLOW,
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
)
from .credentials.bindings import resolve_credentials
from .credentials.providers import CredentialProvider
from .credentials.types import ResolvedCredential
from .errors import (
    ApprovalRequiredError,
    DriverPermissionDeniedError,
)
from .contracts import (
    DriverCard,
    DriverPolicy,
    PolicyRule,
    PolicyTarget,
    coerce_driver_policy,
)
from .policy import DriverInvocationContext, evaluate_policy
from .time import current_policy_time

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..security.tool_guard.execution_level import ToolExecutionLevel


def _resolve_driver_execution_level(
    request_context: dict[str, Any],
) -> "ToolExecutionLevel":
    """Resolve runtime approval level for Driver invocation."""
    from ..security.tool_guard.execution_level import ToolExecutionLevel

    raw = request_context.get("approval_level")
    if raw:
        return ToolExecutionLevel.from_config(str(raw))

    agent_id = str(
        request_context.get("agent_id")
        or request_context.get("root_agent_id")
        or "",
    ).strip()
    if not agent_id:
        try:
            from ..config.utils import load_config

            config = load_config()
            agent_id = str(config.agents.active_agent or "default")
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "Failed to resolve active agent for Driver approval level: %s",
                exc,
            )
            agent_id = "default"

    try:
        from ..config.config import load_agent_config

        profile = load_agent_config(agent_id)
        return ToolExecutionLevel.from_config(
            getattr(profile, "approval_level", None),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning(
            "Failed to resolve Driver approval_level for agent=%s: %s",
            agent_id,
            exc,
        )
        return ToolExecutionLevel.AUTO


class DriverHandler(ABC):
    def __init__(
        self,
        card: DriverCard,
        credential_provider: CredentialProvider,
        credential_providers: dict[str, CredentialProvider] | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self._card = card
        self._credential_provider = credential_provider
        self._credential_providers = credential_providers or {
            CREDENTIAL_ALIAS_DEFAULT: credential_provider,
        }
        self._approval_gate = approval_gate

    async def init(self) -> None:
        await self._setup()

    async def shutdown(self) -> None:
        try:
            await self._teardown()
        finally:
            seen: set[int] = set()
            for provider in self._credential_providers.values():
                provider_id = id(provider)
                if provider_id in seen:
                    continue
                seen.add(provider_id)
                await provider.close()

    @abstractmethod
    async def _setup(self) -> None:
        ...

    @abstractmethod
    async def _teardown(self) -> None:
        ...

    async def list_capabilities(
        self,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        """Return protocol-neutral capabilities exposed by this Driver."""
        del request_context
        return []

    async def invoke_capability(
        self,
        invocation: DriverInvocation,
    ) -> DriverInvocationResult:
        """Invoke one capability. Protocol handlers override this method."""
        return DriverInvocationResult(
            ok=False,
            error_type="unsupported_capability",
            message=(
                f"Driver '{self.name}' does not support capability "
                f"invocation: {invocation.capability_id}"
            ),
        )

    async def _authorize_invocation(
        self,
        subject: str,
        operation: str = DRIVER_OPERATION_INVOKE,
        request_context: dict[str, str] | None = None,
        target: PolicyTarget | None = None,
        subjects: list[str] | tuple[str, ...] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> DriverInvocationContext:
        """Evaluate Driver policy for one protocol-specific operation."""
        context = DriverInvocationContext(
            subject=subject,
            driver_name=self._card.name,
            protocol=self._card.protocol,
            operation=operation,
            target=target or PolicyTarget(),
            subjects=tuple(subjects or ()),
            request_context=dict(request_context or {}),
            now=current_policy_time(),
            extras=dict(extras or {}),
        )
        effect = evaluate_policy(self._card.policy, context)
        if effect == POLICY_EFFECT_DENY:
            raise DriverPermissionDeniedError(
                self._card.name,
                subject,
                operation,
            )

        execution_level = _resolve_driver_execution_level(
            context.request_context,
        )
        needs_approval = (
            effect == POLICY_EFFECT_ASK and not execution_level.is_disabled()
        ) or (
            effect == POLICY_EFFECT_ALLOW
            and execution_level.requires_approval_for_all_tools()
        )
        if needs_approval:
            await self._request_approval(context)
        return context

    async def _resolve_credentials(self) -> dict[str, ResolvedCredential]:
        """Resolve all credential aliases for protocol handlers."""
        return await resolve_credentials(self._credential_providers)

    async def _request_approval(
        self,
        context: DriverInvocationContext,
    ) -> None:
        if self._approval_gate is None:
            raise ApprovalRequiredError(
                "Driver approval required but no approval gate is wired: "
                f"{context.subject} -> {context.driver_name}",
            )
        await self._approval_gate.request_approval(context)

    async def _execute(
        self,
        credential: ResolvedCredential,
        context: DriverInvocationContext,
        **kwargs: Any,
    ) -> Any:
        del credential
        del context
        del kwargs
        raise NotImplementedError(
            f"Driver '{self.name}' does not implement _execute(). "
            "Protocol handlers may instead override invoke_capability().",
        )

    def set_policy(self, policy: DriverPolicy | list[PolicyRule]) -> None:
        self._card.policy = coerce_driver_policy(policy)

    def sync_runtime_metadata(self, card: DriverCard) -> None:
        """Refresh DriverCard fields that do not require reconnecting."""
        if (
            card.name != self._card.name
            or card.protocol != self._card.protocol
        ):
            return
        self._card.config = dict(card.config)
        self._card.policy = coerce_driver_policy(card.policy)
        self._card.enabled = bool(card.enabled)

    @property
    def name(self) -> str:
        return self._card.name

    @property
    def card(self) -> DriverCard:
        return self._card
