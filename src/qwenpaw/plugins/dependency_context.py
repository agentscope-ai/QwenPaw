# -*- coding: utf-8 -*-
"""Host-selected dependency installer, separate from consumer evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from .dependency_maintenance import canonical, contains_environment_path


def _runtime_environment_snapshot(runtime):
    if runtime is None:
        return None
    return (
        runtime.python_executable,
        runtime.support_root,
        tuple(runtime.dependency_paths),
        runtime.dependency_install_target,
        json.dumps(runtime.runtime_identity, sort_keys=True),
    )


def _capture_runtime_selection(get_runtime, is_frozen=None):
    """Capture once; subsequent checks compare only in-memory policy."""
    if is_frozen is None:
        is_frozen = lambda: bool(getattr(sys, "frozen", False))
    runtime = get_runtime()
    identity = _runtime_environment_snapshot(runtime)
    frozen = is_frozen()

    def validate():
        if (
            get_runtime() is not runtime
            or _runtime_environment_snapshot(runtime) != identity
            or is_frozen() != frozen
        ):
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")

    return validate


def host_bundle_identity():
    """Bind desktop recovery to the bundle independently of runtime policy."""
    from .channel_bootstrap import plugin_runtime_site, runtime_manifest

    return plugin_runtime_site(Path("/"), runtime_manifest()).parent.name


@dataclass(frozen=True)
class DependencyEnvironmentContext:
    """One trusted installer and publication policy across a transaction."""

    python_executable: str
    support_root: Path
    dependency_paths: tuple[Path, ...]
    install_target: Path | None
    immutable_roots: tuple[Path, ...] = ()
    runtime_identity: dict | None = None
    immutable_identity: str | None = None

    @classmethod
    def from_runtime(cls, runtime):
        from .channel_bootstrap import dependency_metadata_identity

        target = runtime.dependency_install_target
        if target is not None and Path(target).is_symlink():
            raise ValueError("CHANNEL_RUNTIME_TARGET_INVALID")
        immutable = (
            tuple(
                canonical(path)
                for path in runtime.dependency_paths
                if target is None
                or str(canonical(path)) != str(canonical(target))
            )
            if runtime.runtime_identity is not None
            else ()
        )
        if runtime.runtime_identity is not None:
            executable = Path(runtime.python_executable).absolute()
            native = None
            if executable.name.lower() == "python.exe":
                prefix = (
                    executable.parent.parent
                    if executable.parent.name.casefold() == "scripts"
                    else executable.parent
                )
                prefix = canonical(prefix)
                native = prefix / "Lib/site-packages"
            elif executable.parent.name == "bin":
                prefix = canonical(executable.parent.parent)
                major, minor = runtime.runtime_identity["version"][:2]
                native = prefix / f"lib/python{major}.{minor}/site-packages"
            if native is not None and native.is_dir():
                native = canonical(native)
                if not contains_environment_path(prefix, native):
                    raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
                if target is None or str(native) != str(canonical(target)):
                    immutable = tuple(
                        {
                            str(path): path for path in (*immutable, native)
                        }.values(),
                    )
        return cls(
            str(Path(runtime.python_executable).absolute()),
            Path(runtime.support_root).resolve(),
            tuple(
                Path(key)
                for key in dict.fromkeys(
                    str(canonical(path)) for path in runtime.dependency_paths
                )
            ),
            canonical(target) if target is not None else None,
            immutable,
            json.loads(json.dumps(dict(runtime.runtime_identity)))
            if runtime.runtime_identity is not None
            else None,
            dependency_metadata_identity(immutable, "immutable")
            if immutable
            else None,
        )

    @classmethod
    def from_snapshot(cls, snapshot):
        sites = tuple(
            Path(key)
            for key in dict.fromkeys(
                str(canonical(site))
                for site in snapshot.dependency_sites or ()
            )
        )
        prefix = canonical(snapshot.prefix)
        targets = [
            site
            for site in sites
            if site.name in {"site-packages", "dist-packages"}
            and contains_environment_path(prefix, site)
        ]
        return cls(
            snapshot.executable,
            Path(__file__).resolve().parents[2],
            sites,
            targets[0] if len(targets) == 1 else None,
        )

    def to_mapping(self):
        return json.loads(json.dumps(asdict(self), default=str))

    @classmethod
    def from_mapping(cls, value):
        fields = {
            "python_executable",
            "support_root",
            "dependency_paths",
            "install_target",
            "immutable_roots",
            "runtime_identity",
            "immutable_identity",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise RuntimeError("DEPENDENCY_PLAN_UNVERIFIED: invalid context.")
        if any(
            not isinstance(value[key], list)
            for key in ("dependency_paths", "immutable_roots")
        ) or (
            value["runtime_identity"] is not None
            and not isinstance(value["runtime_identity"], dict)
        ):
            raise RuntimeError("DEPENDENCY_PLAN_UNVERIFIED: invalid context.")
        identity = value["immutable_identity"]
        if identity is not None and (
            not isinstance(identity, str)
            or len(identity) != 64
            or any(char not in "0123456789abcdef" for char in identity)
        ):
            raise RuntimeError("DEPENDENCY_PLAN_UNVERIFIED: invalid context.")
        paths = [value["python_executable"], value["support_root"]]
        paths.extend(value["dependency_paths"])
        paths.extend(value["immutable_roots"])
        if value["install_target"] is not None:
            paths.append(value["install_target"])
        if any(
            not isinstance(path, str) or not Path(path).is_absolute()
            for path in paths
        ):
            raise RuntimeError("DEPENDENCY_PLAN_UNVERIFIED: invalid context.")
        return cls(
            value["python_executable"],
            Path(value["support_root"]),
            tuple(Path(path) for path in value["dependency_paths"]),
            Path(value["install_target"]) if value["install_target"] else None,
            tuple(Path(path) for path in value["immutable_roots"]),
            value["runtime_identity"],
            identity,
        )

    def protected(self, site):
        return any(
            contains_environment_path(root, site)
            for root in self.immutable_roots
        )

    def immutable_providers(self):
        """Read bundled provider policy without changing consumer evidence."""
        from .execution.dependencies import (
            _installed_metadata,
            dependency_error,
        )

        if not self.immutable_roots:
            return {}
        rows, invalid, _observed = _installed_metadata(self.immutable_roots)
        if invalid:
            raise dependency_error(next(iter(invalid.values())))
        return rows

    @staticmethod
    def refuse_immutable_provider(name, row):
        from .dependency_gate import GateDecision, SharedDependencyError

        raise SharedDependencyError(
            GateDecision(
                False,
                False,
                reason=(
                    f"{name} {row['version']} is bundled with the dependency "
                    "runtime and cannot be overlaid. Update the desktop app "
                    "or use the environment owner's package manager."
                ),
                reason_code="DEPENDENCY_ENVIRONMENT_PROTECTED",
            ),
        )

    def inspect_executor(self):
        """Validate actual Python identity; return its actual wheel tags."""
        from .channel_bootstrap import validate_runtime_identity

        code = (
            "import sys,json;sys.path.insert(0,sys.argv[1]);"
            "from packaging.markers import default_environment;"
            "from packaging.tags import sys_tags;"
            "print(json.dumps(dict(executable=sys.executable,"
            "marker_environment=default_environment(),"
            "supported_tags=[str(t) for t in sys_tags()])))"
        )
        result = subprocess.run(
            [
                self.python_executable,
                "-I",
                "-B",
                "-c",
                code,
                str(self.support_root),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(
                "DEPENDENCY_INSTALLER_UNAVAILABLE: installer inspection failed.",
            )
        evidence = SimpleNamespace(**json.loads(result.stdout))
        if (
            Path(evidence.executable).resolve()
            != Path(self.python_executable).resolve()
        ):
            raise ValueError("CHANNEL_RUNTIME_IDENTITY_MISMATCH")
        validate_runtime_identity(
            evidence,
            self.runtime_identity,
            self.python_executable,
        )
        return tuple(evidence.supported_tags)
