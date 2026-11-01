# -*- coding: utf-8 -*-
"""Disposable pip environments with verified installer integrity."""

import ensurepip
import os
from pathlib import Path
import site
import shutil
import subprocess
import venv
import zipfile

import qwenpaw


def expose(source, destination):
    """Link dependencies, or copy when symlinks need extra privileges."""
    try:
        destination.symlink_to(source, target_is_directory=source.is_dir())
    except OSError:
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def dependency_python(root):
    """Reuse host dependencies, exposing exactly one pip installation."""
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(root)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    library = Path(
        subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            text=True,
        ).strip(),
    )
    # Project dependencies rather than adding the host site directory: its pip
    # and editable .pth files would defeat this interpreter's isolation.
    for directory in site.getsitepackages():
        for entry in Path(directory).iterdir():
            # pywin32's bootstrap exposes win32/lib and its DLLs on Windows.
            if (
                entry.suffix == ".pth" and entry.name != "pywin32.pth"
            ) or entry.name == "__pycache__":
                continue
            destination = library / entry.name
            if not destination.exists():
                # Audits resolve metadata origins within the observed site.
                if entry.suffix == ".dist-info" and entry.is_dir():
                    shutil.copytree(entry, destination)
                else:
                    expose(entry, destination)
    source = library / "qwenpaw"
    if not source.exists():
        expose(Path(qwenpaw.__file__).resolve().parent, source)
    if not (library / "pip").exists():
        bundled = next(
            (Path(ensurepip.__file__).parent / "_bundled").glob("pip-*.whl"),
        )
        with zipfile.ZipFile(bundled) as archive:
            archive.extractall(library)
    subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata as m, importlib.util; "
            "items = [d for d in m.distributions() "
            "if d.metadata['Name'].lower() == 'pip']; "
            "assert len(items) == 1, items; "
            "assert importlib.util.find_spec('pip') is not None",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return python, library
