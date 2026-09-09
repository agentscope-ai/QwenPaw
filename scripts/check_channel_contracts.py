#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check built-in channel contract coverage without importing QwenPaw.

Usage:
    python scripts/check_channel_contracts.py
    python scripts/check_channel_contracts.py --list-specs

The built-in registry is the source of truth. Source implementations and
contract tests are inspected with the standard-library AST module so the
check does not require optional channel dependencies.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = Path("src/qwenpaw/app/channels/registry.py")
CHANNELS_PATH = Path("src/qwenpaw/app/channels")
CONTRACT_TESTS_PATH = Path("tests/contract/channels")
CHANNEL_PACKAGE = "qwenpaw.app.channels"
BASE_CHANNEL = f"{CHANNEL_PACKAGE}.base.BaseChannel"
CONTRACT_BASE = "tests.contract.channels.ChannelContractTest"
DISABLED_PYTEST_CALLS = {
    "pytest.importorskip",
    "pytest.skip",
    "pytest.xfail",
}


class CoverageCheckError(RuntimeError):
    """Raised when the static coverage model cannot be evaluated safely."""


@dataclass(frozen=True)
class ChannelSpec:
    """A statically declared built-in channel."""

    key: str
    module: str
    class_name: str

    @property
    def suggested_test_path(self) -> str:
        """Return the canonical contract-test path for this registry key."""
        return f"tests/contract/channels/test_{self.key}_contract.py"


@dataclass(frozen=True)
class SourceClass:
    """A module-qualified class declaration."""

    qualified_name: str
    bases: tuple[str, ...]
    path: Path


@dataclass(frozen=True)
class ModuleInfo:
    """Static exports for one Python module."""

    name: str
    path: Path
    exports: dict[str, str]


@dataclass(frozen=True)
class SourceIndex:
    """Static channel modules and their class declarations."""

    classes: dict[str, SourceClass]
    modules: dict[str, ModuleInfo]


@dataclass(frozen=True)
class CoverageReport:
    """Static coverage result for the current repository."""

    specs: tuple[ChannelSpec, ...]
    tested_classes: frozenset[str]
    errors: tuple[str, ...]

    @property
    def all_classes(self) -> frozenset[str]:
        """Return all registered built-in class names."""
        return frozenset(spec.class_name for spec in self.specs)

    @property
    def missing_specs(self) -> tuple[ChannelSpec, ...]:
        """Return registered channels without a recognized contract test."""
        return tuple(
            spec
            for spec in self.specs
            if spec.class_name not in self.tested_classes
        )


def _read_ast(path: Path) -> ast.Module:
    """Read a UTF-8 Python file and return its parsed syntax tree."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CoverageCheckError(f"cannot read {path}: {exc}") from exc

    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise CoverageCheckError(f"cannot parse {path}: {exc}") from exc


def _allowed_registry_read(
    node: ast.Name,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    """Return whether a registry load is a known read-only method call."""
    parent = parents.get(node)
    grandparent = parents.get(parent) if parent is not None else None
    return bool(
        isinstance(parent, ast.Attribute)
        and parent.value is node
        and parent.attr in {"items", "keys"}
        and isinstance(grandparent, ast.Call)
        and grandparent.func is parent,
    )


def _validate_registry_statement(node: ast.stmt, name: str) -> None:
    """Reject dynamic mutation, aliasing, or passing of the registry."""
    parents = {
        child: parent
        for parent in ast.walk(node)
        for child in ast.iter_child_nodes(parent)
    }
    mutating_methods = {
        "clear",
        "pop",
        "popitem",
        "setdefault",
        "update",
    }
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Name)
            and child.id == name
            and isinstance(child.ctx, (ast.Store, ast.Del))
        ):
            raise CoverageCheckError(
                f"{name} cannot be modified dynamically",
            )
        if (
            isinstance(child, ast.Subscript)
            and isinstance(child.ctx, (ast.Store, ast.Del))
            and isinstance(child.value, ast.Name)
            and child.value.id == name
        ):
            raise CoverageCheckError(
                f"{name} cannot be modified dynamically",
            )
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == name
            and child.func.attr in mutating_methods
        ):
            raise CoverageCheckError(
                f"{name} cannot be modified dynamically",
            )
        if (
            isinstance(child, ast.Name)
            and child.id == name
            and isinstance(child.ctx, ast.Load)
            and not _allowed_registry_read(child, parents)
        ):
            raise CoverageCheckError(
                f"{name} cannot be aliased or passed dynamically",
            )


def _assigned_value(tree: ast.Module, name: str) -> ast.expr:
    """Return one simple top-level assignment and reject later mutation."""
    assignments: list[tuple[ast.stmt, ast.expr]] = []
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            assignments.append((node, node.value))
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            if not (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name
            ):
                raise CoverageCheckError(
                    f"{name} must use a single-name assignment",
                )
            assignments.append((node, node.value))

    if not assignments:
        raise CoverageCheckError(f"{name} is not declared in the registry")
    if len(assignments) != 1:
        raise CoverageCheckError(
            f"{name} must have exactly one top-level assignment",
        )

    assignment, value = assignments[0]
    for node in tree.body:
        if node is not assignment:
            _validate_registry_statement(node, name)
    return value


def _string_literal(node: ast.expr, description: str) -> str:
    """Return a string literal or fail with an actionable message."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise CoverageCheckError(f"{description} must be a string literal")


