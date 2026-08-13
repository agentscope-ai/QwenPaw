# 记忆自进化与主动交互（Beta）

> 本文重点介绍 Auto-Memory、Auto-Dream、Auto-Memory-Search 与 Proactive 如何协作。记忆目录、文件格式、索引原理和完整配置请参见[长期记忆](./memory)。

上周，你告诉 QwenPaw：“生产发布前先验证 staging，发布说明要写清风险和回滚步骤。”几天后，团队又补充了一条例外：“紧急 hotfix 经负责人批准，可以先发布，但事后必须补做检查。”

如果系统只会保存聊天记录，这两句话只会散落在两次对话里。真正有用的长期记忆需要做得更多：先保留当时发生了什么，再判断新信息是重复确认、补充细节，还是修正旧结论，最后在下一次发布时找回已经整理好的流程。

QwenPaw 用一条连续的链路完成这件事：

1. **Auto-Memory** 从对话中提取值得以后继续使用的信息，写成每日记忆；
2. **Auto-Dream** 把不同日期的证据整合成可持续更新的长期知识；
3. **Memory Search** 在新问题出现时，只召回相关内容和它的关联证据；
4. **Proactive** 在用户明确开启后，根据近期活动判断是否值得提前提供帮助。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg" alt="QwenPaw 长期记忆从捕获、整理到检索与发现的全景" />
</p>

这里有两条相关但尚未完全打通的闭环：记忆进化依靠 `memory/`、`digest/` 和检索；当前 `/proactive` 则读取近期 session 和可选的屏幕上下文，**不会直接读取** Auto-Dream 生成的 `interests.yaml` 或 `digest/`。

## 第一步：把对话变成可靠素材

Auto-Memory 不是把整段聊天换一种格式保存，而是挑出未来仍可能有用的信息，例如：

- 稳定偏好与长期约定；
- 项目背景、限制条件和关键事实；
- 已确认的决定、原因和例外；
- 当前进展、阻塞项和下一步；
- 可以复用的流程与排查经验。

默认每累计 5 个用户回合，Auto-Memory 会处理一批新对话。它会清理工具结果和大块 Base64 数据，把来源对话保存到 `mem_session/dialog/`，再创建或更新当天 `memory/YYYY-MM-DD/` 下的一条 Markdown 记忆。发生上下文淘汰或折叠时，尚未处理的回合也会提前进入同一条流程。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01Qg6uAk1VoeXMqbE54_!!6000000002700-55-tps-1200-640.svg" alt="Auto-Memory 把长对话提炼成可复用、可追溯的每日记忆" />
</p>

例如，一次发布讨论可能先变成：

```markdown
---
name: 生产发布约定
description: 生产发布前先验证 staging，中文发布说明需包含风险和回滚步骤。
source_conversation: "[[mem_session/dialog/qpsid_sha256_<64-hex>.jsonl]]"
---

- 生产发布前必须完成 staging 验证。
- 发布说明使用中文，并列出风险与回滚步骤。
```

这仍是“当天的证据”，还不是最终不变的结论。每日记忆保留现场，后续的 Auto-Dream 负责跨时间整理它。

## 第二步：让每日证据长成长期知识

一份静态记忆只能追加或检索。自进化记忆还会判断：**新证据会怎样改变已经知道的事情？**

Auto-Dream 默认每天运行，扫描目标日期及前一天发生变化的每日记忆。它先提取可复用的 `personal`、`procedure` 和 `wiki` 单元，再搜索 `digest/` 中可能相同或相关的节点，最后选择一种整合动作：

| 动作          | 它在做什么                 | 常见情况                             |
| ------------- | -------------------------- | ------------------------------------ |
| `CREATE`      | 创建新的长期节点           | 第一次出现的新偏好、流程、事实或原则 |
| `CORROBORATE` | 保留结论并补充支持证据     | 相同偏好或做法再次出现               |
| `REFINE`      | 增加范围、步骤、条件或例外 | 后续对话补齐了细节                   |
| `CORRECT`     | 修正过期、遗漏或冲突的结论 | 用户改变决定或纠正旧事实             |

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01DSVTuF1rEr7yobCav_!!6000000005600-55-tps-1200-640.svg" alt="Auto-Dream 把每日经验整合为带来源链接的长期知识" />
</p>

图中的 `CONFIRM` 是“增加支持证据”的视觉化简称；当前接口中的正式动作名称是 `CORROBORATE`。

Auto-Dream 不会改写每日记忆。`memory/` 始终保留当时发生的事情，`digest/` 则保存跨时间仍有用、并允许继续修正的结论。成功处理过的输入会记录在 dream catalog 中；失败的路径不会被标记完成，因此下次仍可重试。

