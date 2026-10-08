# -*- coding: utf-8 -*-
"""Render a native Harbor job and normalize its single trial receipt."""

import argparse
import base64
import copy
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from harbor.models.job.config import JobConfig

from .common import load, manifest, resolve, save, tree_hash


def job_config(data: dict, task: dict, model: dict, root: Path) -> dict:
    """Keep the model key in the environment, never in saved configuration."""
    config = copy.deepcopy(data[f"harbor"])
    agent = config[f"agents"][0]
    registry = agent[f"kwargs"][f"registry_entry"]
    version = data[f"product_version"]
    registry[f"version"] = version
    registry[f"distribution"][f"uvx"][f"package"] = f"qwenpaw=={version}"
    # OPENAI_MODEL fixes the runtime provider for this task.
    # Avoid the optional ACP session model-selection extension.
    agent.pop(f"model_name", None)
    agent[f"override_setup_timeout_sec"] = data[f"suite"][
        f"agent_setup_seconds"
    ]
    settings = data[f"models"]
    info = {
        key: settings[key]
        for key in (
            f"max_input_tokens",
            f"max_output_tokens",
            f"generate_kwargs",
        )
    }
    info.update(supports_image=model[f"supports_image"])
    agent[f"env"].update(
        {
            f"OPENAI_BASE_URL": settings[f"base_url"],
            f"OPENAI_MODEL": model[f"id"],
            f"QWENPAW_MODEL_INFO_JSON": json.dumps(info),
        },
    )
    config[f"tasks"] = [{f"path": str(resolve(root, task[f"path"]))}]
    config[f"job_name"] = f"task"
    config[f"jobs_dir"] = f"harbor"
    # Validate against the pinned Harbor schema before starting containers.
    JobConfig.model_validate(config)
    return config


def normalize(raw: dict, data: dict, task: dict, model: dict, attempt: int):
    """Keep missing usage unknown and infrastructure errors unscored."""
    error = (raw.get(f"exception_info") or {}).get(f"exception_type")
    rewards = (raw.get(f"verifier_result") or {}).get(f"rewards") or {}
    score = rewards.get(f"reward")
    if error == f"AgentTimeoutError":
        status, score = f"agent_timeout", 0.0
    elif error or not isinstance(score, (float, int)):
        status, score = f"infra_error", None
    elif not math.isfinite(score) or score not in (0, 1):
        status, score = f"infra_error", None
    else:
        status = f"scored"
    usage = raw.get(f"agent_result") or {}
    runtime = None
    if raw.get(f"started_at") and raw.get(f"finished_at"):
        runtime = (
            datetime.fromisoformat(raw[f"finished_at"])
            - datetime.fromisoformat(raw[f"started_at"])
        ).total_seconds()
    cost = usage.get(f"cost_usd")
    if cost is not None and (not math.isfinite(cost) or cost < 0):
        cost = None
    return {
        f"schema_version": 1,
        f"manifest_sha256": data[f"sha256"],
        f"task_id": task[f"id"],
        f"benchmark": task[f"benchmark"],
        f"model_id": model[f"id"],
        f"harness": f"QwenPaw",
        f"sdk_version": data[f"product_version"],
        f"trial": 0,
        f"attempt": attempt,
        f"status": status,
        f"score": score,
        f"runtime_seconds": runtime,
        f"usage": {
            key: usage.get(key)
            for key in (
                f"n_input_tokens",
                f"n_cache_tokens",
                f"n_output_tokens",
            )
        },
        f"model_cost_usd": cost,
        f"cost_source": f"harbor_reported" if cost is not None else f"unknown",
        f"tool_cost_usd": None,
        f"judge_cost_usd": None,
        f"infrastructure_cost_usd": None,
        f"error_type": error,
    }


def redact(message: str) -> str:
    """Remove the injected credential and its common encoded forms."""
    key = os.environ.get(f"DASHSCOPE_API_KEY", f"")
    if key:
        for variant in (
            key,
            quote(key, safe=f""),
            json.dumps(key)[1:-1],
            base64.b64encode(key.encode()).decode(),
            key.encode().hex(),
        ):
            message = message.replace(variant, f"[REDACTED]")
    return re.sub(rf"sk-[a-zA-Z0-9_-]+", f"[REDACTED]", message)


