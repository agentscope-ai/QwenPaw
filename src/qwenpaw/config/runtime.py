# -*- coding: utf-8 -*-
"""Construct runtime parameters from global, agent and session settings."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self, TypeVar

from pydantic import BaseModel

from ..constant import WORKING_DIR
from .config import AgentProfileConfig, Config, ModelSlotConfig, SessionConfig
from .context import current_runtime_parameters
from .overrides import merge_overrides, _check_fields

_Model = TypeVar("_Model", bound=BaseModel)


def merge_session_overrides(base: Mapping, values: Mapping) -> dict:
    """Merge overrides while keeping the primary and directory list aligned."""
    patch = dict(values)
    if "project_dirs" in patch:
        patch.setdefault("project_dir", None)
    elif "project_dir" in patch and patch["project_dir"] is None:
        patch["project_dirs"] = []
    return merge_overrides(base, patch)


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


def _with_validated_fields(model: _Model, validated: BaseModel) -> _Model:
    """Apply validated fields while retaining the model's extended schema."""
    updates = {}
    for name, value in validated:
        original = getattr(model, name)
        if isinstance(value, BaseModel) and type(original) is not type(value):
            if isinstance(original, type(value)):
                value = _with_validated_fields(original, value)
        updates[name] = value
    return model.model_copy(update=updates, deep=True)


def _apply_session(
    config: AgentProfileConfig,
    overrides: Mapping,
    fallback_model: ModelSlotConfig | None,
) -> AgentProfileConfig:
    """Validate only session fields, then preserve agent-owned resources."""
    if not isinstance(overrides, Mapping):
        raise ValueError("Session configuration must be an object")
    values = _session_values(config, SessionConfig)
    patch = deepcopy(dict(overrides))
    if fallback_model is not None:
        active_model = config.active_model
        if active_model is not None:
            values["active_model"] = merge_overrides(
                fallback_model.model_dump(),
                active_model.model_dump(exclude_unset=True),
            )
        elif isinstance(patch.get("active_model"), dict):
            values["active_model"] = fallback_model.model_dump()
    if (
        "active_model" in patch
        and merge_overrides(values, patch)["active_model"]
        != values["active_model"]
    ):
        values.update(thinking_level="inherit", thinking_budget=None)
    candidate = SessionConfig.model_validate(
        merge_overrides(values, patch),
        strict=True,
    )
    _check_fields(patch, candidate, "session")
    if "project_dir" in patch and candidate.project_dir:
        directory = candidate.project_dir
        candidate.project_dirs = [
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
    elif "project_dirs" in patch:
        candidate.project_dir = next(
            (
                path
                for item in candidate.project_dirs
                if isinstance(path := item.get("path"), str) and path.strip()
            ),
            None,
        )
    elif "project_dir" in patch:
        candidate.project_dirs = []
    result = _with_validated_fields(config, candidate)
    result._runtime_scoped = True  # pylint: disable=protected-access
    return result


@dataclass(frozen=True, kw_only=True)
class RuntimeParameters:
    """A session snapshot with one schema and explicit configuration layers."""

    profile: AgentProfileConfig
    defaults: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    mode_defaults: dict[str, Any] = field(default_factory=dict)
    restored_mode: str | None = None
    fallback_model: ModelSlotConfig | None = None
    _config: AgentProfileConfig = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", self.profile.model_copy(deep=True))
        object.__setattr__(self, "defaults", deepcopy(self.defaults))
        object.__setattr__(self, "mode_defaults", deepcopy(self.mode_defaults))
        object.__setattr__(self, "overrides", deepcopy(self.overrides))
        fallback = deepcopy(self.fallback_model)
        object.__setattr__(self, "fallback_model", fallback)
        object.__setattr__(
            self,
            "_config",
            _apply_session(self.base, self.overrides, fallback),
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
        profile = profile.model_copy(deep=True)
        if global_config is not None:
            values: dict[str, Any] = {}
            fields = AgentProfileConfig.model_fields
            for source in (global_config, global_config.agents):
                values.update(
                    source.model_dump(
                        include=fields.keys()
                        & type(source).model_fields.keys(),
                    ),
                )
            inherited = AgentProfileConfig.model_validate(
                merge_overrides(
                    {**values, "id": profile.id, "name": profile.name},
                    profile.model_dump(
                        include=set(values),
                        exclude_unset=True,
                    ),
                ),
            )
            profile = profile.model_copy(
                update={key: getattr(inherited, key) for key in values},
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
        profile = _apply_session(
            self.profile,
            self.mode_defaults,
            self.fallback_model,
        )
        return _apply_session(profile, self.defaults, self.fallback_model)

    @property
    def config(self) -> AgentProfileConfig:
        """Give consumers a detached, fully validated execution snapshot."""
        return self._config.model_copy(deep=True)

    @property
    def model_slot_override(self) -> ModelSlotConfig | None:
        """Preserve an explicit model selection for the Provider factory."""
        slot = self._config.active_model
        if (
            slot is not None
            and slot.provider_id
            and slot.model
            and (
                self.overrides.get("active_model")
                or self.defaults.get("active_model")
            )
        ):
            return slot.model_copy()
        return None

    def with_overrides(self, values: Mapping) -> Self:
        """Replace the snapshot atomically after validating the new layer."""
        if not isinstance(values, Mapping):
            raise ValueError("Session configuration must be an object")
        return replace(
            self,
            overrides=merge_session_overrides(self.overrides, values),
        )

    @contextmanager
    def scope(self) -> Iterator[None]:
        """Bind the snapshot to this task and its child IO operations."""
        token = current_runtime_parameters.set(self)
        try:
            yield
        finally:
            current_runtime_parameters.reset(token)
