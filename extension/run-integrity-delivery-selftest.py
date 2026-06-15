#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run all Integrity Protection delivery self-test nets (wiring + backend + frontend).

Covers:
  - Built-in tool rule integrity
  - File Baseline Protection
  - Integrity Protection Health Check

Usage:
  python extension/run-integrity-delivery-selftest.py
  python extension/run-integrity-delivery-selftest.py --delivery file-baseline
  python extension/run-integrity-delivery-selftest.py --delivery rule-integrity --delivery health-check
  python extension/run-integrity-delivery-selftest.py --layer backend
  python extension/run-integrity-delivery-selftest.py --layer frontend --layer wiring
  python extension/run-integrity-delivery-selftest.py --layer typecheck
  python extension/run-integrity-delivery-selftest.py --list

Layers: wiring, backend, frontend, typecheck (console npm run build — catches tsc errors vitest misses)

Argo gate:
  sec-e2e-029-builtin-rule-line-ending-invariant runs this script with no args via npm run test:argo.
  Update testcase targets in extension/*-selftest.manifest.json and scripts/*-selftest.manifest.json only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXTENSION_DIR.parent
MASTER_MANIFEST_PATH = EXTENSION_DIR / "integrity-delivery-selftest.manifest.json"

ALL_LAYERS = ("wiring", "backend", "frontend", "typecheck")


@dataclass
class LayerResult:
    delivery_id: str
    delivery_label: str
    name: str
    label: str
    ok: bool
    command: str
    detail: str = ""


@dataclass
class DeliverySummary:
    delivery_id: str
    delivery_label: str
    results: list[LayerResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _resolve_manifest_path(relative_path: str) -> Path:
    path = REPO_ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    return path


def _backend_pytest_args(manifest: dict) -> list[str]:
    pytest_args = [sys.executable, "-m", "pytest", "-v", "--tb=short"]
    layer = manifest["layers"]["backend"]

    if "module" in layer:
        module = layer["module"]
        for test_name in layer["targets"]:
            pytest_args.append(f"{module}::{test_name}")
        return pytest_args

    for target in layer["targets"]:
        if isinstance(target, str):
            pytest_args.append(target)
            continue
        module = target["module"]
        tests = target.get("tests") or []
        if tests:
            pytest_args.extend(f"{module}::{name}" for name in tests)
        else:
            pytest_args.append(module)
    return pytest_args


def run_wiring_layer(delivery_id: str, delivery_label: str, manifest: dict) -> LayerResult:
    layer = manifest["layers"]["wiring"]
    label = layer["label"]
    cmd = ["node", *layer["targets"]]
    _print_header(f"[{delivery_id}] wiring — {label}")
    print("Command:", " ".join(cmd))
    proc = _run(cmd, cwd=REPO_ROOT)
    return LayerResult(delivery_id, delivery_label, "wiring", label, proc.returncode == 0, " ".join(cmd))


def run_backend_layer(delivery_id: str, delivery_label: str, manifest: dict) -> LayerResult:
    layer = manifest["layers"]["backend"]
    label = layer["label"]
    pytest_args = _backend_pytest_args(manifest)
    _print_header(f"[{delivery_id}] backend — {label}")
    print("Command:", " ".join(pytest_args))
    proc = _run(pytest_args, cwd=REPO_ROOT)
    return LayerResult(delivery_id, delivery_label, "backend", label, proc.returncode == 0, " ".join(pytest_args))


def run_frontend_layer(delivery_id: str, delivery_label: str, manifest: dict) -> LayerResult:
    layer = manifest["layers"]["frontend"]
    label = layer["label"]
    cwd = REPO_ROOT / layer.get("cwd", "console")
    npx = shutil.which("npx")
    if npx is None:
        return LayerResult(
            delivery_id,
            delivery_label,
            "frontend",
            label,
            False,
            "npx",
            detail="npx not found on PATH",
        )
    env = os.environ.copy()
    env.setdefault("NODE_OPTIONS", "--max-old-space-size=4096")
    cmd = [npx, "vitest", "run", *layer["targets"]]
    _print_header(f"[{delivery_id}] frontend — {label}")
    print("Command:", " ".join(cmd))
    print("CWD:", cwd)
    proc = _run(cmd, cwd=cwd, env=env)
    return LayerResult(delivery_id, delivery_label, "frontend", label, proc.returncode == 0, " ".join(cmd))


def run_typecheck_layer(master: dict) -> LayerResult:
    gate = master.get("console_gate", {}).get("typecheck", {})
    label = gate.get("label", "Console TypeScript build")
    cwd = REPO_ROOT / gate.get("cwd", "console")
    command = gate.get("command", "npm run build")
    if isinstance(command, str):
        cmd = command.split()
    else:
        cmd = list(command)
    npm = shutil.which(cmd[0]) if cmd else None
    if npm is None:
        return LayerResult(
            "console-gate",
            "Console compile gate",
            "typecheck",
            label,
            False,
            " ".join(cmd),
            detail=f"{cmd[0]} not found on PATH",
        )
    cmd[0] = npm
    env = os.environ.copy()
    env.setdefault("NODE_OPTIONS", "--max-old-space-size=4096")
    _print_header("[console-gate] typecheck — " + label)
    print("Command:", " ".join(cmd))
    print("CWD:", cwd)
    proc = _run(cmd, cwd=cwd, env=env)
    return LayerResult(
        "console-gate",
        "Console compile gate",
        "typecheck",
        label,
        proc.returncode == 0,
        " ".join(cmd),
    )


LAYER_RUNNERS = {
    "wiring": run_wiring_layer,
    "backend": run_backend_layer,
    "frontend": run_frontend_layer,
}


def list_master_manifest(master: dict) -> None:
    _print_header("Integrity Protection delivery self-test index")
    print(f"Master manifest: {MASTER_MANIFEST_PATH.relative_to(REPO_ROOT)}")
    for delivery in master["deliveries"]:
        manifest_path = _resolve_manifest_path(delivery["manifest"])
        manifest = _load_json(manifest_path)
        print(f"\n{delivery['id']} — {delivery['label']}")
        print(f"  manifest: {delivery['manifest']}")
        for layer_name in ALL_LAYERS:
            layer = manifest["layers"][layer_name]
            print(f"  {layer_name} ({layer['label']}):")
            if layer_name == "backend" and "module" in layer:
                for target in layer["targets"]:
                    print(f"    - {layer['module']}::{target}")
            elif layer_name == "backend":
                for target in layer["targets"]:
                    if isinstance(target, str):
                        print(f"    - {target}")
                        continue
                    tests = target.get("tests") or []
                    if tests:
                        for test_name in tests:
                            print(f"    - {target['module']}::{test_name}")
                    else:
                        print(f"    - {target['module']} (all tests)")
            else:
                for target in layer["targets"]:
                    print(f"    - {target}")
        for item in manifest.get("scenarios", []):
            print(f"    scenario {item['id']}: [{item['layer']}] {item['target']}")
    gate = master.get("console_gate", {}).get("typecheck")
    if gate:
        print("\nconsole-gate — Console compile gate")
        print(f"  typecheck ({gate.get('label', 'Console TypeScript build')}):")
        command = gate.get("command", "npm run build")
        if isinstance(command, list):
            print(f"    - {' '.join(command)}")
        else:
            print(f"    - {command}")
        print(f"    cwd: {gate.get('cwd', 'console')}")


def run_delivery(delivery: dict, selected_layers: list[str]) -> DeliverySummary:
    manifest_path = _resolve_manifest_path(delivery["manifest"])
    manifest = _load_json(manifest_path)
    summary = DeliverySummary(delivery_id=delivery["id"], delivery_label=delivery["label"])
    _print_header(f"Delivery: {delivery['label']} ({delivery['id']})")
    print(f"Manifest: {delivery['manifest']}")
    for layer_name in ALL_LAYERS:
        if layer_name not in selected_layers:
            continue
        runner = LAYER_RUNNERS[layer_name]
        summary.results.append(runner(delivery["id"], delivery["label"], manifest))
    return summary


def print_summary(
    summaries: list[DeliverySummary],
    *,
    gate_result: LayerResult | None = None,
) -> int:
    _print_header("Integrity Protection delivery self-test summary")
    failed = 0
    for summary in summaries:
        delivery_ok = summary.ok
        if not delivery_ok:
            failed += 1
        status = "PASS" if delivery_ok else "FAIL"
        print(f"\n[{status}] {summary.delivery_id}: {summary.delivery_label}")
        for result in summary.results:
            layer_status = "PASS" if result.ok else "FAIL"
            print(f"  [{layer_status}] {result.name}: {result.label}")
            if result.detail:
                print(f"           {result.detail}")
    if gate_result is not None:
        gate_ok = gate_result.ok
        if not gate_ok:
            failed += 1
        gate_status = "PASS" if gate_ok else "FAIL"
        print(f"\n[{gate_status}] {gate_result.delivery_id}: {gate_result.delivery_label}")
        print(f"  [{gate_status}] {gate_result.name}: {gate_result.label}")
        if gate_result.detail:
            print(f"           {gate_result.detail}")
    print()
    if failed:
        print(f"FAILED: {failed} delivery net(s) did not pass.")
        return 1
    print("ALL DELIVERY NETS PASSED.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all Integrity Protection delivery self-test nets.",
    )
    parser.add_argument(
        "--delivery",
        action="append",
        dest="deliveries",
        help="Run only selected delivery net(s). Default: all deliveries.",
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
        help="Print delivery manifests and exit.",
    )
    return parser.parse_args()


def main() -> int:
    if not MASTER_MANIFEST_PATH.is_file():
        print(f"Master manifest not found: {MASTER_MANIFEST_PATH}", file=sys.stderr)
        return 2

    master = _load_json(MASTER_MANIFEST_PATH)
    args = parse_args()

    if args.list:
        list_master_manifest(master)
        return 0

    delivery_ids = {item["id"] for item in master["deliveries"]}
    selected_deliveries = master["deliveries"]
    if args.deliveries:
        unknown = [item for item in args.deliveries if item not in delivery_ids]
        if unknown:
            print(f"Unknown delivery id(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        selected_deliveries = [item for item in master["deliveries"] if item["id"] in args.deliveries]

    selected_layers = args.layer or list(ALL_LAYERS)
    per_delivery_layers = [layer for layer in selected_layers if layer != "typecheck"]
    summaries: list[DeliverySummary] = []
    for delivery in selected_deliveries:
        try:
            summaries.append(run_delivery(delivery, per_delivery_layers))
        except FileNotFoundError as exc:
            print(f"Manifest not found for {delivery['id']}: {exc}", file=sys.stderr)
            return 2

    gate_result = run_typecheck_layer(master) if "typecheck" in selected_layers else None
    return print_summary(summaries, gate_result=gate_result)


if __name__ == "__main__":
    raise SystemExit(main())
