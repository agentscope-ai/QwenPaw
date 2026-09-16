# Task 4.5-B/4 验收记录：记忆、ADBPG 与 Embedding 配置保真

## 实现范围

- 管理员代管运行配置时，ReMe 状态轮询、记忆重建和 Embedding 验证统一携带目标 Agent 请求上下文。
- 后端为 Embedding 验证和记忆维护增加显式治理目标解析；目标不一致时拒绝请求。
- ADBPG 未配置时由卡片初始化完整默认对象，包含 REST 地址、密钥、隔离开关、超时和自动搜索嵌套配置。
- ADBPG `search_timeout` 后端限制为至少 1 秒。
- Embedding 运行时失败保持已有局部回滚、并发无关字段保留、同字段冲突和 `needs_reindex` 语义。
- 普通未治理请求的 API 调用形态保持不变，不额外传递 `undefined` 选项。
- 未修改数据库结构，也未把运行配置迁移到 PostgreSQL。

## 自动化验证

- 前端聚焦测试：7 个测试文件、64 个测试通过。
- 后端聚焦测试：83 个测试通过。
- TypeScript：`npx tsc -b --noEmit` 通过。
- 生产构建：`npm run build` 通过，Monaco CSS 校验通过。

## 真实页面验收

- 管理员代管 `task41-member-agent` 时页面显示目标 Agent 标识，侧边栏仍选中 `default`。
- ReMe 长期记忆卡片和 Embedding 模型卡片可正常打开。
- 浏览器请求已确认带有：
  - `X-Agent-Id: task41-member-agent`
  - `X-Agent-Governance: runtime-config`
- 直接治理请求结果：记忆运行状态返回 `503`（目标 Agent 当前记忆运行时不可用，权限已通过）；Embedding 测试请求返回 `200`。
- 切换 ADBPG 标签后显示完整默认字段，搜索超时为 `10` 秒；切换仅发生在表单内，未提交保存。
- 目标 Agent 和侧边栏 Agent 的运行配置前后快照均未变化。
- 页面截图：
  - `tmp/task-2-1-acceptance/task-4-5-b4-reme-governance.png`
  - `tmp/task-2-1-acceptance/task-4-5-b4-embedding-governance.png`
  - `tmp/task-2-1-acceptance/task-4-5-b4-adbpg-defaults.png`

## 非阻塞警告

- 测试环境仍有既有的 Ant Design `InputNumber addonAfter` 弃用提示，以及 jsdom 的 `getComputedStyle` 提示；不影响测试结果。
- 记忆运行状态返回 503 是当前验收实例没有可用 ReMe 运行时，不是治理权限错误。