def load_builtin_specs(
    repo_root: Path = REPO_ROOT,
) -> tuple[ChannelSpec, ...]:
    """Load the static _BUILTIN_SPECS registry declaration."""
    value = _assigned_value(
        _read_ast(repo_root / REGISTRY_PATH),
        "_BUILTIN_SPECS",
    )
    if not isinstance(value, ast.Dict):
        raise CoverageCheckError(
            "_BUILTIN_SPECS must be a dictionary literal",
        )

    specs: list[ChannelSpec] = []
    seen_keys: set[str] = set()
    seen_classes: set[str] = set()
    for key_node, value_node in zip(value.keys, value.values):
        if key_node is None:
            raise CoverageCheckError(
                "_BUILTIN_SPECS cannot contain dictionary unpacking",
            )
        key = _string_literal(key_node, "channel registry key")
        if (
            not key
            or key[0] not in "abcdefghijklmnopqrstuvwxyz"
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in key
            )
        ):
            raise CoverageCheckError(
                f"invalid channel registry key: {key!r}",
            )
        if not (
            isinstance(value_node, (ast.Tuple, ast.List))
            and len(value_node.elts) == 2
        ):
            raise CoverageCheckError(
                f"registry entry {key!r} must be a (module, class) pair",
            )
        module = _string_literal(
            value_node.elts[0],
            f"module for {key!r}",
        )
        class_name = _string_literal(
            value_node.elts[1],
            f"class for {key!r}",
        )
        if not module.startswith(".") or not module.lstrip("."):
            raise CoverageCheckError(
                f"module for {key!r} must be package-relative",
            )
        if key in seen_keys:
            raise CoverageCheckError(f"duplicate registry key: {key}")
        if class_name in seen_classes:
            raise CoverageCheckError(
                f"duplicate registered class: {class_name}",
            )
        seen_keys.add(key)
        seen_classes.add(class_name)
        specs.append(ChannelSpec(key, module, class_name))

    if not specs:
        raise CoverageCheckError("_BUILTIN_SPECS is empty")
    return tuple(specs)


def _module_name(path: Path, base: Path) -> tuple[str, bool]:
    """Return a module name and whether path is a package initializer."""
    relative = path.relative_to(base).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _import_target(
    node: ast.ImportFrom,
    module_name: str,
    is_package: bool = False,
) -> str:
    """Resolve an absolute or relative from-import module."""
    if not node.level:
        return node.module or ""

    package = module_name if is_package else module_name.rpartition(".")[0]
    relative = "." * node.level + (node.module or "")
    try:
        return importlib.util.resolve_name(relative, package)
    except (ImportError, ValueError) as exc:
        raise CoverageCheckError(
            f"cannot resolve import {relative!r} in {module_name}",
        ) from exc


def _direct_imports(
    statements: Iterable[ast.stmt],
    module_name: str,
    is_package: bool = False,
) -> dict[str, str]:
    """Resolve imports declared directly in one lexical scope."""
    aliases: dict[str, str] = {}
    for node in statements:
        if isinstance(node, ast.ImportFrom):
            target_module = _import_target(
                node,
                module_name,
                is_package,
            )
            for imported in node.names:
                if imported.name == "*":
                    continue
                local_name = imported.asname or imported.name
                aliases[local_name] = f"{target_module}.{imported.name}"
        elif isinstance(node, ast.Import):
            for imported in node.names:
                local_name = imported.asname or imported.name.split(".")[0]
                aliases[local_name] = (
                    imported.name
                    if imported.asname
                    else imported.name.split(".")[0]
                )
    return aliases


class _BoundNameCollector(ast.NodeVisitor):
    """Collect names rebound without entering nested lexical scopes."""

    def __init__(self, include_imports: bool = False) -> None:
        self.names: set[str] = set()
        self.include_imports = include_imports

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Import(self, node: ast.Import) -> None:
        if self.include_imports:
            self.names.update(
                alias.asname or alias.name.split(".")[0]
                for alias in node.names
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.include_imports:
            self.names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name != "*"
            )

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node


