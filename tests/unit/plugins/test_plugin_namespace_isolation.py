# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for per-plugin bare-import namespace isolation (#6683).

Two plugins shipping the same top-level module name (``utils``) must not
collide: bare absolute imports (``import utils`` / ``from utils.env
import x``) are redirected into each plugin's private ``plugin_<id>``
namespace, including nested and lazy (function-level) imports, while
stdlib / third-party imports fall through untouched.
"""

import json
import sys
import types
from pathlib import Path
from typing import Dict

import pytest

# ---------------------------------------------------------------------------
# Stub missing agentscope 2.0 modules (same pattern as sibling test file)
# ---------------------------------------------------------------------------
_AGENTSCOPE_STUBS = [
    "agentscope.state",
]
for _mod_name in _AGENTSCOPE_STUBS:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        _stub.AgentState = type(
            "AgentState",
            (),
            {},
        )  # type: ignore[attr-defined]
        sys.modules[_mod_name] = _stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry():
    """Create a fresh PluginRegistry (bypass singleton)."""
    from qwenpaw.plugins.registry import PluginRegistry

    old_instance = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old_instance


@pytest.fixture()
def loader(fresh_registry, tmp_path):
    """Create a PluginLoader wired to the fresh registry."""
    from qwenpaw.plugins.loader import PluginLoader

    ldr = PluginLoader(plugin_dirs=[tmp_path])
    ldr.registry = fresh_registry
    return ldr


@pytest.fixture(autouse=True)
def _cleanup_test_modules(tmp_path):
    """Remove modules loaded from tmp_path and its sys.path entries."""
    yield
    tmp_str = str(tmp_path)
    for key, mod in list(sys.modules.items()):
        mod_file = getattr(mod, "__file__", None)
        if mod_file is not None and mod_file.startswith(tmp_str):
            sys.modules.pop(key, None)
    sys.path[:] = [p for p in sys.path if not str(p).startswith(tmp_str)]


def _write_manifest(
    plugin_dir: Path,
    backend_entry: str = "plugin.py",
) -> Dict:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": plugin_dir.name,
        "name": plugin_dir.name,
        "version": "1.0.0",
        "entry": {"backend": backend_entry},
        "qwenpaw_version": {"min": "0.1.0", "max": "99.0.0"},
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return manifest


async def _load(loader, plugin_dir: Path, backend_entry: str = "plugin.py"):
    from qwenpaw.plugins.architecture import PluginManifest

    manifest = PluginManifest.from_dict(
        json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8")),
    )
    return await loader._load_backend_module(
        manifest.id,
        plugin_dir / backend_entry,
        plugin_dir,
        None,
        manifest,
    )


_REGISTER_OK = (
    "\n"
    "class P:\n"
    "    def register(self, api):\n"
    "        pass\n"
    "\n"
    "plugin = P()\n"
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBareImportNamespaceIsolation:
    @pytest.mark.asyncio
    async def test_conflicting_utils_module_and_package(
        self,
        loader,
        tmp_path,
    ):
        """The #6683 repro: plugin A ships ``utils.py`` (a plain module),
        plugin B ships ``utils/`` (a package).  Both must load and see
        their own ``utils`` regardless of load order."""
        dir_a = tmp_path / "plug-a"
        dir_a.mkdir()
        (dir_a / "utils.py").write_text("WHO = 'A'\n", encoding="utf-8")
        _write_manifest(dir_a)
        (dir_a / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import utils\n"
            "WHO = utils.WHO\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        dir_b = tmp_path / "plug-b"
        (dir_b / "utils").mkdir(parents=True)
        (dir_b / "utils" / "__init__.py").write_text("", encoding="utf-8")
        (dir_b / "utils" / "env.py").write_text(
            "WHO = 'B'\n",
            encoding="utf-8",
        )
        _write_manifest(dir_b)
        (dir_b / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "from utils.env import WHO\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, dir_a)
        # Before the fix this raised: No module named 'utils.env';
        # 'utils' is not a package.
        await _load(loader, dir_b)

        assert sys.modules["plugin_plug_a"].WHO == "A"
        assert sys.modules["plugin_plug_b"].WHO == "B"
        assert "plugin_plug_a.utils" in sys.modules
        assert "plugin_plug_b.utils" in sys.modules

    @pytest.mark.asyncio
    async def test_nested_bare_import_stays_namespaced(
        self,
        loader,
        tmp_path,
    ):
        """Bare imports *inside* plugin submodules resolve to the plugin's
        own files, not to another plugin's same-named module."""
        dir_a = tmp_path / "aaa-first"
        dir_a.mkdir()
        (dir_a / "helper.py").write_text("TAG = 'first'\n", encoding="utf-8")
        _write_manifest(dir_a)
        (dir_a / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import helper\n"
            "TAG = helper.TAG\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        dir_b = tmp_path / "bbb-second"
        (dir_b / "pkg").mkdir(parents=True)
        (dir_b / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        # pkg.core reaches a sibling top-level module via a bare import.
        (dir_b / "pkg" / "core.py").write_text(
            "from helper import TAG\n",
            encoding="utf-8",
        )
        (dir_b / "helper.py").write_text("TAG = 'second'\n", encoding="utf-8")
        _write_manifest(dir_b)
        (dir_b / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "from pkg.core import TAG\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, dir_a)
        await _load(loader, dir_b)

        assert sys.modules["plugin_aaa_first"].TAG == "first"
        assert sys.modules["plugin_bbb_second"].TAG == "second"

    @pytest.mark.asyncio
    async def test_lazy_function_level_import(self, loader, tmp_path):
        """A bare import executed at call time (after other plugins have
        loaded) still resolves inside the calling plugin."""
        dir_a = tmp_path / "lazy-a"
        dir_a.mkdir()
        (dir_a / "shared_name.py").write_text(
            "OWNER = 'lazy-a'\n",
            encoding="utf-8",
        )
        _write_manifest(dir_a)
        (dir_a / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "def whoami():\n"
            "    from shared_name import OWNER\n"
            "    return OWNER\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        dir_b = tmp_path / "lazy-b"
        dir_b.mkdir()
        (dir_b / "shared_name.py").write_text(
            "OWNER = 'lazy-b'\n",
            encoding="utf-8",
        )
        _write_manifest(dir_b)
        (dir_b / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import shared_name\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, dir_a)
        await _load(loader, dir_b)

        # Called only now — after lazy-b claimed ``shared_name`` too.
        assert sys.modules["plugin_lazy_a"].whoami() == "lazy-a"

    @pytest.mark.asyncio
    async def test_stdlib_imports_fall_through(self, loader, tmp_path):
        """Names not shipped by the plugin resolve via the regular
        machinery and are not captured into the plugin namespace."""
        plugin_dir = tmp_path / "std-plug"
        plugin_dir.mkdir()
        _write_manifest(plugin_dir)
        (plugin_dir / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import json\n"
            "JSON_MOD = json\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir)

        assert sys.modules["plugin_std_plug"].JSON_MOD is sys.modules["json"]
        assert "plugin_std_plug.json" not in sys.modules

    @pytest.mark.asyncio
    async def test_nested_entry_dir_imports(self, loader, tmp_path):
        """The qwenpaw-creator layout: entry at ``backend/main.py`` with
        bare imports resolving against ``backend/``."""
        plugin_dir = tmp_path / "nested-entry"
        backend = plugin_dir / "backend"
        (backend / "utils").mkdir(parents=True)
        (backend / "utils" / "__init__.py").write_text("", encoding="utf-8")
        (backend / "utils" / "env.py").write_text(
            "VALUE = 'nested'\n",
            encoding="utf-8",
        )
        _write_manifest(plugin_dir, backend_entry="backend/main.py")
        (backend / "main.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "from utils.env import VALUE\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir, backend_entry="backend/main.py")

        assert sys.modules["plugin_nested_entry"].VALUE == "nested"

    @pytest.mark.asyncio
    async def test_nested_entry_dir_precedes_plugin_root(
        self,
        loader,
        tmp_path,
    ):
        """When the plugin root and the entry directory both ship the same
        bare module name, the entry directory wins — matching the
        ``sys.path.insert(0, dirname(__file__))`` semantics nested-entry
        plugins rely on."""
        plugin_dir = tmp_path / "nested-priority"
        backend = plugin_dir / "backend"
        backend.mkdir(parents=True)
        (plugin_dir / "helper.py").write_text(
            "VALUE = 'plugin-root'\n",
            encoding="utf-8",
        )
        (backend / "helper.py").write_text(
            "VALUE = 'entry-dir'\n",
            encoding="utf-8",
        )
        _write_manifest(plugin_dir, backend_entry="backend/main.py")
        (backend / "main.py").write_text(
            "import os, sys\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "from helper import VALUE\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir, backend_entry="backend/main.py")

        assert sys.modules["plugin_nested_priority"].VALUE == "entry-dir"

    @pytest.mark.asyncio
    async def test_pep420_namespace_packages_stay_isolated(
        self,
        loader,
        tmp_path,
    ):
        """Packages without __init__.py (PEP 420 namespace packages) are
        still plugin-local: two plugins shipping the same namespace
        package name must not share modules."""
        code = (
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "from helpers.value import VALUE\n" + _REGISTER_OK
        )
        for name, val in (("pep-a", "A"), ("pep-b", "B")):
            plugin_dir = tmp_path / name
            (plugin_dir / "helpers").mkdir(parents=True)
            # No __init__.py on purpose — a PEP 420 namespace package.
            (plugin_dir / "helpers" / "value.py").write_text(
                f"VALUE = '{val}'\n",
                encoding="utf-8",
            )
            _write_manifest(plugin_dir)
            (plugin_dir / "plugin.py").write_text(code, encoding="utf-8")
            await _load(loader, plugin_dir)

        assert sys.modules["plugin_pep_a"].VALUE == "A"
        assert sys.modules["plugin_pep_b"].VALUE == "B"

    @pytest.mark.asyncio
    async def test_data_directory_does_not_shadow_stdlib(
        self,
        loader,
        tmp_path,
    ):
        """A bare data directory (no __init__.py, no code) must not be
        treated as a plugin-local module: ``import wave`` with a
        ``wave/`` assets dir present still resolves to the stdlib."""
        plugin_dir = tmp_path / "data-dir"
        (plugin_dir / "wave").mkdir(parents=True)
        (plugin_dir / "wave" / "sample.bin").write_bytes(b"\x00")
        _write_manifest(plugin_dir)
        (plugin_dir / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import wave\n"
            "WAVE = wave\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir)

        import wave as real_wave

        assert sys.modules["plugin_data_dir"].WAVE is real_wave
        assert "plugin_data_dir.wave" not in sys.modules

    @pytest.mark.asyncio
    async def test_loader_forwards_resource_access(
        self,
        loader,
        tmp_path,
    ):
        """importlib.resources works on namespaced plugin packages: the
        wrapping loader must forward get_resource_reader etc."""
        import importlib.resources

        plugin_dir = tmp_path / "res-plug"
        pkg = plugin_dir / "assets_pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "data.txt").write_text("hello-resource", encoding="utf-8")
        _write_manifest(plugin_dir)
        (plugin_dir / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import assets_pkg\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir)

        mod = sys.modules["plugin_res_plug.assets_pkg"]
        text = importlib.resources.files(mod).joinpath("data.txt").read_text()
        assert text == "hello-resource"

    @pytest.mark.asyncio
    async def test_bare_import_of_entry_aliases_running_module(
        self,
        loader,
        tmp_path,
    ):
        """A submodule bare-importing the entry file gets the running
        entry module, not a second freshly-executed copy."""
        plugin_dir = tmp_path / "self-imp"
        plugin_dir.mkdir()
        (plugin_dir / "helper.py").write_text(
            "import plugin\nplugin.X.append(1)\n",
            encoding="utf-8",
        )
        _write_manifest(plugin_dir)
        (plugin_dir / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "X = []\n"
            "import helper\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir)

        assert sys.modules["plugin_self_imp"].X == [1]
        assert "plugin_self_imp.plugin" not in sys.modules

    @pytest.mark.asyncio
    async def test_dotted_import_as_binding(self, loader, tmp_path):
        """``import a.b as c`` binds the submodule under the alias."""
        plugin_dir = tmp_path / "dotted-as"
        pkg = plugin_dir / "a"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "b.py").write_text("V = 7\n", encoding="utf-8")
        _write_manifest(plugin_dir)
        (plugin_dir / "plugin.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import a.b as c\n"
            "VAL = c.V\n" + _REGISTER_OK,
            encoding="utf-8",
        )

        await _load(loader, plugin_dir)

        assert sys.modules["plugin_dotted_as"].VAL == 7

    @pytest.mark.asyncio
    async def test_failed_load_unregisters_namespace(
        self,
        loader,
        tmp_path,
    ):
        """A failed load must remove the plugin's import redirection."""
        from qwenpaw.plugins.module_isolation import get_namespace_finder

        plugin_dir = tmp_path / "fail-ns"
        plugin_dir.mkdir()
        _write_manifest(plugin_dir)
        (plugin_dir / "plugin.py").write_text(
            "raise RuntimeError('boom')\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="boom"):
            await _load(loader, plugin_dir)

        assert not get_namespace_finder().is_registered("plugin_fail_ns")
