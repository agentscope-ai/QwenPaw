# -*- coding: utf-8 -*-
"""Download Harbor datasets once and freeze portable task batches."""

import math
import re
from datetime import datetime, timezone
from pathlib import Path

from harbor.models.task.task import Task

from .common import digest, load, tree_hash


def validate_prices(prices: dict, models: dict) -> None:
    """Reject a price snapshot for another endpoint or invalid rates."""
    if prices[f"base_url"] != models[f"base_url"]:
        raise ValueError(f"Price region does not match API endpoint")
    if (
        prices[f"currency"] not in (f"CNY", f"USD")
        or prices[f"unit_tokens"] != 1000000
    ):
        raise ValueError(f"Unsupported price currency or token unit")
    fx = prices[f"fx"][f"cny_per_usd"]
    if prices[f"currency"] == f"CNY" and (
        type(fx) not in (int, float) or not math.isfinite(fx) or fx <= 0
    ):
        raise ValueError(f"Invalid exchange rate")
    for model in models[f"models"]:
        rate = prices[f"models"].get(model[f"id"])
        if rate is None:
            continue
        for key in (f"input", f"output", f"cache"):
            value = rate[key]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"Invalid price")
            if value < 0:
                raise ValueError(f"Negative price")
        if rate[f"cache"] > rate[f"input"]:
            raise ValueError(f"Cache price exceeds uncached price")


def harness_identity(suite: dict, version: str) -> tuple[str, str]:
    """Validate the selected harness and its publication boundary."""
    harness = suite[f"harness"]
    harness_version = suite[f"harness_version"]
    if not re.fullmatch(rf"[A-Za-z0-9_. -]{{1,80}}", harness):
        raise ValueError(f"Invalid harness name")
    if harness == f"QwenPaw":
        harness_version = version
    elif harness_version == f"source" or not harness_version:
        raise ValueError(f"Alternative harness requires an explicit version")
    if harness != f"QwenPaw" and suite[f"visibility"] != f"private":
        raise ValueError(f"Alternative harness results must remain private")
    return harness, harness_version


def freeze(
    config: Path,
    datasets: Path,
    version: str,
    sha: str,
    repository: str = f"agentscope-ai/QwenPaw",
) -> dict:
    """Validate coverage and native budgets without modifying tasks."""
    if not re.fullmatch(rf"[0-9][0-9a-zA-Z.+-]*", version):
        raise ValueError(f"Expected an explicit QwenPaw package version")
    if not re.fullmatch(rf"[0-9a-f]{{40}}", sha):
        raise ValueError(f"Expected a full source commit SHA")
    if not re.fullmatch(rf"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError(f"Invalid public source repository")
    suite = load(config / f"suite.yaml")
    models = load(config / f"models.yaml")
    prices = load(config / f"prices.yaml")
    validate_prices(prices, models)
    if not 1 <= suite[f"batch_size"] <= 256:
        raise ValueError(f"Batch size must be between 1 and 256")
    for field, records in (
        (f"benchmark", suite[f"benchmarks"]),
        (f"model", models[f"models"]),
    ):
        ids = [item[f"id"] for item in records]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError(f"Empty or duplicate {field} IDs")
    harness, harness_version = harness_identity(suite, version)
    tasks = []
    for benchmark in suite[f"benchmarks"]:
        if not re.fullmatch(rf"[a-z0-9-]+", benchmark[f"id"]):
            raise ValueError(f"Invalid benchmark ID")
        paths = sorted((datasets / benchmark[f"id"]).rglob(f"task.toml"))
        if len(paths) != benchmark[f"count"]:
            raise ValueError(f"Task count mismatch: {benchmark[f'id']}")
        for path in paths:
            task = Task(path.parent)
            native = task.config
            if native.steps or native.agent.timeout_sec is None:
                raise ValueError(f"Unsupported or missing budget: {task.name}")
            minutes = math.ceil(
                (
                    native.agent.timeout_sec
                    + native.verifier.timeout_sec
                    + native.environment.build_timeout_sec
                    + suite[f"agent_setup_seconds"]
                    + suite[f"upload_margin_seconds"]
                )
                / 60,
            )
            if minutes > 360:
                raise ValueError(f"Native budget exceeds hosted: {task.name}")
            relative = path.parent.relative_to(datasets).as_posix()
            tasks.append(
                {
                    f"id": digest({f"path": relative})[:24],
                    f"benchmark": benchmark[f"id"],
                    f"path": relative,
                    f"sha256": tree_hash(path.parent),
                    f"job_minutes": minutes,
                    f"resources": native.environment.model_dump(mode=f"json"),
                },
            )
    size = suite[f"batch_size"]
    payload = {
        f"schema_version": 1,
        f"created_at": datetime.now(timezone.utc).isoformat(),
        f"product_version": version,
        f"harness": harness,
        f"harness_version": harness_version,
        f"evaluation_sha": sha,
        f"source_repository": repository,
        f"suite": suite,
        f"models": models,
        f"prices": prices,
        f"harbor": load(config / f"harbor.yaml"),
        f"tasks": tasks,
        f"batches": [tasks[i : i + size] for i in range(0, len(tasks), size)],
    }
    return {**payload, f"sha256": digest(payload)}
