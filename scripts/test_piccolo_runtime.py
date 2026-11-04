#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exercise a packaged runtime with public Flash and Piccolo GGUFs."""

import argparse
import json
import math
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path


def request(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=300) as response:
        return json.load(response)


@contextmanager
def server(executable, model, decision, gpu_layers, log):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    args = [
        str(executable),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--model",
        str(model),
        "--alias",
        "smoke",
        "--ctx-size",
        "2048",
        "--parallel",
        "1",
        "--gpu-layers",
        gpu_layers,
    ]
    if decision:
        args += [
            "--batch-size",
            "2048",
            "--ubatch-size",
            "2048",
            "--no-cache-prompt",
            "--cache-ram",
            "0",
            "--no-context-shift",
        ]
    with log.open("w") as output:
        environment = os.environ.copy()
        if os.name == "nt":
            # Test bundled DLLs without tools installed on the build runner.
            windows = Path(environment["SystemRoot"])
            environment["PATH"] = os.pathsep.join(
                (str(windows / "System32"), str(windows)),
            )
        process = subprocess.Popen(
            args,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Runtime exited; see {log}")
                try:
                    request(port, "/health")
                    break
                except (OSError, urllib.error.HTTPError):
                    time.sleep(0.5)
            else:
                raise TimeoutError(f"Runtime did not become ready; see {log}")
            yield port
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def verify(executable, flash, piccolo, output, gpu_layers):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    # Flash -> Piccolo -> Flash also checks that the same binary supports both.
    for name, model, decision in (
        ("flash", flash, False),
        ("piccolo", piccolo, True),
        ("flash-restored", flash, False),
    ):
        with server(
            executable,
            model,
            decision,
            gpu_layers,
            output / f"{name}.log",
        ) as port:
            models = request(port, "/v1/models")["data"]
            expected = "decisions" if decision else "text"
            assert expected in models[0]["architecture"]["output_modalities"]
            if decision:
                result = request(
                    port,
                    "/v1/systemone",
                    {
                        "state": "A user requests the total in a CSV file. No file changes are requested.",
                        "questions": {
                            "action": {
                                "type": "choice",
                                "instructions": "Select the next action.",
                                "criteria": {
                                    "read": "Read the CSV",
                                    "delete": "Delete the CSV",
                                },
                            },
                            "keep": {
                                "type": "noul",
                                "instructions": "Keep the user's request in context?",
                            },
                        },
                    },
                )
                answer = result["answers"]["action"]
                probabilities = answer["probabilities"]
                assert set(probabilities) == {"read", "delete"}
                assert all(
                    math.isfinite(p) and 0 <= p <= 1
                    for p in probabilities.values()
                )
                assert abs(sum(probabilities.values()) - 1) < 1e-5
                assert answer["choice"] == max(
                    probabilities,
                    key=probabilities.get,
                )
                assert 0 <= result["answers"]["keep"]["noul"] <= 1
                assert result["usage"]["output_tokens"] == 0
            else:
                result = request(
                    port,
                    "/v1/chat/completions",
                    {
                        "model": "smoke",
                        "messages": [
                            {"role": "user", "content": "Say hello briefly."},
                        ],
                        "max_tokens": 32,
                        "temperature": 0,
                        "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                assert result["choices"][0]["message"]["content"].strip()
                assert result["usage"]["completion_tokens"] > 0
            results.append({"case": name, "result": result})
    (output / "report.json").write_text(json.dumps(results, indent=2) + "\n")
    print("Packaged Flash, Piccolo decisions and Flash restart passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--flash", type=Path, required=True)
    parser.add_argument("--piccolo", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/runtime-smoke"),
    )
    parser.add_argument("--gpu-layers", default="0")
    args = parser.parse_args()
    import shutil

    with tempfile.TemporaryDirectory() as temporary:
        bundle = Path(temporary)
        shutil.unpack_archive(args.archive, bundle)
        executable = bundle / (
            "llama-server.exe"
            if (bundle / "llama-server.exe").exists()
            else "llama-server"
        )
        verify(
            executable,
            args.flash.resolve(),
            args.piccolo.resolve(),
            args.output,
            args.gpu_layers,
        )


if __name__ == "__main__":
    main()
