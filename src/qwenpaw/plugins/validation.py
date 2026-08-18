# -*- coding: utf-8 -*-
"""Plugin module-loading validation utilities.

This module provides the core validation logic used by both the CLI
``plugin install`` and ``plugin validate`` commands. It replicates
the module-loading semantics of PluginLoader.load_plugin so that
plugins are validated under the same conditions they will run in.
"""

import importlib.util
import os
import sys
from pathlib import Path

from .module_isolation import (
    build_plugin_builtins,
    get_namespace_finder,
    strip_plugin_sys_path,
    sweep_bare_tree_modules,
    unregister_namespace,
)


def validate_plugin_module(
    plugin_id: str,
    plugin_path: Path,
    backend_entry: str,
) -> None:
    """Validate a plugin module can be imported with relative imports.

    This replicates the module-loading semantics of PluginLoader.load_plugin:
    - Sanitizes plugin_id (replace '-' with '_') for a valid Python identifier
    - Registers in sys.modules BEFORE exec_module
    - Cleans up all ephemeral modules in finally

    Args:
        plugin_id: The plugin identifier (may contain hyphens).
        plugin_path: Path to the plugin directory.
        backend_entry: Relative path to the backend entry file.

    Raises:
        FileNotFoundError: If the backend entry file doesn't exist.
        ImportError: If the module cannot be loaded (e.g. broken imports).
        AttributeError: If the module exports neither Plugin class nor plugin
            instance.
    """
    backend_path = plugin_path / backend_entry
    if not backend_path.exists():
        raise FileNotFoundError(
            f"Backend entry point not found: {backend_entry}",
        )

    safe_id = plugin_id.replace("-", "_")
    module_name = f"_plugin_validation_{safe_id}"
    plugin_dir_str = str(plugin_path)
    # Nested entry files (e.g. ``backend/main.py``) resolve their bare
    # imports against the entry directory — mirror PluginLoader,
    # including entry-directory-first precedence.
    entry_dir_str = str(backend_path.parent)
    search_paths = [entry_dir_str]
    if os.path.normcase(os.path.realpath(entry_dir_str)) != os.path.normcase(
        os.path.realpath(plugin_dir_str),
    ):
        search_paths.append(plugin_dir_str)

    spec = importlib.util.spec_from_file_location(
        module_name,
        backend_path,
        submodule_search_locations=search_paths,
    )
    if not (spec and spec.loader):
        raise ImportError(
            f"Cannot create module spec for {backend_entry}",
        )

    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module so that
    # relative imports can resolve the parent package.
    sys.modules[module_name] = module
    module.__package__ = module_name
    module.__path__ = search_paths
    # Same bare-import redirection as PluginLoader (#6683) so the plugin
    # is validated under the exact conditions it will run in.
    plugin_builtins = build_plugin_builtins(
        module_name,
        search_paths,
        entry_file=backend_path,
    )
    module.__dict__["__builtins__"] = plugin_builtins
    get_namespace_finder().register(module_name, plugin_builtins)
    try:
        spec.loader.exec_module(module)

        if not hasattr(module, "plugin"):
            raise AttributeError(
                "Plugin module must export a 'plugin' instance",
            )
    finally:
        # Clean up ephemeral validation modules to avoid
        # leaking into the process on repeated installs.  Sweep
        # sys.modules BEFORE unregistering the namespace — same
        # ordering invariant as PluginLoader cleanup, so a lazy
        # import cannot resolve a submodule without the plugin
        # builtins in the window between the two.
        prefix = module_name + "."
        for key in list(sys.modules):
            if key == module_name or key.startswith(prefix):
                sys.modules.pop(key, None)
        unregister_namespace(module_name)
        # Drop any sys.path entries the plugin inserted at import
        # time, and any bare sys.modules entries rooted in its tree,
        # so validation leaves no residue in the CLI process.
        strip_plugin_sys_path(plugin_path)
        sweep_bare_tree_modules(plugin_path)
