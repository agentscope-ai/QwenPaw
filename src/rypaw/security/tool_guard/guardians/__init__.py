# -*- coding: utf-8 -*-
"""Abstract base class for all tool-call guardians.

Every guardian must subclass :class:`BaseToolGuardian` and implement
:meth:`guard`.  The interface is intentionally minimal so that new
detection engines (e.g. LLM-based, semantic analysis) can be added
as drop-in plugins without touching the guard engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import GuardFinding


class BaseToolGuardian(ABC):
    """Abstract base class for all tool-call guardians.

    Parameters
    ----------
    name:
        Human-readable guardian name (used in :attr:`GuardFinding.guardian`).
    """

    def __init__(self, name: str) -> None:
        self.name = name

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        """Guard the parameters of a tool call for security issues.

        Parameters
        ----------
        tool_name:
            The name of the tool being called (e.g. ``execute_shell_command``).
        params:
            The keyword arguments that will be passed to the tool function.

        Returns
        -------
        list[GuardFinding]
            Findings discovered by this guardian.  An empty list means
            no issues were found.
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
