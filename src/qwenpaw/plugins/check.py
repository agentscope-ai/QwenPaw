# -*- coding: utf-8 -*-
"""Run with ``python -m qwenpaw.plugins.check PATH``; opt in to execution."""

import argparse
import asyncio
import json
import sys
import tempfile
import threading
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

from .compliance import PUBLIC_API, CheckFinding, check_plugin


def _source_file(filename: str, directory: Path) -> Path | None:
    """Resolve caller ownership using the current platform's path rules."""
    try:
        file = Path(filename).resolve()
        return file if file.is_relative_to(directory) else None
    except (ValueError, OSError):
        return None


# Keep related adapter declarations and lifecycle ordering together.
# pylint: disable-next=too-many-statements
async def _runtime(directory, report):
    from .testing import PluginTestHost

    findings = list(report.findings)
    seen = set()
    phases = []
    stage = "host-start"
    public_types = {
        (module, name)
        for module, names in PUBLIC_API.items()
        for name in names
    }
    public_types.update(
        {
            ("qwenpaw.plugins.sdk", "PluginContext"),
            ("qwenpaw.plugins.sdk", "Plugin"),
            ("qwenpaw.plugins.activity", "PluginBusyError"),
            ("qwenpaw.pawapp.app", "PawApp"),
            *(
                ("qwenpaw.plugins.errors", name)
                for name in (
                    "SDKError",
                    "SDKAccessError",
                    "SDKCompatibilityError",
                    "SDKRestartRequiredError",
                    "StaleContextError",
                    "ResourceError",
                    "ToolInputError",
                )
            ),
            *(
                ("qwenpaw.plugins._testing_http", name)
                for name in ("TestHttpResponse", "TestConnection")
            ),
        },
    )
    directory = directory.resolve()

    @lru_cache(maxsize=4096)
    def source_file(filename):
        return _source_file(filename, directory)

    protocols = {
        ("qwenpaw.plugins.resources", "Registration"): {
            "__aenter__",
            "__aexit__",
        },
        ("qwenpaw.plugins.testing", "TestFault"): {"__enter__", "__exit__"},
        ("qwenpaw.plugins.testing", "PluginTestHost"): {
            "__aenter__",
            "__aexit__",
        },
        ("qwenpaw.plugins._testing_http", "TestConnection"): {
            "__aenter__",
            "__aexit__",
            "__aiter__",
            "__anext__",
        },
    }

    def profile(frame, event, _arg):
        if event != "call" or frame.f_back is None:
            return
        caller = frame.f_back
        file = source_file(caller.f_code.co_filename)
        if file is None:
            return
        module = frame.f_globals.get("__name__", "")
        if module == "importlib" and frame.f_code.co_name == "import_module":
            imported = frame.f_locals.get("name", "")
            if imported.startswith("qwenpaw.") and imported not in PUBLIC_API:
                key = (
                    str(file.relative_to(directory)),
                    caller.f_lineno,
                    imported,
                )
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        CheckFinding(
                            key[0],
                            key[1],
                            "runtime-private-import",
                            f"Plugin imported private host module: {imported}",
                        ),
                    )
            return
        if not module.startswith("qwenpaw."):
            return
        qualname = frame.f_code.co_qualname
        if (
            module == "qwenpaw.plugins.module_isolation"
            and qualname == "build_plugin_builtins.<locals>._plugin_import"
        ):
            imported = frame.f_locals.get("name", "")
            fromlist = frame.f_locals.get("fromlist", ()) or ()
            if not imported.startswith("qwenpaw") or (
                imported in PUBLIC_API
                and all(
                    name in PUBLIC_API[imported]
                    or f"{imported}.{name}" in PUBLIC_API
                    for name in fromlist
                )
            ):
                return
        owner, _, method = qualname.partition(".")
        allowed = (module, owner) in public_types and (
            not method.startswith("_") or method == "__init__"
        )
        allowed |= module in PUBLIC_API and qualname in PUBLIC_API[module]
        allowed |= method in protocols.get((module, owner), ())
        if frame.f_code.co_name in {
            "__init__",
            "__eq__",
            "__hash__",
            "__repr__",
        }:
            from dataclasses import is_dataclass

            cls = type(frame.f_locals.get("self"))
            allowed |= (
                is_dataclass(cls)
                and (cls.__module__, cls.__qualname__) in public_types
            )
        if allowed:
            return
        key = (
            str(file.relative_to(directory)),
            caller.f_lineno,
            module,
            qualname,
        )
        if key not in seen:
            seen.add(key)
            findings.append(
                CheckFinding(
                    key[0],
                    key[1],
                    "runtime-private-call",
                    f"Plugin called private host entry: {module}.{qualname}",
                ),
            )

    previous = sys.getprofile()
    previous_threads = threading.getprofile()
    try:
        threading.setprofile(profile)
        with tempfile.TemporaryDirectory(
            prefix="qwenpaw-sdk-check-",
        ) as temporary:
            sys.setprofile(profile)
            try:
                async with PluginTestHost(Path(temporary)) as host:
                    stage = "load/activation"
                    await host.load(directory)
                    phases.extend(("load:passed", "activation:passed"))
                    stage = "cleanup"
                phases.append("cleanup:passed")
            finally:
                sys.setprofile(previous)
    except Exception as exc:
        phases.append(f"{stage}:failed")
        findings.append(
            CheckFinding(
                "plugin.json",
                1,
                "runtime-failure",
                f"{type(exc).__name__}: {exc}",
            ),
        )
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_threads)
    return replace(
        report,
        findings=tuple(findings),
        uncovered=(
            *report.uncovered,
            "Only load/activation/cleanup executed; uncalled handlers, "
            "dynamic attribute access, pre-existing threads and native "
            "calls remain unverified",
        ),
        runtime_checked=True,
        lifecycle_checks=tuple(phases),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument(
        "--template",
        type=Path,
        help="Copy the public hello plugin to a new directory",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help=(
            "Execute plugin activation in an isolated temporary host "
            "(plugin code is trusted)"
        ),
    )
    parser.add_argument(
        "--frontend",
        type=Path,
        help="Copy the standalone frontend npm package to this new directory",
    )
    args = parser.parse_args(argv)
    if args.template is not None:
        import shutil

        shutil.copytree(
            Path(__file__).with_name("templates") / "hello",
            args.template,
        )
    if args.frontend is not None:
        import shutil

        shutil.copytree(Path(__file__).with_name("frontend"), args.frontend)
    if args.directory is None:
        if args.template is not None or args.frontend is not None:
            return 0
        parser.error("Provide a plugin directory, --template or --frontend")
    report = check_plugin(args.directory)
    if args.runtime and report.ok:
        report = asyncio.run(_runtime(args.directory.resolve(), report))
    print(
        json.dumps(
            {"ok": report.ok, **asdict(report)},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
