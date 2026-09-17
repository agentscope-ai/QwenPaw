#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WeldonAgent production environment validation and compatibility mapping."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import quote


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER_PASSWORDS = {
    "REPLACE_WITH_RANDOM_PASSWORD",
    "CHANGE_ME",
    "CHANGEME",
    "PASSWORD",
}


@dataclass(frozen=True)
class ProductionSettings:
    """Validated production database settings."""

    db_name: str = "weldonagent"
    db_schema: str = "weldonagent"
    db_user: str = "weldon"
    db_password: str = ""


def _identifier(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, default).strip()
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} 必须是合法的 PostgreSQL 标识符")
    return value


def validate_environment(env: Mapping[str, str]) -> ProductionSettings:
    """Validate public deployment settings without returning secret values."""

    password = env.get("WELDON_DB_PASSWORD", "")
    if not password or password.upper() in _PLACEHOLDER_PASSWORDS:
        raise ValueError("WELDON_DB_PASSWORD 必须设置为非示例随机强密码")
    if len(password) < 16:
        raise ValueError("WELDON_DB_PASSWORD 长度至少为 16 个字符")
    if "\x00" in password or "\n" in password or "\r" in password:
        raise ValueError("WELDON_DB_PASSWORD 包含不允许的控制字符")

    return ProductionSettings(
        db_name=_identifier(env, "WELDON_DB_NAME", "weldonagent"),
        db_schema=_identifier(env, "WELDON_DB_SCHEMA", "weldonagent"),
        db_user=_identifier(env, "WELDON_DB_USER", "weldon"),
        db_password=password,
    )


def build_database_url(settings: ProductionSettings) -> str:
    """Build a PostgreSQL URL while safely encoding credentials."""

    user = quote(settings.db_user, safe="")
    password = quote(settings.db_password, safe="")
    database = quote(settings.db_name, safe="")
    return f"postgresql://{user}:{password}@agent-pg:5432/{database}"


def build_internal_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Map public WELDON_* settings to the existing internal contract."""

    settings = validate_environment(env)
    internal = {
        "QWENPAW_MULTI_USER_ENABLED": "true",
        "QWENPAW_STORAGE_MODE": "postgres",
        "QWENPAW_DATABASE_URL": build_database_url(settings),
        "QWENPAW_DATABASE_SCHEMA": settings.db_schema,
        "QWENPAW_WORKING_DIR": "/data/working",
        "QWENPAW_SECRET_DIR": "/data/secrets",
        "QWENPAW_BACKUP_DIR": "/data/backups",
        "QWENPAW_CUTOVER_VALIDATED_DOMAINS": "all",
        "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS": "all",
        "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS": "all",
    }
    timezone = env.get("WELDON_TIMEZONE", "Asia/Shanghai").strip()
    if timezone:
        internal["TZ"] = timezone
    return internal


def _command_environment(env: Mapping[str, str]) -> dict[str, str]:
    result = dict(env)
    result.update(build_internal_environment(env))
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="weldon-runtime",
        description="Validate WeldonAgent production settings and run internal commands.",
    )
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("check", help="validate production environment")
    execute = subcommands.add_parser("exec", help="run a command with compatibility variables")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        internal = build_internal_environment(os.environ)
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    if args.action == "check":
        print(
            "WeldonAgent 生产配置有效："
            f"database={os.environ.get('WELDON_DB_NAME', 'weldonagent')} "
            f"schema={internal['QWENPAW_DATABASE_SCHEMA']}"
        )
        return 0

    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        print("配置错误：exec 后必须提供命令", file=sys.stderr)
        return 2
    try:
        return subprocess.call(command, env=_command_environment(os.environ))
    except OSError:
        print("命令启动失败，请检查容器镜像和部署日志", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