### 一条发布流程如何越用越准确

沿用前面的例子，同一个长期节点可以经历四次变化：

| 时间     | 动作          | 新证据带来的变化                 |
| -------- | ------------- | -------------------------------- |
| 第 1 天  | `CREATE`      | 建立“生产前验证 staging”的流程   |
| 第 3 天  | `CORROBORATE` | 另一次发布再次确认这条规则       |
| 第 8 天  | `REFINE`      | 增加中文发布说明、风险和回滚步骤 |
| 第 20 天 | `CORRECT`     | 加入经批准的紧急 hotfix 例外     |

到第 20 天，`digest/procedure/production-release.md` 可能已经演化为：

```markdown
---
name: 生产发布流程
description: 常规发布必须验证 staging；紧急 hotfix 使用经批准的例外流程。
---

# 生产发布

## 常规流程

1. 在 staging 验证版本。
2. 使用中文编写发布说明，并列出风险和回滚步骤。
3. 验证通过后才能进入生产环境。

## 紧急 hotfix 例外

只有取得事故负责人批准后才可跳过完整 staging；必须记录原因，并在事后补做检查。

relates_to:: [[digest/personal/release-communication-preference.md]]
depends_on:: [[digest/procedure/rollback-verification.md]]

## Sources

- [[memory/2026-08-01/release-planning.md]]
- [[memory/2026-08-08/release-notes.md]]
- [[memory/2026-08-20/hotfix-retrospective.md]]
```

真正的变化不只是文字变多：重复信息增强了可信度，新细节被整理成可执行步骤，冲突变成了有适用范围的例外，而且每个结论仍能回到来源。

### Auto-Link 为什么重要

Auto-Link 不是独立任务，而是 Auto-Dream 整合阶段的一部分：

- `## Sources` 中的链接把长期结论连回每日证据；
- 正文中的 Wikilink 把相关的偏好、流程、项目与概念连接起来；
- 更新节点时保留已有来源和关系，不会因为纠错抹掉形成过程；
- 搜索命中一个节点后，可以按需沿入链和出链展开相关上下文。

因此，`digest/` 不是摘要堆积，而是一份可读、可追溯、会随新证据调整的个人知识库。

## 第三步：让进化后的记忆回到工作中

记忆经过整理后，还要在正确的时机被找回来。`memory_search` 会在 `memory/` 与 `digest/` 的 Markdown 中组合三种信号：

- **BM25** 找到函数名、错误码、项目名等精确关键词；
- **Vector** 在配置 Embedding 后找到措辞不同但语义相近的内容；
- **Wikilink** 从命中的文件展开来源、相关流程和相邻知识。

两路检索结果通过 RRF 融合。没有配置 Embedding 时，BM25 和 Wikilink 展开仍然可以正常工作。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01Zln7TK1TJOGqP84hk_!!6000000002361-55-tps-1200-640.svg" alt="BM25 与向量检索融合后按需展开相关记忆" />
</p>

Agent 可以在需要历史信息时主动调用 `memory_search`。启用 Auto-Memory-Search 后，每个普通用户请求都会先自动搜索，结果只注入当前请求的上下文，不写回正式会话历史，也不会再次进入 Auto-Memory，从而避免记忆复制自己。

例如，用户问“上线前要做哪些检查？”时，搜索可以同时找到 `staging`、语义相近的“生产发布验证”，以及与它相连的回滚流程和沟通偏好。Agent 得到的是当前问题需要的片段和路径，而不是全部历史。

## 从兴趣主题到主动交互

Auto-Dream 整理长期节点时，还会从近期证据中选择少量、不重复的兴趣主题，默认最多写入 3 个到 `memory/<date>/interests.yaml`。每个主题包含标题、原因、证据、关键词和相关路径，例如：

```yaml
- title: 验证紧急回滚流程
  reason: 已增加 hotfix 例外，但尚未记录事后补做的检查。
  evidence:
    - hotfix 复盘中讨论了跳过 staging 的情况。
  keywords: [hotfix, rollback, release]
  paths:
    - memory/2026-08-20/hotfix-retrospective.md
```

ReMe 提供底层 `proactive` job 读取这个文件，便于其他集成消费主题；文件不存在时会正常返回 skipped。Auto-Dream 完成后，整合结果和兴趣主题也可以推送到 Inbox，真正的内容仍保存在 `digest/` 与 `interests.yaml` 中。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream 的整合结果与兴趣主题摘要" />
</p>

### 当前 `/proactive` 如何工作

