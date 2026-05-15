# -*- coding: utf-8 -*-
"""Shared constants for CloudPaw plugin."""

import sys
from pathlib import Path
from typing import Any

PLUGIN_DIR = Path(__file__).parent

_plugin_dir_str = str(PLUGIN_DIR)
if _plugin_dir_str not in sys.path:
    sys.path.insert(0, _plugin_dir_str)

BUILTIN_ORCHESTRATION_AGENT_ID = "cloud-orchestrator"
BUILTIN_EXECUTOR_AGENT_ID = "cloud-executor"
BUILTIN_VERIFIER_AGENT_ID = "cloud-verifier"

_PLUGIN_SKILLS = [
    "alicloud_cli",
    "terraform-cli-setup",
    "terraform-skill",
]

_DISABLED_AGENT_TOOLS: dict[str, dict[str, Any]] = {
    "chat_with_agent": {
        "name": "chat_with_agent",
        "enabled": False,
        "description": "Send a message to another configured agent",
        "icon": "💬",
    },
}

_AGENT_SPECS: list[dict[str, Any]] = [
    {
        "agent_id": BUILTIN_ORCHESTRATION_AGENT_ID,
        "name": "CloudPaw-Master",
        "description": (
            "主控编排 Agent：负责与用户对话、澄清需求、编排多 Agent 工作流、汇总与回传执行结果；"
            "通过 ACP 协议直接调用 iac-code 引擎完成 IaC 模板生成、费用估算与资源栈管理。"
        ),
        "persona_pack": "orchestration",
        "skill_names": sorted(
            [
                "multi_agent_collaboration",
                "file_reader",
            ],
        ),
        "extra_tools": {
            "proposal_choice": {
                "name": "proposal_choice",
                "enabled": True,
                "description": "展示资源部署方案供用户确认或调整",
                "icon": "☁️",
            },
            "manage_prd": {
                "name": "manage_prd",
                "enabled": True,
                "description": (
                    "操作 PRD stories：" "create/add/update/delete/mark_passed"
                ),
                "icon": "📋",
            },
            "delegate_external_agent": {
                "name": "delegate_external_agent",
                "enabled": True,
                "async_execution": True,
                "description": "异步调用外部 ACP Runner（iac-code），后台执行并返回 task_id",
                "icon": "⚡",
            },
            "a2a_list": {
                "name": "a2a_list",
                "enabled": True,
                "description": "列出当前智能体已注册的远程 A2A Agent",
                "icon": "🔍",
            },
            "a2a_call": {
                "name": "a2a_call",
                "enabled": True,
                "description": "向远程 A2A Agent 发送消息并获取响应",
                "icon": "🤖",
            },
            **_DISABLED_AGENT_TOOLS,
        },
        "running_overrides": {
            "auto_continue_on_text_only": False,
            "max_iters": 2000,
        },
        "acp_agent": {
            "name": "iac-code",
            "command": "iac-code",
            "args": ["acp"],
            "env": {},
            "trusted": True,
            "tool_parse_mode": "call_detail",
        },
    },
    {
        "agent_id": BUILTIN_EXECUTOR_AGENT_ID,
        "name": "CloudPaw-Executor",
        "description": (
            "CloudPaw-Executor：承接主控委派的具体执行类任务，涵盖应用"
            "代码编写与部署、环境配置、云资源 CLI 操作、脚本执行、文件处理"
            "以及必要的 Web 自动化操作。"
        ),
        "persona_pack": "executor",
        "skill_names": sorted(
            [
                "alicloud_cli",
                "file_reader",
                "browser_cdp",
            ],
        ),
        "extra_tools": {
            **_DISABLED_AGENT_TOOLS,
        },
    },
    {
        "agent_id": BUILTIN_VERIFIER_AGENT_ID,
        "name": "CloudPaw-Verifier",
        "description": (
            "验证 Agent：面向 Mission 流程中的每个 story 提供统一的验证能力，"
            "覆盖云资源部署、应用功能、访问性与安全合规等各类验证需求，"
            "只产出验证结论，不修改任何资源与应用。"
        ),
        "persona_pack": "verifier",
        "skill_names": sorted(
            [
                "alicloud_cli",
                "file_reader",
                "browser_cdp",
            ],
        ),
        "extra_tools": {
            **_DISABLED_AGENT_TOOLS,
        },
    },
]
