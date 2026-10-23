# -*- coding: utf-8 -*-
"""Setuptools hooks for the dormant official channel resources."""

from pathlib import Path
import runpy
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


def bundle(destination, version):
    root = Path(__file__).resolve().parent
    builder = runpy.run_path(
        str(root / "scripts/pack/generate_plugin_metadata.py"),
    )["build_official_channel_bundle"]
    builder(root, Path(destination), host_version=version)


class BuildPy(build_py):
    """Generate resources where the installed package resolves them."""

    def run(self):
        super().run()
        package_dir = (
            Path(self.get_package_dir("qwenpaw"))
            if getattr(self, "editable_mode", False)
            else Path(self.build_lib) / "qwenpaw"
        )
        bundle(
            package_dir / "official_channels",
            self.distribution.get_version(),
        )

    def get_outputs(self, include_bytecode=1):
        outputs = super().get_outputs(include_bytecode)
        directory = Path(self.build_lib) / "qwenpaw/official_channels"
        return sorted(
            set(outputs) | {str(path) for path in directory.glob("*")},
        )

    def get_output_mapping(self):
        mapping = super().get_output_mapping()
        if getattr(self, "editable_mode", False):
            directory = (
                Path(self.get_package_dir("qwenpaw")) / "official_channels"
            )
            build_directory = (
                Path(self.build_lib) / "qwenpaw/official_channels"
            )
            # Metadata prepared before generation may list an older archive.
            for output in list(mapping):
                if Path(output).parent == build_directory:
                    del mapping[output]
            # Strict editable installs link build paths to these source files.
            mapping.update(
                {
                    str(build_directory / path.name): str(path)
                    for path in directory.glob("*")
                },
            )
        return mapping


class SDist(sdist):
    """Ship both private resources and their reproducible source inputs."""

    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        root = Path(__file__).resolve().parent
        builder = runpy.run_path(
            str(root / "scripts/pack/generate_plugin_metadata.py"),
        )
        inventory = runpy.run_path(
            str(root / "src/qwenpaw/plugins/official_channel_catalog.py"),
        )["OFFICIAL_CHANNELS"]
        bundle(
            Path(base_dir) / "src/qwenpaw/official_channels",
            self.distribution.get_version(),
        )
        # A wheel rebuilt from sdist uses exactly the same delivered inputs.
        # Unmigrated plugins remain outside this official source distribution.
        for row in inventory:
            relative = Path("plugins/channel") / row["source_dir"]
            shutil.copytree(
                root / relative,
                Path(base_dir) / relative,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*builder["EXCLUDE_PATTERNS"]),
            )


setup(cmdclass={"build_py": BuildPy, "sdist": SDist})
