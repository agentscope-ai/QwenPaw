# -*- coding: utf-8 -*-
"""Desktop installs resolve all requirements but never shadow host packages."""

# pylint: disable=protected-access

import json
import subprocess
import zipfile

import pytest

from qwenpaw.plugins import SDKRestartRequiredError
from qwenpaw.plugins import _sdk_dependencies as dependencies

from .sdk_dependency_fixture import dependency_python
from .test_sdk_dependency_environment import audit_paths, distribution

pytestmark = pytest.mark.p1


def wheel(root, name, version, requires=""):
    module = name.replace("-", "_")
    info = f"{module}-{version}.dist-info"
    path = root / f"{module}-{version}-py3-none-any.whl"
    files = {
        f"{module}/__init__.py": f"VERSION = {version!r}\n",
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + (f"Requires-Dist: {requires}\n" if requires else "")
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    files[f"{info}/RECORD"] = "".join(f"{key},,\n" for key in files)
    with zipfile.ZipFile(path, "w") as archive:
        for key, value in files.items():
            archive.writestr(key, value)
    return path


@pytest.mark.parametrize("case", ["install", "conflict", "source", "tamper"])
def test_desktop_target_preserves_host_and_installs_verified_additions(
    tmp_path,
    monkeypatch,
    case,
):
    python, _ = dependency_python(tmp_path / "installer")
    host = tmp_path / "host"
    distribution(host, "sdk-target-shared", "1.0")
    audit_paths(monkeypatch, host)
    shared = wheel(tmp_path, "sdk-target-shared", "1.0")
    wheel(tmp_path, "sdk-target-shared", "2.0")
    child = wheel(
        tmp_path,
        "sdk-target-child",
        "1.0",
        "sdk-target-shared" + (">=2" if case == "conflict" else ">=1"),
    )
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        f"sdk-target-shared @ {shared.as_uri()}\n"
        if case == "source"
        else "sdk-target-child==1.0\n",
    )
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path))
    monkeypatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    target = tmp_path / "target"
    commands = []

    def run(args, **_):
        commands.append(args)
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if case == "tamper" and "--report" in args and not result.returncode:
            with child.open("ab") as archive:
                archive.write(b"changed-after-resolution")
        return result

    def install():
        dependencies.install_sdk_requirements(
            requirements,
            "target-probe",
            python=str(python),
            target=str(target),
            run=run,
            find_uv=lambda: None,
        )

    if case in {"conflict", "source"}:
        with pytest.raises(SDKRestartRequiredError):
            install()
        assert all("--dry-run" in command for command in commands)
    elif case == "tamper":
        with pytest.raises(RuntimeError, match="HASHES"):
            install()
    else:
        install()
        assert (target / "sdk_target_child/__init__.py").read_text() == (
            "VERSION = '1.0'\n"
        )
        # The complete resolver saw the shared dependency, but no copy of it
        # can shadow code already loaded by the desktop host.
        assert "--require-hashes" in commands[-1]
        assert "--no-deps" in commands[-1]
    assert not list(target.glob("sdk_target_shared*"))
    assert (host / "sdk_target_shared.py").read_text() == "VERSION = '1.0'\n"


def test_desktop_unknown_artifact_hash_is_rejected():
    plan = json.loads(
        '{"install":[{"metadata":{"name":"new-package","version":"1"},'
        '"download_info":{"url":"https://example.invalid/a.whl",'
        '"archive_info":{"hashes":{}}}}]}',
    )
    with pytest.raises(SDKRestartRequiredError, match="sha256"):
        dependencies._target_requirements(
            plan,
            {},
        )  # pylint: disable=protected-access