def _rebound_names(
    statements: Iterable[ast.stmt],
    include_imports: bool = False,
) -> frozenset[str]:
    """Return assignment targets in one lexical scope."""
    collector = _BoundNameCollector(include_imports)
    for statement in statements:
        collector.visit(statement)
    return frozenset(collector.names)


def _stable_imports(
    statements: Iterable[ast.stmt],
    module_name: str,
    is_package: bool = False,
) -> dict[str, str]:
    """Return direct imports that are not rebound in the same scope."""
    statement_list = tuple(statements)
    imports = _direct_imports(
        statement_list,
        module_name,
        is_package,
    )
    non_imports = (
        statement
        for statement in statement_list
        if not isinstance(statement, (ast.Import, ast.ImportFrom))
    )
    for name in _rebound_names(non_imports, include_imports=True):
        imports.pop(name, None)
    return imports


def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted identifier represented by an expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _dotted_name(node.value)
    return None


def _resolve_expr(
    node: ast.expr,
    aliases: dict[str, str],
    module_name: str,
) -> str | None:
    """Resolve a name expression to a module-qualified identifier."""
    dotted = _dotted_name(node)
    if not dotted:
        return None
    head, separator, tail = dotted.partition(".")
    if head in aliases:
        resolved = aliases[head]
        return f"{resolved}.{tail}" if separator else resolved
    if not separator:
        return f"{module_name}.{head}"
    return None


def _build_source_index(repo_root: Path) -> SourceIndex:
    """Index module-qualified channel source classes and exports."""
    source_root = repo_root / "src"
    channels_dir = repo_root / CHANNELS_PATH
    classes: dict[str, SourceClass] = {}
    modules: dict[str, ModuleInfo] = {}

    for source_path in sorted(channels_dir.rglob("*.py")):
        tree = _read_ast(source_path)
        module_name, is_package = _module_name(
            source_path,
            source_root,
        )
        exports: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                exports.update(
                    _direct_imports(
                        (node,),
                        module_name,
                        is_package,
                    ),
                )
                continue
            if not isinstance(node, ast.ClassDef):
                for name in _rebound_names((node,), include_imports=True):
                    exports.pop(name, None)
                continue
            qualified_name = f"{module_name}.{node.name}"
            bases = tuple(
                resolved
                for base in node.bases
                if (
                    resolved := _resolve_expr(
                        base,
                        exports,
                        module_name,
                    )
                )
            )
            if qualified_name in classes:
                raise CoverageCheckError(
                    f"duplicate source class: {qualified_name}",
                )
            classes[qualified_name] = SourceClass(
                qualified_name=qualified_name,
                bases=bases,
                path=source_path,
            )
            exports[node.name] = qualified_name
        modules[module_name] = ModuleInfo(
            name=module_name,
            path=source_path,
            exports=exports,
        )
    return SourceIndex(classes=classes, modules=modules)


def _inherits_base_channel(
    qualified_name: str,
    classes: dict[str, SourceClass],
    active: frozenset[str] = frozenset(),
) -> bool:
    """Return whether a specific source class derives from BaseChannel."""
    if qualified_name in active:
        return False
    declaration = classes.get(qualified_name)
    if declaration is None:
        return False
    if BASE_CHANNEL in declaration.bases:
        return True
    next_active = active | {qualified_name}
    return any(
        _inherits_base_channel(base, classes, next_active)
        for base in declaration.bases
    )


