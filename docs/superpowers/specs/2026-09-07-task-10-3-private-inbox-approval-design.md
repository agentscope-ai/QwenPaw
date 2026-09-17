# Task 10.3 私人通知与审批隔离设计

## 目标

在多用户模式下，将收件箱通知、用户回执和审批事实落入既有 PostgreSQL 表，确保查看、未读统计、全部已读、批量删除、Trace 和审批都以当前登录用户为边界。Legacy 单用户模式保留现有 JSON 行为。

## 已确认方案

采用既有 `notifications`、`notification_receipts`、`approval_requests` 表，不新增数据库结构。

- `notifications` 保存通知事实与明确的 `recipient_user_id`。
- `notification_receipts` 保存该收件人的 `read_at`、`deleted_at`；删除通知只软删除回执。
- `approval_requests` 保存审批人和决定状态；运行时 Future 仍由现有 `ApprovalService` 管理。
- 多用户 API 从认证上下文取得用户 ID，忽略客户端传入或管理员角色推导出的其他用户身份。
- Legacy 模式继续使用 `inbox_events.json`，保持原部署兼容性。

## 通知写入与读取

`inbox_store` 提供统一入口，内部按运行模式选择 PostgreSQL 或 JSON。多用户写入必须提供合法 UUID 收件人；缺少收件人时拒绝写入，避免产生全局广播通知。

PostgreSQL 写入在同一事务内创建通知和收件人回执。查询始终限定 `notifications.recipient_user_id = 当前用户` 且 `notification_receipts.user_id = 当前用户`，排除 `deleted_at` 非空记录。筛选、总数和未读数使用同一条件，避免页面数字与列表不一致。

已有字段中 `agent_id`、`source_id` 可能是 Legacy 字符串，而表字段为 UUID。可解析 UUID 的值写入结构列；原始字符串和业务 payload 一并编码进 `payload_ref`，读取时恢复原 API 契约。

## 已读、批量删除与 Trace

- 单条和全部已读只更新当前用户的回执。
- 新增批量删除接口，一次事务软删除当前用户选中的回执；不存在或属于他人的 ID 不计入删除数。
- 删除通知不删除通知事实、Trace、Run 或审计记录。
- Trace 读取先检查当前用户仍有一条未删除通知引用该 `run_id`，否则统一返回 404。
- Legacy 模式保留原单条删除兼容行为，但多用户模式不再调用 `delete_trace`。

## 审批

创建审批时以服务端上下文写入 `approval_user_id`。审批列表、批准和拒绝继续先校验该字段，再校验会话写权限。管理员只因管理员角色不会获得代批能力。

审批表保存脱敏后的工具参数、状态、创建/决定时间；内存 Future 是正在执行进程的控制信号，数据库记录是持久事实。进程重启后遗留的 pending 记录不能恢复执行，启动或查询时按过期规则处理，不自动批准。

## 管理员治理告警

管理员个人收件箱与平台治理告警保持两个资源边界。本任务不把无收件人的旧通知广播给管理员，也不把治理告警注入个人收件箱。平台治理视图继续读取审计/治理数据；管理员查看自己的收件箱时与普通用户使用相同 recipient 过滤。

## 前端

保留现有收件箱标签、筛选、全部已读、审批和 Trace 交互。批量删除改为一次 API 请求，并以服务端返回的实际删除数刷新列表；失败时重新加载，避免 `Promise.allSettled` 导致部分失败却全部从本地消失。

## 验收

1. 两个用户各有不同通知和未读数，筛选、全部已读和批量删除互不影响。
2. 用户不能通过通知 ID 或 `run_id` 读取他人的通知或 Trace。
3. 删除通知后 Trace、Run、审计和其他用户数据仍存在。
4. 普通用户只能处理分配给自己的审批；管理员也不能代批普通用户审批。
5. 单个无头 Chromium 使用两个隔离 BrowserContext 完成页面验收，无需打开多个浏览器进程。

