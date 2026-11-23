# -*- coding: utf-8 -*-
"""Read-only checks shared by consumers of the doctor contract."""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from .errors import SDKError
from .extensions import ExtensionPoint


@dataclass(frozen=True)
class DoctorResult:
    """One observed check outcome; SKIP means the check was not performed."""

    status: Literal["OK", "FAIL", "SKIP"]
    message: str

    def __post_init__(self):
        if self.status not in {"OK", "FAIL", "SKIP"}:
            raise ValueError("Doctor status must be OK, FAIL or SKIP")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("Doctor result must include a message")


@dataclass(frozen=True)
class DoctorContext:
    """The same configuration and target used by core doctor checks.

    selected_providers contains the global default and enabled agents' primary
    providers. A configured selection does not imply an activated provider.
    """

    config: dict[str, Any] | None
    raw_config: dict[str, Any] | None
    base_url: str
    timeout: float
    deep: bool
    _get_runtime: Callable[[str], Awaitable[Any]] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    selected_providers: frozenset[str] = field(default_factory=frozenset)

    async def get_runtime(self, path: str) -> Any:
        """Read JSON from the selected runtime using its host-owned credentials.

        The path is relative to the runtime's API root. This operation only
        sends GET requests. It never starts the App or a plugin service.
        """
        if self._get_runtime is None:
            raise SDKError("The consumer does not provide runtime API access")
        return await self._get_runtime(path)


_DoctorNotes = list[str] | list[DoctorResult] | list[str | DoctorResult]


@dataclass(frozen=True)
class DoctorSpec:
    """Return check outcomes or notes without starting providers or channels."""

    id: str
    check: Callable[
        [DoctorContext],
        _DoctorNotes | Awaitable[_DoctorNotes],
    ]

    def __post_init__(self):
        if not callable(self.check):
            raise ValueError("DoctorSpec.check must be callable")


DOCTOR = ExtensionPoint("qwenpaw.doctor", DoctorSpec)
