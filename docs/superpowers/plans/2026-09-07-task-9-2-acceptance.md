# Task 9.2 插件治理与应用授权验收记录

## 结论

Task 9.2 已完成实现、隔离技术验收和原环境部署。管理员拥有插件安装、升级、重装、全局启停、授权和卸载能力；普通成员只能看到并加载授予自己的 active 插件与 PawApp；Agent 插件设置受 Agent 角色、用户 grant、插件状态和 manifest 配置字段共同约束。

原验收 schema `qwenpaw_task21_acceptance` 已从 `0016_shared_app_publications` 增量升级至 `0017_plugin_governance`。原 18089 服务已重启并由 PID 51008 正常监听，HTTP 200。

## 交付行为

- 新增 `plugins.manage` capability，所有全局插件管理接口只允许管理员。
- PostgreSQL 成为安装状态、全局启停、`all_members`/`selected_users` 授权和 Agent 设置的事实源。
- 安装记录与 audience 在同一事务中提交；失败撤销已加载插件；卸载清理 grant、Agent 设置、能力和个人数据。
- Loader 启动只执行数据库中 active 的插件，并将首次发现的存量磁盘插件显式登记为 `all_members`，不覆盖已有授权。
- `/api/frontend_plugin`、PawApp 列表/详情/设置/静态资源和 PawApp SDK 上下文均使用可信 `ActorContext`；客户端 `user_id/agent_id` 不能覆盖身份。
- PawApp 个人存储按可信用户 ID 隔离；单用户 `default` 命名空间保持兼容。
- Agent owner/collaborator 可读写获授权插件设置，普通 Agent user 只读；未声明配置字段被拒绝。
- 插件管理页支持状态、全体成员/指定用户授权、用户多选和授权人数；成员应用中心隐藏安装、市场和卸载入口。
- 用户身份变化时清理上一用户的 menu、route、slot、chat 和 tool 插件注册，再加载当前用户获授权插件。

## 验证证据

- 后端目标组合：`48 passed`，包含 0017 完整 upgrade/repeat/downgrade、4 项真实 PostgreSQL Repository 矩阵、治理/API/身份测试和 Loader/PawApp 回归。
- 前端目标组合：`28 passed`，覆盖 PluginContext 身份切换、PluginManager、AppCenter 和 route registry。
- `pnpm exec tsc -b --noEmit`：通过。
- `pnpm build`：通过；Monaco CSS 校验通过。Vite 仅报告既有循环 chunk 和体积提示。
- 新增及核心文件 Ruff：通过。
- 单浏览器真实验收：一个 headless Chrome、三个独立 context，6 个检查点全部通过。证据位于 `tmp/task92-browser-20260907-151741/`。
- 隔离验收 schema 已删除；隔离验收期间原服务保持 PID 60212、HTTP 200。
- 原环境部署后只读浏览器验收通过 4 个检查点：管理员治理 API/页面、普通用户治理拒绝、授权应用 API、成员应用中心。
- 部署复验发现并修正“普通成员无应用时仍显示市场入口”的遗漏；新增回归后应用中心 14 项测试通过，TypeScript、生产构建和 Monaco CSS 校验通过。

## 原数据库迁移评估

迁移前生成并校验 custom-format 备份：`tmp/task92-original-backup-20260907-152302/qwenpaw-task92-before-0017.dump`，大小 3,933,655 字节，SHA-256 为 `6acba4a6196f55209ac82ef9b2eeddcf60d7c44947502b893504c45472530180`。0017 迁移后 59 张既有业务表事实哈希不变，3 个约束和 1 个索引核验通过；结果位于 `tmp/task92-original-migration-result.json`。

## 剩余任务

按纵向任务表，Task 9.2 完成后还剩 13 项：10.1–10.3、11.1–11.4、12.1–12.4、13.1–13.2。按原内部技术细目统计还剩 18 项。已进入纵向 Task 10.1「自动化与 Heartbeat」现状审计。
