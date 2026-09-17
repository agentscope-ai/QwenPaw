# Task 9.2 插件治理与应用授权设计

## 1. 目标与边界

Task 9.2 将现有“文件系统中存在即全员可见、任意登录用户可调用管理 API”的插件机制收口为平台级治理：管理员负责安装、升级、强制重装、全局启停、授权和卸载；普通用户只加载并运行已启用且授权给自己的插件与 PawApp；Agent owner/collaborator 只能配置自己可编辑 Agent 上已经安装并获授权的插件能力。

保留 URL、ZIP、官方目录、市场安装、热加载、插件隔离、应用中心搜索/分类/内嵌打开和 Agent 工具配置。首期只实现 `all_members`、`selected_users` 和全局停用，不建设用户组、购买、计费、灰度版本或跨实例插件分发。

## 2. 既有事实与选型

迁移 0003 已建立 `plugin_installations`、`plugin_capabilities`、`app_grants`、`agent_plugin_settings` 和 `app_user_data`。本任务复用这些表，不创建平行授权模型。

选择“数据库为治理事实、文件系统为代码制品、运行 Loader 为派生状态”：

- PostgreSQL 决定插件是否安装、是否全局启用、哪些用户可见以及 Agent 是否启用。
- 插件目录保存 Python、JavaScript、静态资源和依赖，不承担授权判断。
- Loader 只装载数据库中处于 `active` 的插件；运行状态与数据库不一致时拒绝使用并向管理员报告。

不采用仅在前端隐藏按钮的方案，因为直接调用当前安装、上传、卸载、PawApp 静态资源接口仍可越权。不采用把授权写回 `plugin.json` 的方案，因为会产生多进程竞争、缺少事务与审计，并把用户关系混入可执行制品。

## 3. 权限模型

| 操作 | 普通成员 | Agent owner/collaborator | 平台管理员 |
|---|---:|---:|---:|
| 浏览/运行获授权应用 | 是 | 是 | 是 |
| 加载获授权前端插件 | 是 | 是 | 是 |
| 配置可编辑 Agent 的插件能力 | 否 | 是 | 是（显式 Agent 管理范围） |
| 查看全局插件清单和影响范围 | 否 | 否 | 是 |
| URL/ZIP/官方/市场安装与升级 | 否 | 否 | 是 |
| 全局启用、停用、授权、卸载 | 否 | 否 | 是 |

后端新增稳定 capability `plugins.manage`，只授予平台管理员。前端已有 `platform.settings.manage` 继续控制设置菜单；后端不依赖该菜单。

管理员在应用内运行时仍使用自己的 `ActorContext.user_id`，不自动读取其他用户数据。所有 PawApp 列表、详情、设置、iframe、静态文件和应用数据入口均从可信 `ActorContext` 判定，不接收客户端 `user_id`。需要 Agent 时通过既有可信 Agent 上下文解析并校验成员关系，不接受请求体或查询参数覆盖 `agent_id`。

## 4. 状态与授权语义

`plugin_installations.status` 首期只使用：

- `active`：允许 Loader 装载，并继续检查用户授权；
- `disabled`：全平台不可见、不可运行，保留 Agent 设置以便恢复；
- `installing` / `failed`：安装过程或失败诊断状态，不向用户暴露；
- `uninstalling`：卸载中的短暂状态，不可使用。

`app_grants` 使用现有主体模型：

- `subject_type='all_members'` 且 `subject_id IS NULL`：所有有效管理员和成员均可使用；
- `subject_type='user'` 且 `subject_id=<用户 UUID>`：指定有效用户可使用；
- `selected_users` 是 API/UI 的授权模式，由一组 `user` grant 表示，不另增冗余列。

管理员管理视图不受 grant 过滤；管理员运行应用时与普通用户一样需要命中授权。为保持升级兼容，首次登记磁盘上已有插件时建立 `all_members` grant；新安装插件由安装请求明确提交授权模式，默认 `selected_users` 空集合，防止刚安装的代码自动向全员开放。

全局停用只改变安装状态并卸载运行能力，保留 `app_grants` 和 `agent_plugin_settings`。重新启用后恢复原授权和 Agent 设置。卸载在事务中先进入 `uninstalling`，卸载运行代码并清理派生配置，最后删除安装事实；失败则记为 `failed` 并保留可诊断事实，不能出现数据库显示 active 而 Loader 已不存在的假成功。

## 5. 服务与持久化

新增 `PluginGovernanceRepository` 负责明确查询和原子写入，新增 `PluginGovernanceService` 负责角色、授权和状态机。路由只处理 DTO、Loader 协调和错误映射。

