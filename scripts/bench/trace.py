# -*- coding: utf-8 -*-
"""Publish credential-redacted Harbor artifacts for offline attribution."""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path
from urllib.parse import quote

from .common import save


CREDENTIAL = re.compile(
    rf"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|"
    rf"client[_-]?secret|authorization)$",
    re.IGNORECASE,
)


def scrub_fields(value):
    """Remove credential values without deleting trajectory structure."""
    if isinstance(value, dict):
        return {
            key: f"[REDACTED]"
            if CREDENTIAL.search(key)
            else scrub_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_fields(item) for item in value]
    return value


def redacted(payload: bytes, suffix: str) -> bytes:
    """Remove the injected key and common encodings before publication."""
    key = os.environ.get(f"BENCH_API_KEY", f"")
    if key:
        for value in (
            key,
            quote(key, safe=f""),
            json.dumps(key)[1:-1],
            base64.b64encode(key.encode()).decode(),
            key.encode().hex(),
        ):
            payload = payload.replace(value.encode(), b"[REDACTED]")
    try:
        text = payload.decode(f"utf-8")
    except UnicodeDecodeError:
        return payload
    text = re.sub(
        rf"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{{16,}}",
        f"[REDACTED]",
        text,
    )
    text = re.sub(
        rf"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        rf"\1[REDACTED]",
        text,
    )
    if suffix in (f".json", f".jsonl"):
        try:
            if suffix == f".jsonl":
                text = (
                    f"\n".join(
                        json.dumps(scrub_fields(json.loads(line)))
                        for line in text.splitlines()
                        if line.strip()
                    )
                    + f"\n"
                )
            else:
                text = json.dumps(scrub_fields(json.loads(text)), indent=2)
        except json.JSONDecodeError:
            # Interrupted JSONL writes still contain useful timeout evidence.
            pass
    return text.encode(f"utf-8")


def publish(root: Path, output: Path) -> dict:
    """Archive regular trial files and describe any redaction or omission."""
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Public archive must be outside trial output")
    output.mkdir(parents=True, exist_ok=False)
    files, omitted = [], []
    with tarfile.open(output / f"trajectory.tar.gz", f"w:gz") as archive:
        for path in sorted(root.rglob(f"*")):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                omitted.append({f"path": name, f"reason": f"symlink"})
                continue
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Trace file escapes trial directory")
            original = path.read_bytes()
            payload = redacted(original, path.suffix)
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(payload), 0o644
            archive.addfile(info, io.BytesIO(payload))
            files.append(
                {
                    f"path": name,
                    f"bytes": len(payload),
                    f"sha256": hashlib.sha256(payload).hexdigest(),
                    f"redacted": payload != original,
                },
            )
    if not files:
        raise ValueError(f"No trial artifacts to archive")
    manifest = {
        f"schema_version": 1,
        f"archive_sha256": hashlib.sha256(
            (output / f"trajectory.tar.gz").read_bytes(),
        ).hexdigest(),
        f"files": files,
        f"omitted": omitted,
    }
    save(output / f"files.json", manifest)
    return manifest


def main() -> None:
    """Create a public archive without printing trajectory contents."""
    parser = argparse.ArgumentParser()
    parser.add_argument(f"--input", type=Path, required=True)
    parser.add_argument(f"--output", type=Path, required=True)
    args = parser.parse_args()
    publish(args.input, args.output)


if __name__ == f"__main__":
    main()
