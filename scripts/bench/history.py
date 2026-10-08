# -*- coding: utf-8 -*-
"""Validate and append immutable public evaluation summaries."""

import argparse
import math
import re
from pathlib import Path

from .common import load, save


def text(value, pattern: str) -> str:
    """Validate public identifiers without exporting arbitrary strings."""
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"Invalid public identifier")
    return value


def number(value, maximum: float | None = None):
    """Keep missing metrics null and reject nonfinite or negative metrics."""
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Invalid public metric")
    if value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"Public metric outside range")
    return value


def counts(value: dict, allowed: set[str]) -> dict:
    """Export only supported accounting labels and integer counts."""
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"Unsupported cost metadata")
    if any(type(n) is not int or n < 0 for n in value.values()):
        raise ValueError(f"Invalid cost coverage")
    return value


def public_run(summary: dict, workflow_url: str) -> dict:
    """Project a complete public QwenPaw run into the website contract."""
    if (
        summary[f"schema_version"] != 1
        or summary[f"visibility"] != f"public"
        or summary[f"complete"] is not True
        or not summary[f"records"]
    ):
        raise ValueError(f"Only complete public results can be published")
    sha = text(summary[f"evaluation_sha"], rf"[0-9a-f]{{40}}")
    sources = {
        f"harbor_reported",
        f"litellm_estimated",
        f"snapshot_estimated",
        f"unknown",
    }
    bases = {f"reported", f"list_price", f"upper_bound", f"unknown"}
    records = []
    identities = set()
    for record in summary[f"records"]:
        if (
            record[f"harness"] != f"QwenPaw"
            or record[f"complete"] is not True
            or record[f"source_sha"] != sha
        ):
            raise ValueError(f"Foreign harness, source or partial result")
        model = text(record[f"model"], rf"[a-zA-Z0-9_.:/-]{{1,160}}")
        if model in identities:
            raise ValueError(f"Duplicate model record")
        identities.add(model)
        parts = []
        for part in record[f"benchmarks"]:
            expected, scored = part[f"expected"], part[f"scored"]
            if (
                type(expected) is not int
                or expected <= 0
                or scored != expected
            ):
                raise ValueError(f"Incomplete benchmark")
            parts.append(
                {
                    f"benchmark": text(part[f"benchmark"], rf"[a-z0-9-]+"),
                    f"domains": [
                        text(d, rf"[a-z0-9-]+") for d in part[f"domains"]
                    ],
                    f"expected": expected,
                    f"scored": scored,
                    f"score": number(part[f"score"], 100),
                    f"mean_runtime_seconds": number(
                        part[f"mean_runtime_seconds"],
                    ),
                    f"mean_model_cost_usd": number(
                        part[f"mean_model_cost_usd"],
                    ),
                    f"cost_sources": counts(part[f"cost_sources"], sources),
                    f"cost_bases": counts(part[f"cost_bases"], bases),
                    f"cost_observed_attempts": number(
                        part[f"cost_observed_attempts"],
                    ),
                    f"cost_known_attempts": number(
                        part[f"cost_known_attempts"],
                    ),
                },
            )
        if not parts or any(p[f"score"] is None for p in parts):
            raise ValueError(f"Missing benchmark score")
        if len({p[f"benchmark"] for p in parts}) != len(parts):
            raise ValueError(f"Duplicate benchmark")
        records.append(
            {
                f"model": model,
                f"harness": f"QwenPaw",
                f"sdk_version": text(
                    record[f"sdk_version"],
                    rf"[0-9a-zA-Z.+-]+",
                ),
                f"source_sha": sha,
                f"complete": True,
                f"index_score": number(record[f"index_score"], 100),
                f"index_model_cost_usd": number(
                    record[f"index_model_cost_usd"],
                ),
                f"index_runtime_seconds": number(
                    record[f"index_runtime_seconds"],
                ),
                f"observed_model_spend_usd": number(
                    record[f"observed_model_spend_usd"],
                ),
                f"attempts_with_known_cost": number(
                    record[f"attempts_with_known_cost"],
                ),
                f"observed_attempts": number(record[f"observed_attempts"]),
                f"cost_status": text(
                    record[f"cost_status"],
                    rf"model_only|unknown",
                ),
                f"domains": {
                    text(k, rf"[a-z0-9-]+"): number(v, 100)
                    for k, v in record[f"domains"].items()
                },
                f"benchmarks": parts,
            },
        )
    prices = summary[f"prices"]
    return {
        f"schema_version": 1,
        f"visibility": f"public",
        f"complete": True,
        f"index_version": text(summary[f"index_version"], rf"[a-z0-9.-]+"),
        f"manifest_sha256": text(
            summary[f"manifest_sha256"],
            rf"[a-f0-9]{{64}}",
        ),
        f"evaluation_sha": sha,
        f"date": text(summary[f"date"], rf"[0-9T:+.Z-]+"),
        f"workflow_url": text(
            workflow_url,
            rf"https://github.com/[\w.-]+/[\w.-]+/actions/runs/[0-9]+",
        ),
        f"records": records,
        f"prices": {
            f"version": text(prices[f"version"], rf"[a-z0-9.-]+"),
            f"fx": {
                f"date": text(prices[f"fx"][f"date"], rf"[0-9-]+"),
                f"cny_per_usd": number(prices[f"fx"][f"cny_per_usd"]),
            },
        },
    }


def append(history: dict, run: dict) -> dict:
    """Treat repeated publication as a no-op; never rewrite an existing run."""
    if history[f"schema_version"] != 1 or history[f"visibility"] != f"public":
        raise ValueError(f"Invalid public history")
    runs = []
    seen = set()
    for previous in [*history[f"runs"], run]:
        previous = public_run(previous, previous[f"workflow_url"])
        identity = previous[f"manifest_sha256"]
        if identity in seen:
            if (
                next(r for r in runs if r[f"manifest_sha256"] == identity)
                != previous
            ):
                raise ValueError(f"Immutable run conflict")
            continue
        seen.add(identity)
        runs.append(previous)
    runs.sort(key=lambda r: (r[f"date"], r[f"manifest_sha256"]), reverse=True)
    return {f"schema_version": 1, f"visibility": f"public", f"runs": runs}


def main() -> None:
    """Write only validated public data; the workflow owns git publication."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--summary", type=Path, required=True)
    parser.add_argument(f"--index", type=Path, required=True)
    parser.add_argument(f"--workflow-url", required=True)
    args = parser.parse_args()
    history = (
        load(args.index)
        if args.index.exists()
        else {
            f"schema_version": 1,
            f"visibility": f"public",
            f"runs": [],
        }
    )
    run = public_run(load(args.summary), args.workflow_url)
    save(args.index, append(history, run))


if __name__ == f"__main__":
    main()
