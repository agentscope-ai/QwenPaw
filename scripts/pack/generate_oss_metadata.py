#!/usr/bin/env python3
"""
Generate OSS metadata JSON files for release artifacts.

Usage:
  python generate_oss_metadata.py \
    --file dist/QwenPaw-Setup-1.0.0.exe \
    --product desktop \
    --platform win \
    --version 1.0.0 \
    --output metadata.json
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def calculate_sha256(filepath: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def format_file_size(size_bytes: int) -> str:
    """Format file size to human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def get_file_type(filename: str) -> str:
    """Extract file type from filename extension."""
    ext = Path(filename).suffix.lower()
    return ext[1:] if ext else "unknown"


def generate_metadata(
    filepath: str,
    product: str,
    platform: str,
    version: str,
) -> dict:
    """Generate metadata for a single artifact file."""
    file_path = Path(filepath)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    filename = file_path.name
    file_size = file_path.stat().st_size
    sha256 = calculate_sha256(filepath)
    file_type = get_file_type(filename)

    file_id = f"{product}-{platform}-{version}"

    platform_names = {
        "win": {"zh-CN": "Windows 版", "en-US": "for Windows"},
        "mac": {"zh-CN": "macOS 版", "en-US": "for macOS"},
        "linux": {"zh-CN": "Linux 版", "en-US": "for Linux"},
    }

    product_names = {
        "desktop": {"zh-CN": "桌面客户端", "en-US": "Desktop Client"},
        "cli": {"zh-CN": "命令行工具", "en-US": "CLI Tool"},
    }

    platform_suffix = platform_names.get(
        platform, {"zh-CN": platform, "en-US": platform}
    )
    product_name = product_names.get(
        product, {"zh-CN": product, "en-US": product}
    )

    oss_path = f"/files/apps/{product}/{platform}/{filename}"

    metadata = {
        "id": file_id,
        "name": {
            "zh-CN": f"{product_name['zh-CN']} {platform_suffix['zh-CN']}",
            "en-US": f"{product_name['en-US']} {platform_suffix['en-US']}",
        },
        "description": {
            "zh-CN": f"适用于 {platform_suffix['zh-CN']}的{product_name['zh-CN']}安装包",
            "en-US": f"{product_name['en-US']} installer {platform_suffix['en-US']}",
        },
        "product": product,
        "platform": platform,
        "version": version,
        "filename": filename,
        "url": oss_path,
        "size": format_file_size(file_size),
        "size_bytes": file_size,
        "sha256": sha256,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "type": file_type,
    }

    return metadata


def merge_desktop_index(
    existing_index_path: str,
    new_metadata: dict,
    platform: str,
) -> dict:
    """Merge new metadata into desktop/index.json."""
    if os.path.exists(existing_index_path):
        with open(existing_index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {
            "product": "desktop",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "platforms": {},
            "files": {},
        }

    if "platforms" not in index:
        index["platforms"] = {}
    if "files" not in index:
        index["files"] = {}
    if "product" not in index:
        index["product"] = "desktop"

    index["updated_at"] = datetime.now(timezone.utc).isoformat()

    if platform not in index["platforms"]:
        index["platforms"][platform] = {"latest": "", "versions": []}

    file_id = new_metadata["id"]
    index["platforms"][platform]["latest"] = file_id

    if file_id not in index["platforms"][platform]["versions"]:
        index["platforms"][platform]["versions"].insert(0, file_id)

    index["files"][file_id] = new_metadata

    return index


def main():
    parser = argparse.ArgumentParser(
        description="Generate OSS metadata for release artifacts"
    )
    parser.add_argument(
        "--file", required=True, help="Path to the artifact file"
    )
    parser.add_argument(
        "--product", required=True, help="Product name (e.g., desktop, cli)"
    )
    parser.add_argument(
        "--platform",
        required=True,
        help="Platform name (e.g., win, mac, linux)",
    )
    parser.add_argument(
        "--version", required=True, help="Version string (e.g., 1.0.0)"
    )
    parser.add_argument(
        "--output",
        default="metadata.json",
        help="Output metadata JSON file path",
    )
    parser.add_argument(
        "--merge-index",
        help="Path to existing desktop/index.json to merge into",
    )
    parser.add_argument(
        "--output-index",
        help="Output path for merged desktop/index.json",
    )

    args = parser.parse_args()

    print(f"Generating metadata for: {args.file}")
    metadata = generate_metadata(
        args.file, args.product, args.platform, args.version
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"✓ Metadata written to: {args.output}")
    print(f"  ID: {metadata['id']}")
    print(f"  Size: {metadata['size']}")
    print(f"  SHA256: {metadata['sha256'][:16]}...")

    # Merge into desktop/index.json if requested
    if args.merge_index and args.output_index:
        print(f"\nMerging into desktop index: {args.merge_index}")
        merged_index = merge_desktop_index(
            args.merge_index, metadata, args.platform
        )
        with open(args.output_index, "w", encoding="utf-8") as f:
            json.dump(merged_index, f, indent=2, ensure_ascii=False)
        print(f"✓ Desktop index written to: {args.output_index}")
        print(
            f"  Latest {args.platform}: {merged_index['platforms'][args.platform]['latest']}"
        )


if __name__ == "__main__":
    main()
