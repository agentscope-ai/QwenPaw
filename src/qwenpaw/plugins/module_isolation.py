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
"""

import builtins
import importlib
import importlib.abc
import importlib.machinery
import sys
import threading
from typing import Any, Dict, List, Optional


class _NamespaceLoader(importlib.abc.Loader):
    """Wrap a real loader so the module executes with plugin builtins."""

    def __init__(
        self,
        wrapped: importlib.abc.Loader,
        plugin_builtins: Dict[str, Any],
    ) -> None:
        self._wrapped = wrapped
        self._builtins = plugin_builtins

    def create_module(self, spec: Any) -> Any:
        return self._wrapped.create_module(spec)

    def exec_module(self, module: Any) -> None:
        module.__dict__["__builtins__"] = self._builtins
        self._wrapped.exec_module(module)


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
        if not sep:
            # The entry module itself is loaded explicitly by the caller.
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


def build_plugin_builtins(
    module_name: str,
    search_paths: List[str],
) -> Dict[str, Any]:
    """Builtins mapping with a plugin-aware ``__import__``.

    Bare top-level imports whose name exists under *search_paths* (the
    plugin's own directories) are imported as ``<module_name>.<name>``;
    everything else falls through to the regular machinery.
    """
    local_cache: Dict[str, bool] = {}

    def _is_local(top: str) -> bool:
        found = local_cache.get(top)
        if found is None:
            found = (
                importlib.machinery.PathFinder.find_spec(top, search_paths)
                is not None
            )
            local_cache[top] = found
        return found

    def _plugin_import(
        name: str,
        globals: Any = None,  # pylint: disable=redefined-builtin
        locals: Any = None,  # pylint: disable=redefined-builtin
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if level == 0 and name:
            top = name.partition(".")[0]
            if top != module_name and _is_local(top):
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
