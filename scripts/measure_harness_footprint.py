#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure isolated native lifecycle stages with process/network denial.

Every invocation uses a fresh process and disposable home/config directories.
Only model transport is replaced; Workspace, Runtime, Agent and history are real.
The frontend label remains import-only; browser evidence is collected separately.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

SCENARIOS = (
    "native-startup",
    "native-agent-list",
    "native-chat",
    "frontend-native",
)
ROOT = Path(__file__).resolve().parents[1]
_VENDORS = {"codex", "qoder", "qodercli", "claude"}
_SOURCE_PATHS = (
    "src",
    "packages",
    "pyproject.toml",
    "scripts/measure_harness_footprint.py",
    "plugins/harness",
)


class VendorProbeGuard:
    """Deny launches (including wrappers) and record redacted probe attempts."""

    def __init__(self):
        self.vendor_process_count = 0
        self.vendor_probe_count = 0
        self.blocked_process_attempts = []
        self.blocked_network_attempts = 0
        self._active = False
        self._which = None

    @staticmethod
    def _basename(value):
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        return Path(str(value)).name

    def _audit(self, event, arguments):
        if not self._active:
            return
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.exec",
            "os.spawn",
            "os.fork",
            "os.forkpty",
        }:
            basename = self._basename(arguments[0]) if arguments else ""
            vendor = basename.lower().removesuffix(".exe")
            executable = (
                "<shell>"
                if event == "os.system"
                else (
                    "<fork>"
                    if event in {"os.fork", "os.forkpty"}
                    else vendor
                    if vendor in _VENDORS
                    else "<process>"
                )
            )
            argv = arguments[1] if len(arguments) > 1 else ()
            names = {basename}
            if isinstance(argv, (list, tuple)):
                names.update(self._basename(part) for part in argv)
            if any(
                name.lower().removesuffix(".exe") in _VENDORS for name in names
            ):
                self.vendor_probe_count += 1
            self.blocked_process_attempts.append(
                {"event": event, "executable": executable},
            )
            raise RuntimeError("Footprint probe blocked process execution")
        if event in {
            "socket.connect",
            "socket.sendto",
            "socket.sendmsg",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.getnameinfo",
        }:
            self.blocked_network_attempts += 1
            raise RuntimeError("Footprint probe blocked network access")

    def __enter__(self):
        self._which = shutil.which

        def which(command, *args, **kwargs):
            if (
                self._basename(command).lower().removesuffix(".exe")
                in _VENDORS
            ):
                self.vendor_probe_count += 1
            return self._which(command, *args, **kwargs)

        sys.addaudithook(self._audit)
        shutil.which = which
        self._active = True
        return self

    def __exit__(self, *_):
        self._active = False
        shutil.which = self._which


def _rss():
    try:
        import psutil

        process = psutil.Process()
        rss = process.memory_info().rss
        try:
            children_rss = sum(
                child.memory_info().rss
                for child in process.children(recursive=True)
            )
            source = "psutil-current-rss"
        except (PermissionError, psutil.AccessDenied):
            # The sandbox can deny process enumeration. All Python launch
            # boundaries are blocked; this process has created no children.
            children_rss = 0
            source = "psutil-current-rss; children-zero-by-launch-denial"
        return (
            rss,
            children_rss,
            source,
        )
    except ImportError:
        try:
            import resource
        except ImportError:
            return (
                None,
                None,
                "rss-unavailable: psutil and resource unavailable",
            )

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return (
            int(rss if sys.platform == "darwin" else rss * 1024),
            0,
            "resource-peak-rss",
        )


def _install_model_boundary():
    from agentscope.formatter import OpenAIChatFormatter
    from agentscope.message import TextBlock
    from agentscope.model import ChatModelBase, ChatResponse
    from qwenpaw.agents import model_factory

    class NativeModel(ChatModelBase):
        def __init__(self):
            super().__init__(
                credential=None,
                model="footprint-native",
                parameters=ChatModelBase.Parameters(),
                stream=True,
            )
            self.formatter = OpenAIChatFormatter()

        async def _call_api(self, *_args, **_kwargs):
            async def chunks():
                yield ChatResponse(
                    content=[TextBlock(text="native-answer")],
                    is_last=False,
                )
                yield ChatResponse(
                    content=[TextBlock(text="native-answer")],
                    is_last=True,
                )

            return chunks()

    model_factory.create_model_and_formatter = lambda **_kwargs: (
        NativeModel(),
        OpenAIChatFormatter(),
    )


