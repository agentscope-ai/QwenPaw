---
name: cron
description: 通过 copaw 命令管理定时任务 - 创建、查询、暂停、恢复、删除任务
metadata: { "copaw": { "emoji": "⏰" } }
---

# 定时任务管理

使用 `copaw cron` 命令管理定时任务。

## 常用命令

```bash
# 列出所有任务
copaw cron list

# 查看任务详情
copaw cron get <job_id>

# 查看任务状态
copaw cron state <job_id>

# 删除任务
copaw cron delete <job_id>

# 暂停/恢复任务
copaw cron pause <job_id>
copaw cron resume <job_id>

# 立即执行一次
copaw cron run <job_id>
```

## 创建任务

支持两种任务类型：
- **text**：定时向频道发送固定消息
- **agent**：定时向 Agent 提问并发送回复到频道

### 快速创建

```bash
# 每天 9:00 发送文本消息
copaw cron create \
  --type text \
  --name "每日早安" \
  --cron "0 9 * * *" \
  --channel imessage \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "早上好！"

# 每 2 小时向 Agent 提问
copaw cron create \
  --type agent \
  --name "检查待办" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "我有什么待办事项？"
```

### 必填参数

创建任务需要：
- `--type`：任务类型（text 或 agent）
- `--name`：任务名称
- `--cron`：cron 表达式（如 `"0 9 * * *"` 表示每天 9:00）
- `--channel`：目标频道（console / feishu / dingtalk / discord / qq / telegram / imessage / matrix / mattermost 等）。用户未指定时，使用"当前的channel"的值
- `--target-user`：用户标识
- `--target-session`：会话标识
- `--text`：消息内容（text 类型）或提问内容（agent 类型）

### 从 JSON 创建（复杂配置）

```bash
copaw cron create -f job_spec.json
```

## Cron 表达式示例

```
0 9 * * *      # 每天 9:00
0 */2 * * *    # 每 2 小时
30 8 * * 1-5   # 工作日 8:30
0 0 * * 0      # 每周日零点
*/15 * * * *   # 每 15 分钟
```

## 使用建议

- 缺少参数时，询问用户补充后再创建
- 暂停/删除/恢复前，用 `copaw cron list` 查找 job_id
- 排查问题时，用 `copaw cron state <job_id>` 查看状态
- 给用户的命令要完整、可直接复制执行