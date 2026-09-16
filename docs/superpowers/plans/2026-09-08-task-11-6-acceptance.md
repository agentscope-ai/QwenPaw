# Task 11.6 管理员脱敏日志和普通用户诊断验收记录

## 结论

Task 11.6 已完成技术验收，等待用户确认。全局后端日志只允许平台管理员读取，服务端在响应前统一移除凭据、部署环境变量值和宿主绝对路径；普通用户继续通过本人 Chat、Run、Trace 和 Inbox 查看错误过程。

## 实现范围

- 新增集中式日志响应脱敏模块，覆盖 Authorization、Proxy-Authorization、Cookie、Set-Cookie、API Key、Token、Secret、Password、Credential、Bearer、常见厂商 Token 和 Windows/Linux 宿主绝对路径。
- 已保存的部署环境变量值按实际值脱敏，即使变量名不包含 `KEY`、`TOKEN` 或 `PASSWORD` 也不会出现在响应中。
- `/api/console/debug/backend-logs` 在多用户模式下直接校验平台设置管理能力；普通用户返回 403。
- 接口的 `path` 字段只返回日志文件名 `qwenpaw.log`，不返回宿主路径。
- 调试页面标记“敏感信息已脱敏”，并将路径展示改为“日志来源”。
- 前端按认证模式、用户 ID 和平台角色隔离日志状态；切换身份后立即清空旧数据并丢弃迟到响应，普通用户不发起全局日志请求。

## 验证证据

- 后端授权与脱敏测试：`2 passed`。
- Chat、后台 Run、Trace、Inbox、工具调用和日志工具组合回归：`58 passed`。
- 前端调试 API、Hook 和页面测试：`6 passed`。
- TypeScript `tsc -b --noEmit`、目标文件 Prettier、Python compileall 和生产构建通过；Monaco CSS 校验通过。
- 真实多用户 API：普通用户读取全局日志返回 403，管理员返回 200；注入假 Authorization、Cookie、API Key 和两类绝对路径后泄漏数量为 0。
- 浏览器：管理员页面显示脱敏标识、安全日志来源和 `[REDACTED_PATH]`；普通用户菜单无“调试”入口，直接访问 `/debug` 不呈现调试内容，原聊天历史正常显示。

## 页面验收与数据影响

- 管理员登录后进入“设置 → 调试”，可继续使用自动刷新、倒序、级别筛选、搜索和复制。
- 普通用户不拥有全局调试入口；其个人诊断数据入口和权限未改变。
- 假 Secret 只写入本地验收实例日志，页面和 API 仅返回脱敏结果。
- 截图：`tmp/task-11-6-admin-redacted-logs.png`。
- 多用户验收服务：<http://127.0.0.1:18089>，当前 PID `65688`。

## 下一确认门

用户确认后进入 Task 12.1「只读扫描与迁移预览」。该任务只扫描旧数据并生成数量、哈希、映射、冲突和拒绝项，不写目标数据；真正迁移将在 Task 12.2 前再次执行危险操作确认。
