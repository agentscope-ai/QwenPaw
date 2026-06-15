#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the File baseline self-test net (wiring + backend + frontend).

Usage:
  python scripts/run-file-baseline-selftest.py
  python scripts/run-file-baseline-selftest.py --layer backend
  python scripts/run-file-baseline-selftest.py --layer frontend --layer wiring
  python scripts/run-file-baseline-selftest.py --list
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MANIFEST_PATH = SCRIPT_DIR / "file-baseline-selftest.manifest.json"

ALL_LAYERS = ("wiring", "backend", "frontend")


@dataclass
class LayerResult:
    name: str
    label: str
    ok: bool
    command: str
    detail: str = ""


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _print_header(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=False,
        check=False,
    )


def run_wiring_layer(manifest: dict) -> LayerResult:
    layer = manifest["layers"]["wiring"]
    label = layer["label"]
    targets = layer["targets"]
    cmd = ["node", *targets]
    _print_header(f"[wiring] {label}")
    print("Command:", " ".join(cmd))
    proc = _run(cmd, cwd=REPO_ROOT)
    ok = proc.returncode == 0
    return LayerResult("wiring", label, ok, " ".join(cmd))


def run_backend_layer(manifest: dict) -> LayerResult:
    layer = manifest["layers"]["backend"]
    label = layer["label"]
    module = layer["module"]
    targets = layer["targets"]
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "--tb=short",
    ]
    pytest_args.extend(f"{module}::{name}" for name in targets)
    _print_header(f"[backend] {label}")
    print("Command:", " ".join(pytest_args))
    proc = _run(pytest_args, cwd=REPO_ROOT)
    ok = proc.returncode == 0
    return LayerResult("backend", label, ok, " ".join(pytest_args))


def run_frontend_layer(manifest: dict) -> LayerResult:
    layer = manifest["layers"]["frontend"]
    label = layer["label"]
    cwd = REPO_ROOT / layer.get("cwd", "console")
    targets = layer["targets"]
    npx = shutil.which("npx")
    if npx is None:
        return LayerResult(
            "frontend",
            label,
            False,
            "npx",
            detail="npx not found on PATH",
        )
    env = os.environ.copy()
    env.setdefault("NODE_OPTIONS", "--max-old-space-size=4096")
    cmd = [npx, "vitest", "run", *targets]
    _print_header(f"[frontend] {label}")
    print("Command:", " ".join(cmd))
    print("CWD:", cwd)
    proc = _run(cmd, cwd=cwd, env=env)
    ok = proc.returncode == 0
    return LayerResult("frontend", label, ok, " ".join(cmd))


LAYER_RUNNERS = {
    "wiring": run_wiring_layer,
    "backend": run_backend_layer,
    "frontend": run_frontend_layer,
}


def list_manifest(manifest: dict) -> None:
    _print_header("File baseline self-test manifest")
    print(f"Manifest: {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    for layer_name in ALL_LAYERS:
        layer = manifest["layers"][layer_name]
        print(f"\n{layer_name} ({layer['label']}):")
        for target in layer["targets"]:
            print(f"  - {target}")
    print("\nScenario map:")
    for item in manifest.get("scenarios", []):
        print(f"  - {item['id']}: [{item['layer']}] {item['target']}")


def print_summary(results: list[LayerResult]) -> int:
    _print_header("File baseline self-test summary")
    failed = 0
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        if not result.ok:
            failed += 1
        print(f"  [{status}] {result.name}: {result.label}")
        if result.detail:
            print(f"         {result.detail}")
    print()
    if failed:
        print(f"FAILED: {failed} layer(s) did not pass.")
        return 1
    print("ALL LAYERS PASSED.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Persona Protection wiring/backend/frontend self-test net.",
    )
    parser.add_argument(
        "--layer",
        action="append",
        choices=ALL_LAYERS,
        help="Run only selected layer(s). Default: all layers.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print manifest targets and exit.",
    )
    return parser.parse_args()


def main() -> int:
    if not MANIFEST_PATH.is_file():
        print(f"Manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 2

    manifest = _load_manifest()
    args = parse_args()

    if args.list:
        list_manifest(manifest)
        return 0

    selected = args.layer or list(ALL_LAYERS)
    results: list[LayerResult] = []
    for layer_name in ALL_LAYERS:
        if layer_name not in selected:
            continue
        runner = LAYER_RUNNERS[layer_name]
        results.append(runner(manifest))

    return print_summary(results)


if __name__ == "__main__":
    raise SystemExit(main())
