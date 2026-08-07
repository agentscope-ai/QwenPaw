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
  ``importlib.import_module("utils")`` bypass ``__import__`` and still
  resolve in the global top-level namespace.
- Directories a plugin adds to ``sys.path`` itself (e.g. a vendored
  ``lib/``) are not part of the plugin's search paths; bare imports
  from them remain global.
- The plugin's ``__builtins__`` is a snapshot dict: later monkeypatches
  of the ``builtins`` module (e.g. ``mock.patch("builtins.open")``) are
  not visible inside plugin modules.
- Objects pickled with a ``plugin_<id>.…`` ``__module__`` are only
  unpicklable in a process where that plugin is loaded.
"""

import builtins
import importlib
import importlib.abc
import importlib.machinery
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


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
        return getattr(self._wrapped, name)


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
            # A bare data directory (no __init__.py) resolves as a
            # namespace-package portion (loader is None).  The real
            # machinery would keep searching sys.path and let e.g. the
            # stdlib win, so treat it as non-local instead of shadowing
            # the name with an empty package (a plugin's ``locale/``
            # assets dir must not hijack the stdlib ``locale``).
            if spec is not None and spec.loader is None:
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
