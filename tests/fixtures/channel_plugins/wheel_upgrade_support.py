"""Offline real-wheel helpers; ambient host dependencies exclude the test SDK.

The candidate is built unchanged by the project's backend. Host dependencies
are borrowed from the test interpreter, then pip resolves their genuine
metadata without downloads. The SDK wheel contains the real installed paho
package and its original metadata.
"""

import base64
import csv
import hashlib
from importlib import metadata
import io
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[3]
PROBE = Path(__file__).with_name("wheel_upgrade_probe.py")


def run(args, *, env, cwd, timeout=120):
    result = subprocess.run(
        list(map(str, args)),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        result.stdout[-8000:] + result.stderr[-8000:]
    )
    return result


def clean_environment(root):
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR")
        if key in os.environ
    }
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        QWENPAW_WORKING_DIR=str(root / "host"),
        QWENPAW_SECRET_DIR=str(root / "secrets"),
        QWENPAW_BACKUP_DIR=str(root / "backups"),
        QWENPAW_TELEMETRY_DISABLED="1",
        QWENPAW_RUNNING_IN_CONTAINER="true",
        PIP_NO_INDEX="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def build_candidate(root):
    helpers = runpy.run_path(
        str(ROOT / "tests/unit/pack/test_c7_distribution.py")
    )
    stage = root / "stage"
    helpers["_copy_release_inputs"](ROOT, stage)
    return helpers["_build"](stage, root / "wheel", "build_wheel")


def create_environment(root, *, with_pip=True):
    """Borrow actual host libraries while keeping paho genuinely absent."""
    venv.EnvBuilder(with_pip=with_pip).create(root)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    target = Path(result.stdout.strip())
    roots = [
        Path(value)
        for value in sys.path
        if Path(value).name in {"site-packages", "dist-packages"}
    ]
    excluded = ("qwenpaw", "paho", "pip", "__editable__")
    for source in roots:
        for item in source.iterdir():
            if item.name.endswith(".pth") or item.name.startswith(excluded):
                continue
            output = target / item.name
            if output.exists() or output.is_symlink():
                continue
            if item.name.endswith((".dist-info", ".egg-info")):
                if item.is_dir():
                    shutil.copytree(item, output)
                else:
                    shutil.copy2(item, output)
            else:
                output.symlink_to(item, target_is_directory=item.is_dir())
    return python


def _write_wheel(output, name, version, files):
    output.mkdir(parents=True, exist_ok=True)
    normalized = name.replace("-", "_")
    info = f"{normalized}-{version}.dist-info"
    files.setdefault(
        f"{info}/WHEEL",
        b"Wheel-Version: 1.0\nGenerator: qwenpaw-offline-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    )
    records = []
    for path, content in files.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            .rstrip(b"=")
            .decode()
        )
        records.append((path, "sha256=" + digest, str(len(content))))
    record = f"{info}/RECORD"
    rows = io.StringIO()
    csv.writer(rows, lineterminator="\n").writerows(
        [*records, (record, "", "")]
    )
    files[record] = rows.getvalue().encode()
    wheel = output / f"{normalized}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return wheel


def installed_sdk_wheel(output, name="paho-mqtt"):
    sdk = metadata.distribution(name)
    files = {}
    for item in sdk.files:
        path = Path(str(item))
        if path.is_absolute() or ".." in path.parts or path.suffix == ".pyc":
            continue
        if path.name in {
            "RECORD",
            "INSTALLER",
            "direct_url.json",
            "REQUESTED",
        }:
            continue
        files[path.as_posix()] = sdk.locate_file(item).read_bytes()
    assert any(path.startswith("paho/mqtt/") for path in files)
    return _write_wheel(output, name, sdk.version, files)


def legacy_host_wheel(output):
    """A real fixture wheel models the former monolith's SDK dependency."""
    info = "qwenpaw-0.0.0.dist-info"
    return _write_wheel(
        output,
        "qwenpaw",
        "0.0.0",
        {
            "qwenpaw/__init__.py": b"# Legacy monolithic host fixture.\n",
            "qwenpaw/__version__.py": b"__version__ = '0.0.0'\n",
            f"{info}/METADATA": b"Metadata-Version: 2.1\nName: qwenpaw\nVersion: 0.0.0\nRequires-Dist: paho-mqtt>=2.0.0\n\n",
        },
    )
