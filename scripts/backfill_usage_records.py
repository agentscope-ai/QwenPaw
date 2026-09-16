# -*- coding: utf-8 -*-
"""预览或幂等迁移 Legacy 会话中的逐轮 Token 用量。"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qwenpaw.access.agent_repository import agent_database_id  # noqa: E402
from qwenpaw.token_usage.legacy_backfill import (  # noqa: E402
    collect_usage_candidates,
)

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


async def run(args: argparse.Namespace) -> dict:
    schema = args.schema.strip().lower()
    if not _SAFE_SCHEMA.fullmatch(schema):
        raise ValueError("invalid_database_schema")
    candidates = collect_usage_candidates(args.working_dir)
    connection = await asyncpg.connect(
        args.database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    report: dict[str, object] = {
        "mode": "apply" if args.apply else "preview",
        "discovered": len(candidates),
        "valid": 0,
        "already_present": 0,
        "missing_relations": 0,
        "inserted": 0,
        "by_user": {},
    }
    by_user = defaultdict(
        lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    )
    transaction = connection.transaction()
    transaction_finished = False
    try:
        await transaction.start()
        for candidate in candidates:
            resolved = await connection.fetchrow(
                f"SELECT u.username,p.id AS provider_id,m.id AS model_id "
                f'FROM "{schema}".conversations c '
                f'JOIN "{schema}".users u ON u.id=c.owner_user_id '
                f'JOIN "{schema}".agents a ON a.id=c.agent_id '
                f'JOIN "{schema}".model_providers p ON p.name=$4 '
                f'JOIN "{schema}".models m ON m.provider_id=p.id AND m.model_key=$5 '
                "WHERE c.id=$1 AND c.owner_user_id=$2 AND c.agent_id=$3 "
                "AND c.deleted_at IS NULL",
                candidate.conversation_id,
                candidate.user_id,
                agent_database_id(candidate.agent_key),
                candidate.provider_key,
                candidate.model_key,
            )
            if resolved is None:
                report["missing_relations"] = int(report["missing_relations"]) + 1
                continue
            report["valid"] = int(report["valid"]) + 1
            user_summary = by_user[str(resolved["username"])]
            user_summary["calls"] += 1
            user_summary["prompt_tokens"] += candidate.prompt_tokens
            user_summary["completion_tokens"] += candidate.completion_tokens
            exists = await connection.fetchval(
                f'SELECT EXISTS (SELECT 1 FROM "{schema}".usage_records '
                "WHERE id=$1 OR (user_id=$2 AND agent_id=$3 AND conversation_id=$4 "
                "AND provider_id=$5 AND model_id=$6 AND occurred_at=$7 "
                "AND prompt_tokens=$8 AND completion_tokens=$9))",
                candidate.record_id,
                candidate.user_id,
                agent_database_id(candidate.agent_key),
                candidate.conversation_id,
                resolved["provider_id"],
                resolved["model_id"],
                candidate.occurred_at,
                candidate.prompt_tokens,
                candidate.completion_tokens,
            )
            if exists:
                report["already_present"] = int(report["already_present"]) + 1
                continue
            if args.apply:
                await connection.execute(
                    f'INSERT INTO "{schema}".usage_records '
                    "(id,occurred_at,user_id,actor_type,agent_id,conversation_id,"
                    "provider_id,model_id,prompt_tokens,completion_tokens,call_count) "
                    "VALUES($1,$2,$3,'user',$4,$5,$6,$7,$8,$9,1) ON CONFLICT DO NOTHING",
                    candidate.record_id,
                    candidate.occurred_at,
                    candidate.user_id,
                    agent_database_id(candidate.agent_key),
                    candidate.conversation_id,
                    resolved["provider_id"],
                    resolved["model_id"],
                    candidate.prompt_tokens,
                    candidate.completion_tokens,
                )
                report["inserted"] = int(report["inserted"]) + 1
        if args.apply:
            await transaction.commit()
        else:
            await transaction.rollback()
        transaction_finished = True
        report["by_user"] = dict(sorted(by_user.items()))
        return report
    except BaseException:
        if not transaction_finished:
            await transaction.rollback()
        raise
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--working-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
