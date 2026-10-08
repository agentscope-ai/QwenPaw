# -*- coding: utf-8 -*-
"""Load the data branch on every website build without running its code."""

import argparse
import json
import subprocess
from pathlib import Path

from .common import save
from .history import append


def hydrate(output: Path) -> None:
    """An absent branch is empty history; network errors must not erase it."""
    probe = subprocess.run(
        [
            f"git",
            f"ls-remote",
            f"--exit-code",
            f"origin",
            f"refs/heads/bench-results",
        ],
        capture_output=True,
        check=False,
    )
    empty = {f"schema_version": 1, f"visibility": f"public", f"runs": []}
    if probe.returncode == 2:
        save(output, empty)
        return
    if probe.returncode:
        raise RuntimeError(f"Cannot query evaluation data branch")
    subprocess.run(
        [
            f"git",
            f"fetch",
            f"--depth=1",
            f"origin",
            f"refs/heads/bench-results:refs/remotes/origin/bench-results",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    raw = subprocess.run(
        [
            f"git",
            f"show",
            f"refs/remotes/origin/bench-results:public/index.json",
        ],
        capture_output=True,
        check=True,
    )
    history = json.loads(raw.stdout)
    if history[f"schema_version"] != 1 or history[f"visibility"] != f"public":
        raise ValueError(f"Non-public evaluation history")
    for run in history[f"runs"]:
        empty = append(empty, run)
    save(output, empty)


def main() -> None:
    """Hydrate the public history before the website build."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--output", type=Path, required=True)
    args = parser.parse_args()
    hydrate(args.output)


if __name__ == f"__main__":
    main()
