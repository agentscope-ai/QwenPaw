# Airport SMS Agent

企业级机场集团安全管理体系（SMS）Agent。基于 AgentScope，分层参考 QwenPaw，主数据是案件状态机而不是个人聊天 JSON。

## AIA 支柱

### 指令与上下文

角色职责、场站规则、手册条款进入系统提示。实现落在后续 `context` 与 `runtime` 相关模块。当前占位目录是 `memory` 与 `runtime`。

### 状态与记忆

案件状态与多用户会话是系统真源。模块目录是 `domain`、`session`、`memory`。

### 计划与任务

整改计划与超期调度进入同一命令总线。后续落在任务与调度模块。当前由 `runtime` 承接入口。

### 能力

工具描述符与角色白名单。模块目录是 `tools`。

### 资产执行环境

证据资产与受限执行。后续 `execenv`。当前由 `api` 健康检查证明包可导入。

### 控制和交互

治理闸、审批、控制台与通道。模块目录是 `governance`、`channels`、`api`。

### 质量和反馈

观测、评估与人工纠正回流。模块目录是 `obs`。

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

需要 AgentScope 运行时时再装 `packages/airport_sms[runtime]`。钉扎与 QwenPaw 主仓一致，当前为 `agentscope[model-ollama,classifier-jev]==2.0.10`。脚手架默认依赖为空，避免在无网或超时环境里装不下包。

Python 要求 `>=3.11,<3.14`。
