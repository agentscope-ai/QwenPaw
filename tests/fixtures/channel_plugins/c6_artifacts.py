# -*- coding: utf-8 -*-
"""Test access to official artifact modules and real unstarted host proxies."""

import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]


def artifact_root(key):
    """Honor extracted archive roots; never mix them with checkout modules."""
    root = os.environ.get("QWENPAW_CHANNEL_PLUGIN_ROOT")
    return (Path(root) if root else ROOT / "plugins/channel") / key


def artifact_module(key, module):
    """Load an actual inner package; no legacy channel facade or business
    code."""
    root = artifact_root(key) / key
    namespace = "c6_artifact_" + key
    existing = sys.modules.get(namespace)
    if existing is not None and Path(existing.__file__).parent != root:
        raise AssertionError("Artifact namespace crossed code roots")
    if existing is None:
        spec = importlib.util.spec_from_file_location(
            namespace,
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[namespace] = package
        spec.loader.exec_module(package)
    result = importlib.import_module(namespace + "." + module)
    assert Path(result.__file__).is_relative_to(root)
    return result


async def unused_process(_request):
    """Construction must never call the host Agent."""
    raise AssertionError("Agent processing started during construction")
    yield  # pylint: disable=unreachable


def description(key):
    """Read production static metadata from the chosen code root."""
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = artifact_root(key)
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text()),
    )
    return describe_channel(source, manifest)


def proxy(key, config=None, process=unused_process, **kwargs):
    """Create the host Proxy through its actual static factory."""
    return description(key).create_proxy(
        process,
        config or {},
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="c6-" + key,
        generation=1,
        qwenpaw_version="2.2.2b4",
        **kwargs,
    )
