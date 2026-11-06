# -*- coding: utf-8 -*-
"""Measure only actual Workspace driver service descriptors in cold children."""

# pylint: disable=protected-access
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def child(args):  # pylint: disable=too-many-statements
    """Run one isolated source tree; emit raw observations after shutdown."""
    import psutil

    cache_prefix = Path(sys.pycache_prefix or "").resolve()
    assert cache_prefix.is_relative_to(Path(args.root).resolve())
    assert (
        not cache_prefix.exists()
    ), "Both trees must use a fresh unread cache"
    assert sys.dont_write_bytecode
    started = time.perf_counter()
    config_root = Path(os.environ["QWENPAW_WORKING_DIR"])
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "config.json").write_text(
        json.dumps(
            {
                "agents": {
                    "profiles": {
                        f"unused-{index}": {
                            "id": f"unused-{index}",
                            "workspace_dir": str(Path(args.root) / str(index)),
                        }
                        for index in range(args.count)
                    },
                },
            },
        ),
    )
    for index in range(args.count):
        directory = Path(args.root) / str(index)
        directory.mkdir(parents=True)
        (directory / "agent.json").write_text(
            json.dumps({"id": f"unused-{index}", "name": f"unused-{index}"}),
        )
    import qwenpaw
    from qwenpaw.app.workspace import Workspace
    from qwenpaw.config.config import load_agent_config
    from qwenpaw.drivers.manager import DriverManager
    from qwenpaw.drivers.storage import AsyncDriverCardStore
    from qwenpaw.drivers import storage

    counts = {"managers": 0, "snapshots": 0, "file_scans": 0}
    original_init = DriverManager.__init__
    original_snapshot = AsyncDriverCardStore.snapshot
    original_scan = storage.list_card_paths

    def observe_init(self, *values, **kwargs):
        counts["managers"] += 1
        original_init(self, *values, **kwargs)

    async def observe_snapshot(self, *values, **kwargs):
        counts["snapshots"] += 1
        return await original_snapshot(self, *values, **kwargs)

    def observe_scan(*values, **kwargs):
        counts["file_scans"] += 1
        return original_scan(*values, **kwargs)

    DriverManager.__init__ = observe_init
    AsyncDriverCardStore.snapshot = observe_snapshot
    storage.list_card_paths = observe_scan

    async def sample():
        workspaces = []
        for index in range(args.count):
            workspace = Workspace(
                f"unused-{index}",
                str(Path(args.root) / str(index)),
            )
            workspace._config = load_agent_config(workspace.agent_id)
            service_manager = workspace._service_manager
            service_manager.descriptors = {
                key: value
                for key, value in service_manager.descriptors.items()
                if key in {"driver_manager", "driver_config_watcher"}
            }
            await service_manager.start_all()
            assert workspace.driver_manager is not None
            workspaces.append(workspace)
        startup = time.perf_counter() - started
        await asyncio.sleep(args.warmup)
        process = psutil.Process()
        before_cpu = process.cpu_times()
        before = dict(counts)
        initial_tasks = sorted(
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )
        rss = [process.memory_info().rss]
        start = time.perf_counter()
        while time.perf_counter() - start < args.seconds:
            await asyncio.sleep(min(1, args.seconds))
            rss.append(process.memory_info().rss)
        elapsed = time.perf_counter() - start
        after_cpu = process.cpu_times()
        project_imports = sorted(
            name
            for name in sys.modules
            if name.startswith(
                (
                    "qwenpaw.drivers.handlers.mcp",
                    "qwenpaw.drivers.transports.mcp",
                    "qwenpaw.app.mcp.manager",
                    "qwenpaw_plugin_qwenpaw_mcp",
                ),
            )
        )
        result = {
            "source": args.source,
            "count": args.count,
            "qwenpaw_file": qwenpaw.__file__,
            "bytecode_cache_policy": "fresh-private-prefix-and-no-writes",
            "pycache_prefix": str(cache_prefix),
            "cache_prefix_exists": cache_prefix.exists(),
            "python": sys.version,
            "executable": sys.executable,
            "agentscope": importlib.metadata.version("agentscope"),
            "startup_seconds": startup,
            "sample_seconds": elapsed,
            "cpu_seconds": (
                after_cpu.user
                + after_cpu.system
                - before_cpu.user
                - before_cpu.system
            ),
            "rss_bytes_median": statistics.median(rss),
            "rss_bytes_samples": rss,
            "counts_after_start": before,
            "idle_counts": {
                key: value - before[key] for key, value in counts.items()
            },
            "tasks": initial_tasks,
            "project_mcp_imports": project_imports,
            "upstream_mcp_imports": sorted(
                name
                for name in sys.modules
                if name == "mcp" or name.startswith("mcp.")
            ),
        }
        for workspace in reversed(workspaces):
            await workspace._service_manager.stop_all()
        await asyncio.sleep(0)
        result["tasks_after_stop"] = sorted(
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )
        print(json.dumps(result))

    asyncio.run(sample())


