# Task 10.1 自动化所有者与长期授权验收记录

## 结果

Task 10.1 已完成代码实现、隔离 PostgreSQL 验证、真实浏览器验收和原环境部署。原数据库已从 0017 升级到 0018，18089 服务已从 PID 51008 重启为 PID 64548，部署后 HTTP 200。

## 已验证行为

- 多用户 Cron 以 PostgreSQL 为唯一事实源，任务创建者同时成为 automation owner。
- owner 可以批准自己的任务；普通 user、collaborator、Agent owner 都不依赖 Agent owner 在线审批。
- 客户端提交的 user/owner 和 `tool_safety=false` 不会改变可信身份，也不能进入 Tool Guard OFF。
- 修改 schedule、task、runtime 或 dispatch 会递增版本、撤销 grant，并回到 `pending_authorization`。
- 其他用户看不到任务；Agent owner/管理员可看 Agent 全部任务和暂停他人任务，不能替他人修改、批准、恢复或运行。
- 手动运行与定时运行使用同一执行前校验；失效、暂停和待授权任务在执行前拒绝。
- 页面默认显示“我的任务”，授权前展示服务端目标与工具摘要，工具安全关闭开关已移除。

## 自动化验证

- 后端 Cron、对象权限与治理最终组合：96 passed。
- 前端 API 与 Hook：22 passed。
- TypeScript 与 Vite 生产构建成功；Monaco CSS 验证成功。
- Ruff 目标文件检查通过。
- 隔离 PostgreSQL migration/repository：6 passed，覆盖 upgrade、重复 upgrade、downgrade 和真实事务。

## 浏览器证据

单个 headless Chromium 内创建四个隔离 context，分别模拟管理员、Agent owner、collaborator 和普通 user。六项检查全部通过：

1. 四身份单浏览器隔离登录；
2. Agent owner/collaborator/user 角色建立；
3. 每个创建者批准自己的任务；
4. 跨用户隐藏及 Agent owner 仅暂停；
5. 变更范围撤销授权并阻断运行；
6. 页面显示创建者任务且不再提供 OFF 开关。

证据：`tmp/task101-browser-20260907-190819/acceptance.json` 和 `creator-owned-automation.png`。临时 schema 已删除。

## 原环境部署结果

原 schema 已从 0017 升级到 0018，只新增四个 CHECK 约束和三个索引，未删表、未改列、未导入历史任务。迁移前既有事实数量保持不变。

- 备份：`tmp/task101-original-backup-20260907-191416`
- 备份 SHA256：`879234a2c6da159a8e291fc93c615c2d0144fdcadd393a31dca6584fa3a15481`
- 迁移结果：`tmp/task101-original-migration-result.json`
- 部署结果：`tmp/task101-deployment.json`
- 部署后冒烟：`tmp/task101-deployed-smoke.json`

部署后冒烟确认 owner 可读取自己的自动化授权、页面没有 Tool Guard OFF 开关、当前 revision 为 `0018_automation_authorization`，且未创建或删除原环境任务。
