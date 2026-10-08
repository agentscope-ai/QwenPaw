# -*- coding: utf-8 -*-
"""Validate complete coverage and export only public summary fields."""

import argparse
import math
from collections import Counter, defaultdict
from pathlib import Path

from .common import load, manifest, save


def aggregate(data: dict, receipts: list[dict]) -> dict:
    """Select the first non-infrastructure attempt, never the best score."""
    expected = {
        (model[f"id"], task[f"id"]): task
        for model in data[f"models"][f"models"]
        for task in data[f"tasks"]
    }
    grouped = defaultdict(list)
    identities = set()
    for receipt in receipts:
        key = (receipt[f"model_id"], receipt[f"task_id"])
        identity = (*key, receipt[f"attempt"])
        # Keep receipt identity checks together for auditability.
        # pylint: disable=too-many-boolean-expressions
        if (
            key not in expected
            or identity in identities
            or receipt[f"manifest_sha256"] != data[f"sha256"]
            or receipt[f"source_sha"] != data[f"evaluation_sha"]
            or receipt[f"provider"] != data[f"models"][f"provider"][f"id"]
            or receipt[f"harness"] != data[f"harness"]
            or receipt[f"sdk_version"] != data[f"harness_version"]
            or receipt[f"status"]
            not in (f"infra_error", f"scored", f"agent_timeout")
            or receipt[f"trial"] != 0
            or receipt[f"benchmark"] != expected[key][f"benchmark"]
        ):
            raise ValueError(f"Foreign, inconsistent, or duplicate receipt")
        identities.add(identity)
        grouped[key].append(receipt)
    selected = {}
    for key, attempts in grouped.items():
        attempts.sort(key=lambda r: r[f"attempt"])
        if [r[f"attempt"] for r in attempts] != list(
            range(1, len(attempts) + 1),
        ):
            raise ValueError(f"Attempt history has gaps")
        completed = [r for r in attempts if r[f"status"] != f"infra_error"]
        if completed:
            first = completed[0]
            if len(completed) > 1 or first is not attempts[-1]:
                raise ValueError(f"A scored task cannot be retried")
            if first[f"score"] not in (0, 1):
                raise ValueError(f"Invalid binary score")
            selected[key] = first
    records = []
    for model in data[f"models"][f"models"]:
        parts = []
        for benchmark in data[f"suite"][f"benchmarks"]:
            tasks = [
                t
                for t in data[f"tasks"]
                if t[f"benchmark"] == benchmark[f"id"]
            ]
            rows = [
                selected[(model[f"id"], t[f"id"])]
                for t in tasks
                if (model[f"id"], t[f"id"]) in selected
            ]
            complete = len(rows) == len(tasks) and bool(tasks)
            attempts = [
                r
                for r in receipts
                if r[f"model_id"] == model[f"id"]
                and r[f"benchmark"] == benchmark[f"id"]
            ]
            costs = [r[f"model_cost_usd"] for r in attempts]
            known = all(
                c is not None and math.isfinite(c) and c >= 0 for c in costs
            )
            runtimes = [r[f"runtime_seconds"] for r in rows]
            timed = all(
                t is not None and math.isfinite(t) and t >= 0 for t in runtimes
            )
            parts.append(
                {
                    f"benchmark": benchmark[f"id"],
                    f"cost_sources": dict(
                        Counter(r[f"cost_source"] for r in attempts),
                    ),
                    f"cost_bases": dict(
                        Counter(r[f"cost_basis"] for r in attempts),
                    ),
                    f"cost_observed_attempts": len(attempts),
                    f"cost_known_attempts": sum(c is not None for c in costs),
                    f"domains": benchmark[f"domains"],
                    f"expected": len(tasks),
                    f"scored": len(rows),
                    f"score": sum(r[f"score"] for r in rows) / len(tasks) * 100
                    if complete
                    else None,
                    f"mean_runtime_seconds": sum(runtimes) / len(tasks)
                    if complete and timed
                    else None,
                    f"mean_model_cost_usd": sum(costs) / len(tasks)
                    if complete and known
                    else None,
                },
            )
        complete = all(p[f"score"] is not None for p in parts)
        costs = [p[f"mean_model_cost_usd"] for p in parts]
        runtimes = [p[f"mean_runtime_seconds"] for p in parts]
        attempted_costs = [
            r[f"model_cost_usd"]
            for r in receipts
            if r[f"model_id"] == model[f"id"]
        ]
        known_costs = [
            c
            for c in attempted_costs
            if c is not None and math.isfinite(c) and c >= 0
        ]
        domains = {}
        for domain in sorted({d for p in parts for d in p[f"domains"]}):
            scores = [p[f"score"] for p in parts if domain in p[f"domains"]]
            domains[domain] = (
                sum(scores) / len(scores) if None not in scores else None
            )
        records.append(
            {
                f"model": model[f"id"],
                f"provider": data[f"models"][f"provider"][f"id"],
                f"harness": data[f"harness"],
                f"sdk_version": data[f"harness_version"],
                f"source_sha": data[f"evaluation_sha"],
                f"complete": complete,
                f"index_score": sum(p[f"score"] for p in parts) / len(parts)
                if complete
                else None,
                f"index_model_cost_usd": sum(costs) / len(costs)
                if complete and None not in costs
                else None,
                f"index_runtime_seconds": sum(runtimes) / len(runtimes)
                if complete and None not in runtimes
                else None,
                f"observed_model_spend_usd": sum(known_costs)
                if known_costs
                else None,
                f"attempts_with_known_cost": len(known_costs),
                f"observed_attempts": len(attempted_costs),
                f"cost_status": f"model_only"
                if None not in costs
                else f"unknown",
                f"domains": domains,
                f"benchmarks": parts,
            },
        )
    return {
        f"schema_version": 1,
        f"visibility": data[f"suite"][f"visibility"],
        f"index_version": data[f"suite"][f"version"],
        f"manifest_sha256": data[f"sha256"],
        f"evaluation_sha": data[f"evaluation_sha"],
        f"prices": data[f"prices"],
        f"date": data[f"created_at"],
        f"records": records,
        f"complete": len(selected) == len(expected),
    }


def main() -> None:
    """Keep raw transcripts separate from the website's allowlisted JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--manifest", type=Path, required=True)
    parser.add_argument(f"--receipts", type=Path, required=True)
    parser.add_argument(f"--output", type=Path, required=True)
    parser.add_argument(f"--public", action=f"store_true")
    args = parser.parse_args()
    data = manifest(args.manifest)
    if args.public and data[f"suite"][f"visibility"] != f"public":
        raise ValueError(f"Private results cannot be published")
    rows = [load(path) for path in args.receipts.rglob(f"receipt.json")]
    result = aggregate(data, rows)
    save(args.output, result)
    if not result[f"complete"]:
        raise SystemExit(1)


if __name__ == f"__main__":
    main()
