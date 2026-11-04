# -*- coding: utf-8 -*-
"""Host-selected dependency installer, separate from consumer evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import SimpleNamespace

from .dependency_maintenance import canonical, contains_environment_path

_STARTUP_ENV = "QWENPAW_DEPENDENCY_ENVIRONMENT"
_SELECTED_ENVIRONMENT = None
_SELECTED_POLICY = None


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


def policy_path(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    if not path.parent.is_dir():
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    if os.name != "nt":
        if path.parent.stat().st_mode & 0o022 or (
            path.exists() and path.stat().st_mode & 0o022
        ):
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_POLICY_INVALID: policy control must not be writable by other users.",
            )
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    return (
        canonical(path)
        if path.exists()
        else canonical(path.parent) / path.name
    )


@contextmanager
def dependency_policy_lock(path):
    """Serialize control-directory publication, including absent-name aliases."""
    from .dependency_maintenance import file_lock, state_root

    path = policy_path(path)
    key = hashlib.sha256(str(canonical(path.parent)).encode()).hexdigest()
    with file_lock(state_root() / ("policy-" + key + ".lock"), timeout=5):
        if path.is_symlink():
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
        yield path


def read_dependency_policy(path, *, prepared=False):
    path = policy_path(path)
    if path.stat().st_size > 1024 * 1024:
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    data = json.loads(path.read_text(encoding="utf-8"))
    return _validate_policy_data(data, prepared=prepared)


def _validate_policy_data(data, *, prepared=False):
    data = dict(data) if isinstance(data, dict) else data
    required = {"base_id", "base_sites", "overlay_root", "legacy_sites"}
    if (
        not isinstance(data, dict)
        or not required <= set(data) <= required | {"generation"}
        or not isinstance(data["base_id"], str)
        or not data["base_id"].strip()
        or not isinstance(data["base_sites"], list)
        or not data["base_sites"]
        or not isinstance(data["legacy_sites"], list)
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    generation = data.get("generation")
    if generation is not None and (
        not isinstance(generation, str)
        or re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", generation) is None
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    if not prepared and generation is None:
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_NOT_PREPARED")
    for value in (
        *data["base_sites"],
        *data["legacy_sites"],
        data["overlay_root"],
    ):
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    data["base_sites"] = list(
        dict.fromkeys(str(canonical(p)) for p in data["base_sites"]),
    )
    data["legacy_sites"] = list(
        dict.fromkeys(str(canonical(p)) for p in data["legacy_sites"]),
    )
    data["overlay_root"] = str(canonical(data["overlay_root"]))
    roots = tuple(Path(p) for p in data["base_sites"])
    overlay = Path(data["overlay_root"])
    if (
        any(not root.is_dir() for root in roots)
        or any(
            contains_environment_path(root, overlay)
            or contains_environment_path(overlay, root)
            for root in roots
        )
        or any(
            contains_environment_path(root, legacy)
            or contains_environment_path(legacy, root)
            for root in roots
            for legacy in data["legacy_sites"]
        )
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    return data


def context_for_policy(data, *, support_root=None):
    """Construct policy using only stdlib and native filesystem identity."""
    executable = str(Path(sys.executable).absolute())
    roots = tuple(canonical(p) for p in data["base_sites"])
    support = (
        Path(support_root)
        if support_root is not None
        else Path(__file__).resolve().parents[2]
    )
    import sysconfig

    overlay = canonical(data["overlay_root"])
    if any(
        contains_environment_path(root, overlay)
        for root in (
            support,
            sys.prefix,
            sys.base_prefix,
            *filter(
                None,
                (
                    sysconfig.get_path("stdlib"),
                    sysconfig.get_path("platstdlib"),
                ),
            ),
        )
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    identity = _digest(
        [
            data["base_id"],
            str(canonical(executable)),
            str(sys.implementation.cache_tag),
            [str(p) for p in roots],
        ],
    )
    bucket = (
        f"{sys.implementation.cache_tag}-{sys.platform}-{platform.machine()}"
    )
    target = canonical(
        Path(data["overlay_root"])
        / bucket
        / identity
        / data["generation"]
        / "site",
    )
    if any(
        contains_environment_path(target, p)
        or contains_environment_path(p, target)
        for p in (*roots, *data["legacy_sites"])
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    return DependencyEnvironmentContext(
        executable,
        support,
        (*roots, target),
        target,
        roots,
        None,
        identity,
    )


def dependency_import_paths(paths, context):
    """Keep trusted support/stdlib before explicit dependencies and other paths."""
    import sysconfig

    standard = {
        canonical(value)
        for value in (
            sysconfig.get_path("stdlib"),
            sysconfig.get_path("platstdlib"),
            sysconfig.get_config_var("DESTSHARED"),
        )
        if value
    }
    zip_name = f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    standard.update(root.parent / zip_name for root in tuple(standard))
    standard.add(canonical(Path(sys.base_prefix) / zip_name))
    if sys.platform == "win32":
        standard.add(canonical(Path(sys.base_exec_prefix) / "DLLs"))
    trusted, other = [], []
    for value in paths:
        if value and (
            canonical(value) in standard
            or canonical(value) == canonical(context.support_root)
        ):
            trusted.append(value)
        else:
            other.append(value)
    return list(
        dict.fromkeys(
            [
                *trusted,
                *(str(root) for root in context.dependency_paths),
                *other,
            ],
        ),
    )


def selected_dependency_environment():
    return _SELECTED_ENVIRONMENT


def selected_dependency_policy():
    return dict(_SELECTED_POLICY) if _SELECTED_POLICY is not None else None


def verify_dependency_policy(binding, context=None):
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise RuntimeError("DEPENDENCY_PLAN_STALE: missing dependency policy.")
    path = policy_path(binding["path"])
    data = read_dependency_policy(path)
    if str(path) != binding["path"] or _digest(data) != binding["sha256"]:
        raise RuntimeError(
            "DEPENDENCY_PLAN_STALE: active dependency policy changed.",
        )
    if (
        context is not None
        and context_for_policy(
            data,
            support_root=context.support_root,
        ).to_mapping()
        != context.to_mapping()
    ):
        raise RuntimeError(
            "DEPENDENCY_PLAN_STALE: dependency context changed.",
        )


@contextmanager
def dependency_policy_operation(binding=None, context=None):
    binding = selected_dependency_policy() if binding is None else binding
    if binding is None:
        yield
        return
    with dependency_policy_lock(binding["path"]):
        verify_dependency_policy(binding, context)
        yield


@contextmanager
def prepare_startup_environment():
    """Hold policy protection until the caller has acquired reader custody."""
    global _SELECTED_ENVIRONMENT, _SELECTED_POLICY
    value = os.environ.get(_STARTUP_ENV)
    if not value:
        yield _SELECTED_ENVIRONMENT
        return
    if _SELECTED_ENVIRONMENT is not None:
        yield _SELECTED_ENVIRONMENT
        return
    if getattr(sys, "frozen", False) or os.environ.get(
        "QWENPAW_CHANNEL_RUNTIME_MANIFEST",
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_DESKTOP_CONFLICT")
    with dependency_policy_lock(value) as path:
        if sys.flags.no_site:
            from .dependency_maintenance import (
                restore_managed_interpreter_prefix,
            )

            restore_managed_interpreter_prefix()
        data = read_dependency_policy(path)
        context = context_for_policy(data)
        report = context.install_target.parent / "prepared.json"
        if (
            not report.is_file()
            or report.is_symlink()
            or not context.install_target.is_dir()
        ):
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_NOT_PREPARED")
        record = json.loads(report.read_text(encoding="utf-8"))
        if (
            record.get("policy_sha256") != _digest(data)
            or record.get("dependency_context") != context.to_mapping()
            or record.get("active_policy_path") != str(path)
        ):
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_NOT_PREPARED")
        journal = path.parent / ("." + path.name + ".migration.json")
        if journal.exists() and json.loads(journal.read_text()).get(
            "phase",
        ) not in {"committed", "aborted"}:
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED")
        legacy = tuple(Path(p) for p in data["legacy_sites"])
        for module in tuple(sys.modules.values()):
            origins = [
                getattr(module, "__file__", None),
                *tuple(getattr(module, "__path__", ()) or ()),
            ]
            if any(
                origin
                and any(
                    contains_environment_path(root, origin) for root in legacy
                )
                for origin in origins
            ):
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_DIRTY_PROCESS: start a clean interpreter.",
                )
        sys.path[:] = [
            str(canonical(item or Path.cwd()))
            for item in sys.path
            if not any(
                contains_environment_path(root, item or Path.cwd())
                for root in legacy
            )
        ]
        sys.path[:] = dependency_import_paths(sys.path, context)
        _SELECTED_ENVIRONMENT = context
        _SELECTED_POLICY = {"path": str(path), "sha256": _digest(data)}
        yield context


@lru_cache(maxsize=8)
def _bundle_dependency_fingerprint(identity, metadata):
    """Cache metadata reads by file stat; paths never enter the digest."""
    contents = [
        (label, hashlib.sha256(path.read_bytes()).hexdigest())
        for label, path, *_stat in metadata
    ]
    return hashlib.sha256(
        json.dumps([identity, contents], separators=(",", ":")).encode(),
    ).hexdigest()


def dependency_metadata_identity(sites, identity):
    """Fingerprint immutable metadata with stable site-relative labels."""
    metadata = []
    for index, site in enumerate(sites):
        for distribution in sorted(site.glob("*.dist-info")):
            for name in ("METADATA", "RECORD", "WHEEL"):
                path = distribution / name
                if not path.is_file():
                    continue
                if not path.resolve().is_relative_to(site):
                    raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
                stat = path.stat()
                metadata.append(
                    (
                        f"{index}/{path.relative_to(site).as_posix()}",
                        path,
                        stat.st_mtime_ns,
                        stat.st_ctime_ns,
                        stat.st_size,
                    ),
                )
    return _bundle_dependency_fingerprint(identity, tuple(metadata))


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
            (
                json.loads(json.dumps(dict(runtime.runtime_identity)))
                if runtime.runtime_identity is not None
                else None
            ),
            (
                dependency_metadata_identity(immutable, "immutable")
                if immutable
                else None
            ),
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

    def _managed_bootstrap(self):
        return (
            "import sys,json,runpy;p=json.loads(sys.argv.pop(1));"
            "runpy.run_path(p.pop(0))['restore_managed_interpreter_prefix']();"
            "sys.path.extend(p);",
            json.dumps(
                [
                    str(
                        self.support_root
                        / "qwenpaw/plugins/dependency_maintenance.py",
                    ),
                    str(self.support_root),
                    *(str(p) for p in self.dependency_paths),
                ],
            ),
        )

    def pip_command(self, *arguments):
        if self.immutable_roots and self.runtime_identity is None:
            code, paths = self._managed_bootstrap()
            return [
                self.python_executable,
                "-I",
                "-B",
                "-S",
                "-c",
                code + "runpy.run_module('pip',run_name='__main__')",
                paths,
                *arguments,
            ]
        return [self.python_executable, "-I", "-B", "-m", "pip", *arguments]

    def require_pip(self):
        from ..utils.runtime_environment import _require_installer_version

        return _require_installer_version(
            self.pip_command("--version"),
            "pip",
            (26, 2, 2),
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

        managed = self.runtime_identity is None and bool(self.immutable_roots)
        code = (
            (
                self._managed_bootstrap()[0]
                if managed
                else "import sys,json;sys.path.insert(0,sys.argv[1]);"
            )
            + "from packaging.markers import default_environment;"
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
                *(["-S"] if managed else []),
                "-c",
                code,
                (
                    self._managed_bootstrap()[1]
                    if managed
                    else str(self.support_root)
                ),
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