def run(args):
    """Alternate independent baseline/final children under identical conditions."""
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(Path(args.manifest).read_text())
    for row in manifest["files"]:
        path = Path(args.baseline) / row["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    (output / "baseline-manifest.json").write_text(
        json.dumps(manifest, indent=2),
    )
    results = []
    for count in args.counts:
        for replicate in range(args.replicates):
            # Alternate order to reduce systematic temporal bias.
            sources = [("baseline", args.baseline), ("final", args.final)]
            if replicate % 2:
                sources.reverse()
            for label, source in sources:
                with tempfile.TemporaryDirectory(prefix="mcp-bench-") as root:
                    env = {
                        key: value
                        for key, value in os.environ.items()
                        if key not in {"HOME", "PYTHONPATH"}
                    }
                    env.update(
                        {
                            "PYTHONPATH": os.pathsep.join(
                                [
                                    str(Path(source) / "src"),
                                    str(
                                        Path(source)
                                        / "packages/qwenpawmail-mcp/src",
                                    ),
                                    args.dependencies,
                                ],
                            ),
                            "QWENPAW_WORKING_DIR": str(Path(root) / "config"),
                            "QWENPAW_SECRET_DIR": str(Path(root) / "secrets"),
                            "XDG_CONFIG_HOME": str(Path(root) / "xdg"),
                            "XDG_CACHE_HOME": str(Path(root) / "cache"),
                            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                            "PYTHONPYCACHEPREFIX": str(Path(root) / "pycache"),
                            "PYTHONNOUSERSITE": "1",
                            "PYTHONDONTWRITEBYTECODE": "1",
                            "QWENPAW_TELEMETRY_DISABLED": "1",
                        },
                    )
                    command = [
                        sys.executable,
                        "-B",
                        str(Path(__file__).resolve()),
                        "--child",
                        "--source",
                        label,
                        "--root",
                        root,
                        "--count",
                        str(count),
                        "--seconds",
                        str(args.seconds),
                        "--warmup",
                        str(args.warmup),
                    ]
                    completed = subprocess.run(
                        command,
                        env=env,
                        cwd=source,
                        capture_output=True,
                        text=True,
                        timeout=args.seconds + 180,
                        check=False,
                    )
                    stem = f"{count}-{replicate + 1}-{label}"
                    (output / (stem + ".stdout.log")).write_text(
                        completed.stdout,
                    )
                    (output / (stem + ".stderr.log")).write_text(
                        completed.stderr,
                    )
                    assert completed.returncode == 0, stem + completed.stderr
                    result = json.loads(completed.stdout.splitlines()[-1])
                    result["replicate"] = replicate + 1
                    (output / (stem + ".json")).write_text(
                        json.dumps(result, indent=2),
                    )
                    results.append(result)
                    print(
                        stem,
                        result["cpu_seconds"],
                        result["rss_bytes_median"],
                        flush=True,
                    )
    medians = []
    for count in args.counts:
        for source in ["baseline", "final"]:
            rows = [
                row
                for row in results
                if row["count"] == count and row["source"] == source
            ]
            medians.append(
                {
                    "count": count,
                    "source": source,
                    **{
                        key: statistics.median(row[key] for row in rows)
                        for key in [
                            "cpu_seconds",
                            "rss_bytes_median",
                            "startup_seconds",
                        ]
                    },
                },
            )
    (output / "medians.json").write_text(json.dumps(medians, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--root")
    parser.add_argument("--count", type=int)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--warmup", type=float, default=3)
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 10, 50])
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--baseline")
    parser.add_argument("--final")
    parser.add_argument("--dependencies")
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    args = parser.parse_args()
    (child if args.child else run)(args)


if __name__ == "__main__":
    main()
