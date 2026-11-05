# -*- coding: utf-8 -*-
"""Construct runtime parameters from global, agent and session settings."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel

from ..constant import WORKING_DIR
from .config import AgentProfileConfig, Config, SessionConfig
from .context import current_runtime_parameters
from .overrides import merge_overrides, _check_fields


def _session_values(value: BaseModel, schema: type[BaseModel]) -> dict:
    """Project an agent model onto the session schema without losing nulls."""
    result = {}
    for name, definition in schema.model_fields.items():
        item = getattr(value, name)
        if isinstance(item, BaseModel):
            annotation = definition.annotation
            if isinstance(annotation, type) and issubclass(
                annotation,
                BaseModel,
            ):
                item = _session_values(item, annotation)
            else:
                item = item.model_dump()
        result[name] = deepcopy(item)
    return result


def _apply_session(
    config: AgentProfileConfig,
    overrides: Mapping,
) -> AgentProfileConfig:
    """Validate only session fields, then preserve agent-owned resources."""
    if not isinstance(overrides, Mapping):
        raise ValueError("Session configuration must be an object")
    values = _session_values(config, SessionConfig)
    patch = deepcopy(dict(overrides))
    if (
        "active_model" in patch
        and patch["active_model"] != values["active_model"]
    ):
        values.update(thinking_level="inherit", thinking_budget=None)
    candidate = SessionConfig.model_validate(
        merge_overrides(values, patch),
        strict=True,
    )
    _check_fields(patch, candidate, "session")
    values = candidate.model_dump()
    if "project_dir" in patch and candidate.project_dir:
        directory = candidate.project_dir
        values["project_dirs"] = [
            next(
                (
                    item
                    for item in candidate.project_dirs
                    if item.get("path") == directory
                ),
                {"path": directory},
            ),
            *(
                item
                for item in candidate.project_dirs
                if item.get("path") != directory
            ),
        ]
    result = AgentProfileConfig.model_validate(
        merge_overrides(config.model_dump(), values),
        strict=True,
    )
    result._runtime_scoped = True  # pylint: disable=protected-access
    return result


@dataclass(frozen=True, kw_only=True)
class RuntimeParameters:
    """A session snapshot with one schema and explicit configuration layers."""

    profile: AgentProfileConfig
    defaults: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    start_mode: bool = True
    _config: AgentProfileConfig = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", self.profile.model_copy(deep=True))
        object.__setattr__(self, "defaults", deepcopy(self.defaults))
        object.__setattr__(self, "overrides", deepcopy(self.overrides))
        object.__setattr__(
            self,
            "_config",
            _apply_session(self.base, self.overrides),
        )

    @classmethod
    def from_profile(
        cls,
        profile: AgentProfileConfig,
        *,
        global_config: Config | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> Self:
        """Use explicit agent values over defaults from the global config."""
        values: dict[str, Any] = {}
        if global_config is not None:
            fields = AgentProfileConfig.model_fields
            for source in (global_config, global_config.agents):
                values.update(
                    {
                        key: value
                        for key, value in source.model_dump().items()
                        if key in fields
                    },
                )
        profile = AgentProfileConfig.model_validate(
            merge_overrides(values, profile.model_dump(exclude_unset=True)),
        )
        if not profile.workspace_dir:
            reference = (
                global_config.agents.profiles.get(profile.id)
                if global_config is not None
                else None
            )
            profile.workspace_dir = (
                reference.workspace_dir
                if reference is not None
                else str(Path(WORKING_DIR) / "workspaces" / profile.id)
            )
        return cls(profile=profile, defaults=defaults or {})

    @property
    def base(self) -> AgentProfileConfig:
        """Return the agent and startup defaults without session overrides."""
        return _apply_session(self.profile, self.defaults)

    @property
    def config(self) -> AgentProfileConfig:
        """Give consumers a detached, fully validated execution snapshot."""
        return self._config.model_copy(deep=True)

    def with_overrides(self, values: Mapping, *, reset: bool = False) -> Self:
        """Replace the snapshot atomically after validating the new layer."""
        if not isinstance(values, Mapping):
            raise ValueError("Session configuration must be an object")
        return replace(
            self,
            overrides=merge_overrides({} if reset else self.overrides, values),
        )

    def with_defaults(self, values: Mapping) -> Self:
        """Apply entry-point defaults below explicit session settings."""
        return replace(self, defaults=merge_overrides(self.defaults, values))

    @contextmanager
    def scope(self) -> Iterator[None]:
        """Bind the snapshot to this task and its child IO operations."""
        token = current_runtime_parameters.set(self)
        try:
            yield
        finally:
            current_runtime_parameters.reset(token)
