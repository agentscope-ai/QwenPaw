"""Immutable, verified skill-only snapshots stored below a controlled root."""

import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
from uuid import uuid4

from ..agents.skill_system.store import scan_skill_dir_or_raise, staged_skill_dir
from .records import SkillSnapshot

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_KEY = re.compile(r"[a-f0-9]{32}\Z")
_PRIVATE = {
    "skill.json",
    "config.json",
    "agent.json",
    "manifest.json",
    "credentials.json",
    "secrets.json",
    ".env",
    ".git",
}


def validate_name(name):
    if not _NAME.fullmatch(name):
        raise ValueError("invalid_skill_name")
    return name


def _check_path(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("unsafe_skill_path")


def directory_hash(root, *, shared=True):
    """Hash every path and byte; shared publication additionally rejects private files."""
    root = Path(root)
    for ancestor in [root, *root.parents]:
        _check_path(ancestor)
    if shared and not (root / "SKILL.md").is_file():
        raise ValueError("missing_skill_document")
    digest = hashlib.sha256()
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            _check_path(path)
            lowered = name.lower()
            if shared and (
                lowered in _PRIVATE
                or lowered.startswith(".env.")
                or lowered.endswith((".pem", ".key"))
            ):
                raise ValueError("private_skill_file")
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big") + relative)
            if path.is_dir():
                digest.update(b"D")
            elif path.is_file():
                content = path.read_bytes()
                digest.update(b"F" + len(content).to_bytes(8, "big") + content)
            else:
                raise ValueError("unsafe_skill_path")
        dirs.sort()
    return digest.hexdigest()


def require_no_shared_credentials(root):
    """Always apply bundled secret signatures, independent of optional scan policy."""
    try:
        import yaml
        from ..security.skill_scanner.analyzers import pattern_analyzer

        rules_path = (
            Path(pattern_analyzer.__file__).parents[1]
            / "rules"
            / "signatures"
            / "hardcoded_secrets.yaml"
        )
        entries = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list) or not entries:
            raise RuntimeError("missing_secret_rules")
        rules = [pattern_analyzer.SecurityRule(entry) for entry in entries]
        if any(
            not rule.patterns or len(rule.compiled_patterns) != len(rule.patterns)
            for rule in rules
        ):
            raise RuntimeError("invalid_secret_rules")
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            content = (
                path.read_bytes()
                .decode("utf-8", errors="replace")
                .replace("\r\n", "\n")
            )
            for rule in rules:
                # Shared publication does not honor optional file/doc/placeholder exclusions.
                for pattern in rule.compiled_patterns:
                    for match in pattern.finditer(content):
                        value = match.group(0)
                        if rule.id == "SECRET_PASSWORD_VAR" and re.fullmatch(
                            r"[^=]+=\s*['\"](?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%)['\"]",
                            value,
                        ):
                            continue
                        if rule.id == "SECRET_CONNECTION_STRING" and re.fullmatch(
                            r"[^:]+://[^:@]+:(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%)@",
                            value,
                        ):
                            continue
                        raise ValueError("shared_skill_credentials_detected")
    except ValueError as exc:
        if str(exc) == "shared_skill_credentials_detected":
            raise
        raise ValueError("shared_skill_credential_scan_failed") from exc
    except Exception as exc:
        raise ValueError("shared_skill_credential_scan_failed") from exc


class SnapshotStore:
    def __init__(self, root):
        self.root = Path(root)

    def capture(self, source, name):
        validate_name(name)
        source = Path(source)
        original = directory_hash(source)
        with staged_skill_dir(name) as staged:
            shutil.copytree(source, staged, symlinks=True)
            if directory_hash(staged) != original:
                raise ValueError("snapshot_source_changed")
            require_no_shared_credentials(staged)
            scan_skill_dir_or_raise(staged, name)
            self.root.mkdir(parents=True, exist_ok=True)
            for ancestor in [self.root, *self.root.parents]:
                _check_path(ancestor)
            key = uuid4().hex
            target = self.root / key
            # UUID destinations are never replaced; incomplete copies have no DB reference.
            shutil.copytree(staged, target, symlinks=True)
            if directory_hash(target) != original:
                raise ValueError("snapshot_integrity_failed")
        return SkillSnapshot(key, original)

    def verify(self, key, expected_hash):
        if not _KEY.fullmatch(key):
            raise ValueError("invalid_snapshot_key")
        target = self.root / key
        try:
            actual = directory_hash(target)
        except (OSError, ValueError) as exc:
            raise ValueError("snapshot_integrity_failed") from exc
        if actual != expected_hash:
            raise ValueError("snapshot_integrity_failed")
        require_no_shared_credentials(target)
        return target
