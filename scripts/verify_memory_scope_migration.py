# -*- coding: utf-8 -*-
"""执行并输出旧记忆公共作用域迁移的可核验摘要。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qwenpaw.config.config import load_agent_config, save_agent_config
from qwenpaw.config.utils import load_config
from qwenpaw.constant import WORKING_DIR
from qwenpaw.migrations.memory_scope_migration import (
    MEMORY_SCOPE_MANIFEST,
    migrate_legacy_memory_scopes,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="登记旧 Agent Markdown 为公共记忆并验证幂等性",
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        default=Path(WORKING_DIR),
        help="QwenPaw 工作目录；默认使用当前配置",
    )
    args = parser.parse_args()
    working_dir = args.working_dir.expanduser().resolve()
    config = load_config()
    workspaces = {
        agent_id: Path(reference.workspace_dir).expanduser()
        for agent_id, reference in config.agents.profiles.items()
    }
    first = migrate_legacy_memory_scopes(
        working_dir=working_dir,
        agent_workspaces=workspaces,
        load_agent=load_agent_config,
        save_agent=save_agent_config,
    )
    second = migrate_legacy_memory_scopes(
        working_dir=working_dir,
        agent_workspaces=workspaces,
        load_agent=load_agent_config,
        save_agent=save_agent_config,
    )
    payload = {
        "working_dir": str(working_dir),
        "manifest": str(working_dir / MEMORY_SCOPE_MANIFEST),
        "first_run": {
            "changed": first.changed,
            "registered_agents": first.registered_agents,
            "registered_files": first.registered_files,
        },
        "idempotent_second_run": not second.changed,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not second.changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