面向用户的 `/proactive` 是另一条运行时链路。明确开启后，它会等待 workspace 进入空闲状态，再根据近期聊天和可选的桌面截图推断 1–3 个可能有帮助的目标。它会为最多 3 个候选目标尝试具体查询，在第一次成功后停止，并把建议发回对话。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01bGrMQC1kGxdbG4IDT_!!6000000004657-55-tps-1200-640.svg" alt="主动模式根据近期信号发现下一步并在行动前询问用户" />
</p>

监控器每 30 秒检查一次。空闲时间取当前 workspace 所有聊天中最新的 `updated_at`，而不只看执行命令的那条聊天。达到阈值后，它读取最近 7 天更新过的 session；不足 5 个时回退到最新 5 个。输入最多包含 100 条近期非 system 文本消息，总长度不超过 50,000 字符。当前模型支持多模态输入时，还可能截取并分析桌面画面。

如果用户在任务执行期间重新活跃，本次任务会中断；上一条 `[PROACTIVE]` 消息尚未得到回应时，也不会继续发送新消息。监控配置只保存在进程内存中，重启后需要重新开启。

> **当前边界：** `/proactive` 的触发和任务推断来自近期 session 与可选屏幕，不会直接读取 `interests.yaml` 或 `digest/`。兴趣主题和面向用户的主动模式目前是两条独立路径。

### 隐私与安全

Proactive assistant 可以读取历史聊天；模型支持时可能截取桌面；它还会初始化带网页搜索/抓取、浏览器、文件读取、Shell 和可选截图工具的独立 assistant，并以 bypass 权限运行。`/proactive` 会显示相应警告。只在这些访问权限合适时开启，并可随时用 `/proactive off` 停止监控。

## 参数配置速查

下面只列出本页工作流直接相关的参数。它们位于 `agent.json` 的 `running.reme_light_memory_config`；目录、Embedding、Daily Paper 和索引维护参数请参见[长期记忆](./memory)。

```json
{
  "running": {
    "memory_manager_backend": "remelight",
    "reme_light_memory_config": {
      "auto_memory_interval": 5,
      "auto_memory_inbox_push_enabled": true,
      "dream_cron_enabled": true,
      "dream_cron": "0 23 * * *",
      "auto_dream_inbox_push_enabled": true,
      "memory_search_enabled": true,
      "auto_memory_search_config": {
        "enabled": false,
        "max_results": 2
      }
    }
  }
}
```

| 配置项                                  | 默认值         | 说明                                                               |
| --------------------------------------- | -------------- | ------------------------------------------------------------------ |
| `auto_memory_interval`                  | `5`            | 每累计 N 个用户回合运行 Auto-Memory；`null` 或 `<= 0` 关闭周期触发 |
| `auto_memory_inbox_push_enabled`        | `true`         | Auto-Memory 实际修改记忆后，将结果推送到 Inbox                     |
| `dream_cron_enabled`                    | `true`         | 是否定时运行 Auto-Dream                                            |
| `dream_cron`                            | `"0 23 * * *"` | 5 段 Cron 表达式；触发后随机延迟 0–60 秒启动                       |
| `auto_dream_inbox_push_enabled`         | `true`         | 将 Auto-Dream 的成功或失败摘要推送到 Inbox                         |
| `memory_search_enabled`                 | `true`         | 是否向 Agent 提供手动调用的 `memory_search` 工具                   |
| `auto_memory_search_config.enabled`     | `false`        | 是否在每个普通用户请求前自动搜索记忆                               |
| `auto_memory_search_config.max_results` | `2`            | 每次自动搜索最多注入的结果数                                       |

Auto-Memory 间隔越小，记忆更新越及时，但模型调用、Token 消耗和后台负担也越高。`memory_search_enabled` 与自动搜索开关彼此独立：关闭手动工具不会自动关闭 Auto-Memory-Search，反之亦然。

Auto-Dream 也可以随时手动运行：

```text
/dream             # 立即执行一次 Auto-Dream
/dream <提示信息>  # 带提示执行一次 Auto-Dream
```

Proactive 不使用 `agent.json` 参数，而是通过命令管理当前 Agent 的内存任务：

```text
/proactive           # 开启，默认空闲 30 分钟后触发
/proactive on        # 同上
/proactive 45        # 改为空闲 45 分钟后触发
/proactive off       # 停止主动监控
```

简而言之：Auto-Memory 保留可靠素材，Auto-Dream 让知识随证据进化，Memory Search 让新对话真正用上这些知识，而 `/proactive` 在用户明确授权后判断何时值得提前提供帮助。