核心接口：

```text
list_manageable(actor)
list_authorized(actor)
register_installation(actor, manifest, source, content_hash, audience)
replace_audience(actor, plugin_id, mode, selected_user_ids)
disable(actor, plugin_id)
enable(actor, plugin_id)
begin_uninstall(actor, plugin_id)
complete_uninstall(actor, plugin_id)
require_app_access(actor, plugin_id)
get_agent_setting(actor, agent_context, plugin_id)
save_agent_setting(actor, agent_context, plugin_id, enabled, config)
```

授权替换使用一个数据库事务：锁定 installation，验证目标用户均为 active，删除旧 grant，写入规范化后的新 grant，记录审计。`selected_users` 去重并排序；空集合合法，表示仅管理员可治理但无人可运行。

## 6. API

管理员接口：

```text
GET    /api/plugins
POST   /api/plugins/install
POST   /api/plugins/upload
POST   /api/plugins/{plugin_id}/enable
POST   /api/plugins/{plugin_id}/disable
PUT    /api/plugins/{plugin_id}/audience
DELETE /api/plugins/{plugin_id}
GET    /api/plugins/{plugin_id}/status
```

安装请求在原 `source`、`force` 之外增加 `audience_mode` 与 `selected_user_ids`。管理清单返回状态、授权模式、指定用户、运行加载状态和受影响 Agent 数量。

用户接口：

```text
GET /api/frontend_plugin
GET /api/frontend_plugin/{plugin_id}/files/{path}
GET /api/pawapps
GET /api/pawapps/{app_id}
GET /api/pawapps/{app_id}/settings
GET /api/pawapps/{app_id}/iframe
GET /api/pawapps/{app_id}/static/{path}
```

多用户模式下 `/api/frontend_plugin` 不再匿名公开。登录页只使用核心前端；认证成功后按当前用户重新加载获授权插件，切换用户时清空上一用户注册的插件路由、菜单和组件。旧版单用户模式继续加载全部磁盘插件。

PawApp 的卸载入口统一转发到管理员插件卸载状态机，删除重复的直接 `shutil.rmtree` 路径。

## 7. Agent 配置边界

保存 Agent 插件设置前同时校验：

1. 当前 actor 是该 Agent 的 owner 或 collaborator；
2. installation 存在且为 `active`；
3. actor 命中插件授权；
4. 请求配置只包含 manifest 声明的 Agent 级非敏感字段；Secret 只保存 credential reference；
5. 全局停用时拒绝新增或修改，已有设置保留但运行时忽略。

普通 `user` 角色只能使用 Agent，不能改插件设置。配置操作只影响目标 Agent，不改变全局版本、授权、供应商或插件文件。

## 8. 前端行为

插件管理页保持“已安装 / 官方 / 市场”结构，并增加：全局状态、授权范围、指定用户编辑、启停和影响数量。它只对管理员可见，收到 403 时显示明确权限错误。

应用中心的“已安装”列表仅使用 `/api/pawapps` 已过滤结果；普通成员不显示卸载操作，“官方/市场”安装入口只向管理员显示。深链到未授权应用返回 404，避免泄露安装事实。切换用户后清空 active app 与插件注册状态并重新拉取。

## 9. 失败、安全与兼容

- 安装先在 staging 校验 manifest、哈希和解包路径，再写安装中状态并进入既有 lifecycle lock；失败不留下可加载半目录。
- 授权检查失败统一返回 404（资源读取）或 403（明确管理动作），防止普通用户枚举未授权插件。
- 前端静态资源也做同一授权检查，避免通过猜测 URL 下载未授权代码。
- catalog/market 查询属于管理能力，在多用户模式只允许管理员；单用户模式保持原行为。
- 原 18089 服务在实现与隔离验收阶段不重启、不写业务数据；原数据库迁移或既有插件登记另行执行确认门。

## 10. 验收矩阵

后端至少覆盖：成员调用安装/上传/升级/停用/卸载均为 403；管理员完成安装、授权替换、停用、恢复和卸载；两个成员在 `all_members` 与 `selected_users` 下获得不同应用清单；未授权详情、静态资源、iframe 均不可访问；伪造 `user_id/agent_id` 无效；owner/collaborator 可配置获授权且 active 的插件，user、未授权用户和停用插件均被拒绝；切换用户不残留前端插件。

浏览器验收使用独立 PostgreSQL schema、独立插件目录和独立端口，演示管理员治理页、普通成员应用中心、指定用户差异和直接 API 拒绝。原服务保持运行。
