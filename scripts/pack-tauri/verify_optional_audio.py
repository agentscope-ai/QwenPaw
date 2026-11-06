# -*- coding: utf-8 -*-
"""Reject optional local-audio dependencies in a finished desktop bundle."""

import json
import sys
from importlib.metadata import distributions
from pathlib import Path


HEAVY_MODULES = {"whisper", "torch", "torchaudio", "torchvision", "triton"}


def verify(bundle: Path) -> dict:
    """Inspect shipped files and both executable Python archives."""
    from PyInstaller.archive.readers import CArchiveReader

    internal = bundle / "_internal"
    optional = internal / "qwenpaw/plugins/optional/local_whisper"
    for name in ("main.py", "plugin.json"):
        if not (optional / name).is_file():
            raise ValueError(f"Missing optional Whisper adapter: {name}")
    forbidden = set()
    bundled_modules = set()
    size = 0
    for path in bundle.rglob("*"):
        name = path.name.lower().replace("-", "_")
        if (
            (path.parent == internal and name in HEAVY_MODULES)
            or name.startswith("libtorch")
            or any(
                name.startswith(module + "_")
                and name.endswith((".dist_info", ".egg_info"))
                for module in HEAVY_MODULES | {"openai_whisper"}
            )
        ):
            forbidden.add(str(path.relative_to(bundle)))
        if path.is_file() and not path.is_symlink():
            size += path.stat().st_size
    for executable in ("qwenpaw-backend", "qwenpaw"):
        path = bundle / (
            executable + (".exe" if sys.platform == "win32" else "")
        )
        archive = CArchiveReader(str(path))
        pyz_names = [name for name in archive.toc if name.endswith(".pyz")]
        if not pyz_names:
            raise ValueError(f"No Python archive in {path}")
        for name in pyz_names:
            pyz = archive.open_embedded_archive(name)
            bundled_modules.update(module.split(".")[0] for module in pyz.toc)
            forbidden.update(
                f"{executable}:{module}"
                for module in pyz.toc
                if module.split(".")[0] in HEAVY_MODULES
            )
    if forbidden:
        raise ValueError(
            f"Unexpected local-audio dependencies: {sorted(forbidden)}",
        )
    metadata = {
        package.metadata["Name"].lower().replace("_", "-")
        for package in distributions(path=[str(internal)])
    }
    # Whisper shares these with the host. Missing metadata makes a target
    # installer mistake live host code for an absent dependency.
    for module, package in {
        "numpy": "numpy",
        "requests": "requests",
        "fsspec": "fsspec",
        "typing_extensions": "typing-extensions",
        "sympy": "sympy",
    }.items():
        if module in bundled_modules and package not in metadata:
            raise ValueError(f"Missing bundled dependency metadata: {package}")
    return {
        "bundle": str(bundle),
        "bytes": size,
        "optional_audio_check": "passed",
        "bundled_distributions": len(metadata),
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
