# -*- coding: utf-8 -*-
"""Regression tests for evaluation isolation, identity, and scoring."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts.bench.collect import aggregate
from scripts.bench.common import manifest, resolve, save
from scripts.bench.prepare import freeze
from scripts.bench.retry import plan
from scripts.bench.history import append, public_run
from scripts.bench.run import diagnostics, job_config, normalize


@pytest.fixture(name=f"prepared")
def prepared_fixture(tmp_path):
    config = tmp_path / f"config"
    config.mkdir()
    for source in Path(f".github/bench").glob(f"*.yaml"):
        (config / source.name).write_text(source.read_text(encoding=f"utf-8"))
    suite = yaml.safe_load(
        (config / f"suite.yaml").read_text(encoding=f"utf-8"),
    )
    suite[f"benchmarks"] = suite[f"benchmarks"][:2]
    suite[f"benchmarks"][0][f"count"] = 1
    suite[f"benchmarks"][1][f"count"] = 2
    (config / f"suite.yaml").write_text(yaml.safe_dump(suite))
    models = yaml.safe_load(
        (config / f"models.yaml").read_text(encoding=f"utf-8"),
    )
    models[f"models"] = models[f"models"][:1]
    (config / f"models.yaml").write_text(yaml.safe_dump(models))
    datasets = tmp_path / f"datasets"
    for bench in suite[f"benchmarks"]:
        for i in range(bench[f"count"]):
            task = datasets / bench[f"id"] / str(i)
            (task / f"environment").mkdir(parents=True)
            (task / f"tests").mkdir()
            (task / f"instruction.md").write_text(f"Write /app/answer.txt")
            (task / f"environment/Dockerfile").write_text(f"FROM ubuntu:24.04")
            (task / f"tests/test.sh").write_text(
                f"echo 1 > /logs/verifier/reward.txt",
            )
            (task / f"task.toml").write_text(
                f'version="1.0"\n[agent]\ntimeout_sec=600\n'
                f"[verifier]\ntimeout_sec=300\n"
                f"[environment]\nbuild_timeout_sec=300\n",
            )
    data = freeze(config, datasets, f"1.0.0", f"a" * 40)
    return data, datasets, config


def receipt(data, task, score=1, cost=None, error=None):
    return normalize(
        {
            f"verifier_result": {f"rewards": {f"reward": score}},
            f"agent_result": {f"cost_usd": cost},
            f"exception_info": {f"exception_type": error} if error else None,
        },
        data,
        task,
        data[f"models"][f"models"][0],
        1,
    )


def test_macro_average_not_task_weighted(prepared):
    data, _, _ = prepared
    rows = [
        receipt(data, t, int(t[f"benchmark"] == f"gaia"))
        for t in data[f"tasks"]
    ]
    result = aggregate(data, rows)
    assert result[f"complete"]
    assert result[f"records"][0][f"index_score"] == 50
    assert result[f"records"][0][f"index_model_cost_usd"] is None


def test_missing_task_does_not_publish_complete_score(prepared):
    data, _, _ = prepared
    rows = [receipt(data, t) for t in data[f"tasks"][:-1]]
    result = aggregate(data, rows)
    assert not result[f"complete"]
    assert result[f"records"][0][f"index_score"] is None


def test_native_timeouts_are_preserved(prepared):
    data, datasets, _ = prepared
    task = data[f"tasks"][0]
    assert task[f"job_minutes"] == 45
    config = job_config(data, task, data[f"models"][f"models"][0], datasets)
    assert config[f"timeout_multiplier"] == 1
    assert f"model_name" not in config[f"agents"][0]
    assert config[f"agents"][0][f"env"][f"OPENAI_MODEL"] == (
        data[f"models"][f"models"][0][f"id"]
    )
    assert f"override_timeout_sec" not in config[f"agents"][0]
    assert (
        config[f"agents"][0][f"env"][f"OPENAI_API_KEY"]
        == f"${{DASHSCOPE_API_KEY}}"
    )
    assert (
        config[f"agents"][0][f"kwargs"][f"registry_entry"][f"distribution"][
            f"uvx"
        ][f"package"]
        == f"--no-cache"
    )
    assert f"QwenPaw" not in json.dumps(config.get(f"dependencies", {}))


def test_hosted_limit_is_not_clamped(prepared):
    _, datasets, config = prepared
    task = next(datasets.rglob(f"task.toml"))
    task.write_text(
        task.read_text(encoding=f"utf-8").replace(
            f"timeout_sec=600",
            f"timeout_sec=22000",
        ),
    )
    with pytest.raises(ValueError, match=f"exceeds hosted"):
        freeze(config, datasets, f"1.0.0", f"a" * 40)


def test_manifest_tampering(prepared, tmp_path):
    data, _, _ = prepared
    path = tmp_path / f"manifest.json"
    save(path, data)
    assert manifest(path)[f"sha256"] == data[f"sha256"]
    data[f"product_version"] = f"2.0.0"
    save(path, data)
    with pytest.raises(ValueError, match=f"checksum"):
        manifest(path)


@pytest.mark.parametrize(
    f"relative",
    [f"../escape", f"/tmp/escape", f"..\\escape"],
)
def test_paths_cannot_escape(tmp_path, relative):
    with pytest.raises(ValueError):
        resolve(tmp_path, relative)


def test_retry_only_after_infrastructure_error(prepared):
    data, _, _ = prepared
    rows = [receipt(data, t) for t in data[f"tasks"]]
    failed = copy.deepcopy(rows[0])
    failed.update(status=f"infra_error", score=None)
    rows[0][f"attempt"] = 2
    assert aggregate(data, [failed, *rows])[f"complete"]
    failed.update(status=f"scored", score=0)
    with pytest.raises(ValueError, match=f"cannot be retried"):
        aggregate(data, [failed, *rows])


def test_foreign_and_duplicate_receipts_are_rejected(prepared):
    data, _, _ = prepared
    row = receipt(data, data[f"tasks"][0])
    with pytest.raises(ValueError):
        aggregate(data, [row, row])
    row[f"manifest_sha256"] = f"wrong"
    with pytest.raises(ValueError):
        aggregate(data, [row])


def test_timeout_scores_zero_but_verifier_error_is_incomplete(prepared):
    data, _, _ = prepared
    task = data[f"tasks"][0]
    assert receipt(data, task, error=f"AgentTimeoutError")[f"score"] == 0
    assert receipt(data, task, error=f"VerifierTimeoutError")[f"score"] is None


def test_public_projection_never_exports_raw_secrets(prepared):
    data, _, _ = prepared
    rows = [receipt(data, t, cost=1) for t in data[f"tasks"]]
    for row in rows:
        row[f"transcript"] = f"SECRET-KEY"
    result = aggregate(data, rows)
    assert f"SECRET-KEY" not in json.dumps(result)
    assert result[f"records"][0][f"index_model_cost_usd"] == 1


def test_missing_task_count_blocks_freeze(prepared):
    _, datasets, config = prepared
    next(datasets.rglob(f"task.toml")).unlink()
    with pytest.raises(ValueError, match=f"count mismatch"):
        freeze(config, datasets, f"1.0.0", f"a" * 40)


def test_runtime_and_infrastructure_retry_spend(prepared):
    data, _, _ = prepared
    rows = [receipt(data, t, cost=2) for t in data[f"tasks"]]
    for row in rows:
        row[f"runtime_seconds"] = 120
    failed = copy.deepcopy(rows[0])
    failed.update(status=f"infra_error", score=None, model_cost_usd=1)
    rows[0][f"attempt"] = 2
    record = aggregate(data, [failed, *rows])[f"records"][0]
    assert record[f"index_runtime_seconds"] == 120
    assert record[f"index_model_cost_usd"] == 2.5
    assert record[f"observed_model_spend_usd"] == 7
    assert record[f"attempts_with_known_cost"] == 4


def test_unknown_status_is_rejected(prepared):
    data, _, _ = prepared
    row = receipt(data, data[f"tasks"][0])
    row[f"status"] = f"invented"
    with pytest.raises(ValueError):
        aggregate(data, [row])


def test_yaml_scope_fits_serial_batches():
    suite = yaml.safe_load(
        Path(f".github/bench/suite.yaml").read_text(encoding=f"utf-8"),
    )
    total = sum(b[f"count"] for b in suite[f"benchmarks"])
    sizes = [
        min(suite[f"batch_size"], total - i)
        for i in range(0, total, suite[f"batch_size"])
    ]
    assert sizes == [128] * 8 + [41]
    workflow = yaml.safe_load(
        Path(f".github/workflows/bench-model.yml").read_text(
            encoding=f"utf-8",
        ),
    )
    assert len(workflow[f"jobs"]) == len(sizes)
    for i in range(1, len(sizes)):
        assert workflow[f"jobs"][f"batch_{i}"][f"needs"] == f"batch_{i - 1}"


def test_diagnostics_export_labels_not_raw_credentials(tmp_path):
    (tmp_path / f"stderr.txt").write_text(
        f"SECRET_TEST_VALUE no such option: --runtime-provider exit code: 2",
    )
    assert diagnostics(tmp_path) == [f"exit_code_2", f"unsupported_cli_option"]


def test_acp_summary_redacts_secret_encodings(tmp_path, monkeypatch):
    key = f"TEST_ONLY_CREDENTIAL"
    monkeypatch.setenv(f"DASHSCOPE_API_KEY", key)
    save(
        tmp_path / f"acp-summary.json",
        {f"error": {f"type": f"RuntimeError", f"message": key}},
    )
    result = json.dumps(diagnostics(tmp_path))
    assert key not in result
    assert f"[REDACTED]" in result


def test_public_history_is_immutable_and_private_results_rejected(prepared):
    data, _, _ = prepared
    summary = aggregate(
        data,
        [receipt(data, t, cost=1) for t in data[f"tasks"]],
    )
    url = f"https://github.com/example/project/actions/runs/123"
    run = public_run(summary, url)
    empty = {f"schema_version": 1, f"visibility": f"public", f"runs": []}
    history = append(empty, run)
    assert append(history, run) == history
    modified = copy.deepcopy(run)
    modified[f"records"][0][f"benchmarks"][0][f"score"] = 0
    with pytest.raises(ValueError, match=f"Immutable"):
        append(history, modified)
    summary[f"visibility"] = f"private"
    with pytest.raises(ValueError):
        public_run(summary, url)


def test_recovery_uses_only_infrastructure_and_missing_attempts(prepared):
    data, _, _ = prepared
    tasks = data[f"tasks"]
    scored = receipt(data, tasks[0], score=0, cost=1)
    timeout = receipt(data, tasks[1], error=f"AgentTimeoutError")
    retry, missing = plan(data, [scored, timeout], 0, 0)
    assert [task[f"id"] for task in retry] == [tasks[2][f"id"]]
    assert len(missing) == 1
    assert missing[0][f"model_cost_usd"] is None
    recovered = receipt(data, tasks[2], cost=1)
    recovered[f"attempt"] = 2
    result = aggregate(data, [scored, timeout, *missing, recovered])
    assert result[f"complete"]
    assert result[f"records"][0][f"index_model_cost_usd"] is None
