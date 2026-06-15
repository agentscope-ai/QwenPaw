# -*- coding: utf-8 -*-
"""YAML storage helpers for DriverCard files."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import yaml

from .constants import (
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
    POLICY_TARGET_WILDCARD,
)
from .errors import DriverCardError
from .contracts import (
    CredentialRef,
    DriverCard,
    coerce_card,
    validate_card,
    validate_card_name,
)
from .policy_types import (
    DriverPolicy,
    PolicyEffect,
    PolicyCondition,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
    PolicyTargetKind,
    TimeRange,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AsyncDriverCardStore",
    "card_path",
    "card_paths_for_name",
    "delete_card",
    "delete_card_paths_for_name",
    "dump_card",
    "list_card_paths",
    "load_card",
]


class AsyncDriverCardStore:
    """Async facade for filesystem-backed DriverCard storage."""

    def __init__(self, cards_dir: Path) -> None:
        self._cards_dir = cards_dir

    @property
    def cards_dir(self) -> Path:
        """Return the root directory used for DriverCard files."""
        return self._cards_dir

    def path_for(self, name: str, *, protocol: str) -> Path:
        """Return the canonical YAML path for one DriverCard name."""
        return card_path(self._cards_dir, name, protocol=protocol)

    async def load(self, name: str, *, protocol: str) -> DriverCard:
        """Load one DriverCard by name and protocol."""
        return await asyncio.to_thread(self._load_sync, name, protocol)

    async def load_path(self, path: Path) -> DriverCard:
        """Load one DriverCard from a concrete path."""
        return await asyncio.to_thread(load_card, path)

    async def list_paths(self) -> list[Path]:
        """Return sorted protocol-scoped DriverCard YAML paths."""
        return await asyncio.to_thread(list_card_paths, self._cards_dir)

    async def save(self, card: DriverCard) -> Path:
        """Persist one DriverCard and remove stale same-name card files."""
        return await asyncio.to_thread(self._save_sync, card)

    async def delete(self, name: str) -> None:
        """Delete stored card files for one Driver name."""
        await asyncio.to_thread(
            delete_card_paths_for_name,
            self._cards_dir,
            name,
        )

    async def stored_path(self, name: str) -> Path | None:
        """Return the first stored DriverCard path for a name, if any."""
        return await asyncio.to_thread(self._stored_path_sync, name)

    async def snapshot(self) -> dict[str, tuple[str, float]]:
        """Return a lightweight snapshot for change detection."""
        return await asyncio.to_thread(self._snapshot_sync)

    def _load_sync(self, name: str, protocol: str) -> DriverCard:
        path = self.path_for(name, protocol=protocol)
        return load_card(path)

    def _save_sync(self, card: DriverCard) -> Path:
        path = self.path_for(card.name, protocol=card.protocol)
        dump_card(card, path)
        delete_card_paths_for_name(self._cards_dir, card.name, keep=path)
        return path

    def _stored_path_sync(self, name: str) -> Path | None:
        paths = card_paths_for_name(self._cards_dir, name)
        if paths:
            return paths[0]
        return None

    def _snapshot_sync(self) -> dict[str, tuple[str, float]]:
        snapshot: dict[str, tuple[str, float]] = {}
        paths_by_name: dict[str, str] = {}
        for path in list_card_paths(self._cards_dir):
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            relative_path = path.relative_to(self._cards_dir).as_posix()
            driver_name = path.stem
            previous_path = paths_by_name.get(driver_name)
            if previous_path is not None:
                logger.warning(
                    "Duplicate DriverCard name '%s' found at %s and %s; "
                    "Driver runtime names are globally unique",
                    driver_name,
                    previous_path,
                    relative_path,
                )
            else:
                paths_by_name[driver_name] = relative_path
            snapshot[relative_path] = (
                driver_name,
                mtime,
            )
        return snapshot


def load_card(path: Path) -> DriverCard:
    """Load one DriverCard from YAML."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DriverCardError(
            f"Failed to read DriverCard {path}: {exc}",
        ) from exc
    except yaml.YAMLError as exc:
        raise DriverCardError(
            f"Failed to parse DriverCard YAML {path}: {exc}",
        ) from exc

    if not isinstance(raw, dict):
        raise DriverCardError(f"DriverCard YAML must be a mapping: {path}")

    card = coerce_card(_card_from_mapping(raw, path))
    validate_card(card)
    return card


