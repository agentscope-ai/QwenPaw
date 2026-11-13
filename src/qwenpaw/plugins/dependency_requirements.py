# -*- coding: utf-8 -*-
"""Static package requirements shared by host and worker admission."""

from contextlib import contextmanager
from pathlib import Path
import tempfile


def normalize_package_requirements(values) -> tuple[str, ...]:
    """Use the installer's manifest syntax for capability prerequisites."""
    from .dependency_gate import manifest_requirements

    if not isinstance(values, (list, tuple)):
        raise ValueError("Dependencies must be a list of requirements")
    return tuple(
        dict.fromkeys(manifest_requirements({"dependencies": list(values)})),
    )


def validate_optional_dependencies(groups) -> None:
    """Check every declaration without inspecting an installed environment."""
    if not isinstance(groups, dict):
        raise ValueError("optional_dependencies must be an object")
    for name, values in groups.items():
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError("Optional dependency names must be nonempty")
        normalize_package_requirements(values)


# TODO: Add a separate resolver for live plugin-service prerequisites. Reuse
# contract identities and owned scopes, tracking provider readiness, in-flight
# calls and dependent revocation. Service IDs are not package requirements.
def resolve_optional_dependencies(groups, requires) -> tuple[str, ...]:
    """Resolve a capability's named requirements from its owner's manifest.

    Groups describe Python distributions, not live service providers. The
    consumer selects the execution environment and owns dependency admission.
    """
    if not isinstance(requires, (list, tuple)) or any(
        not isinstance(name, str) or not name for name in requires
    ):
        raise ValueError(
            "requires must be a list of optional dependency names",
        )
    values = []
    for name in requires:
        if name not in groups:
            raise ValueError(f"Unknown optional dependency: {name}")
        values.extend(normalize_package_requirements(groups[name]))
    return tuple(dict.fromkeys(values))


def host_requirements(manifest) -> tuple[str, ...]:
    """Select packages for declared host contributions during installation."""
    # TODO: Extend the same requires resolution/admission to Tool and Skill
    # declarations. Preserve their existing package-level dependencies when
    # adding optional per-capability prerequisites; do not duplicate a resolver.
    requires = []
    for declaration in (
        *manifest.get("cli", ()),
        *manifest.get("extensions", ()),
    ):
        requires.extend(declaration.get("requires", ()))
    return resolve_optional_dependencies(
        manifest.get("optional_dependencies", {}),
        requires,
    )


@contextmanager
def requirements_file(requirements, path=None):
    """Adapt resolved declarations to the existing file-based installer.

    The generated file is temporary installer input, never plugin metadata.
    """
    if path is not None:
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="qwenpaw-requirements-") as temp:
        target = Path(temp) / "requirements.txt"
        target.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        yield target
