# -*- coding: utf-8 -*-
"""Verify the tested Engine revision and any explicit compatibility patches."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine_source", type=Path)
    args = parser.parse_args()
    manifest = json.loads(
        (ROOT / "tests/fixtures/pawapp-compatibility.json").read_text(),
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=args.engine_source,
        text=True,
    ).strip()
    if revision != manifest["engine_revision"]:
        raise SystemExit(
            "Engine revision differs from the tested compatibility pin",
        )
    for item in manifest["patches"]:
        patch = ROOT / item["path"]
        if hashlib.sha256(patch.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit("Engine patch checksum mismatch")
        command = ["git", "apply", "--check", str(patch)]
        if (
            subprocess.run(
                command,
                cwd=args.engine_source,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        ):
            subprocess.run(
                ["git", "apply", str(patch)],
                cwd=args.engine_source,
                check=True,
            )
        else:
            # Existing local development checkout may already contain this
            # exact patch.
            subprocess.run(
                ["git", "apply", "--reverse", "--check", str(patch)],
                cwd=args.engine_source,
                check=True,
            )
    print("Engine compatibility source verified")


if __name__ == "__main__":
    main()
