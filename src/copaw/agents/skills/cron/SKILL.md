---
name: cron
description: Use this skill only for scheduled or recurring tasks. Manage cron jobs with copaw cron list/create/get/state/pause/resume/delete/run. Always pass --agent-id explicitly. | 仅在需要未来定时执行或周期执行时使用本 skill。用 copaw cron list/create/get/state/pause/resume/delete/run 管理任务；必须显式传 --agent-id
categories:
  - automation
  - scheduling
metadata:
  builtin_skill_version: "1.2"
  copaw:
    emoji: "⏰"
---

# Cron（定时任务管理）

## 什么时候用

只有在需要**未来某个时间自动执行**，或**按周期重复执行**时，使用本 skill。

### 应该使用
- 用户要求"每天 / 每周 / 每小时"执行某事
- 用户要求"明天 9 点 / 下周一 / 某个时间"自动提醒或执行
- 需要长期周期性通知、检查、汇报

### 不应使用
- 只是要**现在立即执行一次**
- 只是当前会话中的正常回复
- 用户没有明确执行时间或周期
- 目标 channel / user / session 还不明确

## 决策规则

1. **只有在未来定时执行或周期执行时才使用 cron**
2. **如果只是立即做一次，通常不要创建 cron**
3. **创建前必须确认执行时间/周期、目标 channel、target-user、target-session**
4. **所有 cron 命令都必须显式传 `--agent-id`**
5. **不要依赖默认 agent，否则任务可能落到 default workspace**

---

## 硬规则

### 必须显式指定 `--agent-id`

所有 `copaw cron` 命令都**必须**传：

```bash
--agent-id <your_agent_id>
```

你的 agent_id 在系统提示中的 Agent Identity 部分（Your agent id is ...）。  
不得省略，否则任务可能错误创建到 default agent 的 workspace。

---

## 常用命令

```bash
# 列出任务
copaw cron list --agent-id <agent_id>

# 查看任务详情
copaw cron get <job_id> --agent-id <agent_id>

# 查看任务状态
copaw cron state <job_id> --agent-id <agent_id>

# 创建任务
copaw cron create --agent-id <agent_id> ...

# 删除任务
copaw cron delete <job_id> --agent-id <agent_id>

# 暂停 / 恢复任务
copaw cron pause <job_id> --agent-id <agent_id>
copaw cron resume <job_id> --agent-id <agent_id>

# 立即执行一次已有任务
copaw cron run <job_id> --agent-id <agent_id>
```

---

## 创建任务

支持两种类型：
- **text**：定时发送固定消息
- **agent**：定时向 agent 提问，并把回复发送到目标 channel

### 创建前最少要确认
- `--type`
- `--name`
- `--cron`
- `--channel`
- `--target-user`
- `--target-session`
- `--text`
- `--agent-id`

如果缺少这些信息，应先向用户确认，再创建任务。

### 创建示例

```bash
copaw cron create \
  --agent-id <agent_id> \
  --type text \
  --name "每日早安" \
  --cron "0 9 * * *" \
  --channel imessage \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "早上好！"
```

```bash
copaw cron create \
  --agent-id <agent_id> \
  --type agent \
  --name "检查待办" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "我有什么待办事项？"
```

### 从 JSON 创建

```bash
copaw cron create --agent-id <agent_id> -f job_spec.json
```

---

## 最小工作流

```
1. 判断是否真的是"未来定时"或"周期执行"
2. 确认执行时间/周期
3. 确认 channel、target-user、target-session
4. 显式带上 --agent-id
5. copaw cron create 创建任务
6. 后续用 list / state / pause / resume / delete 管理
```

---

## Cron 表达式示例

```
0 9 * * *      每天 9:00
0 */2 * * *    每 2 小时
30 8 * * 1-5   工作日 8:30
0 0 * * 0      每周日零点
*/15 * * * *   每 15 分钟
```

---

## 常见错误

### 错误 1：把一次性立即执行当成 cron

如果只是现在执行一次，通常不要创建 cron。

### 错误 2：没传 --agent-id

这会导致任务落到错误的 agent / workspace。所有 cron 命令都必须显式传 `--agent-id`。

### 错误 3：信息没补全就创建

如果用户没说明时间、周期、目标 channel 或目标 session，应先追问。

### 错误 4：操作已有任务前不先查

暂停、恢复、删除前，先用：

```bash
copaw cron list --agent-id <agent_id>
```

找到正确的 `job_id`。

---

## 使用建议

- 缺少参数时，先问用户再创建
- 修改/暂停/删除前，先 `copaw cron list --agent-id <agent_id>`
- 排查问题时，用 `copaw cron state <job_id> --agent-id <agent_id>`
- 给用户展示命令时，提供完整、可直接复制的版本

---

## 帮助信息

```bash
copaw cron -h
copaw cron list -h
copaw cron create -h
copaw cron get -h
copaw cron state -h
copaw cron pause -h
copaw cron resume -h
copaw cron delete -h
copaw cron run -h
```
