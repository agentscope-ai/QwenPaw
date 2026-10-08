# -*- coding: utf-8 -*-
"""Expand dispatch selections into independently frozen experiments."""

import argparse
import copy
import json
import os
import subprocess
import sys
import tarfile
from itertools import product
from pathlib import Path

from .common import digest, load, save, source_version
from .prepare import freeze
from .provider import configured, selection


def select(value: str, available: list[str]) -> list[str]:
    """Resolve one or many IDs without silently widening the selection."""
    selected = list(dict.fromkeys(item.strip() for item in value.split(f",")))
    if selected == [f"all"]:
        return available
    if not selected or any(item not in available for item in selected):
        raise ValueError(f"Unknown or empty selection: {value}")
    return selected


def experiments(
    data: dict,
    models: str,
    benchmarks: str,
    task_limit: int = 0,
) -> list[dict]:
    """Keep configuration identity independent of neighboring selections."""
    if task_limit < 0:
        raise ValueError(f"Task limit cannot be negative")
    model_ids = select(models, [m[f"id"] for m in data[f"models"][f"models"]])
    benchmark_ids = select(
        benchmarks,
        [b[f"id"] for b in data[f"suite"][f"benchmarks"]],
    )
    records = []
    for model in data[f"models"][f"models"]:
        if model[f"id"] not in model_ids:
            continue
        leaf = copy.deepcopy(data)
        leaf.pop(f"sha256")
        leaf[f"models"][f"models"] = [model]
        identity = copy.deepcopy(leaf)
        for key in (f"created_at", f"batches", f"product_version"):
            identity.pop(key)
        leaf[f"configuration_sha256"] = digest(identity)
        leaf[f"index_benchmarks"] = copy.deepcopy(
            data[f"suite"][f"benchmarks"],
        )
        leaf[f"tasks"] = [
            t for t in data[f"tasks"] if t[f"benchmark"] in benchmark_ids
        ]
        leaf[f"suite"][f"benchmarks"] = [
            b
            for b in data[f"suite"][f"benchmarks"]
            if b[f"id"] in benchmark_ids
        ]
        scheduled = leaf[f"tasks"]
        if task_limit:
            scheduled = [
                task
                for benchmark in benchmark_ids
                for task in [
                    t for t in scheduled if t[f"benchmark"] == benchmark
                ][:task_limit]
            ]
        leaf[f"task_limit"] = task_limit
        size = leaf[f"suite"][f"batch_size"]
        leaf[f"batches"] = [
            scheduled[i : i + size] for i in range(0, len(scheduled), size)
        ]
        if not 1 <= len(leaf[f"batches"]) <= 9:
            raise ValueError(f"Configured suite exceeds nine batch slots")
        records.append({**leaf, f"sha256": digest(leaf)})
    return records


def concurrency(task_parallelism: int, experiment_parallelism: int) -> dict:
    """Bound requested slots; GitHub account limits remain authoritative."""
    if type(task_parallelism) is not int or not 1 <= task_parallelism <= 128:
        raise ValueError(f"Task parallelism must be between 1 and 128")
    if (
        type(experiment_parallelism) is not int
        or not 1 <= experiment_parallelism <= 256
    ):
        raise ValueError(f"Experiment parallelism must be between 1 and 256")
    return {
        f"max_parallel": task_parallelism,
        f"experiment_parallelism": experiment_parallelism,
    }


