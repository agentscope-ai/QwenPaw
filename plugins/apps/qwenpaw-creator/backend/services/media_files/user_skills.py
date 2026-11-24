# -*- coding: utf-8 -*-
"""User-created Creator skills persisted to the data root.

Content-based (name + SKILL.md body), mirroring the QwenPaw skill-add
UX. The body is written to ``$CREATOR_DATA_ROOT/skills/<name>/SKILL.md``
and the directory is registered in ``skills_config.json`` so the existing
loader (``services.external_skills.load_skills``) picks it up unchanged.

Skills are domain knowledge only: this module never executes skill code
and never grants a skill any capability beyond the SKILL.md text.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from models.config import (
    load_skills_config,
    load_skills_config_issues,
    write_skills_config,
)
from schemas.skills import SkillEntry
from services.external_skills import (
    _BUILTIN_SKILLS_ROOT,
    _clear_load_cache,
    parse_skill_md,
)
from services.runtime_files.atomic_store import atomic_replace_bytes
from services.skill_hub import HubBundle
from services.storage_root import require_creator_data_root
from utils.logger import setup_logger

logger = setup_logger("services.media_files.user_skills")

_USER_SKILL_DIR_NAME = "skills"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# Mirrors SkillEntry.name's max_length: an over-long name that only fails
# registration would leave SKILL.md written and the directory unregistered,
# which no delete can then remove (delete only drops registered entries) and
# which makes the name permanently "taken" for every later create.
_MAX_NAME_CHARS = 64
# Skills are plain-text domain knowledge; 32 MiB is far beyond any real
# SKILL.md bundle and stops accidental huge uploads before extraction.
MAX_SKILL_ZIP_BYTES = 32 * 1024 * 1024
# A skill bundle is text, so it carries its own budget instead of inheriting
# the Project archive's 16 GiB expansion headroom and 20000 members. The
# extractor enforces these against the bytes actually written, which also
# covers a member declaring less than it carries.
_MAX_SKILL_EXTRACTED_BYTES = 32 * 1024 * 1024
_MAX_SKILL_MEMBERS = 256
# One SKILL.md is parsed whole and then written to the data root, so this
# bounds both the memory one document can take and what can land there, for
# every writer (editor save, ZIP member, hub bundle). Attachments are
# deliberately not capped per member (they are discarded, and a total cap
# already bounds them).
_MAX_SKILL_DOC_BYTES = 1024 * 1024
# Serializes the read-modify-write of skills_config.json for every writer
# (route work dispatched through asyncio.to_thread, plus the ZIP import
# worker) so concurrent save/toggle/delete/import cannot lose each other's
# updates. Single-process mutual exclusion is the documented project-wide
# topology (see services/runtime_files/locking.py): a multi-process
# deployment would need a real advisory lock file, since atomic_replace_bytes
# guarantees a whole-file swap but not a read-modify-write transaction.
# CrossProcessFileLock is not that lock -- despite its name it is
# process-local and never creates a file.
_CONFIG_LOCK = threading.RLock()
# Upper bound for one skipped-member reason: it travels to the client, and
# parse/OS failures quote the offending path and payload back.
_MAX_SKIP_REASON_CHARS = 400


class UserSkillError(ValueError):
    """A user skill save/delete request that must be refused."""


def _skills_config_path() -> Path:
    """Where ``write_skills_config`` would persist the document.

    Mirrors the writer instead of the reader: the reader falls back to a
    read-only sentinel, while an explicit ``CREATOR_SKILLS_CONFIG_PATH``
    still wins over the data root here.
    """

    configured = os.environ.get("CREATOR_SKILLS_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return require_creator_data_root() / "config" / "skills_config.json"


def _require_repairable_config() -> None:
    """Refuse a full write-back while the document still holds bad entries.

    ``load_skills_config`` deliberately returns only the validated subset, so
    writing it back would delete every entry the tolerant reader preserved as
    a diagnostic -- including ones unrelated to this request. Invalid rows
    cannot be removed through the UI either (they never reach the valid
    subset), so an ordinary toggle of another skill would be the only thing
    that silently destroyed them.
    """

    issues = load_skills_config_issues()
    if not issues:
        return
    names = ", ".join(str(issue.get("name") or "?") for issue in issues[:5])
    target = _skills_config_path()
    logger.warning(
        "user skill write refused: %d rejected entries in %s: %s",
        len(issues),
        target,
        names,
    )
    detail = "；".join(
        (
            f"skills_config.json 存在被拒绝的条目（{names}）",
            "为避免丢失无关配置已拒绝写入",
            f"请先修复 {target}",
        ),
    )
    raise UserSkillError(detail)


def _skills_root() -> Path:
    directory = require_creator_data_root() / _USER_SKILL_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _validated_dir(name: str) -> Path:
    # The regex rejects separators and "..", so the resolved directory can
    # never escape the managed skills root.
    if not _NAME_RE.match(name or ""):
        raise UserSkillError(
            "技能名只能包含小写字母、数字、点、下划线、连字符，且以字母或数字开头",
        )
    if len(name) > _MAX_NAME_CHARS:
        raise UserSkillError(
            f"技能名最多 {_MAX_NAME_CHARS} 个字符（当前 {len(name)}）",
        )
    return _skills_root() / name


def _managed_skill_names() -> set[str]:
    """Names already occupied under the managed skills root.

    Includes directories holding a hand-authored SKILL.md that never made it
    into the config: that content is invisible to the panel and unrecoverable
    once a duplicate create replaces it.
    """

    try:
        return {
            path.name
            for path in _skills_root().iterdir()
            if (path / "SKILL.md").is_file()
        }
    except OSError:
        return set()


def save_user_skill(
    name: str,
    content: str,
    *,
    overwrite: bool = False,
) -> SkillEntry:
    """Write SKILL.md content and register/refresh its config entry.

    ``overwrite`` states the caller's intent, which the endpoint cannot
    recover on its own: the name is a skill's only identity, so a create that
    lands on an occupied name silently replaces the SKILL.md (and the entry)
    of the skill already living there. The UI fixes the name while editing an
    existing skill and leaves it free while creating one, so it passes True
    for the former and gets refused for the latter.
    """

    directory = _validated_dir(name)
    # Encoded once: the budget check and the write both need these bytes, and
    # checking before parse_skill_md refuses an oversized document before the
    # YAML parse rather than after it.
    encoded = content.encode("utf-8")
    if len(encoded) > _MAX_SKILL_DOC_BYTES:
        raise UserSkillError(_skill_doc_too_large_detail())
    try:
        parse_skill_md(content)
    except Exception as exc:
        raise UserSkillError(
            f"SKILL.md 格式无效（需要 --- front matter --- 头部）：{exc}",
        ) from exc
    with _CONFIG_LOCK:
        _require_repairable_config()
        entries = list(load_skills_config())
        existing = next((item for item in entries if item.name == name), None)
        if existing is None and name in _builtin_skill_names():
            # Overriding a builtin stays a deployment decision taken through
            # an explicit skills_config.json entry; an ordinary create must
            # not shadow one silently because the UI renders builtins as
            # read-only and would then hide the original content.
            raise UserSkillError(
                f"技能名与内置技能同名，保存将覆盖内置内容: {name}",
            )
        if not overwrite and (
            existing is not None or (directory / "SKILL.md").is_file()
        ):
            # Either occupant counts: a registered entry means the panel was
            # showing that skill (editing it is the overwrite=True path), and
            # an unregistered SKILL.md means hand-authored content that no
            # listing would ever reveal before it got destroyed.
            raise UserSkillError(
                f"技能名已存在: {name}；如需修改请在技能列表中编辑该技能",
            )
        # Publish SKILL.md and register the entry in one critical section so
        # a concurrent delete cannot remove the directory in between and leave
        # a registered entry whose file is gone (resurrected as unavailable).
        directory.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(directory / "SKILL.md", encoded)
        if existing is not None:
            entry = existing.model_copy(update={"path": str(directory)})
            entries = [
                entry if item.name == name else item for item in entries
            ]
        else:
            entry = SkillEntry(name=name, path=str(directory), enabled=True)
            entries.append(entry)
        write_skills_config(entries)
        _clear_load_cache()
    return entry


def _locate_skill_dirs(root: Path) -> list[Path]:
    """One skill (SKILL.md at the root) or many (one per subdir)."""

    if (root / "SKILL.md").is_file():
        return [root]
    found = []
    for child in sorted(root.iterdir()):
        if (
            child.is_dir()
            and not child.is_symlink()
            and (child / "SKILL.md").is_file()
        ):
            found.append(child)
    return found


def _builtin_skill_names() -> set[str]:
    try:
        return {
            path.name
            for path in _BUILTIN_SKILLS_ROOT.iterdir()
            if path.is_dir()
        }
    except OSError:
        return set()


def zip_too_large_detail() -> str:
    """Refusal text shared by the upload route and the importer.

    The route needs it before it has read anything, the importer needs it
    because it is also reachable without that route; one source keeps the
    two answers identical.
    """

    return f"ZIP 超过 {MAX_SKILL_ZIP_BYTES // (1024 * 1024)}MB 上限"


def _skill_doc_too_large_detail() -> str:
    """Refusal text shared by every path that writes a SKILL.md.

    The ZIP importer reports it as a skipped member and ``save_user_skill``
    raises it as a request failure; one source keeps the limit and its wording
    from drifting apart between the two.
    """

    return f"SKILL.md 超过 {_MAX_SKILL_DOC_BYTES // 1024}KB 上限"


def _read_skill_doc(path: Path) -> str:
    """Read one SKILL.md within the document budget.

    ``read_text`` would buffer a member of whatever size the archive budget
    allowed; reading one byte past the cap keeps both this member's memory
    and what can reach the data root bounded, and turns an oversized
    document into a reported skip instead of an allocation.
    """

    with path.open("rb") as handle:
        raw = handle.read(_MAX_SKILL_DOC_BYTES + 1)
    if len(raw) > _MAX_SKILL_DOC_BYTES:
        raise UserSkillError(_skill_doc_too_large_detail())
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserSkillError(f"SKILL.md 不是有效的 UTF-8 文本：{exc}") from exc


def import_skills_from_zip_bytes(data: bytes) -> dict:
    """Extract an uploaded zip and install each SKILL.md as a user skill.

    Reuses the Project archive extractor, so zip-slip, symlink and
    expansion-bomb members are rejected before anything touches disk. A
    zip may carry a single skill (SKILL.md at the root) or several (one
    directory each). Builtin-name collisions, names that an existing skill
    already occupies and invalid skills are skipped and reported rather than
    overwriting anything or aborting the whole import.
    """

    if len(data) > MAX_SKILL_ZIP_BYTES:
        raise UserSkillError(zip_too_large_detail())
    from domain.errors import BadRequestError
    from services.project_files.archive import (
        archive_limits,
        extract_archive,
    )

    imported: list[str] = []
    skipped: list[dict] = []
    builtin = _builtin_skill_names()
    # Snapshot of the names an import may not replace. The strict create below
    # stays the authoritative guard (this races a concurrent save); the check
    # here only turns an expected collision into a clean reported skip instead
    # of a logged traceback for an ordinary business refusal.
    occupied = {item.name for item in load_skills_config()}
    occupied |= _managed_skill_names()
    with tempfile.TemporaryDirectory(prefix="creator-skill-") as tmp:
        extract_dir = Path(tmp) / "extract"
        extract_dir.mkdir(mode=0o700)
        zip_path = Path(tmp) / "upload.zip"
        zip_path.write_bytes(data)
        try:
            extract_archive(
                zip_path,
                extract_dir,
                limits=archive_limits(
                    max_archive_bytes=MAX_SKILL_ZIP_BYTES,
                    max_extracted_bytes=_MAX_SKILL_EXTRACTED_BYTES,
                    max_members=_MAX_SKILL_MEMBERS,
                ),
            )
        except BadRequestError as exc:
            raise UserSkillError(f"ZIP 无效：{exc}") from exc
        skill_dirs = _locate_skill_dirs(extract_dir)
        if not skill_dirs:
            raise UserSkillError(
                "ZIP 中未找到 SKILL.md（技能需包含 SKILL.md 文件）",
            )
        for directory in skill_dirs:
            label = directory.name
            try:
                content = _read_skill_doc(directory / "SKILL.md")
                parsed = parse_skill_md(content)
                fm_name = (parsed.get("name") or "").strip()
                if _NAME_RE.match(fm_name):
                    name = fm_name
                elif directory != extract_dir:
                    name = directory.name
                else:
                    skipped.append(
                        {
                            "name": label,
                            "reason": "SKILL.md 缺少合规的 name 字段",
                        },
                    )
                    continue
                if name in builtin:
                    skipped.append(
                        {"name": name, "reason": "与内置技能同名"},
                    )
                    continue
                if name in occupied:
                    # Covers a skill the data root already has and a second
                    # member reusing a name installed earlier in this zip.
                    skipped.append(
                        {
                            "name": label,
                            "reason": f"技能名 {name} 已存在，未覆盖",
                        },
                    )
                    continue
                save_user_skill(name, content)
                imported.append(name)
                occupied.add(name)
            except Exception as exc:
                # One bad member must never abort the batch: parse_skill_md
                # re-raises PyYAML errors (ParserError/ScannerError) which are
                # not ValueError subclasses, and a narrow tuple would let them
                # escape as a 500 after some skills were already installed and
                # before the rest were even looked at.
                #
                # A catch-all also hides our own defects, so keep the
                # traceback on the server and bound what the client sees.
                logger.warning(
                    "skill zip member skipped: name=%s",
                    label,
                    exc_info=True,
                )
                skipped.append(
                    {
                        "name": label,
                        "reason": str(exc)[:_MAX_SKIP_REASON_CHARS],
                    },
                )
    return {"imported": imported, "skipped": skipped, "count": len(imported)}


def _hub_skill_name(remote: str) -> tuple[str, str | None]:
    """Map a hub skill name onto the managed naming rule.

    A market name is display text, not an identifier: ``Excel / XLSX`` and
    ``My Skill`` both arrive from real bundles, while a skill directory must
    be a lowercase slug. Rather than refusing the import, fold it the way the
    host folds its own names and report the original so the caller can say
    which name landed. Nothing here can silently land on an occupied name:
    the strict ``save_user_skill`` create below still decides that.
    """

    if _NAME_RE.match(remote):
        return remote, None
    slug = re.sub(r"[^a-z0-9]+", "-", remote.lower()).strip("-")
    if _NAME_RE.match(slug):
        return slug, remote or None
    raise UserSkillError(
        f"远端技能名不合规，无法用作技能标识: {remote or '(空)'}；" "请自行填写技能名后重试",
    )


def install_skill_from_hub_bundle(bundle: HubBundle) -> dict:
    """Register a hub-fetched bundle as a user skill (SKILL.md only).

    Mirrors ``import_skills_from_zip_bytes`` in what it promises: only
    SKILL.md reaches the data root, and an occupied name is refused instead
    of replaced. The difference is that a one-skill import reports its
    failure as an error rather than a skipped member, because the caller
    asked for exactly this skill.
    """

    name, renamed_from = _hub_skill_name((bundle.name or "").strip())
    # The SKILL.md text is the whole product: Creator's loader reads only
    # SKILL.md and a skill is granted no capability beyond that text, so the
    # bundle's references/scripts/extra_files are counted and reported
    # instead of being written next to it.
    entry = save_user_skill(name, bundle.content)
    return {
        "imported": [entry.name],
        "skipped": [],
        "count": 1,
        "name": entry.name,
        "renamed_from": renamed_from,
        "source_url": bundle.source_url,
        "installed_from": bundle.installed_from,
        "ignored_files": bundle.ignored_files,
    }


def set_user_skill_enabled(name: str, enabled: bool) -> bool:
    """Toggle a configured (non-builtin) skill; report whether it changed."""

    with _CONFIG_LOCK:
        _require_repairable_config()
        entries = list(load_skills_config())
        changed = False
        for index, item in enumerate(entries):
            if item.name == name:
                entries[index] = item.model_copy(update={"enabled": enabled})
                changed = True
        if changed:
            write_skills_config(entries)
            _clear_load_cache()
    return changed


def delete_user_skill(name: str) -> bool:
    """Remove a configured skill entry and its managed directory."""

    with _CONFIG_LOCK:
        _require_repairable_config()
        entries = list(load_skills_config())
        remaining = [item for item in entries if item.name != name]
        if len(remaining) == len(entries):
            return False
        write_skills_config(remaining)
        # name is regex-validated (no separators / ".."), so this stays inside
        # the managed skills root.
        shutil.rmtree(_skills_root() / name, ignore_errors=True)
        _clear_load_cache()
    return True


__all__ = [
    "MAX_SKILL_ZIP_BYTES",
    "UserSkillError",
    "delete_user_skill",
    "import_skills_from_zip_bytes",
    "install_skill_from_hub_bundle",
    "save_user_skill",
    "set_user_skill_enabled",
    "zip_too_large_detail",
]
