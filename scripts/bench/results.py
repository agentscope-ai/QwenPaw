# -*- coding: utf-8 -*-
"""Upsert benchmark JSON and build the website index from merged records."""

import argparse
import copy
from pathlib import Path

from .collect import aggregate
from .common import digest, load, manifest, save
from .history import public_run, text


def export(data: dict, receipts: list[dict], url: str) -> dict:
    """Validate metrics and expose only allowlisted result fields."""
    summary = aggregate(data, receipts)
    run = public_run(
        summary,
        url,
        visibility=data[f"suite"][f"visibility"],
        partial=True,
    )
    run[f"configuration_sha256"] = text(
        data[f"configuration_sha256"],
        rf"[a-f0-9]{{64}}",
    )
    run[f"index_benchmarks"] = [
        {
            f"id": text(b[f"id"], rf"[a-z0-9-]+"),
            f"count": b[f"count"],
            f"domains": [text(d, rf"[a-z0-9-]+") for d in b[f"domains"]],
        }
        for b in data[f"index_benchmarks"]
    ]
    return run


def write(data: dict, receipts: list[dict], url: str, root: Path) -> dict:
    """Keep failed attempts visible without erasing a complete score."""
    run = export(data, receipts, url)
    config = run[f"configuration_sha256"]
    for part in run[f"records"][0][f"benchmarks"]:
        key = digest(
            {f"configuration": config, f"benchmark": part[f"benchmark"]},
        )
        path = root / f"results" / f"{key}.json"
        previous = load(path) if path.exists() else None
        if previous and previous[f"configuration_sha256"] != config:
            raise ValueError(f"Configuration key mismatch")
        value = copy.deepcopy(run)
        value[f"result_key"] = key
        value[f"records"][0][f"benchmarks"] = [part]
        value[f"latest_attempt"] = {
            f"benchmark": part[f"benchmark"],
            f"date": run[f"date"],
            f"workflow_url": url,
            f"complete": part[f"score"] is not None,
            f"scored": part[f"scored"],
            f"expected": part[f"expected"],
        }
        if part[f"score"] is None and previous:
            value = {**previous, f"latest_attempt": value[f"latest_attempt"]}
        save(path, value)
    return run


def mean(values: list) -> float | None:
    """Never renormalize an incomplete composite metric."""
    return sum(values) / len(values) if values and None not in values else None


