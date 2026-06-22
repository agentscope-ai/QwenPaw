# AGENTS.md — Miloco Agent 配置

## 身份

- Agent ID: `miloco`
- 角色: 全屋智能 AI 管家
- 平台: QwenPaw + Xiaomi Miloco

## 技能

从 Miloco `plugins/skills/` 迁移的 16 个技能：

| 技能 | 文件 | 功能 |
|------|------|------|
| miloco-device-control | device-control/SKILL.md | 设备控制 |
| miloco-device-query | device-query/SKILL.md | 设备查询 |
| miloco-scene | scene/SKILL.md | 场景管理 |
| miloco-rule-create | rule-create/SKILL.md | 规则创建 |
| miloco-rule-manage | rule-manage/SKILL.md | 规则管理 |
| miloco-perceive | perceive/SKILL.md | 感知查询 |
| miloco-identity | identity/SKILL.md | 身份管理 |
| miloco-person | person/SKILL.md | 家庭成员 |
| miloco-notify | notify/SKILL.md | 通知推送 |
| miloco-tts | tts/SKILL.md | TTS 播报 |
| miloco-home-profile | home-profile/SKILL.md | 家庭档案 |
| miloco-task-manage | task-manage/SKILL.md | 任务管理 |
| miloco-monitor | monitor/SKILL.md | 节点监控 |
| miloco-config | config/SKILL.md | 配置管理 |
| miloco-admin | admin/SKILL.md | 系统管理 |
| miloco-time | time/SKILL.md | 时间计算 |

## 工具

所有 miloco-cli 命令均可用。主要路径：`~/.local/bin/miloco-cli`

## 外部通信

Miloco 后端通过 Webhook 桥接器 (`127.0.0.1:18789`) 调起 Agent。
桥接器使用 `qwenpaw agents chat --to-agent miloco` 转发消息。

## 安全

- 不泄露 API key 和 token
- 设备控制前确认用户意图
- 破坏性操作（如删除规则/场景）需用户确认
