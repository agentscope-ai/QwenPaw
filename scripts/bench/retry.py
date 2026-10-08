# -*- coding: utf-8 -*-
"""Plan one fresh-runner retry for infrastructure failures only."""

import argparse
import json
import os
from pathlib import Path

from .collect import aggregate
from .common import load, manifest, save
from .run import normalize


def plan(data: dict, receipts: list[dict], model_index: int, batch: int):
    """Keep scored failures and agent timeouts immutable."""
    aggregate(data, receipts)
    model = data[f"models"][f"models"][model_index]
    tasks = data[f"batches"][batch]
    by_task = {
        r[f"task_id"]: r
        for r in receipts
        if r[f"model_id"] == model[f"id"] and r[f"attempt"] == 1
    }
    retry, missing = [], []
    for task in tasks:
        receipt = by_task.get(task[f"id"])
        if receipt is None:
            receipt = normalize(
                {f"exception_info": {f"exception_type": f"MissingReceipt"}},
                data,
                task,
                model,
                1,
            )
            missing.append(receipt)
        if receipt[f"status"] == f"infra_error":
            retry.append({k: task[k] for k in (f"id", f"job_minutes")})
    return retry, missing


def main() -> None:
    """Record lost attempts before starting their replacements."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--manifest", type=Path, required=True)
    parser.add_argument(f"--receipts", type=Path, required=True)
    parser.add_argument(f"--missing", type=Path, required=True)
    parser.add_argument(f"--model", type=int, required=True)
    parser.add_argument(f"--batch", type=int, required=True)
    args = parser.parse_args()
    data = manifest(args.manifest)
    rows = [load(p) for p in args.receipts.rglob(f"receipt.json")]
    retry, missing = plan(data, rows, args.model, args.batch)
    for row in missing:
        save(args.missing / row[f"task_id"] / f"receipt.json", row)
    with Path(os.environ[f"GITHUB_OUTPUT"]).open(
        f"a",
        encoding=f"utf-8",
    ) as out:
        out.write(f"tasks={json.dumps(retry)}\n")


if __name__ == f"__main__":
    main()
