# -*- coding: utf-8 -*-
"""Plugin module-loading validation utilities.

This module provides the core validation logic used by both the CLI
``plugin install`` and ``plugin validate`` commands. It replicates
the module-loading semantics of PluginLoader.load_plugin so that
plugins are validated under the same conditions they will run in.
"""

import importlib.util
import sys
from pathlib import Path


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

    spec = importlib.util.spec_from_file_location(
        module_name,
        backend_path,
        submodule_search_locations=[plugin_dir_str],
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
    module.__path__ = [plugin_dir_str]
    try:
        spec.loader.exec_module(module)

        if not hasattr(module, "plugin"):
            raise AttributeError(
                "Plugin module must export a 'plugin' instance",
            )
    finally:
        # Clean up ephemeral validation modules to avoid
        # leaking into the process on repeated installs.
        prefix = module_name + "."
        for key in list(sys.modules):
            if key == module_name or key.startswith(prefix):
                sys.modules.pop(key, None)