def resolve_registered_classes(
    specs: Iterable[ChannelSpec],
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Resolve registry exports to concrete BaseChannel implementations."""
    source_index = _build_source_index(repo_root)
    accepted_imports: dict[str, str] = {}
    errors: list[str] = []

    for spec in specs:
        module_name = f"{CHANNEL_PACKAGE}{spec.module}"
        public_name = f"{module_name}.{spec.class_name}"
        module = source_index.modules.get(module_name)
        if module is None:
            errors.append(
                f"{spec.key}: registry module {module_name} is missing",
            )
            continue
        target = module.exports.get(spec.class_name)
        if target is None:
            errors.append(
                f"{spec.key}: {module_name} does not export "
                f"{spec.class_name}",
            )
            continue
        if target not in source_index.classes:
            errors.append(
                f"{spec.key}: {public_name} does not resolve to a "
                "channel source class",
            )
            continue

        if not _inherits_base_channel(target, source_index.classes):
            errors.append(
                f"{spec.key}: {target} does not inherit the canonical "
                "BaseChannel",
            )
            continue
        accepted_imports[public_name] = spec.class_name
        accepted_imports[target] = spec.class_name
    return accepted_imports, tuple(errors)


def _test_class_bases(
    tree: ast.Module,
    module_name: str,
    aliases: dict[str, str],
) -> tuple[dict[str, ast.ClassDef], dict[str, tuple[str, ...]]]:
    """Return test declarations and their module-qualified bases."""
    declarations: dict[str, ast.ClassDef] = {}
    bases: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        qualified_name = f"{module_name}.{node.name}"
        declarations[qualified_name] = node
        bases[qualified_name] = tuple(
            resolved
            for base in node.bases
            if (
                resolved := _resolve_expr(
                    base,
                    aliases,
                    module_name,
                )
            )
        )
    return declarations, bases


def _inherits_contract(
    qualified_name: str,
    bases: dict[str, tuple[str, ...]],
    active: frozenset[str] = frozenset(),
) -> bool:
    """Return whether a test class derives from ChannelContractTest."""
    if qualified_name in active:
        return False
    class_bases = bases.get(qualified_name, ())
    if CONTRACT_BASE in class_bases:
        return True
    next_active = active | {qualified_name}
    return any(
        _inherits_contract(base, bases, next_active) for base in class_bases
    )


def _decorator_name(
    decorator: ast.expr,
    aliases: dict[str, str],
    module_name: str,
) -> str | None:
    """Resolve a decorator name, including called decorators."""
    expression = (
        decorator.func if isinstance(decorator, ast.Call) else decorator
    )
    return _resolve_expr(expression, aliases, module_name)


def _method_is_abstract(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, str],
    module_name: str,
) -> bool:
    """Return whether a method has an abstractmethod decorator."""
    return any(
        name in {"abc.abstractmethod", "abstractmethod"}
        or (name is not None and name.endswith(".abstractmethod"))
        for decorator in method.decorator_list
        if (
            name := _decorator_name(
                decorator,
                aliases,
                module_name,
            )
        )
    )


def _abstract_methods(
    qualified_name: str,
    declarations: dict[str, ast.ClassDef],
    bases: dict[str, tuple[str, ...]],
    aliases: dict[str, str],
    module_name: str,
    active: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Compute abstract methods inherited by a local contract class."""
    if qualified_name in active:
        return frozenset()
    declaration = declarations.get(qualified_name)
    if declaration is None:
        return frozenset()

    methods: set[str] = set()
    next_active = active | {qualified_name}
    for base in bases.get(qualified_name, ()):
        if base == CONTRACT_BASE:
            methods.add("create_instance")
        elif base in declarations:
            methods.update(
                _abstract_methods(
                    base,
                    declarations,
                    bases,
                    aliases,
                    module_name,
                    next_active,
                ),
            )

    for node in declaration.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _method_is_abstract(node, aliases, module_name):
            methods.add(node.name)
        else:
            methods.discard(node.name)
    return frozenset(methods)


class _ModuleGateVisitor(ast.NodeVisitor):
    """Reject module-level constructs that can disable all contracts."""

    def __init__(
        self,
        aliases: dict[str, str],
        module_name: str,
    ) -> None:
        self.aliases = dict(aliases)
        self.module_name = module_name
        self.class_depth = 0
        self.error: str | None = None

    def visit_Import(self, node: ast.Import) -> None:
        self.aliases.update(_direct_imports((node,), self.module_name))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.aliases.update(_direct_imports((node,), self.module_name))

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.class_depth == 0 and any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            self.error = "uses module-level pytestmark"
            return
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            self.class_depth == 0
            and isinstance(node.target, ast.Name)
            and node.target.id == "pytestmark"
        ):
            self.error = "uses module-level pytestmark"
            return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if self.class_depth == 0 and node.id == "pytestmark":
            self.error = "uses module-level pytestmark"
        resolved = _resolve_expr(node, self.aliases, self.module_name)
        if resolved in DISABLED_PYTEST_CALLS:
            self.error = f"references {resolved} at module scope"

    def visit_Attribute(self, node: ast.Attribute) -> None:
        resolved = _resolve_expr(node, self.aliases, self.module_name)
        if resolved in DISABLED_PYTEST_CALLS:
            self.error = f"references {resolved} at module scope"
        self.generic_visit(node)

    def _visit_function_header(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self.class_depth == 0 and node.name == "pytest_generate_tests":
            self.error = "defines module-level pytest_generate_tests"
            return
        self._visit_function_header(node)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        if self.class_depth == 0 and node.name == "pytest_generate_tests":
            self.error = "defines module-level pytest_generate_tests"
            return
        self._visit_function_header(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self.class_depth += 1
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.class_depth -= 1


def _module_gate_error(
    tree: ast.Module,
    aliases: dict[str, str],
    module_name: str,
) -> str | None:
    """Return a module-level pytest gate that can hide all contracts."""
    visitor = _ModuleGateVisitor(aliases, module_name)
    visitor.visit(tree)
    return visitor.error


class _ClassGateVisitor(ast.NodeVisitor):
    """Reject collection overrides in one contract class body."""

    def __init__(self) -> None:
        self.error: str | None = None

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            self.error = "uses class-level pytestmark"
            return
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            isinstance(node.target, ast.Name)
            and node.target.id == "pytestmark"
        ):
            self.error = "uses class-level pytestmark"
            return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "__test__":
            self.error = "uses class-level __test__"
        elif node.id == "pytestmark":
            self.error = "uses class-level pytestmark"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        del node

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        del node


def _class_gate_error(  # pylint: disable=too-many-return-statements,too-many-branches
    qualified_name: str,
    declarations: dict[str, ast.ClassDef],
    bases: dict[str, tuple[str, ...]],
    aliases: dict[str, str],
    active: frozenset[str] = frozenset(),
) -> str | None:
    """Return a collection override on a contract class or local base."""
    if qualified_name in active:
        return None
    declaration = declarations.get(qualified_name)
    if declaration is None:
        return None
    module_name = qualified_name.rpartition(".")[0]

    if declaration.keywords:
        return "uses class keywords or a custom metaclass"

    if declaration.decorator_list:
        decorator = declaration.decorator_list[0]
        name = _decorator_name(decorator, aliases, module_name)
        return f"uses class decorator {name or '<dynamic>'}"

    for statement in declaration.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name == "pytest_generate_tests":
                return "defines class-level pytest_generate_tests"
            if statement.name in {"__init__", "__new__"}:
                return (
                    f"defines {statement.name}, which prevents "
                    "pytest collection"
                )
            if statement.name == "instance":
                return "overrides the contract instance fixture"
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (statement.target,)
            )
            if any(
                isinstance(target, ast.Name) and target.id == "instance"
                for target in targets
            ):
                return "overrides the contract instance fixture"

    visitor = _ClassGateVisitor()
    for statement in declaration.body:
        visitor.visit(statement)
    if visitor.error:
        return visitor.error

    next_active = active | {qualified_name}
    for base in bases.get(qualified_name, ()):
        inherited = _class_gate_error(
            base,
            declarations,
            bases,
            aliases,
            next_active,
        )
        if inherited:
            return f"inherits disabled contract base that {inherited}"
    return None


