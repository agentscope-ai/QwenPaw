# -*- coding: utf-8 -*-
"""Runtime cache for parsed AgentScope skills."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import frontmatter
from agentscope.skill import Skill

from ...utils.file_snapshot_cache import FileSignature, get_file_snapshot_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SkillRecord:
    name: str
    description: str
    markdown: str
    updated_at: float

    def to_agentscope(self, directory: Path) -> Skill:
        return Skill(
            name=self.name,
            description=self.description,
            dir=os.path.abspath(os.fspath(directory)),
            markdown=self.markdown,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True)
class _ParsedEntry:
    signature: FileSignature
    record: _SkillRecord | None
    byte_size: int


class RuntimeSkillCache:
    """Cache frontmatter and body parsed from runtime ``SKILL.md`` files."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        max_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("cache limits must be positive")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, _ParsedEntry] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def _parse(self, skill_dir: Path) -> _SkillRecord | None:
        skill_md = skill_dir / "SKILL.md"
        cache = get_file_snapshot_cache()
        snapshot = cache.get_bytes(skill_md)
        key = os.path.normcase(os.fspath(snapshot.path))
        with self._lock:
            entry = self._entries.get(key)
            if (
                snapshot.stable
                and entry is not None
                and entry.signature == snapshot.signature
            ):
                self._entries.move_to_end(key)
                return entry.record

            try:
                # Keep AgentScope LocalSkillLoader's strict UTF-8 contract.
                content = snapshot.data.decode("utf-8")
                content = content.replace("\r\n", "\n").replace("\r", "\n")
                post = frontmatter.loads(content)
                name = post.get("name")
                description = post.get("description")
                if not name or not description:
                    logger.warning(
                        "SKILL.md in %s is missing required fields "
                        "(name or description). Skipping.",
                        skill_dir,
                    )
                    record = None
                else:
                    record = _SkillRecord(
                        name=str(name),
                        description=str(description),
                        markdown=post.content,
                        updated_at=snapshot.signature.mtime_ns / 1_000_000_000,
                    )
            except Exception as exc:  # match upstream graceful behavior
                logger.warning(
                    "Failed to load skill from %s: %s",
                    skill_dir,
                    exc,
                )
                record = None

            # An unstable snapshot is safe for this call, but its signature
            # may describe different bytes. Do not reuse its parsed result.
            if not snapshot.stable:
                return record

            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= previous.byte_size
            parsed = _ParsedEntry(
                signature=snapshot.signature,
                record=record,
                byte_size=snapshot.byte_size,
            )
            if parsed.byte_size <= self.max_bytes:
                self._entries[key] = parsed
                self._bytes += parsed.byte_size
                while (
                    len(self._entries) > self.max_entries
                    or self._bytes > self.max_bytes
                ):
                    _, evicted = self._entries.popitem(last=False)
                    self._bytes -= evicted.byte_size
            return record

    def load(self, skill_dirs: Iterable[str | Path]) -> list[Skill]:
        """Return fresh AgentScope values backed by cached parsed records."""
        skills: list[Skill] = []
        for raw_dir in skill_dirs:
            skill_dir = Path(raw_dir)
            try:
                record = self._parse(skill_dir)
            except Exception as exc:  # match AgentScope's per-Skill isolation
                logger.warning(
                    "Failed to load skill from %s: %s",
                    skill_dir,
                    exc,
                )
                continue
            if record is not None:
                skills.append(record.to_agentscope(skill_dir))
        return skills

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0


_RUNTIME_SKILL_CACHE = RuntimeSkillCache()


def load_runtime_skills(skill_dirs: Iterable[str | Path]) -> list[Skill]:
    return _RUNTIME_SKILL_CACHE.load(skill_dirs)


__all__ = [
    "RuntimeSkillCache",
    "load_runtime_skills",
]
