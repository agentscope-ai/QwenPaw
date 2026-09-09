# -*- coding: utf-8 -*-
"""Per-plugin import isolation for bare absolute imports.

Each plugin backend executes under a private top-level namespace
(``plugin_<id>``).  Relative imports already stay inside it, but many
plugins use *bare absolute* imports for their own files (``import
utils`` / ``from utils.env import x``), which the default machinery
resolves into the process-wide top-level namespace: the first plugin to
claim a common name (``utils``, ``models``, ``router``, …) wins, and
every plugin loaded afterwards silently receives that module instead of
its own (#6683).

This module redirects such imports back into the plugin's namespace:

- :func:`build_plugin_builtins` returns a ``__builtins__`` mapping whose
  ``__import__`` resolves a bare top-level name against the plugin's own
  directories first and, when found there, imports it as
  ``plugin_<id>.<name>``.
- :class:`PluginNamespaceFinder` (a ``sys.meta_path`` hook) makes every
  module imported under ``plugin_<id>.`` execute with that same
  ``__builtins__``, so nested and lazy (function-level) bare imports
  stay namespaced too.

Names not present in the plugin's directories fall through to the
regular import machinery, so stdlib and third-party imports behave
exactly as before.

Known limitations (documented, not silently broken):

- Only the ``import`` statement is redirected.  Dynamic imports via
  ``importlib.import_module("utils")`` bypass ``__import__``; since a
  plugin's inserted ``sys.path`` entries are swept once its load
  finishes, such calls raise ``ModuleNotFoundError`` after load
  instead of resolving globally.
- Directories a plugin adds to ``sys.path`` itself (e.g. a vendored
  ``lib/``) are not part of the plugin's search paths.  Module-level
  bare imports from them work during load; lazy (function-level) ones
  fail after load, because the inserted entries are swept.
- The plugin's ``__builtins__`` is a snapshot dict: later monkeypatches
  of the ``builtins`` module (e.g. ``mock.patch("builtins.open")``) are
  not visible inside plugin modules.
- Objects pickled with a ``plugin_<id>.…`` ``__module__`` are only
  unpicklable in a process where that plugin is loaded.
- The local/non-local decision per bare top-level name is cached for
  the plugin's lifetime; code generated into the plugin directory at
  runtime after a name was first probed resolves globally.  Extension
  modules only count as plugin code when importable by the current
  interpreter (a vendored wrong-ABI ``.so`` reads as data).
- Plugin modules that landed under bare names via a bypass import are
  removed from ``sys.modules`` when the load finishes.  Held object
  references keep working, but name-keyed lookups against them
  (re-import, ``sys.modules[obj.__module__]`` introspection such as
  string-annotation resolution or pickling) fail afterwards.
"""

import builtins
import importlib
import importlib.abc
import importlib.machinery
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class _NamespaceLoader:
    """Wrap a real loader so the module executes with plugin builtins.

    Deliberately not an ``importlib.abc.Loader`` subclass: everything
    except ``exec_module`` is forwarded to the wrapped loader via
    ``__getattr__`` (``create_module``, ``get_data``, ``get_source``,
    ``get_filename``, ``get_resource_reader``, …) so that
    ``importlib.resources`` and ``pkgutil`` keep working on plugin
    packages.
    """

    def __init__(
        self,
        wrapped: importlib.abc.Loader,
        plugin_builtins: Dict[str, Any],
    ) -> None:
        self._wrapped = wrapped
        self._builtins = plugin_builtins

    def exec_module(self, module: Any) -> None:
        module.__dict__["__builtins__"] = self._builtins
        self._wrapped.exec_module(module)

    def __getattr__(self, name: str) -> Any:
        # Read via __dict__: on an instance created without __init__
        # (e.g. cls.__new__ during copy) a plain self._wrapped access
        # would re-enter __getattr__ and recurse forever.
        wrapped = self.__dict__.get("_wrapped")
        if wrapped is None:
            raise AttributeError(name)
        return getattr(wrapped, name)


