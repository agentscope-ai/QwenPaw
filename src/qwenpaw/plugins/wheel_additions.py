# -*- coding: utf-8 -*-
"""Validate a bounded, complete set of plain local wheel additions."""

from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from email.parser import BytesParser
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
from typing import Mapping
import zipfile

from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .execution.dependencies import (
    DependencySnapshot,
    dependency_error,
    valid_metadata_headers,
)


@dataclass(frozen=True)
class WheelAddition:
    """A trusted local wheel and its independently supplied expected hash."""

    path: Path
    sha256: str


class WheelFiles(dict[str, bytes]):
    """Validated target-relative files and their executable script paths."""

    def __init__(self):
        super().__init__()
        self.executable_paths: set[str] = set()


# lark-oapi 1.7.1 has over 11,000 installed non-pyc files.
# Retain expanded byte limits while allowing ordinary large SDK wheels.
def _members(addition: WheelAddition) -> dict[str, bytes]:
    path = Path(addition.path)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 128 * 1024 * 1024
    ):
        raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
    # Validate and publish these immutable bytes; never reopen the path.
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != addition.sha256:
        raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
    result = WheelFiles()
    normalized = set()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if (
            len(archive.infolist()) > 50000
            or sum(info.file_size for info in archive.infolist())
            > 256 * 1024 * 1024
        ):
            raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
        for info in archive.infolist():
            name = info.filename
            relative = PurePosixPath(name)
            # Reject every unsafe archive path form before reading members.
            # pylint: disable=too-many-boolean-expressions
            if (
                not name
                or "\\" in name
                or ":" in name
                or relative.is_absolute()
                or any(
                    part in {"", ".", ".."}
                    for part in name.rstrip("/").split("/")
                )
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            if info.is_dir():
                continue
            key = os.path.normcase(name).casefold()
            # Entry-point declarations remain metadata; no launchers are made.
            if key in normalized or name.endswith(".pth"):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            normalized.add(key)
            result[name] = archive.read(info)
            if info.external_attr >> 16 & 0o111:
                result.executable_paths.add(name)
    if any(
        str(parent) in result
        for name in result
        for parent in PurePosixPath(name).parents
        if str(parent) != "."
    ):
        raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
    return result


def _validate_record(files: Mapping[str, bytes], record: str) -> None:
    rows = list(csv.reader(io.StringIO(files[record].decode("utf-8"))))
    seen = set()
    for row in rows:
        if len(row) != 3 or row[0] in seen or row[0] not in files:
            raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
        name, digest, length = row
        seen.add(name)
        if name == record:
            if digest or length:
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            continue
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest())
            .decode()
            .rstrip("=")
        )
        if digest != "sha256=" + expected or length != str(len(files[name])):
            raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
    if seen != set(files):
        raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")


def _script_bytes(content, executable, windows):
    """Bind wheel Python scripts to the audited interpreter without running."""
    first, _, rest = content.partition(b"\n")
    if first.rstrip(b"\r") not in {b"#!python", b"#!pythonw"}:
        return content, False
    if any(character in executable for character in "\r\n\x00"):
        raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
    encoded = os.fsencode(executable)
    if windows:
        if '"' in executable:
            raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
        if any(character.isspace() for character in executable):
            encoded = b'"' + encoded + b'"'
        header = b"#!" + encoded + b"\n"
    elif any(character.isspace() for character in executable) or (
        len(encoded) + 3 > 127
    ):
        if "\\" in executable:
            raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
        cookie, _, body = rest.partition(b"\n")
        if re.match(rb"[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+", cookie):
            rest = body
            cookie += b"\n"
        else:
            cookie = b""
        header = (
            b"#!/bin/sh\n"
            + cookie
            + b"'''exec' "
            + os.fsencode(shlex.quote(executable))
            + b" \"$0\" \"$@\"\n' '''\n"
        )
    else:
        header = b"#!" + encoded + b"\n"
    return header + rest, True


