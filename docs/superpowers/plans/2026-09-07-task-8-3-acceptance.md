# Task 8.3 多类型频道绑定与外部身份验收记录

状态：实现、自动化回归、独立 PostgreSQL 与真实 Chrome 技术验收通过；用户已于 2026-09-07 确认，并授权进入 Task 9.1。

## 交付行为

- 每个可使用 Agent 的用户都能维护自己的频道绑定；同一用户、同一 Agent、同一频道类型仅有一个实例，同一用户可同时绑定多个频道类型。
- owner、collaborator、user 均以自己的平台用户 ID 作为绑定所有者；管理员访问他人 Agent 时也不能读取或覆盖他人的个人绑定。
- Bot 身份冲突会同时检查其他 Agent 和其他用户已启用的个人绑定，Secret 只存储在加密 Credential Record 中，读取接口仅返回已配置字段名。
- 个人绑定使用独立 `ChannelManager`，启用、替换、停用、删除均不替换 Agent 原频道管理器或改写 Agent 频道文件。
- 外部频道消息进入 Agent 前，外部主体会映射为该绑定所有者的平台用户；原外部主体、频道、会话及必要的非敏感频道元数据保留在请求中，并写入 `channel_external_identities`。数据库写入同时校验绑定确实归属于该平台用户，不能把外部主体伪造映射给其他用户。
- 个人绑定冲突检查同时覆盖 PostgreSQL 中已启用的其他个人绑定和 Agent 原本正在运行的频道，避免同一 Bot 在两类运行源中重复连接。
- 原频道二维码、访问控制、消息收发和 Agent 联动代码路径保持原样。访问控制仍在身份映射前使用真实外部主体判定。

## 本轮补齐

早期 Task 4.2-B 已完成个人频道 CRUD、运行时隔离、冲突检查、Secret 不回读和双用户页面验收。本轮按纵向 Task 8.3 复核时发现 `channel_external_identities` 只有表结构，运行时没有形成持久化事实；现已在消息进入 Agent 前执行幂等写入，同一绑定、同一外部主体只保留一条最新映射。

## 验证结果

| 范围 | 结果 |
| --- | --- |
| 频道运行时、路由、权限、冲突 | 21 passed |
| 全部 app/channel 单元回归、路由、权限、二维码 | 228 passed |
| 独立 PostgreSQL 隔离、Secret、外部身份 | 2 passed；真实建表、消息映射、幂等更新、伪造 owner 拒绝均通过 |
| 前端频道 API、Hook、页面和频道常量 | 5 files / 29 tests passed |
| 前端生产构建 | 通过；Monaco CSS 校验通过，保留既有 chunk 警告 |
| Python 语法 | 本次文件 `compileall` 通过 |
| 真实 Chrome + 独立 PG | 4 个合成账号；3 个角色的个人绑定和页面隔离、多频道类型、Secret 不回显均通过 |
| 原服务 | `127.0.0.1:18089` 仍由 PID 60212 监听，未重启，未对原频道绑定执行写操作 |

独立 PostgreSQL pytest 在 Windows asyncio 清理线程中仍输出既有 access violation 诊断，但进程返回 0 且 2 项测试通过。当前环境没有安装 Ruff，因此未声称 Ruff 检查通过；限定文件已做 Python 编译检查。

真实浏览器证据位于 `tmp/task83-browser-20260907-020540/`：

- `acceptance.json`：5 项真实页面/API 组合检查，包含跨用户个人 Bot 冲突预检，且隔离 schema 已删除。
- `task83-owner-bindings.png`、`task83-collaborator-bindings.png`、`task83-user-bindings.png`：三个角色只看到自己的 Telegram 前缀，Token 输入框为空。
- `app.log`：隔离实例运行日志；未命中合成 Telegram Secret。

## 前端验收步骤

1. 进入“频道”，选择一个自己可使用的 Agent，打开“我的频道绑定”。
2. 分别打开 Telegram、Slack 等不同频道卡片，确认同一 Agent 可以保存多个不同类型绑定。
3. 在 Telegram 中填写 Bot Token 并保存。刷新后应显示 Secret 已配置，但 Token 输入框为空。
4. 以另一个账号进入同一 Agent 的“我的频道绑定”，确认看不到第一个账号的名称、前缀和 Secret 状态；保存自己的 Telegram 不影响第一个账号。
5. 使用同一个 Bot Token 启用另一条个人绑定，应出现 Bot 冲突提示。取消后不保存；确认后才继续。
6. 对一个无外部连接依赖的 Console 绑定执行“启用 → 停用 → 删除”，确认页面状态随之更新；切回“智能体频道”，原配置应保持不变。

页面验收只需日常浏览器。自动化验收使用一个临时无头 Chrome 进程和多个隔离上下文，完成后立即关闭，不会为每个用户常驻一个浏览器。

## 工程原则

- **KISS：** 复用现有个人绑定运行时，只新增一个外部身份持久化入口。
- **DRY：** 外部身份记录集中在 Repository，运行时统一调用。
- **SOLID：** Repository 负责 PostgreSQL 事实，Runtime Wrapper 负责消息身份转换，Service 继续负责 Agent 访问授权。
- **YAGNI：** 不引入组织级频道共享、多实例同类型频道或新的频道协议层。

## 未执行

- 未修改原环境频道绑定、Agent 配置或 Secret。
- 未执行 git commit、push、reset、建分支或工作区清理。
