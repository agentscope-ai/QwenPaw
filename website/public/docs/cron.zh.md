# 定时任务

在 QwenPaw 里，「定时任务（cron job）」用于让系统在指定时间自动执行动作，比如：

- 工作时段每 25 分钟提醒起身喝水或远眺，减少疲劳。
- 工作日 9:30 自动整理当日热门科技资讯并推送简报。

和 [心跳](./heartbeat) 不同，定时任务支持**多条任务并行**，每条任务都可以独立配置执行时间、内容和投递目标。

---

## 循环任务 vs 日程任务

在实际使用里，定时任务通常有两种组织方式：

- **循环任务**：强调“每隔多久”执行一次，例如每 15 分钟、每 2 小时、每天 9:00。
- **日程任务**：强调“在什么日历时间点”执行，例如 2026 年 1 月 1 日 9:00。

两者底层都由统一调度器驱动：循环任务使用 Cron 表达式，日程任务使用指定起始时间与可选重复规则。你可以按业务习惯选择“间隔视角”或“日程视角”来配置任务。

常见循环任务示例：

![todo](https://img.alicdn.com/imgextra/i1/O1CN01KOSlHG1EBP6mzmTpr_!!6000000000313-2-tps-1734-936.png)

常见日程任务示例：

![todo](https://img.alicdn.com/imgextra/i3/O1CN01AJU7UV1G0zKh4JqRO_!!6000000000561-2-tps-1728-1266.png)

日程任务支持创建 **一次性任务/循环任务指定结束时间/循环任务指定结束次数**，详情见下方创建定时任务。

## 管理定时任务

**创建任务**

> 如果定时任务没有创建成功，可以参考 [FAQ](https://qwenpaw.agentscope.io/docs/faq) 的 **定时任务错误排查** 寻找原因

1. 点击 **创建任务** 按钮。

![todo](https://img.alicdn.com/imgextra/i2/O1CN01bJJo2e1LoydlqxGxu_!!6000000001347-2-tps-1190-1984.png)

2. 填写信息：
   - **基本信息** —— 给任务一个名称，并打开启用开关。
   - **运行结果是否入收件箱** —— 开启后，任务执行结果将自动落入收件箱中，点击可查看任务的执行轨迹。
   - **调度**
     - 调度类型选择 **循环任务**，可选择执行时间；如果选项不满足需求，可填写 **Cron 表达式**（五段式，如 `0 9 * * *` = 每天 9:00）。时区默认采用当前智能体的用户时区，可在此修改。
     - 调度类型选择 **日程任务**，可点击执行时间，以日历形式进行选择。
       - 当关闭 **重复执行** 按钮时，可以理解为创建了一次性任务，将在指定的执行时间只执行一次。
       - 当开启时，可选择 **重复频率** （每隔多少天）和 **结束条件**。
         - 选择 **无限重复**，该日程任务会一直按照执行时间和频率执行下去，此时更类似于循环任务执行方式。
         - 选择 **终止于某天**，并选择 **截止时间**，则在超过截止时间后，该日程任务不会再执行。
         - 选择 **限定次数**，并给定 **执行次数**， 则该日程任务在执行达到该次数后，不会再执行（不包括手动执行）。
   - **任务类型及内容**
     - 选择 **text**：发送**消息内容**中的固定文本
     - 选择**agent**：填写**请求内容**，会定时向QwenPaw转发content.text中的请求文本
   - **投递** —— 选择目标频道（如 Console、dingtalk）、目标用户ID、目标会话ID。支持直接下拉选择，选项与会话页面中存储的会话内容对应的 Channel - userID - SessionID 相匹配，同时也支持自定义输入。
   - **共用会话** —— 开启时，与目标用户共用会话。关闭时，循环任务将在独立的会话中运行，适用于不需要会话记忆历史的独立任务。
   - **高级选项** —— 按需调整最大并发数、超时时间和宽限时间。
3. 点 **保存**。

**查看任务执行记录：**
列表视图下，每行任务最右侧都有 **执行记录**，点击可查看该定时任务在什么时间，以什么方式（定时/手动），是否成功触发。

**启用 / 禁用任务：**
点击行内的开关即可。

**编辑任务：**
先**禁用**需要编辑的任务，点击 **编辑** 按钮 → 修改任意字段 → **保存**。

**立即执行一次：**
点击 **立即执行** → 确认，任务会马上运行一次。

**删除任务：**
先**禁用**需要删除的任务，点击 **删除** → 确认。

**日历视图:**
新增 **日历视图**，所有 **日程任务** 会按日期展示在日历中，方便快速查看当天安排与后续计划。点击任务可打开对应的**编辑任务**页面，方便对任务进行修改。

![todo](https://img.alicdn.com/imgextra/i4/O1CN01gMBL7O1MDFdAXkBDa_!!6000000001400-2-tps-2978-1662.png)

---

## 更多创建方式

### 方式一：对话创建

创建定时任务最简单的方式是直接与 QwenPaw 对话，让QwenPaw帮忙创建：

> 未来七天内，每天早上八点为我查询当天天气。

创建成功后，可以在控制台任务列表中看到该任务。

### 方式二：从模板创建

新增 **从模板创建** 功能，可以先选择 **循环任务** 或 **日程任务** 模板，再按需调整名称、触发时间和消息/请求内容后保存。默认投递到控制台的 cron_job session，UserID 默认为default，可自行修改为需要的投递目标。

![todo](https://img.alicdn.com/imgextra/i1/O1CN01KOSlHG1EBP6mzmTpr_!!6000000000313-2-tps-1734-936.png)

### 方式三：CLI

详见 CLI的 [qwenpaw cron](./cli#qwenpaw-cron) 章节。常用命令：

```bash
qwenpaw cron list
qwenpaw cron create ...
qwenpaw cron state <job_id>
qwenpaw cron run <job_id>
qwenpaw cron pause <job_id>
qwenpaw cron resume <job_id>
qwenpaw cron delete <job_id>
```

示例（每天 9 点发固定文本）：

```bash
qwenpaw cron create \
  --agent-id default \
  --type text \
  --schedule-type cron \
  --name "每日早安" \
  --cron "0 9 * * *" \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "你的会话ID" \
  --text "早上好，记得查看今天待办。"
```

示例（每 2 小时向 QwenPaw 询问并投递回复）：

```bash
qwenpaw cron create \
  --agent-id default \
  --type agent \
  --schedule-type cron \
  --name "待办巡检" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "你的会话ID" \
  --text "请检查我的待办，并输出优先级最高的三项。"
```

示例（日程一次性：只执行一次）：

```bash
qwenpaw cron create \
  --agent-id default \
  --type text \
  --schedule-type scheduled \
  --name "明早组会提醒" \
  --run-at "2026-05-13T09:00:00+08:00" \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "你的会话ID" \
  --text "9 点组会提醒" \
  --save-result-to-inbox
```

示例（日程重复：未来两周每天 9 点，共 14 次）：

```bash
qwenpaw cron create \
  --agent-id default \
  --type text \
  --schedule-type scheduled \
  --name "未来两周组会提醒" \
  --run-at "2026-05-13T09:00:00+08:00" \
  --repeat-every-days 1 \
  --repeat-end-type count \
  --repeat-count 14 \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "你的会话ID" \
  --text "9 点组会提醒" \
  --save-result-to-inbox
```

参数要点：

- `--schedule-type cron`：需要 `--cron`
- `--schedule-type scheduled`：需要 `--run-at`
- `scheduled` 重复任务：需要 `--repeat-every-days`，并搭配结束条件（`count/until/never`）
- 可选设置结果是否入收件箱：`--save-result-to-inbox` 或 `--no-save-result-to-inbox`

---

## Cron 表达式速查

QwenPaw 使用五段式 Cron：**分 时 日 月 周**（无秒）。

| 表达式         | 含义                   |
| -------------- | ---------------------- |
| `0 9 * * *`    | 每天 9:00              |
| `0 */2 * * *`  | 每 2 小时整点          |
| `30 8 * * 1-5` | 工作日 8:30            |
| `0 10 * * 1`   | 每周一 10:00           |
| `0 9 1 * *`    | 每月 1 号 9:00         |
| `0 18 31 12 *` | 每年 12 月 31 日 18:00 |
| `*/15 * * * *` | 每 15 分钟             |

---

## 相关页面

- [控制台](./console) — 在 Web 界面管理定时任务
- [CLI](./cli#qwenpaw-cron) — `qwenpaw cron` 命令详解
- [心跳](./heartbeat) — 固定周期自检/摘要
- [FAQ](./faq#定时任务错误排查) — 常见问题排查
- [配置与工作目录](./config) — `jobs.json` 与工作目录说明
