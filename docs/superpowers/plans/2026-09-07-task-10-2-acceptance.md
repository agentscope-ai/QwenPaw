# Task 10.2 Heartbeat 安全主体和目标验收记录

## 结果

Task 10.2 已完成实现、自动化验证、单浏览器双用户验收和原环境部署。该任务只扩展 Agent JSON 配置，不涉及数据库结构变更。

## 已验证行为

- Heartbeat 配置由服务端从可信 ActorContext 写入 `authorizedByUserId`，客户端伪造值无效。
- 多用户 Heartbeat 使用 `actor_type=automation`、`automation_kind=agent_automation` 和按 Agent/授权用户隔离的专用会话。
- 授权用户必须处于 active 状态并仍有当前 Agent 访问权；旧配置缺少授权时不会进入调度器。
- `last` 只读取授权用户自己的最近目标；个人频道绑定还需保持启用且归该用户所有。
- `last` 无有效目标时不回退到其他用户或共享 `main`，阻断通知只写入授权用户私人收件箱。
- `inbox` 的成功、超时和异常均使用授权用户作为 recipient，Trace 使用同一专用会话。
- Heartbeat 的自动化身份会保留到工具治理层；缺少长期授权快照时工具调用默认拒绝。

## 自动化验证

- 后端最终相关组合：147 passed、1 skipped。
- 前端 Heartbeat API 与页面相关测试：10 passed。
- TypeScript `tsc --noEmit`：通过。
- Python compileall：通过。
- Ruff 错误级规则 `E9,F63,F7,F82`：通过。
- 全规则 Ruff 扫描发现 286 条既有现代化和风格债务，未在本任务扩大修改范围。

## 浏览器证据

单个 headless Chromium 内使用两个隔离 context 模拟用户 A 和 B，六项检查全部通过：

1. 两用户在同一浏览器进程中隔离登录；
2. 建立共享 Agent 的 owner/collaborator 关系；
3. 服务端将 Heartbeat 绑定到实际保存者 A，忽略客户端伪造的 B；
4. B 可以从共享 Agent 页面访问 Heartbeat；
5. A 授权后写入 B 的最近目标事实；
6. A 运行 Heartbeat 时不使用 B 的目标，阻断通知只对 A 可见。

证据：`tmp/task102-browser-20260907-203307/acceptance.json` 和 `single-browser-two-user-heartbeat.png`。临时 PostgreSQL schema 已删除，原 18089 服务在隔离验收前后均为 PID 64548、HTTP 200。

## 原环境部署

- 部署前检查到 6 个 Agent 的 Heartbeat 全部关闭，没有活动任务受影响。
- 服务从 PID 64548 重启为 PID 61504，HTTP 200。
- 只读冒烟验证接口包含 `authorizedByUserId` 状态、Heartbeat 页面正常加载，且没有修改或启用原配置。
- 部署证据：`tmp/task102-deployed-smoke.json`。
