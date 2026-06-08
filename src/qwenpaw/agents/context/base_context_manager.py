# -*- coding: utf-8 -*-
"""Abstract base class for context managers."""
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Callable, TYPE_CHECKING

from agentscope.message import Msg
from agentscope.middleware import MiddlewareBase

from ..utils.registry import Registry

if TYPE_CHECKING:
    from agentscope.agent import Agent

logger = logging.getLogger(__name__)


class BaseContextManager(MiddlewareBase, ABC):
    """Abstract base class defining the context manager interface.

    Concrete implementations are responsible for managing the *active*
    conversation context window:

    - **Compaction**: condense older messages into a rolling summary when
      the context approaches the model's token limit.
    - **Tool-result pruning**: trim oversized tool outputs inline so they
      do not exhaust the context budget unnecessarily.
    - **Context health checks**: decide whether and what to compact before
      each agent step.

    A context manager wears three hats:

    1. **Service** — :meth:`start` / :meth:`close` are called by the
       workspace's ``ServiceManager`` during workspace bring-up / tear-down.
    2. **Public API** — :meth:`compact_context` is invoked by command
       handlers (e.g. ``/compact``) to condense messages on demand.
    3. **Middleware** — instances are passed directly into
       ``Agent(middlewares=[...])``.  This base class implements the
       :class:`agentscope.middleware.MiddlewareBase` ``on_*`` hooks as
       thin onion-wrappers that delegate to the
       :meth:`pre_reply` / :meth:`post_reply` / :meth:`pre_reasoning` /
       :meth:`post_acting` half-hooks subclasses implement.

    Attributes:
        working_dir: Root directory used for any on-disk context storage
            (e.g. compaction indices, cached summaries).
        agent_id: Unique identifier of the owning agent, used for config
            loading and storage namespacing.
    """

    def __init__(
        self,
        working_dir: str,
        agent_id: str,
    ):
        """Initialize common context manager attributes.

        Subclasses should call ``super().__init__()`` before setting up
        backend-specific resources.

        Args:
            working_dir: Root directory for context storage.
            agent_id: Unique agent identifier used for config loading and
                storage namespacing.
        """
        self.working_dir: str = working_dir
        self.agent_id: str = agent_id

    @abstractmethod
    async def start(self) -> None:
        """Start the context manager and initialize the storage backend.

        Called once after instantiation.  Implementations should connect to
        or create any required stores, load cached state, and start
        background services if needed.
        """

    @abstractmethod
    async def close(self) -> bool:
        """Shut down the context manager and release resources.

        Called once before the agent exits.  Implementations should flush
        pending writes, stop background tasks, and close open handles.

        Returns:
            ``True`` if the shutdown completed cleanly, ``False`` otherwise.
        """

    # ------------------------------------------------------------------
    # Agent lifecycle hook methods
    # ------------------------------------------------------------------

    @abstractmethod
    async def pre_reply(
        self,
        agent: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Hook invoked before the agent emits a final reply to the user.

        Implementations may inspect or modify the pending reply arguments.
        Return ``None`` to leave ``kwargs`` unchanged, or return a modified
        copy of ``kwargs`` that the agent will use instead.

        Args:
            agent: The owning agent instance.
            kwargs: Keyword arguments about to be passed into the reply step.

        Returns:
            Optionally modified ``kwargs``, or ``None`` if no change.
        """

    @abstractmethod
    async def pre_reasoning(
        self,
        agent: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Hook invoked before each reasoning step.

        The primary use-case is context health-checking and compaction:
        implementations should inspect the current token budget, compact
        older messages when the threshold is exceeded, and update the
        memory store accordingly.

        Return ``None`` to leave ``kwargs`` unchanged, or return a modified
        copy of ``kwargs`` to alter how the reasoning step proceeds.

        Args:
            agent: The owning agent instance.
            kwargs: Keyword arguments about to be passed into ``_reasoning``.

        Returns:
            Optionally modified ``kwargs``, or ``None`` if no change.
        """

    @abstractmethod
    async def post_acting(
        self,
        agent: Any,
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Hook invoked after each tool-use (acting) step.

        Implementations can use this hook to post-process tool results,
        e.g. truncating oversized outputs so they do not exhaust the
        context budget before the next reasoning step.

        Return ``None`` to leave the acting output unchanged, or return a
        replacement ``Msg`` to override it.

        Args:
            agent: The owning agent instance.
            kwargs: Keyword arguments that were passed into ``_acting``.
            output: The raw output produced by the acting step.

        Returns:
            A replacement ``Msg``, or ``None`` if no change.
        """

    @abstractmethod
    async def post_reply(
        self,
        agent: Any,
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Hook invoked after the agent emits a final reply to the user.

        Implementations may use this hook for logging, telemetry, or any
        post-reply side-effects.  Return ``None`` to leave the reply
        unchanged, or return a replacement ``Msg``.

        Args:
            agent: The owning agent instance.
            kwargs: Keyword arguments that were passed into the reply step.
            output: The reply message produced by the agent.

        Returns:
            A replacement ``Msg``, or ``None`` if no change.
        """

    @abstractmethod
    async def compact_context(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
    ) -> dict:
        """Compact messages into a condensed summary.

        This is the public interface for context compaction, used by
        command handlers and external callers. Implementations should
        handle all configuration internally, including obtaining the LLM
        from agent configuration if needed.

        Args:
            messages: List of messages to compact.
            previous_summary: Previous summary to update (if exists).
            extra_instruction: Extra instruction for compaction.

        Returns:
            Dict with keys:
            - success: Whether compaction produced a valid result.
            - reason: Failure reason (empty string on success).
            - history_compact: The compacted summary text.
            - before_tokens: Token count of messages before compaction.
            - after_tokens: Token count of the compacted summary.
        """

    # ------------------------------------------------------------------
    # Middleware bridge — translate the half-hooks above into the onion
    # ``on_*`` methods that ``MiddlewareBase`` exposes to the agent.
    # Hook exceptions are logged and swallowed so a context-manager bug
    # cannot abort the agent's reply.
    # ------------------------------------------------------------------

    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        try:
            await self.pre_reply(agent, input_kwargs)
        except Exception:
            logger.exception("ContextManager pre_reply raised")

        events: list[Any] = []
        async for event in next_handler():
            events.append(event)
            yield event

        if events:
            try:
                await self.post_reply(agent, input_kwargs, events[-1])
            except Exception:
                logger.exception("ContextManager post_reply raised")

    async def on_reasoning(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        try:
            await self.pre_reasoning(agent, input_kwargs)
        except Exception:
            logger.exception("ContextManager pre_reasoning raised")
        async for event in next_handler():
            yield event

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        events: list[Any] = []
        async for event in next_handler():
            events.append(event)
            yield event

        if events:
            try:
                await self.post_acting(agent, input_kwargs, events[-1])
            except Exception:
                logger.exception("ContextManager post_acting raised")


# ---------------------------------------------------------------------------
# Registry and factory for context manager implementations
# ---------------------------------------------------------------------------

context_registry: Registry[BaseContextManager] = Registry()


def get_context_manager_backend(backend: str) -> type[BaseContextManager]:
    """Return the context manager class for the given backend name.

    If the backend is not registered, falls back to the first registered
    backend.

    Args:
        backend: Backend name to resolve.

    Returns:
        The context manager class.

    Raises:
        ValueError: When no context manager backends are registered.
    """
    cls = context_registry.get(backend)
    if cls is None:
        registered = context_registry.list_registered()
        if not registered:
            raise ValueError(
                f"No context manager backends registered. "
                f"Requested: '{backend}'",
            )
        fallback = registered[0]
        logger.warning(
            f"Unsupported context manager backend: '{backend}'. "
            f"Falling back to '{fallback}'. "
            f"Registered: {registered}",
        )
        cls = context_registry.get(fallback)
        if cls is None:
            raise ValueError(
                f"Fallback backend '{fallback}' not found in registry. "
                f"This should not happen.",
            )
    return cls