# Each branch recognizes an independent diagnostic category.
# pylint: disable=too-many-branches
def diagnostics(output: Path, smoke: bool = False) -> list[str]:
    """Export fixed failure labels, never raw process messages."""
    markers = {
        f"no such option": f"unsupported_cli_option",
        f"no such command": f"unsupported_cli_command",
        f"modulenotfounderror": f"missing_python_module",
        f"importerror": f"python_import_error",
        f"command not found": f"missing_executable",
        f"invalid_api_key": f"authentication_failed",
        f"incorrect api key": f"authentication_failed",
        f"modelnotfoundexception": f"local_model_catalog_error",
        f"connection refused": f"connection_refused",
        f"permission denied": f"permission_denied",
        f"out of memory": f"out_of_memory",
        f"no space left": f"disk_full",
        f"unsupportedmodel": f"unsupported_model",
        f"validationerror": f"validation_error",
    }
    found = set()
    for path in output.rglob(f"acp-summary.json"):
        summary = load(path)
        for stage in (
            f"initialize",
            f"session",
            f"set_model_response",
            f"prompt_response",
            f"set_model_error",
        ):
            if stage in summary:
                found.add(f"acp_stage:{stage}")
        error = summary.get(f"error") or {}
        message = str(error.get(f"message", f""))
        if message:
            found.add(f"acp_error_summary:{redact(message)[:1000]}")
        if error.get(f"type") in (
            f"RequestError",
            f"RuntimeError",
            f"ValueError",
            f"TimeoutError",
        ):
            found.add(f"acp_error:{error['type']}")
    for path in output.rglob(f"*"):
        if path.is_file() and path.suffix in (f".json", f".log", f".txt"):
            content = path.read_text(errors=f"replace").lower()
            found.update(
                label for token, label in markers.items() if token in content
            )
            frames = re.findall(
                rf'file "[^"\n]*/([a-z_]+\.py)", line (\d+), in ([a-z_]+)',
                content,
            )
            for filename, line, function in frames:
                found.add(f"frame:{filename}:{int(line)}:{function}")
            for code in re.findall(rf"exit code[: ]+(\d+)", content):
                found.add(f"exit_code_{int(code)}")
    if smoke:
        chunks = []
        for path in output.rglob(f"acp-events.jsonl"):
            for line in path.read_text(encoding=f"utf-8").splitlines():
                event = json.loads(line)
                update = (event.get(f"payload") or {}).get(f"update") or {}
                if update.get(f"sessionUpdate") == f"agent_message_chunk":
                    content = update.get(f"content") or {}
                    chunks.append(str(content.get(f"text", f"")))
        if chunks:
            text = redact(f"".join(chunks))
            found.add(f"synthetic_task_reply:{text[-1500:]}")
    return sorted(found)


def main() -> None:
    """Run one task and store its raw artifacts beside the receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--manifest", type=Path, required=True)
    parser.add_argument(f"--datasets", type=Path, required=True)
    parser.add_argument(f"--output", type=Path, required=True)
    parser.add_argument(f"--task", required=True)
    parser.add_argument(f"--model", type=int, required=True)
    parser.add_argument(f"--attempt", type=int, default=1)
    args = parser.parse_args()
    data = manifest(args.manifest)
    task = next(t for t in data[f"tasks"] if t[f"id"] == args.task)
    if args.model < 0 or args.attempt < 1:
        raise ValueError(f"Invalid model or attempt index")
    model = data[f"models"][f"models"][args.model]
    path = resolve(args.datasets, task[f"path"])
    if tree_hash(path) != task[f"sha256"]:
        raise ValueError(f"Task checksum mismatch")
    if not os.environ.get(f"DASHSCOPE_API_KEY"):
        raise ValueError(f"DASHSCOPE_API_KEY is required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = job_config(data, task, model, args.datasets)
    save(output / f"job.json", config)
    result = subprocess.run(
        [
            sys.executable,
            f"-m",
            f"harbor.cli.main",
            f"run",
            f"-c",
            str(output / f"job.json"),
        ],
        cwd=output,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=False,
    )
    trials = []
    for file in (output / f"harbor").rglob(f"result.json"):
        raw = load(file)
        if f"task_checksum" in raw:
            trials.append(raw)
    if len(trials) > 1:
        raise ValueError(f"Single-task job produced multiple trial results")
    raw = (
        trials[0]
        if trials
        else {
            f"exception_info": {f"exception_type": f"MissingTrialResult"},
        }
    )
    receipt = normalize(raw, data, task, model, args.attempt)
    receipt[f"diagnostics"] = diagnostics(
        output,
        smoke=task[f"benchmark"] == f"smoke",
    )
    encoded = json.dumps(receipt)
    if os.environ[f"DASHSCOPE_API_KEY"] in encoded:
        raise ValueError(f"Secret detected in receipt; export blocked")
    save(output / f"receipt.json", receipt)
    print(f"Task status: {receipt['status']}")
    print(f"Error type: {receipt['error_type']}")
    if result.returncode or receipt[f"status"] == f"infra_error":
        raise SystemExit(1)


if __name__ == f"__main__":
    main()