class _ModuleClassMutationVisitor(ast.NodeVisitor):
    """Reject module-level mutation of recognized contract classes."""

    def __init__(
        self,
        class_names: frozenset[str],
        aliases: dict[str, str],
        module_name: str,
    ) -> None:
        self.class_names = class_names
        self.aliases = aliases
        self.module_name = module_name
        self.declared: set[str] = set()
        self.error: str | None = None

    def _check_target(self, target: ast.expr) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._check_target(element)
            return
        if isinstance(target, ast.Name):
            qualified_name = f"{self.module_name}.{target.id}"
            if qualified_name in self.class_names:
                self.error = (
                    f"rebinds contract class {target.id} after declaration"
                )
            return
        if not isinstance(target, ast.Attribute):
            return
        owner = _resolve_expr(target.value, self.aliases, self.module_name)
        if owner in self.class_names:
            self.error = (
                f"mutates contract class {owner.rsplit('.', 1)[-1]} "
                f"after declaration"
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_target(target)
        value = _resolve_expr(node.value, self.aliases, self.module_name)
        if value in self.class_names:
            self.error = (
                f"aliases contract class {value.rsplit('.', 1)[-1]} "
                "after declaration"
            )
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_target(node.target)
        if node.value is not None:
            value = _resolve_expr(node.value, self.aliases, self.module_name)
            if value in self.class_names:
                self.error = (
                    f"aliases contract class {value.rsplit('.', 1)[-1]} "
                    "after declaration"
                )
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_target(node.target)
        self.visit(node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._check_target(target)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in {"setattr", "delattr"}
            and node.args
        ):
            owner = _resolve_expr(
                node.args[0],
                self.aliases,
                self.module_name,
            )
            if owner in self.class_names:
                self.error = (
                    f"mutates contract class {owner.rsplit('.', 1)[-1]} "
                    "after declaration"
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_target(ast.Name(id=node.name, ctx=ast.Store()))

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self._check_target(ast.Name(id=node.name, ctx=ast.Store()))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = f"{self.module_name}.{node.name}"
        if qualified_name not in self.class_names:
            return
        if qualified_name in self.declared:
            self.error = f"redefines contract class {node.name}"
            return
        self.declared.add(qualified_name)

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            name = imported.asname or imported.name.split(".")[0]
            self._check_target(ast.Name(id=name, ctx=ast.Store()))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for imported in node.names:
            if imported.name != "*":
                self._check_target(
                    ast.Name(
                        id=imported.asname or imported.name,
                        ctx=ast.Store(),
                    ),
                )

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node


def _module_class_mutation_error(
    tree: ast.Module,
    class_names: Iterable[str],
    aliases: dict[str, str],
    module_name: str,
) -> str | None:
    """Return an out-of-class mutation that invalidates static analysis."""
    visitor = _ModuleClassMutationVisitor(
        frozenset(class_names),
        aliases,
        module_name,
    )
    for statement in tree.body:
        visitor.visit(statement)
    return visitor.error


class _ReturnCollector(ast.NodeVisitor):
    """Collect returns without entering nested functions or classes."""

    def __init__(self) -> None:
        self.values: list[ast.expr | None] = []

    def visit_Return(self, node: ast.Return) -> None:
        self.values.append(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        del node

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        del node


def _factory_returns(
    factory: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.expr | None, ...]:
    """Return expressions belonging directly to a factory body."""
    collector = _ReturnCollector()
    for statement in factory.body:
        collector.visit(statement)
    return tuple(collector.values)


class _BindingCounter(ast.NodeVisitor):
    """Count bindings for one name without entering nested scopes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.name and isinstance(
            node.ctx,
            (ast.Store, ast.Del),
        ):
            self.count += 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == self.name:
            self.count += 1

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        if node.name == self.name:
            self.count += 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == self.name:
            self.count += 1

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    def visit_Import(self, node: ast.Import) -> None:
        self.count += sum(
            (alias.asname or alias.name.split(".")[0]) == self.name
            for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.count += sum(
            (alias.asname or alias.name) == self.name for alias in node.names
        )


def _binding_count(statements: Iterable[ast.stmt], name: str) -> int:
    """Return how many times name is bound in one lexical scope."""
    counter = _BindingCounter(name)
    for statement in statements:
        counter.visit(statement)
    return counter.count


def _factory_signature_error(factory: ast.FunctionDef) -> str | None:
    """Require the canonical synchronous ``create_instance(self)`` shape."""
    if factory.decorator_list:
        return "must not use decorators"
    args = factory.args
    positional = args.posonlyargs + args.args
    has_extra_arguments = any(
        (
            args.vararg is not None,
            args.kwarg is not None,
            bool(args.kwonlyargs),
            bool(args.defaults),
            bool(args.kw_defaults),
        ),
    )
    if [argument.arg for argument in positional] != [
        "self",
    ] or has_extra_arguments:
        return "must have signature create_instance(self)"
    return None


def _pytest_gate_reference(
    statements: Iterable[ast.stmt],
    aliases: dict[str, str],
    module_name: str,
) -> str | None:
    """Return a direct pytest call/reference that can skip execution."""
    local_aliases = dict(aliases)
    statement_list = tuple(statements)
    local_aliases.update(_direct_imports(statement_list, module_name))
    for statement in statement_list:
        for node in ast.walk(statement):
            if isinstance(node, ast.ImportFrom):
                imported = _direct_imports((node,), module_name)
                disabled = DISABLED_PYTEST_CALLS.intersection(
                    imported.values(),
                )
                if disabled:
                    return sorted(disabled)[0]
            if isinstance(node, (ast.Name, ast.Attribute)):
                resolved = _resolve_expr(node, local_aliases, module_name)
                if resolved in DISABLED_PYTEST_CALLS:
                    return resolved
    return None


def _factory_gate_error(
    factory: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, str],
    module_name: str,
) -> str | None:
    """Require a straight-line factory with no runtime pytest gates."""
    unsupported = (
        ast.AsyncFor,
        ast.AsyncWith,
        ast.Break,
        ast.ClassDef,
        ast.Continue,
        ast.For,
        ast.FunctionDef,
        ast.If,
        ast.Lambda,
        ast.Match,
        ast.Raise,
        ast.Try,
        ast.TryStar,
        ast.While,
        ast.With,
    )
    for statement in factory.body:
        for node in ast.walk(statement):
            if isinstance(node, unsupported):
                return (
                    "must use straight-line code; "
                    f"found {type(node).__name__}"
                )

    disabled = _pytest_gate_reference(
        factory.body,
        aliases,
        module_name,
    )
    if disabled:
        return f"references {disabled}"
    return None


def _autouse_fixture_state(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, str],
    module_name: str,
) -> bool | None:
    """Return False/True for static autouse, or None when dynamic."""
    for decorator in method.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = _decorator_name(decorator, aliases, module_name)
        if name != "pytest.fixture":
            continue
        autouse_values = [
            keyword.value
            for keyword in decorator.keywords
            if keyword.arg == "autouse"
        ]
        if not autouse_values:
            return False
        if len(autouse_values) != 1:
            return None
        value = autouse_values[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
        return None
    return False


def _fixture_or_setup_gate_error(
    methods: Iterable[ast.stmt],
    aliases: dict[str, str],
    module_name: str,
    setup_names: frozenset[str],
) -> str | None:
    """Reject skip calls in autouse fixtures and xunit setup hooks."""
    for node in methods:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_autouse = _autouse_fixture_state(node, aliases, module_name)
        if is_autouse is None:
            return f"fixture {node.name} uses dynamic autouse"
        if not is_autouse and node.name not in setup_names:
            continue
        disabled = _pytest_gate_reference(
            node.body,
            aliases,
            module_name,
        )
        if disabled:
            kind = "autouse fixture" if is_autouse else "setup hook"
            return f"{kind} {node.name} references {disabled}"
    return None


def _class_runtime_gate_error(
    qualified_name: str,
    declarations: dict[str, ast.ClassDef],
    bases: dict[str, tuple[str, ...]],
    aliases: dict[str, str],
    active: frozenset[str] = frozenset(),
) -> str | None:
    """Return a runtime gate in a contract class or local base."""
    if qualified_name in active:
        return None
    declaration = declarations.get(qualified_name)
    if declaration is None:
        return None
    module_name = qualified_name.rpartition(".")[0]
    error = _fixture_or_setup_gate_error(
        declaration.body,
        aliases,
        module_name,
        frozenset({"setup_class", "setup_method"}),
    )
    if error:
        return error

    next_active = active | {qualified_name}
    for base in bases.get(qualified_name, ()):
        inherited = _class_runtime_gate_error(
            base,
            declarations,
            bases,
            aliases,
            next_active,
        )
        if inherited:
            return f"inherits contract base with {inherited}"
    return None


def _returned_channel(
    value: ast.expr | None,
    aliases: dict[str, str],
    module_name: str,
    accepted_imports: dict[str, str],
) -> str | None:
    """Resolve a direct channel constructor returned by a factory."""
    if not isinstance(value, ast.Call):
        return None

    called = _resolve_expr(value.func, aliases, module_name)
    if called in accepted_imports:
        return accepted_imports[called]

    if isinstance(value.func, ast.Attribute) and value.func.attr in {
        "from_config",
        "from_env",
    }:
        owner = _resolve_expr(
            value.func.value,
            aliases,
            module_name,
        )
        if owner in accepted_imports:
            return accepted_imports[owner]
    return None


def scan_contract_tests(  # pylint: disable=too-many-branches,too-many-statements
    specs: Iterable[ChannelSpec],
    accepted_imports: dict[str, str],
    repo_root: Path = REPO_ROOT,
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Find channels returned by concrete, collectable contract factories."""
    specs = tuple(specs)
    contract_dir = repo_root / CONTRACT_TESTS_PATH
    if not contract_dir.exists():
        return frozenset(), (f"missing contract directory: {contract_dir}",)

    expected_paths = {
        spec.class_name: Path(spec.suggested_test_path) for spec in specs
    }
    tested_by: dict[str, str] = {}
    duplicate_classes: set[str] = set()
    errors: list[str] = []
    for test_path in sorted(contract_dir.glob("test_*_contract.py")):
        tree = _read_ast(test_path)
        module_name, _ = _module_name(test_path, repo_root)
        module_aliases = _stable_imports(tree.body, module_name)
        module_error = _module_gate_error(
            tree,
            module_aliases,
            module_name,
        )
        if module_error:
            errors.append(f"{test_path.name} {module_error}")
            continue

        module_runtime_error = _fixture_or_setup_gate_error(
            tree.body,
            module_aliases,
            module_name,
            frozenset({"setup_module"}),
        )
        if module_runtime_error:
            errors.append(f"{test_path.name} {module_runtime_error}")
            continue

        declarations, bases = _test_class_bases(
            tree,
            module_name,
            module_aliases,
        )
        contract_names = frozenset(
            name for name in declarations if _inherits_contract(name, bases)
        )
        audited_names = set(contract_names)
        pending_names = list(contract_names)
        while pending_names:
            name = pending_names.pop()
            for base in bases.get(name, ()):
                if base in declarations and base not in audited_names:
                    audited_names.add(base)
                    pending_names.append(base)
        invalid_base = next(
            (
                (name, base)
                for name in audited_names
                for base in bases.get(name, ())
                if base != CONTRACT_BASE and base not in declarations
            ),
            None,
        )
        if invalid_base is not None:
            class_name, base = invalid_base
            errors.append(
                f"{test_path.name}:{class_name.rsplit('.', 1)[-1]} "
                f"uses external contract base {base}",
            )
            continue

        mutation_error = _module_class_mutation_error(
            tree,
            audited_names,
            module_aliases,
            module_name,
        )
        if mutation_error:
            errors.append(f"{test_path.name} {mutation_error}")
            continue

        for qualified_name, declaration in declarations.items():
            if not _inherits_contract(qualified_name, bases):
                continue
            if _abstract_methods(
                qualified_name,
                declarations,
                bases,
                module_aliases,
                module_name,
            ):
                continue

            class_label = f"{test_path.name}:{declaration.name}"
            if not declaration.name.startswith("Test"):
                errors.append(
                    f"{class_label} name must start with Test "
                    "for pytest collection",
                )
                continue
            collection_error = _class_gate_error(
                qualified_name,
                declarations,
                bases,
                module_aliases,
            )
            if collection_error:
                errors.append(f"{class_label} {collection_error}")
                continue
            runtime_error = _class_runtime_gate_error(
                qualified_name,
                declarations,
                bases,
                module_aliases,
            )
            if runtime_error:
                errors.append(f"{class_label} {runtime_error}")
                continue

            factories = tuple(
                node
                for node in declaration.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.name == "create_instance"
            )
            label = f"{class_label}.create_instance"
            if _binding_count(declaration.body, "create_instance") != 1:
                errors.append(
                    f"{label} must have exactly one class-level binding",
                )
                continue
            if len(factories) != 1:
                errors.append(
                    f"{label} must have exactly one direct definition",
                )
                continue
            factory = factories[0]
            if isinstance(factory, ast.AsyncFunctionDef):
                errors.append(f"{label} must be synchronous")
                continue
            signature_error = _factory_signature_error(factory)
            if signature_error:
                errors.append(f"{label} {signature_error}")
                continue
            gate_error = _factory_gate_error(
                factory,
                module_aliases,
                module_name,
            )
            if gate_error:
                errors.append(f"{label} {gate_error}")
                continue

            returned_values = _factory_returns(factory)
            if len(returned_values) != 1:
                errors.append(
                    f"{label} must contain exactly one return statement",
                )
                continue
            aliases = dict(module_aliases)
            for name in _rebound_names(factory.body):
                aliases.pop(name, None)
            aliases.update(_stable_imports(factory.body, module_name))
            tested_class = _returned_channel(
                returned_values[0],
                aliases,
                module_name,
                accepted_imports,
            )
            if tested_class is None:
                errors.append(
                    f"{label} must directly return a registered channel",
                )
                continue

            actual_path = test_path.relative_to(repo_root)
            expected_path = expected_paths[tested_class]
            if actual_path != expected_path:
                errors.append(
                    f"{label} must be declared in "
                    f"{expected_path.as_posix()}",
                )
                continue
            if tested_class in duplicate_classes:
                errors.append(
                    f"{tested_class} has another duplicate contract "
                    f"factory: {label}",
                )
                continue
            if tested_class in tested_by:
                errors.append(
                    f"{tested_class} has duplicate contract factories: "
                    f"{tested_by[tested_class]} and {label}",
                )
                tested_by.pop(tested_class)
                duplicate_classes.add(tested_class)
                continue
            tested_by[tested_class] = label

    return frozenset(tested_by), tuple(errors)


def analyze_repository(repo_root: Path = REPO_ROOT) -> CoverageReport:
    """Build the complete static channel-contract coverage report."""
    specs = load_builtin_specs(repo_root)
    accepted_imports, source_errors = resolve_registered_classes(
        specs,
        repo_root,
    )
    tested, test_errors = scan_contract_tests(
        specs,
        accepted_imports,
        repo_root,
    )
    return CoverageReport(
        specs=specs,
        tested_classes=tested,
        errors=source_errors + test_errors,
    )


def main(argv: Iterable[str] | None = None) -> int:
    """Print coverage and return a CI-friendly status code."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    if args not in {(), ("--list-specs",)}:
        print(
            "Usage: check_channel_contracts.py [--list-specs]",
            file=sys.stderr,
        )
        return 2

    try:
        if args == ("--list-specs",):
            for spec in load_builtin_specs():
                source_dir = spec.module.lstrip(".").split(".", 1)[0]
                print(
                    f"{spec.key}\t{source_dir}\t"
                    f"{spec.suggested_test_path}",
                )
            return 0
        report = analyze_repository()
    except CoverageCheckError as exc:
        print(f"Channel contract check failed: {exc}", file=sys.stderr)
        return 2

    print()
    print("Channel Contract Coverage")
    print(f"   Total channels: {len(report.specs)}")
    print(f"   With tests:     {len(report.tested_classes)}")
    print(f"   Missing:        {len(report.missing_specs)}")

    if report.tested_classes:
        tested = ", ".join(sorted(report.tested_classes))
        print(f"\n[OK] Tested: {tested}")

    if report.errors:
        print("\n[ERROR] Invalid coverage declarations:")
        for error in report.errors:
            print(f"   - {error}")

    if report.missing_specs:
        print("\n[MISSING] Contract tests:")
        for spec in report.missing_specs:
            print(f"   - {spec.class_name}")
            print(f"     Add {spec.suggested_test_path}")
        print(
            "\nCopy an existing contract test and implement "
            "create_instance().",
        )

    if report.errors:
        return 2
    if report.missing_specs:
        return 1

    print("\n[OK] All built-in channels have contract tests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
