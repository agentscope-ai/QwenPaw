# Task 4.5-C/1-H 根 MEMORY.md 索引与自动记忆检索默认值设计

日期：2026-08-28  
状态：设计已口头确认，等待书面规格确认

## 1. 目标

完成 Task 4.5-C/1 的最后两个运行边界：

1. 新建 Agent 在未显式配置时默认启用自动记忆检索；已有 Agent 明确保存的 `false` 必须继续保持关闭。
2. Agent 工作区根目录的 `MEMORY.md` 必须进入对应 ReMe 运行时的索引与检索，但不能把 `AGENTS.md`、`SOUL.md`、`PROFILE.md` 等工作区配置文件误纳入长期记忆。

## 2. 不在本任务范围

- 不修改 Agent Loop、Goal、Mission、Rubric 或 Doom Loop 行为。
- 不修改数据库结构或迁移现有记忆正文到 PostgreSQL。
- 不移动、复制或改写既有 `MEMORY.md`、`memory/`、`digest/` 文件。
- 不改变共享/仅使用 Agent 的文件写权限矩阵。
- 不强制覆盖已有 Agent 明确保存的自动记忆检索开关。

## 3. 设计选择

采用“单文件桥接索引”，不采用复制文件或监听整个工作区。

### 3.1 自动记忆检索默认值

- `AutoMemorySearchConfig.enabled` 的模型默认值改为 `true`。
- 只影响缺少该字段的新配置或旧配置补默认值的场景。
- 已有 `agent.json` 中明确存在 `enabled: false` 时，Pydantic 解析后仍为 `false`。
- 前端继续展示并保存真实配置值，不增加前端强制覆盖逻辑。

### 3.2 根 MEMORY.md 单文件桥接

ReMe 0.4.1.5 的 `watch_dirs` 只能表达目录规则，不能直接表达单文件白名单。直接监听工作区根目录会把其他 Markdown 一起纳入索引，因此 QwenPaw 增加一个职责单一的兼容 Step：

- Step 只检查 `<workspace>/MEMORY.md`。
- 文件存在时，将其作为 ReMe `file_store` 的受控变更输入。
- 文件修改或删除时，同步更新或移除对应索引节点。
- 文件不存在时不创建空文件，也不报错。
- 原文件仍是唯一事实来源；桥接层只产生索引状态，不复制正文文件。

桥接 Step 由以下任务调用：

- ReMe 启动时的初始索引；
- 手动 `reindex`；
- 后台监听任务检测根 `MEMORY.md` 的变化。

若 ReMe 的现有变更处理接口无法安全接收单文件事件，则实现最小的 QwenPaw 后台监听器，仅监听这一条绝对路径并复用 ReMe 的索引更新 Step；禁止退化为扫描整个根目录。

## 4. 公共与个人作用域

- 公共 ReMe 的 `<workspace>/MEMORY.md` 属于 Agent 公共记忆。
- 用户私有 ReMe 的 `<private-workspace>/MEMORY.md` 属于该用户在该 Agent 下的私有记忆。
- 普通对话继续通过 `ScopedMemoryManagerView` 并行查询公共与当前用户私有 ReMe，再按得分合并。
- API、工具参数和浏览器请求都不能传入任意用户 ID；身份继续来自服务端可信请求上下文。
- 管理员代管只能访问公共 ReMe，不得获得任何用户的私有 `MEMORY.md` 或私有索引。

## 5. 数据流

```text
公共根 MEMORY.md ──→ 公共 ReMe 单文件桥接 ──→ 公共索引 ─┐
                                                        ├─→ 合并检索 → 模型临时上下文
个人根 MEMORY.md ──→ 个人 ReMe 单文件桥接 ──→ 私有索引 ─┘

新 Agent/缺省配置 ──→ auto_memory_search.enabled=true
已有 enabled=false ──→ 保持 false
```

## 6. 失败处理

- 根 `MEMORY.md` 读取失败：记录明确错误，不能回退到扫描工作区全部 Markdown。
- 单文件桥接初始化失败：ReMe 启动失败必须按 C/1-G 的机制向 Workspace 暴露，不得静默假成功。
- 公共或个人其中一侧检索失败：保留现有局部降级，返回另一侧结果；两侧都失败时明确返回不可用。
- 重建索引失败：不删除或改写 Markdown，保持现有索引失败状态与重试入口。

## 7. 测试与验收

按 TDD 实施，至少覆盖：

1. `AutoMemorySearchConfig()` 默认 `enabled=true`。
2. 显式 `enabled=false` 往返后仍为 `false`。
3. ReMe 配置只额外纳入根 `MEMORY.md`，不会索引根目录其他 Markdown。
4. 创建、修改、删除根 `MEMORY.md` 后，索引与搜索结果同步变化。
5. 公共根 `MEMORY.md` 与两个用户私有根 `MEMORY.md` 分属三个独立索引。
6. 用户 A 的合并检索只包含公共+A，不包含用户 B。
7. 管理员代管不能访问用户私有根 `MEMORY.md`。
8. 原有 `memory/`、`digest/`、`/memorize`、`/dream`、`/reme_status` 和文件权限回归通过。

页面验收：

- 新建 Agent 后，运行配置页面显示自动记忆检索默认开启。
- 明确关闭、保存、刷新后仍保持关闭。
- 在公共或“我的记忆”对应根 `MEMORY.md` 写入唯一关键词，重建索引后可通过对话 `memory_search` 检索到正确作用域。
- 使用另一个用户检索相同关键词时看不到前一个用户的私有内容。

## 8. 工程约束

- KISS：只桥接一个固定文件，不引入通用文件匹配 DSL。
- YAGNI：不扩展为任意根文件索引配置。
- DRY：复用现有 ReMe 变更处理、作用域解析和合并检索。
- SOLID：默认值、单文件变更发现、ReMe 索引更新、请求作用域继续分离职责。
- 不执行 Git commit、push 或分支操作。

## 9. 完成门

自动化、真实 ReMe 生命周期、双用户隔离和页面验收全部通过后，生成 Task 4.5-C/1-H 验收报告并停止等待确认；确认后才进入 Task 4.5-C/2 Agent Loop 真实运行效果验收。
