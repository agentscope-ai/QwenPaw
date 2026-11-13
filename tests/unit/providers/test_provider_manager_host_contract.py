# -*- coding: utf-8 -*-
"""Guard the declared host contract of ProviderManager's mixins.

The discovery and persistence mixins operate on state and helpers
defined in the other two files of the ``ProviderManager`` trio.  Every
such cross-file member must be declared on ``ProviderManagerHost`` so
the dependency surface stays explicit and statically checkable.  This
test fails when a mixin starts using an undeclared member.
"""

from __future__ import annotations

import ast
from pathlib import Path

import qwenpaw.providers as providers_pkg
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.provider_manager_discovery import (
    ProviderManagerDiscoveryMixin,
)
from qwenpaw.providers.provider_manager_host import ProviderManagerHost
from qwenpaw.providers.provider_manager_persistence import (
    ProviderManagerPersistenceMixin,
)

_PACKAGE_DIR = Path(providers_pkg.__file__).parent


def _members(path: Path) -> tuple[set, set]:
    """Return (defined, used) member names for one module file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined: set = set()
    used: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            target = defined if isinstance(node.ctx, ast.Store) else used
            target.add(node.attr)
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target,
                    ast.Name,
                ):
                    defined.add(item.target.id)
    return defined, used


def _host_declarations() -> set:
    declared, _ = _members(_PACKAGE_DIR / "provider_manager_host.py")
    return declared


def test_mixins_inherit_the_host_contract() -> None:
    assert issubclass(ProviderManagerDiscoveryMixin, ProviderManagerHost)
    assert issubclass(ProviderManagerPersistenceMixin, ProviderManagerHost)


def test_host_stubs_never_shadow_real_implementations() -> None:
    """The host must stay last in the MRO (before object)."""
    mro = ProviderManager.__mro__
    assert mro.index(ProviderManagerHost) == len(mro) - 2


def test_every_cross_file_member_is_declared_on_the_host() -> None:
    host_declared = _host_declarations()
    for module_name in (
        "provider_manager_discovery",
        "provider_manager_persistence",
    ):
        defined, used = _members(_PACKAGE_DIR / f"{module_name}.py")
        undeclared = used - defined - host_declared
        assert not undeclared, (
            f"{module_name} uses members neither defined locally nor "
            f"declared on ProviderManagerHost: {sorted(undeclared)}. "
            "Declare them in provider_manager_host.py."
        )


def test_host_declarations_are_implemented_by_the_manager() -> None:
    """Every declared member must resolve on the assembled manager."""
    host_declared = _host_declarations()
    missing = [
        name
        for name in host_declared
        if not any(name in vars(cls) for cls in ProviderManager.__mro__[:-2])
        and name not in getattr(ProviderManagerHost, "__annotations__", {})
        and name not in ("__init__",)
    ]
    # Instance attributes are created in __init__ and covered by the
    # annotation check above; methods must exist on a concrete class.
    assert not missing, (
        f"ProviderManagerHost declares members no concrete class "
        f"implements: {missing}"
    )