class PluginNamespaceFinder(importlib.abc.MetaPathFinder):
    """Meta-path finder active only for registered ``plugin_<id>.*`` names.

    Returns ``None`` for every other import, so it is inert for the rest
    of the process.
    """

    def __init__(self) -> None:
        self._namespaces: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        module_name: str,
        plugin_builtins: Dict[str, Any],
    ) -> None:
        self._namespaces[module_name] = plugin_builtins

    def unregister(self, module_name: str) -> None:
        self._namespaces.pop(module_name, None)

    def is_registered(self, module_name: str) -> bool:
        return module_name in self._namespaces

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: Any = None,  # pylint: disable=unused-argument
    ) -> Optional[importlib.machinery.ModuleSpec]:
        root, sep, _ = fullname.partition(".")
        if not sep or path is None:
            # The entry module itself is loaded explicitly by the
            # caller; and without a parent ``__path__`` PathFinder would
            # fall back to sys.path and could mis-resolve the tail name.
            return None
        plugin_builtins = self._namespaces.get(root)
        if plugin_builtins is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            return None
        if spec.loader is not None:
            spec.loader = _NamespaceLoader(spec.loader, plugin_builtins)
        return spec


_finder_lock = threading.Lock()
_finder: Optional[PluginNamespaceFinder] = None


def get_namespace_finder() -> PluginNamespaceFinder:
    """Return the process-wide finder, installing it on first use."""
    global _finder
    with _finder_lock:
        if _finder is None:
            _finder = PluginNamespaceFinder()
            sys.meta_path.insert(0, _finder)
        return _finder


def unregister_namespace(module_name: str) -> None:
    """Remove *module_name* from the finder (no-op if never installed)."""
    if _finder is not None:
        _finder.unregister(module_name)


def _norm(path: Any) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def strip_plugin_sys_path(source_path: Any) -> None:
    """Remove *source_path* and its subdirectories from ``sys.path``.

    Nested-entry plugins insert e.g. their ``backend/`` dir, so subpaths
    must go too.  Relative entries (``''`` — the CWD — and any other
    non-absolute path) are never touched: resolving them depends on the
    CWD at sweep time, so stripping them could remove entries that
    belong to the process, not the plugin.
    """
    root = _norm(source_path)
    prefix = root + os.sep

    def _keep(entry: str) -> bool:
        if not os.path.isabs(entry):
            return True
        resolved = _norm(entry)
        return resolved != root and not resolved.startswith(prefix)

    sys.path[:] = [p for p in sys.path if _keep(p)]


def sweep_bare_tree_modules(
    source_path: Any,
    previous_modules: Optional[Mapping[str, Any]] = None,
) -> None:
    """Pop non-namespaced ``sys.modules`` entries rooted in *source_path*.

    Redirected plugin imports live under ``plugin_<id>`` and are exempt
    (their root is registered on the finder).  Anything else whose
    ``__file__`` — or, for namespace packages, any ``__path__`` portion
    — falls inside the plugin tree is residue from a bypass import or a
    data-directory fallthrough; left in place, the ``sys.modules``
    cache would keep serving it to later imports even after the
    plugin's ``sys.path`` entries are swept.

    When *previous_modules* is provided, bindings unchanged since that
    snapshot are skipped.  Changed bindings rooted in the plugin tree are
    removed, or restored when they replaced an existing binding.  This keeps
    load-end cleanup proportional to modules imported by that plugin instead
    of filesystem-normalizing the entire process module table.
    """
    root = _norm(source_path)
    prefix = root + os.sep
    missing = object()

    def _under(path: Any) -> bool:
        resolved = _norm(path)
        return resolved == root or resolved.startswith(prefix)

    def _remove_or_restore(name: str, mod: Any, previous: Any) -> None:
        if sys.modules.get(name, missing) is not mod:
            return
        if previous is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous

    for name, mod in list(sys.modules.items()):
        previous = missing
        if previous_modules is not None:
            previous = previous_modules.get(name, missing)
            if previous is mod:
                continue
        top = name.partition(".")[0]
        if _finder is not None and _finder.is_registered(top):
            continue
        try:
            mod_file = getattr(mod, "__file__", None)
            if mod_file is not None:
                if _under(mod_file):
                    _remove_or_restore(name, mod, previous)
                continue
            # Namespace packages have no __file__; match by __path__.
            # Accessing __path__ recomputes _NamespacePath, which can
            # raise KeyError if a parent was popped earlier in this
            # loop — such an orphan is residue by definition.
            try:
                portions = list(getattr(mod, "__path__", None) or [])
            except KeyError:
                _remove_or_restore(name, mod, previous)
                continue
            if portions and any(_under(p) for p in portions):
                _remove_or_restore(name, mod, previous)
        except Exception:  # pylint: disable=broad-except
            # Best-effort cleanup: lazy-module proxies or broken path
            # hooks must not turn a sweep into a load failure.
            continue