async def _native_scene(app, scenario, report, started):
    await asyncio.wait_for(app.state.startup_ready.wait(), 30)
    report.update(
        milestone="core-agents-ready",
        ready_ms=(time.perf_counter() - started) * 1000,
        unavailable_reason=None,
    )
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://probe",
    ) as client:
        async with asyncio.timeout(30):
            while True:
                ready = getattr(app.state, "plugin_registry", None) is not None
                variant = report["variant"]
                if variant == "absent" and ready:
                    report["plugin_states"] = {}
                    break
                if variant != "absent" and ready:
                    response = await client.get("/api/agents/backends")
                    response.raise_for_status()
                    states = {
                        row["id"]: row["status"]
                        for row in response.json()["backends"]
                    }
                    report["plugin_states"] = states
                    expected = (
                        {"codex": "disabled", "qoder": "disabled"}
                        if variant == "disabled"
                        else {variant: "available"}
                    )
                    if all(
                        states.get(key) == value
                        for key, value in expected.items()
                    ):
                        break
                await asyncio.sleep(0.01)
    report["plugin_ready_ms"] = (time.perf_counter() - started) * 1000
    if scenario == "native-startup":
        return
    listed = time.perf_counter()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://probe",
    ) as client:
        response = await client.get("/api/agents")
        response.raise_for_status()
    report.update(
        milestone="native-agent-list-complete",
        agent_list_ms=(time.perf_counter() - listed) * 1000,
        agent_count=len(response.json()["agents"]),
    )
    if scenario == "native-agent-list":
        return
    from qwenpaw.schemas import AgentRequest

    chatting = time.perf_counter()
    workspace = await app.state.multi_agent_manager.get_agent(
        "default",
    )
    stream = workspace.stream_query(
        AgentRequest(
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "native question"},
                    ],
                },
            ],
            session_id="probe-session",
            user_id="probe-user",
            channel="console",
            agent_id="default",
        ),
    )
    try:
        async for _event in stream:
            pass
    finally:
        await stream.aclose()
    history = workspace.workspace_dir / (
        "sessions/console/probe-user_probe-session.json"
    )
    saved = json.loads(history.read_text(encoding="utf-8"))
    context = saved["agent"]["state"]["context"]
    evidence = {
        role: any(
            message["role"] == role
            and any(
                text in block.get("text", "") for block in message["content"]
            )
            for message in context
        )
        for role, text in (
            ("user", "native question"),
            ("assistant", "native-answer"),
        )
    }
    if not all(evidence.values()):
        raise RuntimeError("Native terminal history was not persisted")
    report.update(
        milestone="native-chat-persisted",
        history_verified=True,
        history_roles=sorted(evidence),
        native_chat_ms=(time.perf_counter() - chatting) * 1000,
    )


async def _lifecycle(app, scenario, report, started, guard):
    failure = None
    async with app.router.lifespan_context(app):
        try:
            await _native_scene(app, scenario, report, started)
        except Exception as exc:
            failure = exc
        finally:
            _snapshot(report, guard)
            report["snapshot_while_running"] = True
            cleanup_started = time.perf_counter()
    report["cleanup"] = {
        "outcome": "completed",
        "elapsed_ms": (time.perf_counter() - cleanup_started) * 1000,
        "vendor_probe_count": guard.vendor_probe_count,
        "blocked_process_attempt_count": len(guard.blocked_process_attempts),
        "blocked_network_attempts": guard.blocked_network_attempts,
    }
    if failure is not None:
        raise failure


