# Airport SMS Agent

企业级机场集团安全管理体系（SMS）Agent。基于 AgentScope，分层参考 QwenPaw，主数据是案件状态机而不是个人聊天 JSON。

## 业主模块（AIA + 运行面）

| 支柱 / 面 | 业主模块 |
| --- | --- |
| 指令与上下文 | `context` |
| 状态与记忆 | `domain` `session` `memory` |
| 计划与任务 | `tasks` |
| 能力 | `tools` |
| 资产执行环境 | `execenv` |
| 控制和交互 | `governance` `api` `channels` `web` |
| 质量和反馈 | `obs` |
| 会话 | `session` |
| 调度 | `tasks` |
| 模型网关 | `models` |
| 运行时 | `runtime` |

## 运维

见 `docs/runbook.md`（备份、密钥轮换、审批 SLA、手册更新、外部桥）。

冒烟：

```bash
python packages/airport_sms/scripts/smoke_e2e.py
```

配置模式版本见 `airport_sms.config.CONFIG_SCHEMA_VERSION`。`external_sms_bridge.enabled` 默认 `false`。

## 模型角色

| 角色 | 模型 | 用途 |
| --- | --- | --- |
| router | qwen2.5-1.5b | 意图路由与工具短名单 |
| worker | qwen3.8-27b | 日常 ReAct |
| judge | qwen3-235b | 高风险与关闭裁判，不执行工具 |
| retrieval | qwen3-embed | 手册与结案检索 |
| vision_text | paddleocr | 证据图片 OCR |
| speech | qwen3-asr | 现场语音转写 |

ASR 只配置一次。不要重复注册第二个 ASR 客户端。

## 开发

```bash
python -m pip install -e "packages/airport_sms[dev]"
pytest packages/airport_sms/tests -q
ruff check packages/airport_sms
```

需要 AgentScope 运行时时再装 `packages/airport_sms[runtime]`。钉扎与 QwenPaw 主仓一致，当前为 `agentscope[model-ollama,classifier-jev]==2.0.10`。

Python 要求 `>=3.11,<3.14`。