def dump_card(card: DriverCard, path: Path) -> None:
    """Atomically write one DriverCard to YAML."""
    card = coerce_card(card)
    validate_card(card)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _card_to_mapping(card)

    tmp_name = ""
    try:
        serialized = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
        )
        try:
            if (
                path.is_file()
                and path.read_text(encoding="utf-8") == serialized
            ):
                return
        except OSError:
            pass
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(serialized)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except Exception as exc:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, DriverCardError):
            raise
        raise DriverCardError(
            f"Failed to write DriverCard {path}: {exc}",
        ) from exc


def list_card_paths(cards_dir: Path) -> list[Path]:
    """Return sorted protocol-scoped DriverCard YAML paths."""
    if not cards_dir.is_dir():
        return []
    paths = []
    for path in cards_dir.rglob("*"):
        if not _is_visible_card_file(cards_dir, path):
            continue
        paths.append(path)
    return sorted(
        paths,
        key=lambda item: item.relative_to(cards_dir).as_posix(),
    )


def card_path(
    cards_dir: Path,
    name: str,
    protocol: str,
) -> Path:
    """Return the canonical YAML path for one DriverCard name."""
    validate_card_name(name)
    path = cards_dir / _protocol_path(protocol) / f"{name}.yaml"
    _ensure_path_under(cards_dir, path)
    return path


def card_paths_for_name(cards_dir: Path, name: str) -> list[Path]:
    """Return all stored paths whose YAML filename matches the card name."""
    validate_card_name(name)
    return [path for path in list_card_paths(cards_dir) if path.stem == name]


def delete_card_paths_for_name(
    cards_dir: Path,
    name: str,
    *,
    keep: Path | None = None,
) -> None:
    """Delete stored card files with this name except optional keep path."""
    keep_resolved = keep.resolve() if keep is not None else None
    for path in card_paths_for_name(cards_dir, name):
        if keep_resolved is not None and path.resolve() == keep_resolved:
            continue
        delete_card(path)


