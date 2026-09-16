# Task 12.2 消息领域迁移报告

## 范围

- 遗留源：`tmp/task-2-1-acceptance/working/workspaces/*/sessions/**/*.json`
- 目标库：`qwenpaw_test_migrations`
- 目标 schema：`qwenpaw_task21_acceptance`
- 目标表：`messages`
- 执行顺序：4（身份、智能体、会话之后）

消息迁移已经执行，并完成幂等、数据库事实和双角色页面复核。

## 迁移规则

1. 通过已有 `chats.json` 和运行时会话路径规则，将消息快照唯一映射到会话。
2. 只向当前没有任何消息的目标会话补录完整快照。
3. 目标会话已有消息时，整段保留 PostgreSQL 的丰富事件历史，不混合两套消息序列。
4. 遗留消息保存为 `legacy_snapshot`，原始结构保存在 `content`；不创建伪造的 run、run event 或 tool call。
5. 用户消息的 `created_by` 使用会话所有者；助手消息保持为空。
6. 消息标识发生跨会话冲突时拒绝该会话，不覆盖目标数据。

## 预演与实际结果

| 指标 | 数量 |
| --- | ---: |
| 遗留消息会话 | 45 |
| 遗留消息 | 158 |
| 可解析并唯一映射的会话 | 45 |
| 缺失目标会话 | 0 |
| 无效消息 | 0 |
| 当前为空、可补录的目标会话 | 16 |
| 实际新增消息 | 56 |
| 已有目标历史、将保留目标数据的会话 | 29 |
| 因目标历史冲突而拒绝的遗留消息 | 102 |
| 迁移前目标消息 | 320 |
| 迁移后目标消息 | 376 |
| 当前 runs | 57 |
| 当前 run events | 64180 |
| 当前 tool calls | 95 |

遗留源哈希：

`sha256:484cf9248d6c5fb33b307fbd243e25f929e583eef5168b6cce330be13ae904ed`

预演明细保存在 `tmp/task122-message-preview.json`。

## 备份

- 目录：`tmp/task122-message-backup-20260908-183858`
- 文件：`messages.sql`
- 大小：846556 字节
- SHA-256：`1bd70bfb81a003b6197a5f44ade52a5953fe1bcd0d2c5a78f9e71cbad2072f2d`

## 验证

- 消息迁移专项集成测试：2 项通过。
- 分领域迁移全套集成测试：10 项通过。
- 已覆盖首次导入、重复执行幂等和目标历史冲突保护。
- pytest 在 Windows Proactor 事件循环关闭时打印访问异常信息，但测试进程退出码为 0，全部断言通过。

## 迁移结果

- 首次有效提交：新增 56、更新 0、删除 0。
- 幂等复核：新增 0、未变化 56、冲突会话 29。
- 迁移后 `legacy_snapshot`：56 条。
- 目标消息哈希：`sha256:5aebb301402b2ddf6ca9e090aec54ece2c51d65d816680e2e0f5ee96ec892671`。
- `runs` 保持 57、`run_events` 保持 64180、`tool_calls` 保持 95。
- 执行结果：`tmp/task122-message-migration-result.json`。

遗留时间戳允许不带时区。迁移器按服务本地时区解释后统一转为 UTC，保证 JSONB 写入后的重复执行能识别为未变化。

## 页面复核

- 管理员：迁移会话可直接打开，用户消息、Assistant 回复、Thinking 和工具过程完整回放。
- 普通用户：默认智能体迁移会话可直接打开，两条消息和时间正常显示。
- 页面截图：`tmp/task122-message-admin.png`、`tmp/task122-message-user-default.png`。
- 另一个属于用户自建 Agent 的旧会话可以回放消息，但模型和项目目录辅助接口返回 `Chat not found`；这是会话运行元数据仍由后续领域处理造成的提示，不影响本次消息行完整性。默认智能体路径没有该提示。
- 页面验证只使用一个无头 Chromium，会话结束后已经关闭。

## 实际写入影响

本次只向 `messages` 表新增 56 行。没有更新或删除原有 320 条消息，也没有修改 `runs`、`run_events`、`tool_calls`。29 个存在目标历史的会话输出明确冲突报告并保持原值。
