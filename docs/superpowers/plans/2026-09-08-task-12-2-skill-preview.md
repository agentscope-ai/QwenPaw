# Task 12.2 技能领域迁移报告

## 范围

- 遗留源：`tmp/task-2-1-acceptance/working/workspaces/*/skill.json` 和对应 `skills/*` 目录
- 目标库：`qwenpaw_test_migrations`
- 目标 schema：`qwenpaw_task21_acceptance`
- 目标表：`agent_skills`
- 执行顺序：5（身份、智能体、会话、消息之后）

技能关系迁移已经执行，并完成幂等、数据库事实和双角色页面复核。

## 迁移规则

1. 只迁移 manifest 中存在且对应目录包含 `SKILL.md` 的 Agent 私有技能关系。
2. 复用已迁移 Agent 的稳定标识；目标 Agent 不存在时拒绝该技能。
3. 保留 manifest 的启用状态、配置、脱离状态及有效技能池版本引用。
4. 目标已有同名技能关系时逐字段比较；完全一致计为未变化，存在差异则保留数据库治理状态。
5. 配置中的敏感键只保存逻辑 Secret 引用，不迁移明文。
6. 技能文件已经位于当前工作目录，本阶段只登记 PostgreSQL 关系，不复制、移动或删除技能目录。

## 只读预演结果

| 指标 | 数量 |
| --- | ---: |
| 遗留 Agent 技能关系 | 20 |
| 当前目标关系 | 3 |
| 实际新增关系 | 17 |
| 完全一致关系 | 0 |
| 目标治理状态冲突 | 3 |
| 缺失目标 Agent | 0 |
| 缺失技能池版本 | 0 |
| 明文敏感配置字段 | 0 |
| 迁移后目标关系 | 20 |

三个冲突均属于 `user-agent` 的既有 Task 7.2 验收技能，差异为运行配置或启用状态。迁移器会保留 PostgreSQL 中已有值。

遗留源哈希：

`sha256:f5a3b37b79da044ea78949a73ab45912b1d265e1a9373564f385f73b4f43acdd`

目标迁移前哈希：

`sha256:988aef287e6111aac70123e207ddb97d77ffa8b644d40085cf2db2d9da28a440`

预演明细保存在 `tmp/task122-skill-preview.json`。

## 备份

- 目录：`tmp/task122-skill-backup-20260908-202554`
- 文件：`agent_skills.sql`
- 大小：1620 字节
- SHA-256：`4ea455522a0363bc702e73f12a003e59c49122d0b4d32ea2566926c3ddc0b38b`

## 验证

- 技能迁移专项集成测试：2 项通过。
- 分领域迁移全套集成测试：12 项通过。
- 已覆盖首次补录、重复执行幂等及既有治理状态冲突保护。
- Python `compileall` 通过。
- pytest 在 Windows Proactor 事件循环关闭时仍打印已知访问异常信息，但进程退出码为 0，全部断言通过。

## 迁移结果

- 首次执行：新增 17、更新 0、删除 0、冲突保留 3。
- 幂等复核：新增 0、未变化 17、冲突保留 3。
- 迁移后共 20 条 Agent 技能关系，其中启用 15、脱离 3。
- 目标哈希：`sha256:c7dd801e65ca9fa411739078ab7a25a64b1e6ab92472adaa939a09044420f5b4`。
- 执行结果：`tmp/task122-skill-migration-result.json`。

## 页面复核

- 管理员选择默认智能体后，技能页正常显示已启用的 `docx` 和 `imagegen`，并保留管理入口。
- 普通用户选择默认智能体后看到相同的两个可用技能，页面明确显示“只读”，不能修改公用 Agent 的技能。
- 截图：`tmp/task122-skill-admin.png`、`tmp/task122-skill-user.png`。
- 验收使用一个无头 Chromium，会话结束后已关闭。

## 实际写入影响

本次只向 `agent_skills` 新增 17 行。没有更新或删除原有 3 行，没有修改技能池条目、版本、授权或发布审核记录，也没有更改技能文件。