def delete_card(path: Path) -> None:
    """Delete one DriverCard YAML file if present."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise DriverCardError(
            f"Failed to delete DriverCard {path}: {exc}",
        ) from exc


def _is_visible_card_file(cards_dir: Path, path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        return False
    try:
        relative_parts = path.relative_to(cards_dir).parts
    except ValueError:
        return False
    return len(relative_parts) >= 2 and not any(
        part.startswith(".") for part in relative_parts
    )


def _protocol_path(protocol: str) -> Path:
    parts = [
        part.strip()
        for part in str(protocol).split("/")
        if part.strip() and part.strip() not in {".", ".."}
    ]
    if not parts:
        raise DriverCardError("DriverCard protocol must be non-empty")
    return Path(*parts)


def _ensure_path_under(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise DriverCardError(
            f"DriverCard path escapes storage directory: {path}",
        ) from exc


def _card_from_mapping(data: dict[str, Any], path: Path) -> DriverCard:
    required = {"name", "protocol", "endpoint"}
    missing = sorted(required - set(data))
    if missing:
        raise DriverCardError(
            f"DriverCard {path} missing required fields: {', '.join(missing)}",
        )

    credentials = data.get("credentials", {})
    if credentials is None:
        credentials = {}
    if not isinstance(credentials, dict):
        raise DriverCardError(
            f"DriverCard {path} credentials must be a mapping",
        )

    endpoint = data["endpoint"]
    if not isinstance(endpoint, dict):
        raise DriverCardError(f"DriverCard {path} endpoint must be a mapping")

    config = data.get("config", {})
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise DriverCardError(f"DriverCard {path} config must be a mapping")

    return DriverCard(
        name=str(data["name"]),
        protocol=str(data["protocol"]),
        endpoint=dict(endpoint),
        credentials={
            str(alias): CredentialRef(
                kind=str(ref.get("kind", "")),
                ref=str(ref.get("ref", "")),
            )
            for alias, ref in credentials.items()
            if isinstance(ref, dict)
        },
        config=dict(config),
        enabled=bool(data.get("enabled", True)),
        policy=_policy_from_mapping(data.get("policy"), path),
    )


def _card_to_mapping(card: DriverCard) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": card.name,
        "protocol": card.protocol,
        "endpoint": card.endpoint,
        "credentials": {
            alias: asdict(ref) for alias, ref in card.credentials.items()
        },
        "config": card.config,
        "enabled": card.enabled,
        "policy": asdict(card.policy),
    }
    return payload


def _policy_from_mapping(value: Any, path: Path) -> DriverPolicy:
    if value is None:
        return DriverPolicy()
    if isinstance(value, list):
        return DriverPolicy(
            default_effect=POLICY_EFFECT_DENY,
            rules=[_policy_rule_from_mapping(item, path) for item in value],
        )
    if not isinstance(value, dict):
        raise DriverCardError(
            f"DriverCard {path} policy must be a mapping or legacy list",
        )

    rules_raw = value.get("rules", [])
    if rules_raw is None:
        rules_raw = []
    if not isinstance(rules_raw, list):
        raise DriverCardError(f"DriverCard {path} policy.rules must be a list")
    return DriverPolicy(
        default_effect=cast(
            PolicyEffect,
            str(value.get("default_effect") or POLICY_EFFECT_DENY),
        ),
        rules=[_policy_rule_from_mapping(item, path) for item in rules_raw],
    )


def _policy_rule_from_mapping(value: Any, path: Path) -> PolicyRule:
    if not isinstance(value, dict):
        raise DriverCardError(
            f"DriverCard {path} policy rule must be a mapping",
        )
    condition = value.get("condition")
    return PolicyRule(
        subject=str(value.get("subject") or POLICY_TARGET_WILDCARD),
        effect=cast(
            PolicyEffect,
            str(value.get("effect") or POLICY_EFFECT_ASK),
        ),
        target=_policy_target_from_mapping(value.get("target"), path),
        principal=_policy_principal_from_mapping(value.get("principal"), path),
        condition=_condition_from_mapping(condition, path),
    )


def _policy_target_from_mapping(value: Any, path: Path) -> PolicyTarget:
    if value is None:
        return PolicyTarget()
    if not isinstance(value, dict):
        raise DriverCardError(
            f"DriverCard {path} policy target must be a mapping",
        )
    return PolicyTarget(
        kind=cast(
            PolicyTargetKind,
            str(value.get("kind") or POLICY_TARGET_WILDCARD),
        ),
        name=str(value.get("name") or POLICY_TARGET_WILDCARD),
    )


def _policy_principal_from_mapping(value: Any, path: Path) -> PolicyPrincipal:
    if value is None:
        return PolicyPrincipal()
    if not isinstance(value, dict):
        raise DriverCardError(
            f"DriverCard {path} policy principal must be a mapping",
        )
    return PolicyPrincipal(
        source_type=_policy_selector_from_mapping(value, "source_type"),
        source_value=_policy_selector_from_mapping(value, "source_value"),
        subject_type=_policy_selector_from_mapping(value, "subject_type"),
        subject_value=_policy_selector_from_mapping(value, "subject_value"),
    )


def _policy_selector_from_mapping(value: dict[str, Any], key: str) -> str:
    if key not in value or value[key] is None:
        return POLICY_TARGET_WILDCARD
    return str(value[key])


def _condition_from_mapping(
    value: Any,
    path: Path,
) -> PolicyCondition | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DriverCardError(f"DriverCard {path} condition must be a mapping")
    if "rate_limit" in value:
        raise DriverCardError(
            f"DriverCard {path} policy condition rate_limit is not supported",
        )

    time_range = value.get("time_range")
    return PolicyCondition(
        time_range=_time_range_from_mapping(time_range, path),
    )


def _time_range_from_mapping(value: Any, path: Path) -> TimeRange | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DriverCardError(
            f"DriverCard {path} time_range must be a mapping",
        )
    weekdays = value.get("weekdays")
    return TimeRange(
        after=value.get("after"),
        before=value.get("before"),
        weekdays=list(weekdays) if weekdays is not None else None,
    )
