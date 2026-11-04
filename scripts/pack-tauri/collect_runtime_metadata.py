# -*- coding: utf-8 -*-
"""Collect the installed desktop dependency graph, including selected extras."""

from importlib import metadata

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def collect_runtime_metadata(requirements, copy_metadata):
    """Copy the validated metadata closure from the build environment."""
    pending = [Requirement(value) for value in requirements]
    visited, copied, datas = set(), set(), []
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        distribution = metadata.distribution(name)
        if not requirement.specifier.contains(
            distribution.version,
            prereleases=True,
        ):
            raise ValueError(
                f"Incompatible desktop dependency: {requirement} "
                f"(installed {distribution.version})",
            )
        key = name, frozenset(requirement.extras)
        if key in visited:
            continue
        visited.add(key)
        if name not in copied:
            datas.extend(copy_metadata(name))
            copied.add(name)
        for value in distribution.requires or ():
            dependency = Requirement(value)
            if dependency.marker is None or any(
                dependency.marker.evaluate({"extra": extra})
                for extra in {"", *requirement.extras}
            ):
                pending.append(dependency)
    return datas
