# -*- coding: utf-8 -*-
"""Exercise the real ACP path without publishing a benchmark score."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .common import load, save
from .prepare import freeze


def main() -> None:
    """Use one synthetic task and one configured model for acceptance."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--output", type=Path, required=True)
    parser.add_argument(f"--version", required=True)
    parser.add_argument(f"--sha", required=True)
    args = parser.parse_args()
    config = args.output / f"config"
    config.mkdir(parents=True)
    source = Path(f".github/bench")
    suite = load(source / f"suite.yaml")
    suite[f"version"] = f"smoke-only"
    suite[f"benchmarks"] = [
        {f"id": f"smoke", f"count": 1, f"domains": [f"smoke"]},
    ]
    models = load(source / f"models.yaml")
    models[f"models"] = [models[f"models"][1]]
    save(config / f"suite.yaml", suite)
    save(config / f"models.yaml", models)
    shutil.copyfile(source / f"harbor.yaml", config / f"harbor.yaml")
    datasets = args.output / f"datasets"
    shutil.copytree(
        Path(f"tests/fixtures/bench/smoke"),
        datasets / f"smoke/task",
    )
    data = freeze(config, datasets, args.version, args.sha)
    manifest_path = args.output / f"manifest.json"
    save(manifest_path, data)
    result_path = args.output / f"result"
    subprocess.run(
        [
            sys.executable,
            f"-m",
            f"scripts.bench.run",
            f"--manifest",
            str(manifest_path),
            f"--datasets",
            str(datasets),
            f"--output",
            str(result_path),
            f"--model",
            f"0",
            f"--task",
            data[f"tasks"][0][f"id"],
        ],
        check=True,
    )
    receipt = load(result_path / f"receipt.json")
    if receipt[f"score"] != 1:
        raise SystemExit(f"ACP smoke task did not pass")


if __name__ == f"__main__":
    main()