# Source and extension modules only: stale bytecode (__pycache__/*.pyc
# or a stray legacy .pyc) is not evidence that a directory is a real
# package, and must not let a data directory shadow a concrete module.
# Deliberate trade-off: a PEP 420 portion shipping ONLY sourceless
# bytecode no longer counts as plugin code either.
_CODE_SUFFIXES = tuple(
    importlib.machinery.SOURCE_SUFFIXES
    + importlib.machinery.EXTENSION_SUFFIXES,
)


def _has_importable_code(portions: List[str]) -> bool:
    """True if any directory portion contains importable code.

    Walks recursively (short-circuiting on the first hit) so a PEP 420
    package whose code lives only in nested subpackages still counts.
    Only paths reachable through valid-identifier components count — a
    file like ``locale/en_US.UTF-8/tool.py`` cannot be imported as a
    module, so it must not make a data directory look like a package.
    The pruning also keeps the walk cheap on large asset trees.
    Bytecode caches are skipped entirely: they are derived artifacts,
    not code the plugin ships.
    """
    for portion in portions:
        for _dirpath, dirnames, filenames in os.walk(portion):
            dirnames[:] = [
                d for d in dirnames if d.isidentifier() and d != "__pycache__"
            ]
            for filename in filenames:
                for suffix in _CODE_SUFFIXES:
                    if (
                        filename.endswith(suffix)
                        and filename[: -len(suffix)].isidentifier()
                    ):
                        return True
    return False


def build_plugin_builtins(
    module_name: str,
    search_paths: List[str],
    entry_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Builtins mapping with a plugin-aware ``__import__``.

    Bare top-level imports whose name exists under *search_paths* (the
    plugin's own directories) are imported as ``<module_name>.<name>``;
    everything else falls through to the regular machinery.  A bare
    import that resolves to *entry_file* itself is aliased to the
    already-loaded entry module instead of executing the file a second
    time.
    """
    entry_origin = _norm(entry_file) if entry_file is not None else None
    spec_cache: Dict[str, Optional[importlib.machinery.ModuleSpec]] = {}

    def _find_local(
        top: str,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        if top not in spec_cache:
            spec = importlib.machinery.PathFinder.find_spec(
                top,
                search_paths,
            )
            # A namespace-package portion (loader is None) needs a
            # tie-break: a genuine PEP 420 package the plugin ships
            # stays plugin-local, but a plain data directory
            # (``locale/`` assets) must fall through so a concrete
            # stdlib/third-party module can win.  Decide purely from
            # the plugin's own files — probing sys.path here would
            # couple the decision to sys.path entries left behind by
            # earlier plugins, reopening the cross-plugin collision
            # this module exists to fix (#6683).
            if spec is not None and spec.loader is None:
                portions = list(spec.submodule_search_locations or [])
                if not _has_importable_code(portions):
                    spec = None
            spec_cache[top] = spec
        return spec_cache[top]

    def _plugin_import(
        name: str,
        globals: Any = None,  # pylint: disable=redefined-builtin
        locals: Any = None,  # pylint: disable=redefined-builtin
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if level == 0 and name:
            top = name.partition(".")[0]
            spec = _find_local(top) if top != module_name else None
            if spec is not None:
                if (
                    name == top
                    and entry_origin is not None
                    and spec.origin is not None
                    and _norm(spec.origin) == entry_origin
                    and module_name in sys.modules
                ):
                    # ``import main`` where main.py IS the entry file:
                    # alias the running entry module instead of
                    # executing the file a second time (which would
                    # duplicate module-level state and side effects).
                    # With a fromlist, delegate so submodules named in
                    # it are imported, mirroring _handle_fromlist.
                    if fromlist:
                        return builtins.__import__(
                            module_name,
                            globals,
                            locals,
                            fromlist,
                            0,
                        )
                    return sys.modules[module_name]
                full = f"{module_name}.{name}"
                if fromlist:
                    return builtins.__import__(
                        full,
                        globals,
                        locals,
                        fromlist,
                        0,
                    )
                builtins.__import__(full, globals, locals, (), 0)
                # ``import utils.env`` binds the name ``utils`` — return
                # the namespaced top package, mirroring the default
                # machinery's contract.
                return sys.modules[f"{module_name}.{top}"]
        return builtins.__import__(name, globals, locals, fromlist, level)

    plugin_builtins = dict(vars(builtins))
    plugin_builtins["__import__"] = _plugin_import
    return plugin_builtins
