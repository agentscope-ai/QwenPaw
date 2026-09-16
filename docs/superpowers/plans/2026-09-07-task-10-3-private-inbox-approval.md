# Task 10.3 私人通知与审批隔离实施计划

## Task 1：建立 PostgreSQL 收件箱 Repository

- [x] 为通知、回执建立最小 Repository 和数据映射。
- [x] 覆盖写入、分页、筛选、未读、全部已读和软删除测试。
- [x] 保持 Legacy JSON 契约。

## Task 2：收紧 API 和 Trace 授权

- [x] 多用户 API 强制绑定当前 Actor。
- [x] 增加事务化批量删除接口。
- [x] Trace 读取验证当前用户的通知引用。
- [x] 删除个人通知不删除 Trace/Run/审计。

## Task 3：持久化审批事实

- [x] 创建审批时记录指定审批用户和脱敏参数。
- [x] 批准、拒绝、超时同步状态。
- [x] 验证管理员不能代批普通用户审批。

## Task 4：前端批量操作与隔离回归

- [x] 前端使用批量删除 API，并按服务端结果刷新。
- [x] 覆盖全部已读、筛选、审批和 Trace 原功能。
- [x] 通过 TypeScript、前端测试和后端相关回归。

## Task 5：真实 PostgreSQL 与浏览器验收

- [x] 在隔离 schema 运行迁移链和 Repository/API 测试。
- [x] 单 Chromium 双 BrowserContext 验证不同未读数、通知和审批。
- [x] 核验原服务、原数据库和旧 JSON 未被测试修改。
- [x] 整理验收报告，等待下一确认门。
