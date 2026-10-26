# -*- coding: utf-8 -*-
"""Disposable installer fixtures remain isolated on all supported platforms."""

from pathlib import Path
import subprocess

import pytest


def distribution(root, name, version):
    """Write discoverable package metadata and importable module bytes."""
    module = name.replace("-", "_")
    info = root / f"{module}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
    )
    (root / f"{module}.py").write_text(f"VERSION = {version!r}\n")
    (info / "top_level.txt").write_text(module + "\n")
    (info / "RECORD").write_text(
        f"{module}.py,,\n{info.name}/METADATA,,\n"
        f"{info.name}/top_level.txt,,\n{info.name}/RECORD,,\n",
    )
    return info


@pytest.mark.parametrize(
    ("installer", "host_has_pip"),
    [("pip", True), ("pip", False), ("uv", True)],
)
def test_installer_environment_exposes_exactly_one_pip_or_none(
    tmp_path,
    monkeypatch,
    installer,
    host_has_pip,
):
    from . import sdk_dependency_fixture

    host = tmp_path / "host-site"
    host.mkdir()
    if host_has_pip:
        info = distribution(host, "pip", "99.0")
        (host / "pip.py").unlink()
        (host / "pip").mkdir()
        (host / "pip/__init__.py").write_text("__version__ = '99.0'\n")
        (info / "RECORD").write_text("pip/__init__.py,,\n")
    monkeypatch.setattr(
        sdk_dependency_fixture.site,
        "getsitepackages",
        lambda: [str(host)],
    )
    python, library = sdk_dependency_fixture.dependency_python(
        tmp_path / "venv",
        installer=installer,
    )
    if installer == "pip":
        result = subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import pip; print(pip.__version__); print(pip.__file__)",
            ],
            text=True,
        ).splitlines()
        if host_has_pip:
            assert result[0] == "99.0"
        assert (
            Path(result[1]).resolve()
            == (library / "pip/__init__.py").resolve()
        )
    else:
        assert not (library / "pip").exists()


def test_installer_fixture_supports_filesystems_without_symlinks(
    tmp_path,
    monkeypatch,
):
    from .sdk_dependency_fixture import expose

    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("VALUE = 1\n")

    def unavailable(*_args, **_kwargs):
        raise OSError("Symlink privilege unavailable")

    monkeypatch.setattr(Path, "symlink_to", unavailable)
    destination = tmp_path / "copy"
    expose(source, destination)
    assert not destination.is_symlink()
    assert (destination / "module.py").read_text() == "VALUE = 1\n"
