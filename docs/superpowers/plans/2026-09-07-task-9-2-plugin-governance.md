# Task 9.2 插件治理与应用授权实施计划

**目标：** 完成管理员插件全局治理、用户应用授权、PawApp ActorContext 收口及 Agent 插件配置权限。

**架构：** 复用 0003 已建表，以 PostgreSQL 为治理事实、文件系统为代码制品、Loader 为派生运行状态；新增 Repository/Service，路由统一授权，前端按当前身份加载插件并展示治理状态。

## 全局约束

- 不建立重复授权表；`selected_users` 映射为多条 `app_grants(subject_type='user')`。
- 多用户模式下管理 API 仅管理员，用户资源 API 同时校验 active 与 grant。
- 不信任客户端身份字段；全部从 ActorContext 和既有 Agent 上下文取值。
- 全局停用保留授权和 Agent 设置，运行时忽略；卸载走单一状态机。
- 不执行 Git 操作。
- 原数据库和 18089 服务仅在单独确认后迁移/重启；开发验证使用隔离 schema、插件目录和端口。

### Task 1：领域服务、Repository 与数据库约束

- [x] 新增 `src/qwenpaw/plugins/governance.py`，定义状态、授权 DTO、Repository 和 Service。
- [x] 新增 0017 增量迁移，为 status、grant 主体、subject_id 配对补 check，并授予运行角色最小表权限；不删除现有数据。
- [x] 为磁盘既有插件提供显式兼容登记函数，默认 `all_members`，不在普通读取请求中静默写库。
- [x] 编写 Repository 集成测试和角色/授权隔离测试。

### Task 2：插件管理 API 与 Loader 状态机

- [x] 新增 `plugins.manage` capability 及依赖。
- [x] 将插件清单、catalog、market、安装、上传、强制重装、启停、授权、状态和卸载纳入管理员校验。
- [x] 安装成功后持久化 manifest/hash/source/audience；失败执行补偿。
- [x] PawApp 卸载复用插件卸载流程，删除第二套直接目录删除逻辑。
- [x] 覆盖成员直接 API 越权、并发 lifecycle、失败补偿和热重载测试。

### Task 3：用户插件与 PawApp 授权

- [x] 多用户模式保护 `/api/frontend_plugin`，按 ActorContext 返回获授权 active 插件。
- [x] 前端 bundle、PawApp 详情/设置/iframe/静态资源做同一授权检查。
- [x] PawApp API 不接受或使用客户端 `user_id/agent_id`。
- [x] 补全 all_members、selected_users、disabled、未授权枚举与身份伪造测试。

### Task 4：Agent 插件设置

- [x] 实现 Agent owner/collaborator 的设置读取与保存 API。
- [x] 校验 Agent 编辑角色、插件 active、用户 grant 和 manifest 声明字段。
- [x] 全局停用时保留设置但拒绝修改并在运行时忽略。
- [x] 覆盖 owner、collaborator、user、未授权和停用矩阵。

### Task 5：前端治理与身份切换

- [x] 扩展插件 API 类型、安装参数、状态切换和授权编辑。
- [x] 插件管理页显示状态、授权和影响范围，只对管理员呈现治理操作。
- [x] 应用中心普通成员隐藏官方/市场安装与卸载；管理员保留原功能。
- [x] PluginContext 在认证完成后加载获授权插件，切换用户时清理旧注册并重载。
- [x] 增补 PluginManager、AppCenter、usePluginLoader 和身份切换 Vitest。

### Task 6：验证与确认门

- [x] 运行目标 pytest、Vitest、类型检查和迁移静态检查。
- [x] 经确认后在隔离 PostgreSQL schema 执行 0017 upgrade/downgrade/upgrade 与 Repository 集成测试。
- [x] 启动隔离后端和前端，以管理员及两个成员完成浏览器矩阵并保存证据。
- [x] 输出原数据库迁移影响、备份/回滚步骤和剩余任务数；原数据库迁移与服务重启单独确认。