# Data schemes and Windows device names must be rejected before publication.
def _install_scripts(members, info, snapshot):
    """Relocate verified script payloads within the target installation."""
    # pylint: disable=too-many-boolean-expressions
    directory = (
        "Scripts"
        if snapshot.marker_environment.get("os_name") == "nt"
        or snapshot.marker_environment.get("sys_platform") == "win32"
        else "bin"
    )
    data = info.removesuffix(".dist-info") + ".data"
    installed = WheelFiles()
    scripts = set()
    destinations = set()
    for path, content in members.items():
        parts = PurePosixPath(path).parts
        destination = path
        if any(part.endswith(".data") for part in parts):
            if (
                len(parts) != 3
                or parts[:2] != (data, "scripts")
                or parts[2].endswith((".", " "))
                or parts[2].split(".", 1)[0].casefold() == "__init__"
                or any(ord(character) < 32 for character in parts[2])
                or (
                    directory == "Scripts"
                    and parts[2].split(".", 1)[0].upper()
                    in {"CON", "PRN", "AUX", "NUL"}
                    | {
                        f"{prefix}{number}"
                        for prefix in ("COM", "LPT")
                        for number in range(1, 10)
                    }
                )
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            destination = f"{directory}/{parts[2]}"
            scripts.add(destination)
            content, python_script = _script_bytes(
                content,
                snapshot.executable,
                directory == "Scripts",
            )
            if (python_script and directory == "bin") or (
                path in members.executable_paths
            ):
                installed.executable_paths.add(destination)
        if destination.casefold() in destinations:
            raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
        destinations.add(destination.casefold())
        installed[destination] = content
    if scripts:
        record = f"{info}/RECORD"
        rows = io.StringIO(newline="")
        writer = csv.writer(rows, lineterminator="\n")
        for path, content in installed.items():
            if path != record:
                digest = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(content).digest(),
                    )
                    .decode()
                    .rstrip("=")
                )
                writer.writerow((path, "sha256=" + digest, len(content)))
        writer.writerow((record, "", ""))
        installed[record] = rows.getvalue().encode("utf-8")
    return installed, scripts, directory


def _check_script_paths(scripts, directory, snapshot, target):
    """Allow shared script directories without merging import providers."""
    key = directory.casefold()
    if any(
        key in {top.casefold() for top in row["top_level"]}
        for row in snapshot.distributions.values()
    ):
        raise dependency_error("DEPENDENCY_RESTART_REQUIRED")
    for site in snapshot.sites:
        root = Path(site)
        for child in root.iterdir() if root.is_dir() else ():
            if child.name.casefold() == key:
                if (
                    child.is_symlink()
                    or not child.is_dir()
                    or any(
                        path.name.casefold().startswith("__init__.")
                        for path in child.iterdir()
                    )
                    or (root == target and child.name != directory)
                ):
                    raise dependency_error("DEPENDENCY_RESTART_REQUIRED")
            elif child.name.split(".", 1)[0].casefold() == key and (
                child.suffix.lower() in {".py", ".pyc", ".so", ".pyd"}
            ):
                raise dependency_error("DEPENDENCY_RESTART_REQUIRED")
    destination = target / directory
    existing = (
        {path.name.casefold() for path in destination.iterdir()}
        if destination.is_dir()
        else set()
    )
    if any(
        PurePosixPath(path).name.casefold() in existing for path in scripts
    ):
        raise dependency_error("DEPENDENCY_RESTART_REQUIRED")


def _directories(files):
    return {
        str(parent)
        for path in files
        for parent in PurePosixPath(path).parents
        if str(parent) != "."
    }


def _check_overlap(left, left_dirs, right, right_dirs, reason):
    """Only implicit namespace directories may belong to two providers."""
    left, right = (
        {path.casefold() for path in paths} for paths in (left, right)
    )
    left_dirs, right_dirs = (
        {path.casefold() for path in paths}
        for paths in (left_dirs, right_dirs)
    )
    shared = left_dirs & right_dirs
    initializers = {
        str(PurePosixPath(path).parent)
        for path in left | right
        if PurePosixPath(path).name.startswith("__init__.")
    }

    def modules(paths):
        return {
            str(
                PurePosixPath(path).with_name(
                    PurePosixPath(path).name.split(".", 1)[0],
                ),
            )
            for path in paths
            if PurePosixPath(path).suffix in {".py", ".pyc", ".so", ".pyd"}
        }

    left_modules, right_modules = modules(left), modules(right)
    if (
        left & (right | right_dirs)
        or right & left_dirs
        or shared & initializers
        or left_modules & (right_modules | right_dirs)
        or right_modules & left_dirs
    ):
        raise dependency_error(reason)


def _check_installed_tree(
    files,
    directories,
    sites,
    *,
    replaced=(),
    reason="DEPENDENCY_RESTART_REQUIRED",
):
    """Inspect only intersecting directories, retaining namespace siblings."""
    replaced = {Path(path) for path in replaced}
    owned_dirs = {parent for path in replaced for parent in path.parents}

    def retained(path):
        if path.is_symlink():
            return True
        if path in replaced:
            return False
        if replaced and path.name == "__pycache__" and path.is_dir():
            # Orphaned bytecode is not an import provider. Keep the actual
            # files for collision checks; replacement does not own them.
            return any(
                child.is_symlink()
                or not child.is_file()
                or child.suffix != ".pyc"
                for child in path.iterdir()
            )
        if path in owned_dirs and path.is_dir():
            return any(retained(child) for child in path.iterdir())
        return True

    for site in sites:
        root = Path(site)
        existing, existing_dirs = set(), set()
        for relative in {".", *directories}:
            directory = root / relative
            if directory.is_symlink():
                raise dependency_error(reason)
            if not directory.is_dir():
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not retained(Path(entry.path)):
                        continue
                    path = str(PurePosixPath(relative) / entry.name)
                    if entry.is_dir(follow_symlinks=False):
                        existing_dirs.add(path)
                    else:
                        existing.add(path)
        _check_overlap(
            files,
            directories,
            existing,
            existing_dirs,
            reason,
        )


