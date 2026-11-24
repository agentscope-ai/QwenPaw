#!/usr/bin/env python3
"""Verify supplied candidate wheels before preparing this checkout for uv sync."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel-dir', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / 'docs/qpd-candidate.json').read_text())
    verified = []
    for name, expected in manifest['wheels'].items():
        source = args.wheel_dir / name
        if not source.is_file():
            parser.error(f'Missing wheel: {source}')
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            parser.error(f'Wheel checksum mismatch: {name}. Use the reviewed candidate artifacts.')
        verified.append(source)
    destination = root / '.artifacts/wheels'
    destination.mkdir(parents=True, exist_ok=True)
    for source in verified:
        target = destination / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
    print(f'Prepared {len(verified)} verified candidate wheels in {destination}')


if __name__ == '__main__':
    main()