def arguments() -> argparse.Namespace:
    """Read dispatch options without modifying configuration."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--task-limit", type=int, default=0)
    parser.add_argument(
        f"--parallelism",
        default=f'{{"experiments":6,"tasks":16}}',
    )
    parser.add_argument(f"--harnesses", default=f"qwenpaw")
    parser.add_argument(f"--models", default=f"all")
    parser.add_argument(f"--benchmarks", default=f"all")
    parser.add_argument(f"--provider", default=f"default")
    parser.add_argument(f"--base-url", default=f"")
    parser.add_argument(f"--secret-name", default=f"")
    parser.add_argument(f"--model-options", default=f"{{}}")
    parser.add_argument(f"--price-snapshot", default=f"")
    parser.add_argument(f"--output", type=Path, required=True)
    parser.add_argument(f"--sha", required=True)
    parser.add_argument(f"--repository", required=True)
    parser.add_argument(f"--private-repository", action=f"store_true")
    return parser.parse_args()


def main() -> None:
    """Export full protocol once, then schedule only selected tasks."""
    args = arguments()
    if args.task_limit < 0:
        raise ValueError(f"Task limit cannot be negative")
    parallelism = json.loads(args.parallelism)
    scheduling = concurrency(
        parallelism[f"tasks"],
        parallelism[f"experiments"],
    )
    registry = load(Path(f".github/bench/harnesses.yaml"))
    matrix = []
    visibility = None
    providers = selection(args.provider)
    if len(providers) > 1 and (
        args.base_url or args.secret_name or args.price_snapshot
    ):
        raise ValueError(
            f"Endpoint, secret and price overrides require one provider",
        )
    for harness_id, provider_id in product(
        select(args.harnesses, list(registry)),
        providers,
    ):
        config = Path(registry[harness_id]).resolve()
        config.relative_to(Path.cwd().resolve())
        config = configured(
            config,
            args.output / f"configs" / harness_id / provider_id,
            provider=provider_id,
            models=args.models,
            base_url=args.base_url,
            secret_name=args.secret_name,
            model_options=args.model_options,
            price_snapshot=args.price_snapshot,
        )
        suite = load(config / f"suite.yaml")
        suite.update(scheduling)
        save(config / f"suite.yaml", suite)
        if suite[f"visibility"] == f"private" and not args.private_repository:
            raise ValueError(
                f"Private configuration requires a private repository",
            )
        if (
            visibility
            and not args.private_repository
            and visibility != suite[f"visibility"]
        ):
            raise ValueError(f"Cannot mix public and private experiments")
        visibility = (
            f"private" if args.private_repository else suite[f"visibility"]
        )
        select(
            args.models,
            [m[f"id"] for m in load(config / f"models.yaml")[f"models"]],
        )
        select(args.benchmarks, [b[f"id"] for b in suite[f"benchmarks"]])
        datasets = args.output / f"datasets" / harness_id
        for item in suite[f"benchmarks"]:
            if (datasets / item[f"id"]).exists():
                continue
            subprocess.run(
                [
                    sys.executable,
                    f"-m",
                    f"harbor.cli.main",
                    f"datasets",
                    f"download",
                    item[f"dataset"],
                    f"--output-dir",
                    str(datasets / item[f"id"]),
                    f"--export",
                ],
                check=True,
            )
        data = freeze(
            config,
            datasets,
            source_version(),
            args.sha,
            args.repository,
        )
        data[f"suite"][f"visibility"] = visibility
        for leaf in experiments(
            data,
            f"all",
            args.benchmarks,
            args.task_limit,
        ):
            experiment = leaf[f"configuration_sha256"][:24]
            folder = args.output / f"experiments" / experiment
            save(folder / f"manifest.json", leaf)
            for i, batch in enumerate(leaf[f"batches"]):
                with tarfile.open(
                    folder / f"batch-{i}.tar.gz",
                    f"w:gz",
                ) as archive:
                    for task in batch:
                        archive.add(
                            datasets / task[f"path"],
                            arcname=task[f"path"],
                        )
            matrix.append(
                {f"experiment": experiment, f"batches": len(leaf[f"batches"])},
            )
    if not matrix or len(matrix) > 256:
        raise ValueError(f"Experiment matrix must contain 1 to 256 entries")
    with Path(os.environ[f"GITHUB_OUTPUT"]).open(
        f"a",
        encoding=f"utf-8",
    ) as stream:
        stream.write(f"experiments={json.dumps(matrix)}\n")
        stream.write(f"visibility={visibility}\n")
        stream.write(f"task_parallelism={scheduling['max_parallel']}\n")
        stream.write(
            f"experiment_parallelism={scheduling['experiment_parallelism']}\n",
        )


if __name__ == f"__main__":
    main()