def _probe(scenario, commit, variant="absent", source_root=ROOT):
    from contextlib import redirect_stdout, redirect_stderr

    started = time.perf_counter()
    report = {
        "commit": commit,
        "python": platform.python_version(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "scenario": scenario,
        "variant": variant,
        "milestone": "app-import-failed",
        "ready_ms": None,
        "agent_list_ms": None,
        "native_chat_ms": None,
        "history_verified": False,
        "import_error": None,
        "missing_module": None,
        "unavailable_reason": "App import has not completed.",
    }
    with VendorProbeGuard() as guard:
        with open(os.devnull, "w", encoding="utf-8") as quiet:
            with redirect_stdout(quiet), redirect_stderr(quiet):
                try:
                    app = importlib.import_module("qwenpaw.app._app").app
                    origin = Path(sys.modules["qwenpaw"].__file__).resolve()
                    report["imported_source_path"] = str(origin)
                    if not origin.is_relative_to(source_root / "src"):
                        raise RuntimeError(
                            "Imported source differs from selected source root",
                        )
                    report["import_ms"] = (
                        time.perf_counter() - started
                    ) * 1000
                    report["milestone"] = "app-imported"
                    if scenario == "frontend-native":
                        report["unavailable_reason"] = (
                            "Import-only; actual browser transfer evidence "
                            "is measured separately."
                        )
                    else:
                        if scenario == "native-chat":
                            _install_model_boundary()
                        asyncio.run(
                            _lifecycle(app, scenario, report, started, guard),
                        )
                except Exception as exc:
                    report["error"] = type(exc).__name__
                    report["unavailable_reason"] = (
                        "Probe stopped after "
                        + report["milestone"]
                        + ": "
                        + type(exc).__name__
                    )
                    if report["milestone"] == "app-import-failed":
                        report["import_error"] = type(exc).__name__
                    if isinstance(exc, ModuleNotFoundError):
                        report["missing_module"] = exc.name
        report.setdefault("import_ms", (time.perf_counter() - started) * 1000)
        if "modules" not in report:
            _snapshot(report, guard)
            report["snapshot_while_running"] = False
    return report


def _snapshot(report, guard):
    rss, children_rss, rss_source = _rss()
    report.update(
        process_rss_bytes=rss,
        children_rss_bytes=children_rss,
        rss_source=rss_source,
        modules=sorted(sys.modules),
        vendor_process_count=guard.vendor_process_count,
        vendor_probe_count=guard.vendor_probe_count,
        blocked_process_attempts=list(guard.blocked_process_attempts),
        blocked_network_attempts=guard.blocked_network_attempts,
        isolation="fresh process; temporary home/config; launches/network denied",
    )
    report["module_origins"] = {
        name: str(origin)
        for name, module in tuple(sys.modules.items())
        if (origin := getattr(module, "__file__", None))
        and (
            "/plugins/" in str(origin).replace("\\", "/")
            or name.startswith(
                (
                    "qwenpaw.harnesses",
                    "openai_codex",
                    "codex_cli_bin",
                    "qoder_agent_sdk",
                ),
            )
        )
    }


def _source_state(root):
    """Fingerprint actual source bytes; archive SHAs are declared separately."""
    root = Path(root)
    try:
        names = subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                *_SOURCE_PATHS,
            ],
            cwd=root,
            stderr=subprocess.DEVNULL,
        ).split(b"\0")
        dirty = bool(
            subprocess.check_output(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                    "--",
                    *_SOURCE_PATHS,
                ],
                cwd=root,
            ),
        )
        kind = "git"
    except subprocess.CalledProcessError:
        names = [
            path.relative_to(root).as_posix().encode()
            for relative in _SOURCE_PATHS
            for path in (
                [root / relative]
                if (root / relative).is_file()
                else (root / relative).rglob("*")
            )
            if path.is_file()
            and not {"__pycache__", "node_modules"}.intersection(path.parts)
            and path.suffix != ".pyc"
        ]
        dirty, kind = None, "archive"
    digest = hashlib.sha256()
    for name in sorted(set(names) - {b""}):
        path = root / os.fsdecode(name)
        digest.update(name + b"\0")
        digest.update(
            b"file\0" + path.read_bytes() if path.is_file() else b"missing\0",
        )
        digest.update(b"\0")
    return {"dirty": dirty, "kind": kind, "fingerprint": digest.hexdigest()}