def index(root: Path, visibility: str) -> dict:
    """Derive the full index after merge to avoid cross-PR index conflicts."""
    groups = {}
    for path in sorted((root / f"results").glob(f"*.json")):
        raw = load(path)
        clean = public_run(
            raw,
            raw[f"workflow_url"],
            visibility=visibility,
            partial=True,
        )
        key = text(raw[f"configuration_sha256"], rf"[a-f0-9]{{64}}")
        if len(clean[f"records"]) != 1:
            raise ValueError(f"One model per result file is required")
        part = clean[f"records"][0][f"benchmarks"]
        if len(part) != 1:
            raise ValueError(f"One benchmark per result file is required")
        expected_key = digest(
            {f"configuration": key, f"benchmark": part[0][f"benchmark"]},
        )
        if path.stem != expected_key or raw[f"result_key"] != expected_key:
            raise ValueError(f"Invalid result file identity")
        groups.setdefault(key, []).append((raw, clean))
    runs = []
    for key, items in groups.items():
        raw, run = max(items, key=lambda pair: pair[1][f"date"])
        record = copy.deepcopy(run[f"records"][0])
        for other, clean in items:
            if other[f"index_benchmarks"] != raw[f"index_benchmarks"] or any(
                clean[f"records"][0][field] != record[field]
                for field in (
                    f"model",
                    f"harness",
                    f"sdk_version",
                    f"source_sha",
                )
            ):
                raise ValueError(
                    f"Incompatible records share a configuration key",
                )
        parts = {
            c[f"records"][0][f"benchmarks"][0][f"benchmark"]: c[f"records"][0][
                f"benchmarks"
            ][0]
            for _, c in items
        }
        if set(parts) - {b[f"id"] for b in raw[f"index_benchmarks"]}:
            raise ValueError(f"Unexpected benchmark in index")
        complete_parts = []
        for benchmark in raw[f"index_benchmarks"]:
            name = text(benchmark[f"id"], rf"[a-z0-9-]+")
            if (
                type(benchmark[f"count"]) is not int
                or benchmark[f"count"] <= 0
            ):
                raise ValueError(f"Invalid expected benchmark size")
            if (
                name in parts
                and parts[name][f"expected"] != benchmark[f"count"]
            ):
                raise ValueError(f"Benchmark coverage differs from protocol")
            complete_parts.append(
                parts.get(
                    name,
                    {
                        f"benchmark": name,
                        f"domains": benchmark[f"domains"],
                        f"expected": benchmark[f"count"],
                        f"scored": 0,
                        f"score": None,
                        f"mean_runtime_seconds": None,
                        f"mean_model_cost_usd": None,
                        f"cost_sources": {},
                        f"cost_bases": {},
                        f"cost_observed_attempts": 0,
                        f"cost_known_attempts": 0,
                    },
                ),
            )
        record[f"benchmarks"] = complete_parts
        record[f"complete"] = all(
            p[f"score"] is not None for p in complete_parts
        )
        for target, source in (
            (f"index_score", f"score"),
            (f"index_model_cost_usd", f"mean_model_cost_usd"),
            (f"index_runtime_seconds", f"mean_runtime_seconds"),
        ):
            record[target] = mean([p[source] for p in complete_parts])
        record[f"domains"] = {
            d: mean(
                [p[f"score"] for p in complete_parts if d in p[f"domains"]],
            )
            for d in {d for p in complete_parts for d in p[f"domains"]}
        }
        costs = [
            p[f"mean_model_cost_usd"] * p[f"expected"]
            for p in complete_parts
            if p[f"mean_model_cost_usd"] is not None
        ]
        record[f"observed_model_spend_usd"] = sum(costs) if costs else None
        record[f"cost_status"] = (
            f"model_only"
            if record[f"index_model_cost_usd"] is not None
            else f"unknown"
        )
        record[f"observed_attempts"] = sum(
            p[f"cost_observed_attempts"] for p in complete_parts
        )
        record[f"attempts_with_known_cost"] = sum(
            p[f"cost_known_attempts"] for p in complete_parts
        )
        runs.append(
            {
                **run,
                f"configuration_sha256": key,
                f"records": [record],
                f"complete": record[f"complete"],
                f"latest_attempts": [r[f"latest_attempt"] for r, _ in items],
            },
        )
    return {
        f"schema_version": 1,
        f"visibility": visibility,
        f"runs": sorted(runs, key=lambda r: r[f"date"], reverse=True),
    }


def main() -> None:
    """Generate PR data or rebuild the index from already merged JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--data", type=Path, required=True)
    parser.add_argument(f"--manifests", type=Path)
    parser.add_argument(f"--receipts", type=Path)
    parser.add_argument(f"--workflow-url")
    parser.add_argument(
        f"--visibility",
        choices=[f"public", f"private"],
        default=f"public",
    )
    parser.add_argument(f"--attempt-id")
    parser.add_argument(f"--build-index", action=f"store_true")
    args = parser.parse_args()
    if args.build_index:
        save(args.data / f"index.json", index(args.data, args.visibility))
        return
    receipts = [load(p) for p in args.receipts.rglob(f"receipt.json")]
    runs = []
    for path in sorted(args.manifests.rglob(f"manifest.json")):
        data = manifest(path)
        if data[f"suite"][f"visibility"] != args.visibility:
            raise ValueError(f"Publication visibility mismatch")
        runs.append(
            write(
                data,
                [
                    r
                    for r in receipts
                    if r[f"manifest_sha256"] == data[f"sha256"]
                ],
                args.workflow_url,
                args.data,
            ),
        )
    if not runs:
        raise ValueError(f"No experiment manifests found")
    attempt = text(args.attempt_id, rf"[0-9]+-[0-9]+")
    save(args.data / f"attempts" / f"{attempt}.json", {f"runs": runs})
    # Validate the assembled index, but do not commit a shared index file.
    index(args.data, args.visibility)


if __name__ == f"__main__":
    main()
