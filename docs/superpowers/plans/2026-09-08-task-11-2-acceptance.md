# Task 11.2 工具后台默认策略验收记录

## 结论

Task 11.2 已完成技术验收，等待用户确认。全局默认策略仅管理员可修改，普通用户仍能读取有效策略并控制本人正在运行的工具；后台执行保持原发起身份和自动化授权。

## 实现范围

- `PUT /api/settings/offload-policy` 增加 `platform.settings.manage` 服务端授权；普通用户返回 403。
- `GET /api/settings/offload-policy` 保持运行用户可读，供聊天工具卡显示当前有效默认策略。
- 保存后直接更新当前 `ToolCoordinator.offload_on_deadline`，无需重启。
- 执行上下文快照增加 Cron、Heartbeat 和自动化授权字段，并深拷贝嵌套数据，防止请求对象后续修改污染后台任务。
- 管理页面明确标注部署级策略仅管理员可改；修复卡片和单选组事件叠加导致一次点击发送两次保存请求的问题。

## 自动化证据

- 后端：`49 passed`，覆盖管理员/普通用户权限、保持前台、自动转后台、运行时热更新、本人手动转后台和身份快照。
- 前端：`10 passed`，覆盖策略载入、单次保存、当前值不重复写入、工具运行控制和 capability 路由。
- TypeScript：`tsc -b --noEmit` 通过。
- 生产构建：18,889 个模块构建成功，Monaco CSS 校验通过；仅有仓库既有的 chunk 与导入提示。
- Ruff 错误级规则、Prettier 和目标文件 `git diff --check` 通过。

## 浏览器与部署证据

- 验收地址：`http://127.0.0.1:18089`，多用户模式，当前 PID `17360`。
- 管理员页面显示部署级管理员提示；切换到自动后台只产生一次 `PUT /api/settings/offload-policy 200`。
- 普通用户设置菜单无“工具后台策略”；认证 API 读取策略返回 200，修改返回 `403 {"detail":"forbidden"}`。
- 普通用户实际启动 `Start-Sleep -Seconds 45` 工具后，控制面板显示立即转后台、禁止转后台、延迟转后台、延长执行超时和取消；工具按管理员设置自动转入“后台任务”，随后正常完成。本人手动转后台接口另由集成测试覆盖。
- 截图：`tmp/task112-admin-offload-policy.png`、`tmp/task112-member-manual-offload.png`。
- 验收结束已把全局策略恢复为 `keep_foreground`。

## 数据影响

没有数据库迁移。仅在隔离验收目录的 `settings.json` 中切换策略，并已恢复为“保持前台”；普通用户测试产生一条新的验收聊天和工具运行记录。

## 下一确认门

用户确认 Task 11.2 后进入 Task 11.3「平台安全基线与 Agent 收紧策略」。