def _seed(temporary, variant, plugin_dir):
    work = temporary / "work"
    workspace = work / "workspaces/default"
    workspace.mkdir(parents=True)
    plugins = {}
    wanted = (
        ("codex", "qoder")
        if variant == "disabled"
        else (() if variant == "absent" else (variant,))
    )
    manifests = {}
    for backend in wanted:
        plugin_id = "qwenpaw-harness-" + backend
        matches = [
            path.parent
            for path in plugin_dir.rglob("plugin.json")
            if json.loads(path.read_text(encoding="utf-8")).get("id")
            == plugin_id
        ]
        archives = []
        if not matches:
            for path in plugin_dir.rglob("*.zip"):
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        if (
                            Path(name).name == "plugin.json"
                            and len(Path(name).parts) <= 2
                            and json.loads(archive.read(name)).get("id")
                            == plugin_id
                        ):
                            archives.append((path, name))
        target = work / "plugins" / plugin_id
        if len(matches) == 1:
            shutil.copytree(
                matches[0],
                target,
                ignore=shutil.ignore_patterns(
                    "node_modules",
                    "tests",
                    "__pycache__",
                ),
            )
        elif not matches and len(archives) == 1:
            bundle, manifest = archives[0]
            with tempfile.TemporaryDirectory() as directory:
                unpacked = Path(directory).resolve()
                with zipfile.ZipFile(bundle) as archive:
                    for name in archive.namelist():
                        if (
                            not (unpacked / name)
                            .resolve()
                            .is_relative_to(unpacked)
                        ):
                            raise ValueError("Unsafe prepared plugin archive")
                    archive.extractall(unpacked)
                shutil.copytree((unpacked / manifest).parent, target)
        else:
            raise ValueError(
                f"Provide exactly one prepared {plugin_id} package",
            )
        plugins[plugin_id] = {"enabled": variant != "disabled"}
        manifests[plugin_id] = hashlib.sha256(
            (target / "plugin.json").read_bytes(),
        ).hexdigest()
    (work / "config.json").write_text(
        json.dumps(
            {
                "agents": {
                    "active_agent": "default",
                    "agent_order": ["default"],
                    "profiles": {
                        "default": {
                            "id": "default",
                            "workspace_dir": str(workspace),
                        },
                    },
                },
                "plugins": plugins,
            },
        ),
        encoding="utf-8",
    )
    (workspace / "agent.json").write_text(
        json.dumps(
            {
                "id": "default",
                "name": "Native probe",
                "backend": "qwenpaw",
                "active_model": {
                    "provider_id": "footprint",
                    "model": "native",
                },
                "running": {"memory_manager_backend": "none"},
            },
        ),
        encoding="utf-8",
    )
    return manifests


def _isolated_env(temporary, source_root=ROOT):
    temporary = Path(temporary)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("QWENPAW_", "CODEX_", "QODER_", "CLAUDE_", "PYTHON"),
        )
        and not any(
            part in key.upper()
            for part in ("TOKEN", "SECRET", "API_KEY", "PASSWORD")
        )
    }
    env.update(
        HOME=str(temporary / "home"),
        USERPROFILE=str(temporary / "home"),
        APPDATA=str(temporary / "config"),
        LOCALAPPDATA=str(temporary / "cache"),
        XDG_CACHE_HOME=str(temporary / "cache"),
        XDG_CONFIG_HOME=str(temporary / "config"),
        XDG_DATA_HOME=str(temporary / "data"),
        QWENPAW_WORKING_DIR=str(temporary / "work"),
        QWENPAW_SECRET_DIR=str(temporary / "secrets"),
        QWENPAW_RUNTIME_ID="harness-footprint-probe",
        QWENPAW_LOG_LEVEL="error",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join(
            (
                str(source_root / "src"),
                str(source_root / "packages/qwenpawmail-mcp/src"),
            ),
        ),
    )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--baseline-commit", help="Trusted source archive SHA")
    parser.add_argument(
        "--variant",
        choices=("absent", "disabled", "codex", "qoder"),
        default="absent",
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        default=ROOT / "plugins/harness",
    )
    parser.add_argument(
        "--_child",
        action="store_true",
        dest="child",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--_commit",
        dest="commit",
        default="",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.child:
        print(
            json.dumps(
                _probe(
                    args.scenario,
                    args.commit,
                    args.variant,
                    args.source_root.resolve(),
                ),
                sort_keys=True,
            ),
        )
        return
    source_root = args.source_root.resolve()
    source_state = _source_state(source_root)
    if source_state["kind"] == "archive" and not args.baseline_commit:
        parser.error("Source archives require --baseline-commit")
    commit = (
        args.baseline_commit
        or subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            text=True,
        ).strip()
    )
    with tempfile.TemporaryDirectory(prefix="qwenpaw-footprint-") as directory:
        temporary = Path(directory)
        # Avoid inherited product overrides, credentials, user Python hooks,
        # config paths, or provider homes reaching the isolated import.
        env = _isolated_env(temporary, source_root)
        for name in ("home", "cache", "config", "data", "work", "secrets"):
            (temporary / name).mkdir()
        manifests = _seed(temporary, args.variant, args.plugin_dir)
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--scenario",
                args.scenario,
                "--output",
                str(args.output),
                "--_child",
                "--variant",
                args.variant,
                "--source-root",
                str(source_root),
                "--_commit",
                commit,
            ],
            cwd=temporary,
            env=env,
            text=True,
            capture_output=True,
            timeout=75,
            check=True,
        )
        report = json.loads(child.stdout)
        report["source_state"] = source_state
        report["source_root"] = str(source_root)
        report["driver_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes(),
        ).hexdigest()
        report["plugin_manifests"] = manifests
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