# Whole-set archive and collision validation is deliberately fail-closed.
# pylint: disable=too-many-branches,too-many-boolean-expressions,too-many-statements
def validate_additions(
    additions: tuple[WheelAddition, ...],
    snapshot: DependencySnapshot,
    target: Path,
) -> tuple[dict[str, bytes], DependencySnapshot]:
    """Return verified bytes and proposed metadata for closure checks."""
    files = WheelFiles()
    distributions = dict(snapshot.distributions)
    occupied = set()
    script_directories = set()
    script_paths = set()
    try:
        for addition in additions:
            name, version, _, tags = parse_wheel_filename(
                Path(addition.path).name,
            )
            name = str(name)
            if name in distributions:
                raise dependency_error("DEPENDENCY_RESTART_REQUIRED")
            if not {str(tag) for tag in tags}.intersection(
                snapshot.supported_tags,
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            members = _members(addition)
            infos = {
                path.split("/", 1)[0]
                for path in members
                if path.split("/", 1)[0].endswith(".dist-info")
            }
            if len(infos) != 1:
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            info = infos.pop()
            info_name, _, info_version = info.removesuffix(
                ".dist-info",
            ).rpartition("-")
            metadata = BytesParser().parsebytes(members[f"{info}/METADATA"])
            wheel = BytesParser().parsebytes(members[f"{info}/WHEEL"])
            if not valid_metadata_headers(
                metadata,
                ("Name", "Version"),
                ("Requires-Python",),
            ) or not valid_metadata_headers(
                wheel,
                ("Wheel-Version", "Root-Is-Purelib"),
                ("Build",),
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            if (
                canonicalize_name(metadata["Name"]) != name
                or Version(metadata["Version"]) != version
                or canonicalize_name(info_name) != name
                or Version(info_version) != version
                or wheel["Wheel-Version"] != "1.0"
                or wheel["Root-Is-Purelib"] not in {"true", "false"}
                or set(wheel.get_all("Tag", [])) != {str(tag) for tag in tags}
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            requires_python = metadata.get("Requires-Python")
            if requires_python and not SpecifierSet(requires_python).contains(
                snapshot.marker_environment["python_full_version"],
                prereleases=True,
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            _validate_record(members, f"{info}/RECORD")
            tops = {
                path.split("/", 1)[0]
                for path in members
                if not path.split("/", 1)[0].endswith(".data")
            }
            members, scripts, directory = _install_scripts(
                members,
                info,
                snapshot,
            )
            stems = {top.split(".", 1)[0] for top in tops}
            if (
                {stem.casefold() for stem in stems} & script_directories
                or (
                    scripts
                    and directory.casefold()
                    in {stem.casefold() for stem in stems | occupied}
                )
                or {path.casefold() for path in scripts} & script_paths
            ):
                raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED")
            if scripts:
                _check_script_paths(scripts, directory, snapshot, target)
                script_directories.add(directory.casefold())
                script_paths.update(path.casefold() for path in scripts)
            directories = _directories(members)
            _check_overlap(
                members,
                directories,
                files,
                _directories(files),
                "DEPENDENCY_PLAN_UNVERIFIED",
            )
            _check_installed_tree(members, directories, snapshot.sites)
            for site in snapshot.sites:
                for origin in Path(site).glob("*.dist-info"):
                    text = origin / "METADATA"
                    installed = (
                        BytesParser().parsebytes(text.read_bytes())
                        if text.is_file()
                        else {}
                    )
                    claimed = installed.get("Name")
                    if (
                        claimed and canonicalize_name(claimed) == name
                    ) or origin.name.lower().replace("_", "-").startswith(
                        name + "-",
                    ):
                        raise dependency_error("DEPENDENCY_RESTART_REQUIRED")
            occupied.update(stems)
            files.update(members)
            files.executable_paths.update(members.executable_paths)
            distributions[name] = {
                "version": str(version),
                "metadata_path": str(target / info),
                "requires_dist": tuple(metadata.get_all("Requires-Dist", [])),
                "top_level": tuple(
                    sorted(
                        top.split(".", 1)[0] for top in tops if top != info
                    ),
                ),
            }
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        zipfile.BadZipFile,
    ) as exc:
        if hasattr(exc, "reason_code"):
            raise
        raise dependency_error("DEPENDENCY_PLAN_UNVERIFIED") from None
    return files, DependencySnapshot(
        snapshot.executable,
        snapshot.prefix,
        snapshot.sites,
        snapshot.marker_environment,
        snapshot.supported_tags,
        distributions,
        snapshot.dependency_sites,
    )
