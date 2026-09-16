# Task 9.1 共享应用发布与用户运行验收记录

## 结论

Task 9.1 已完成实现、技术验收和原数据库增量迁移，并已由用户确认。交付范围同时覆盖总计划中的内部技术细目 9.1（草稿、审核、发布）和 9.2（用户运行空间、私人会话、锁定模型）。下一纵向任务“插件治理与应用授权”尚未开始。

## 已交付能力

- owner 可为自己的 Agent 创建共享应用、保存草稿并提交不可变发布版本；提交时由服务端重新生成模型、技能、MCP、插件和 credential 依赖清单。
- 管理员可审核、拒绝、发布、下架和回滚，状态切换使用数据库行锁、期望当前版本和审计日志。
- 发布快照排除 Secret、会话和临时文件，拒绝 symlink；manifest、基线引用和会话发布绑定由数据库触发器保护。
- 普通用户从应用中心启动私人会话。运行空间按 `user/app/publication` 隔离，同一用户同一版本幂等复用；响应不返回宿主机绝对路径。
- 共享应用会话从数据库 publication 外键解析可信模型。客户端改模型、跨用户读会话、下架后新建会话均被拒绝；历史会话仍可读取。
- 应用中心增加“共享应用”和“我的发布”，管理员增加发布审核页；聊天页显示发布版本及锁定模型。

## 数据库与原实例边界

- 新迁移：`0016_shared_app_publications`。
- 在专用数据库 `qwenpaw_test_migrations` 的一次性 schema 中完成空库 upgrade、重复 upgrade、downgrade、约束与触发器验证，结果为 `3 passed in 16.32s`。
- 最终真实页面验收 schema：`qwenpaw_test_d138e90d000cccdbc185`，验收结束后已自动删除。
- 2026-09-07 经用户明确授权后，原 schema `qwenpaw_task21_acceptance` 已从 `0015_skill_governance` 增量升级到 `0016_shared_app_publications`。
- 迁移前备份：[qwenpaw-task91-before-0016.dump](../../../tmp/task91-original-backup-20260907T045145Z/qwenpaw-task91-before-0016.dump)，大小 `3,927,195` 字节，SHA-256 `25dd8476e7faf8262a9a0457599e2ae76b8fd5593bdb55eeb361ccc2406262f4`；归档目录解析和容器/本地哈希比对均通过。
- 迁移前后 59 张既有业务表的行数与内容哈希一致；新增 4 个字段、2 个不可变触发器和 7 个关键约束均已核对。
- 未修改原工作目录，未重启原服务。迁移后原服务仍为 PID `60212`，根页面和 `/api/auth/status` 均为 HTTP `200`。

## 自动化验证

### 后端和原功能回归

命令覆盖发布快照、依赖报告、权限、双用户运行空间、WorkspaceResolver、Conversation Repository、聊天事件、模型治理、会话分享和 Console 运行目录。

- 结果：`57 passed, 5 skipped, 1 warning in 2.42s`。
- 跳过项均为现有条件型用例；警告为 FastAPI TestClient 的既有 Starlette/httpx 弃用提示。
- 此前完整 Task 9.1 目标组结果：`64 passed, 4 skipped in 2.15s`；受影响后端回归：`32 passed, 1 skipped in 2.18s`。

### 前端

覆盖共享应用 API、应用中心共享页、聊天模型锁定、应用中心原页签、capability、菜单过滤和路由契约。

- 结果：`7 test files, 25 tests passed in 4.07s`。
- 生产构建：通过，`built in 49.07s`；只有既有循环依赖、动态导入和 chunk 大小提示。

## 真实浏览器与 PostgreSQL 验收

最终运行目录：[task91-browser-20260907-111546](../../../tmp/task91-browser-20260907-111546)。机器可读证据见 [acceptance.json](../../../tmp/task91-browser-20260907-111546/acceptance.json)。

使用一个无头 Chromium 进程和四个独立 browser context 登录管理员、owner、用户 A、用户 B，共通过 10 个检查点：

1. 四个真实账户独立登录；
2. 建立源 Agent 和普通用户角色；
3. owner 提交 r1 后修改源文件，管理员读取的 r1 manifest 保持不变；
4. owner 审核返回 403，管理员拒绝 r1，owner 页面显示“请补充使用说明”；
5. 管理员批准并发布 r2，审核页显示当前发布状态；
6. 用户 A、B 目录页只看到 r2，分别建立私人会话并提交 SSE 消息请求；跨用户读取为 404，模型修改为 403，聊天页显示 `r2 · task91-loopback/mock`；
7. r3 提交但未发布时，新会话仍固定 r2；发布 r3 后新会话固定 r3，原 r2 页面标签不变；
8. 下架后目录为空、新会话返回 409、历史会话仍可读；
9. 回滚 r2 后新会话再次固定 r2，既有 r3 会话仍显示 r3；
10. PostgreSQL 记录 3 个发布版本、5 个私人会话、3 个幂等运行空间和 17 条相关审计记录。

页面证据：

- [owner-r1-rejected.png](../../../tmp/task91-browser-20260907-111546/owner-r1-rejected.png)
- [admin-r2-published.png](../../../tmp/task91-browser-20260907-111546/admin-r2-published.png)
- [task91-user-a-catalog-r2.png](../../../tmp/task91-browser-20260907-111546/task91-user-a-catalog-r2.png)
- [task91-user-b-catalog-r2.png](../../../tmp/task91-browser-20260907-111546/task91-user-b-catalog-r2.png)
- [user-a-r2-model-locked.png](../../../tmp/task91-browser-20260907-111546/user-a-r2-model-locked.png)

验收产物 Secret 扫描为 clean，API/数据库投影未包含隔离工作目录绝对路径。测试模型使用隔离的不可达 loopback 地址，因此 SSE 请求验证了受信模型选择、运行门禁和持久化链路，没有调用外部模型服务。

## 工程原则

- KISS：发布状态机、快照、依赖校验和工作区解析分别由单一服务承担，HTTP 层只负责 DTO 与错误映射。
- DRY：复用现有 ActorContext、capability、Conversation Repository、聊天事件流和 WorkspaceResolver。
- YAGNI：只实现当前发布、审核、运行、下架和回滚闭环，没有引入插件授权的未来接口。
- SOLID：依赖检查使用 authority 协议，快照构建、数据库仓储和运行编排可独立验证；前端页面只呈现服务端状态。

## 用户复验路径

1. owner 登录，进入“应用 → 我的发布”，选择自己拥有的 Agent，创建共享应用并填写名称、说明后“保存并提交”。
2. 管理员进入“共享应用发布审核”，填写意见后拒绝或批准；批准后点击“发布”。
3. 普通用户进入“应用 → 共享应用”，点击“开始使用”；聊天顶部应显示锁定图标、版本和模型，不能切换模型。
4. 管理员在审核页下架后，普通用户目录入口消失；回滚已批准版本后，目录重新出现，新会话显示回滚版本。

原实例数据库已经具备 0016 结构；当前 PID 60212 尚未重启，因此仍运行迁移前已加载的应用代码。需要单独确认服务重启后，18089 页面才会加载本次新增路由和前端构建。
