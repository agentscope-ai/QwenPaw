"""Abstract base class for context managers."""
import logging
from abc import ABC, abstractmethod
from typing import Any

from agentscope.message import Msg

from .agent_context import AgentContext
from ..utils.registry import Registry
from ...config.config import load_agent_config

logger = logging.getLogger(__name__)


class BaseContextManager(ABC):
    """Abstract base class defining the context manager interface.

    All context manager backends must implement this interface to be usable
    as a drop-in replacement within the workspace.

    Concrete implementations are responsible for managing the *active*
    conversation context window, including:
    - **Compaction**: condensing older messages into a rolling summary when
      the context approaches the model's token limit.
    - **Tool-result truncation**: trimming oversized tool outputs inline so
      they do not exhaust the context budget unnecessarily.
    - **Context health checks**: deciding whether and what to compact before
      each agent step.

    The typical lifecycle mirrors ``BaseMemoryManager``:
        1. Instantiate with ``working_dir`` and ``agent_id``.
        2. Call ``await start()`` to connect to the backing store.
        3. Use the lifecycle hooks (``pre_reasoning``, ``post_acting``, etc.)
           during the agent loop.
        4. Call ``await close()`` to flush state and release resources.

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
    def get_agent_context(self, **kwargs) -> AgentContext:
        """Return the ``AgentContext`` object attached to this agent.

        ``AgentContext`` is a custom ``InMemoryMemory`` implementation
        with token-aware message handling, dialog persistence, and context
        compression support. It is used by the agent loop for accurate token
        counting and context-window management.

        Args:
            **kwargs: Implementation-specific options (e.g. token counter
                to attach to the returned object).

        Returns:
            The agent context instance configured with the agent's token
            counter.
        """


# ---------------------------------------------------------------------------
# Registry and factory for context manager implementations
# ---------------------------------------------------------------------------

context_registry: Registry[BaseContextManager] = Registry()


def get_context_manager(
        working_dir: str,
        agent_id: str,
) -> BaseContextManager:
    """Create and return a context manager instance for the given agent.

    The backend is resolved from the agent configuration
    (``running.context_manager_backend``).  Importing this module is enough
    to access the registry; concrete implementations register themselves by
    decorating their class with ``@context_registry.register("<name>")``.

    Args:
        working_dir: Root directory for context storage.
        agent_id: Unique agent identifier used for config loading.

    Returns:
        A fully-constructed ``BaseContextManager`` instance.

    Raises:
        ValueError: When the configured backend has no registered
            implementation.
    """

    backend = load_agent_config(agent_id).running.context_manager_backend
    cls = context_registry.get(backend)
    if cls is None:
        raise ValueError(
            f"Unsupported context manager backend: '{backend}'. "
            f"Registered: {context_registry.list_registered()}",
        )
    return cls(working_dir=working_dir, agent_id=agent_id)
