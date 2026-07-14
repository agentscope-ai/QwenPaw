#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Register or update the Zalo webhook.

Usage:
    python3 register_webhook.py --url https://your-domain.com/api/zalo/webhook

Reads config from ~/.qwenpaw/config.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

try:
    # When imported as part of the plugin package.
    from ..client import ZaloClient  # type: ignore
except ImportError:
    # When run as a standalone script (`python3 register_webhook.py`).
    from client import ZaloClient  # type: ignore


def find_bot_token(args_token: str | None, config: dict) -> str:
    if args_token:
        return args_token
    zalo = config.get("channels", {}).get("zalo", {}) or {}
    token = zalo.get("bot_token", "")
    if not token:
        sys.exit("bot_token not found. Pass --bot-token or set in config.json")
    return token


def find_secret_token(args_token: str | None, config: dict) -> str:
    if args_token:
        return args_token
    zalo = config.get("channels", {}).get("zalo", {}) or {}
    token = zalo.get("secret_token", "")
    if not token:
        secret_file = Path.home() / ".qwenpaw" / "zalo_secret_token"
        if secret_file.exists():
            token = secret_file.read_text().strip()
    if not token:
        sys.exit("secret_token not found. Pass --secret-token or set in config.json")
    return token


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"Failed to parse {path}: {e}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Register Zalo webhook")
    parser.add_argument(
        "--config",
        default="~/.qwenpaw/config.json",
        help="Path to config.json",
    )
    parser.add_argument("--bot-token", help="Override bot token")
    parser.add_argument("--secret-token", help="Override secret token")
    parser.add_argument("--url", required=True, help="Public HTTPS URL")
    parser.add_argument("--delete", action="store_true", help="Delete webhook")
    parser.add_argument("--info", action="store_true", help="Show current webhook info")

    args = parser.parse_args()
    config = load_config(Path(args.config).expanduser())

    if args.info:
        bot_token = find_bot_token(args.bot_token, config)
        client = ZaloClient(bot_token)
        await client.start()
        try:
            info = await client.get_webhook_info()
            print(json.dumps(info, indent=2))
        finally:
            await client.close()
        return 0

    if not args.url.startswith("https://"):
        sys.exit("--url must start with https:// (Zalo requires HTTPS)")

    bot_token = find_bot_token(args.bot_token, config)
    secret_token = find_secret_token(args.secret_token, config)

    client = ZaloClient(bot_token)
    await client.start()
    try:
        if args.delete:
            result = await client.delete_webhook()
            print("Webhook deleted:", json.dumps(result, indent=2))
        else:
            result = await client.set_webhook(url=args.url, secret_token=secret_token)
            print("Webhook registered:", json.dumps(result, indent=2))
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
