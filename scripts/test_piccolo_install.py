#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install a packaged runtime through QwenPaw and test both model roles."""

import argparse
import asyncio
import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from piccolo_runtime import CONFIG, digest, identity, target_config
from test_piccolo_runtime import verify


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def install_and_verify(args, workspace):
    # Set the workspace before importing QwenPaw, including in spawned workers.
    os.environ["QWENPAW_WORKING_DIR"] = str(workspace / "qwenpaw")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from qwenpaw.local_models.llamacpp import LlamaCppBackend

    config = target_config(args.target)
    public = workspace / "public" / CONFIG["release"]
    public.mkdir(parents=True)
    shutil.copy2(args.archive, public / args.archive.name)
    manifest = identity() | {
        "artifacts": {
            args.archive.name: {
                "size": args.archive.stat().st_size,
                "sha256": digest(args.archive),
            },
        },
    }
    (public / "runtime-release.json").write_text(json.dumps(manifest))
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(Handler, directory=str(workspace / "public")),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    results = []
    try:
        for upgrade in (False, True):
            case = "upgrade" if upgrade else "clean-install"
            backend = LlamaCppBackend()
            backend.target_dir = workspace / case / "bin"
            # Hosted CUDA builders have no GPU; install their produced target.
            backend.os_name = config["os"]
            backend.arch = config["arch"]
            backend.backend = config["backend"]
            backend.cuda_version = (
                ".".join(config["cuda"].split(".")[:2])
                if "cuda" in config
                else None
            )
            model = workspace / case / "models" / "existing.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"existing model unchanged")
            if upgrade:
                backend.target_dir.mkdir()
                backend.executable.write_bytes(b"old runtime")
                assert asyncio.run(backend.has_update(CONFIG["release"]))
            backend.download(
                base_url=f"http://127.0.0.1:{httpd.server_port}",
                tag=CONFIG["release"],
            )
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                progress = backend.get_download_progress()
                if progress["status"] in ("completed", "failed", "cancelled"):
                    break
                time.sleep(0.2)
            else:
                backend.cancel_download()
                raise TimeoutError(f"Installer timed out: {case}")
            assert progress["status"] == "completed", progress
            assert backend.check_llamacpp_installation()[0]
            assert not asyncio.run(backend.has_update(CONFIG["release"]))
            assert model.read_bytes() == b"existing model unchanged"
            verify(
                backend.executable,
                args.flash.resolve(),
                args.piccolo.resolve(),
                args.output / case,
                args.gpu_layers,
            )
            results.append(
                {
                    "case": case,
                    "target": args.target,
                    "models_preserved": True,
                    "flash_piccolo_flash": True,
                },
            )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
    (args.output / "install-report.json").write_text(
        json.dumps(results, indent=2) + "\n",
    )
    print("Clean installation, upgrade and both model roles passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
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
    with tempfile.TemporaryDirectory() as temporary:
        install_and_verify(args, Path(temporary))


if __name__ == "__main__":
    main()
