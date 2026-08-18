# QwenPaw Pro 本地控制面设计

## 状态

- 方案日期：2026-08-18
- 启动入口：`qwenpaw app --pro`
- 第一阶段安全级别：`isolated-local`（失败时禁止裸进程回退）
- 实现分支：`feat/qwenpaw-pro-local-control-plane`

## 目标

QwenPaw Pro 在现有 QwenPaw App 外增加透明运行时控制面，将一个 QwenPaw App
进程视为单租户执行单元。第一版在本机启动和管理多个相互独立的 QwenPaw
子进程，同时保持调度接口与部署方式无关，以便后续增加 Docker、Kubernetes
和远程 Runtime 实现。

```text
qwenpaw app --pro
        |
        v
QwenPaw Pro Control Plane
        |
        +-- tenant-a -> Local QwenPaw Runtime
        +-- tenant-b -> Local QwenPaw Runtime
        `-- tenant-c -> Local QwenPaw Runtime
```

第一版不把 `tenant_id` 注入现有 Agent 内核，也不把多个租户放进同一个 QwenPaw
进程。每个 Runtime 拥有独立的数据、密钥、备份、日志和监听端口。用户、角色、
注册策略和 Runtime ownership 由外围控制面负责。

## 非目标

- 不在第一版实现 SSO、组织成员邀请和计费界面。
- 不在第一版实现 Docker 或 Kubernetes 调度器。
- 不修改现有 `qwenpaw app` 的默认单用户行为。
- 不把本地 OS sandbox 宣称为容器或虚拟机等级的隔离。
- 不允许 Runtime 启动失败时降级到另一个租户的目录或进程。

## 命令语义

```bash
qwenpaw app --pro
```

未指定 `--pro` 时，现有 App 启动行为保持不变。指定 `--pro` 后，`--host`、
`--port` 和 `--log-level` 配置 Pro 控制面，而不是某个租户 Runtime。

第一版本地控制面仅允许绑定 loopback 地址。未来加入认证和传输安全之后，才能
开放非 loopback 地址。

### Pro 配置文件

Pro 支持独立、版本化的 YAML 配置入口，避免把 runtime policy 和容量限制继续
堆叠为环境变量：

```bash
qwenpaw app --pro --config ./qwenpaw-pro.yaml
```

当前支持的配置结构：

```yaml
version: 1

control_plane:
  registration:
    enabled: false
    default_role: user

runtime:
  default_driver: local
  allowed_drivers: [local]

tenant_defaults:
  max_runtimes: 3
  max_running_runtimes: 2

tenants:
  personal-example-user-id:
    max_running_runtimes: 1
```

配置采用字段级导入：显式 YAML 值高于 SQLite 值并在启动事务中回写控制面
数据库，未出现的字段保留 SQLite 中的现有值；数据库没有记录时才使用内置
默认值。完成一次导入后，即使下次不带 `--config`，仍继续使用最近持久化的结果。
管理员 UI 修改数据库后立即生效；如果下次仍使用包含该字段的 YAML 启动，YAML
会再次覆盖它。YAML 中出现未知字段、错误版本、不可用 driver 或非法 quota 时
启动失败，避免拼写错误被静默忽略。

解析结果生成与部署实现无关的 `ProConfig` 和 `TenantQuota`，由
`RuntimeService` 在创建和启动 Runtime 前执行准入检查。tenant 单独覆盖默认限制
时必须以 `tenant_id` 为键，不能使用可修改的 username。

当前 local driver 可靠执行 Runtime 数量和运行中 Runtime 数量限制，但不能把
应用层统计冒充 CPU、内存、磁盘或任务并发硬配额。硬资源限制只在
能够由 cgroup、容器 runtime、Kubernetes ResourceQuota 或 Windows Job Object
强制执行的 driver 上标记为 `enforced`。不支持的限制必须在启动时明确报错或标记
为 `advisory`，不得静默忽略。

## 目录布局

Pro 数据默认位于 `QWENPAW_PRO_DIR`；未配置时使用
`<QWENPAW_WORKING_DIR>/pro`：

```text
pro/
  control.db
  runtimes/
    runtime-a/
      working/
      secrets/
      backups/
      logs/
        app.log
    runtime-b/
      working/
      secrets/
      backups/
      logs/
        app.log
```

Runtime ID 必须使用受限字符集，并在创建目录前完成规范化和父目录校验，禁止
使用绝对路径或 `..` 越界。

## 核心接口

部署实现必须遵守同一组生命周期操作：

```python
class RuntimeDriver(Protocol):
    name: str
    security_level: str
    def start(self, record, credentials) -> RuntimeRecord: ...
    def stop(self, record) -> RuntimeRecord: ...
    def status(self, record) -> RuntimeRecord: ...
    def close(self) -> None: ...
```

Runtime 注册、ownership 和目录布局由 `RuntimeService + RuntimeRegistry` 负责；
driver 只处理部署相关生命周期。未来 Docker/Kubernetes driver 不需要复制认证、
租户授权、CredentialVault 或 Console API。

`RuntimeSpec` 描述逻辑需求，不包含 Docker SDK 或 Kubernetes client 对象：

```text
runtime_id
tenant_id
driver
host
port
working_dir
secret_dir
backup_dir
metadata
```

第一版只注册 `LocalProcessRuntimeDriver`。未来 driver 通过显式 registry 选择，
控制面 API 不依赖具体部署实现。

## 本地 Runtime

本地 driver 使用当前 Python 解释器启动 QwenPaw，但 Python 进程必须位于平台
隔离器最外层，不能直接裸启动：

```text
macOS: sandbox-exec <runtime-profile> python -m qwenpaw app ...
Linux: bwrap <runtime-mounts-and-namespaces> python -m qwenpaw app ...
Windows: AppContainer adapter（完成前拒绝启动）
```

子进程必须显式注入：

- `QWENPAW_WORKING_DIR`
- `QWENPAW_SECRET_DIR`
- `QWENPAW_BACKUP_DIR`
- Runtime 专属的 keyring account
- Runtime 专属内部访问 token
- UTF-8 和无缓冲日志配置

控制面关闭时应终止自己启动的本地 Runtime。控制面异常退出后，启动恢复流程
只能识别和报告遗留进程；在没有可靠进程身份校验时，不得根据复用 PID 杀死
未知进程。

## 本地控制 API

第一阶段提供机器接口，Console 接入后续完成：

```text
GET    /api/pro/healthz
GET    /api/pro/runtimes
POST   /api/pro/runtimes
GET    /api/pro/runtimes/{runtime_id}
POST   /api/pro/runtimes/{runtime_id}/start
POST   /api/pro/runtimes/{runtime_id}/stop
DELETE /api/pro/runtimes/{runtime_id}
```

创建 Runtime 时 `tenant_id` 必填，`runtime_id` 在控制面全局唯一。删除运行中的
Runtime 必须先停止；第一版删除注册信息但保留数据目录，避免误删用户数据。

所有 Runtime 接口都必须经过 Pro 身份认证。管理员可以管理全部 Runtime；普通
用户只能读取和操作自己 personal tenant 下的 Runtime。

## 用户、角色与注册策略

Pro 控制面使用稳定 `user_id`，不把可修改的 username 用作资源外键。第一版
提供两种角色：

| 角色 | 权限 |
| --- | --- |
| `admin` | 管理用户、注册策略和全部 Runtime |
| `user` | 管理本人 personal tenant 下的 Runtime |

首次启动没有用户时，注册页面创建的第一个账号自动成为管理员。创建首个管理员
后，能否自行注册由全局 `registration_enabled` 设置决定，默认关闭。管理员始终
可以从管理界面直接创建普通用户。

用户支持以下状态：

- `active`：允许登录和访问授权资源。
- `disabled`：所有新请求立即拒绝，已有 token 通过 `token_version` 失效。

第一阶段控制面表增加：

```text
users
  user_id primary key
  username unique
  password_hash
  password_salt
  role
  disabled
  token_version
  created_at
  updated_at

settings
  key primary key
  value

runtimes
  owner_user_id
```

密码使用标准库 PBKDF2-HMAC-SHA256 和随机 salt。Bearer token 使用控制面随机
签名密钥，包含稳定 user ID、角色、token version、签发和过期时间。角色仍以
数据库实时值为准，不能只信任 token 中的旧角色。

公开接口只有首次 bootstrap、允许注册时的 register、login、auth status 和
静态资源。用户与注册策略管理接口只允许管理员访问。

## 产品入口与 Pro Console

`qwenpaw app --pro` 的根路径仍是完整 QwenPaw 产品，而不是 Runtime 管控台。
用户登录后，控制面按账号选择或懒创建默认隔离 Runtime，并把普通 `/api/*`
请求透明代理给该 Runtime。用户不需要看到内部端口，也不需要二次登录。

```text
/login       -> Pro 身份认证
/             -> 用户自己的完整 QwenPaw
/api/*        -> 透明代理到用户默认隔离 Runtime
/api/pro/*    -> Pro 控制面 API
/pro/admin    -> 仅管理员可见的管理页面
```

Pro 管理页面包含：

- 登录与首次管理员创建页面；
- Runtime 概览与创建、启动、停止入口；
- 管理员用户列表；
- 管理员创建账号；
- 启用/禁用账号；
- 普通用户与管理员角色切换；
- 是否允许公开注册的开关。

普通用户不显示管理入口，后端也必须进行同样的权限校验。前端图标统一使用
Lucide React，不新增其他图标库。

## SQLite 控制面

`control.db` 保存 Runtime 的期望状态和最近观测状态：

```text
runtimes
  runtime_id primary key
  tenant_id
  driver
  host
  port
  state
  pid
  working_dir
  secret_dir
  backup_dir
  created_at
  updated_at
  last_error
  metadata_json
```

数据库启用 WAL、foreign keys 和 busy timeout。表结构通过显式 schema version
初始化，为后续 migration runner 留出边界。

## 本地 Shell 与进程隔离

Shell 不是单独的可信组件。隔离边界包裹完整 QwenPaw Runtime，因而 Agent
后续启动的 Shell、MCP、插件和其他子进程都会继承同一个 OS sandbox。

启动流程必须 fail closed：

```text
创建 Runtime 目录
      ↓
生成平台隔离策略
      ↓
执行允许读写自身目录、禁止读取兄弟 Runtime 的主动探针
      ↓
探针通过 → 启动完整 QwenPaw 进程树
探针失败 → Runtime 标记 failed，不执行裸 Popen
```

macOS 使用 deny-default Seatbelt 写策略，只允许写当前 Runtime root；对 Pro
控制面目录和用户主目录设置读取拒绝，再为当前 Runtime、QwenPaw 代码和 Python
环境添加更具体的只读许可。`signal` 和 `process-info` 只允许
`target same-sandbox`，因此租户 Shell 不能观察或向兄弟 Runtime 发送信号。

Linux 使用 Bubblewrap 创建 user、PID、IPC 和 UTS namespace，丢弃全部
capability，以空文件系统开始，只读挂载系统/Python/QwenPaw 代码，只把当前
Runtime root 可写挂载，并提供私有 `/tmp`、`/dev` 和 `/proc`。兄弟 Runtime
目录和控制面数据库不会出现在 mount namespace 中。

所有平台还必须满足：

- Runtime 仅绑定 loopback；
- 每个 Runtime 使用保存在对应 tenant/runtime vault scope 的随机内部 token；
- 内部 token 在普通 QwenPaw 认证之前保护全部 HTTP 和 WebSocket 路径；
- Runtime 不继承控制面 Provider/API Key，只注入本租户解析出的凭据；
- 每个 Runtime 使用独立进程组，停止和强制停止作用于整棵派生进程树，避免后台
  Shell 在主 Agent 退出后残留；
- 隔离器缺失、策略编译失败或主动探针失败时禁止启动；
- Windows AppContainer 长进程 adapter 完成前不允许回退到普通进程。

macOS 默认允许公网出站，但禁止 Runtime 连接其他 loopback 端口，只开放自身
监听端口的 bind/inbound；主动探针会尝试连接另一个临时 loopback 服务，连接
成功则拒绝启动。Linux 第一版为了访问 LLM 和外部渠道仍共享主机网络栈，跨
Runtime QwenPaw API 访问依靠不可跨目录读取的内部 token 阻断，其他本机服务
仍需通过未来的 network broker 或容器网络隔离。

CPU、内存、磁盘和网络带宽的硬配额尚未由 cgroup、Job Object 或容器落实。
因此本地模式解决文件读写、凭据、进程观察/信号、残留子进程和 Runtime API
串租；在 Linux network broker 完成前不将其描述为完整的不可信 SaaS 租户
隔离，也不宣称能够抵抗资源耗尽型 DoS。

## Tenant Credential Vault

Pro 控制面不允许把 Provider API Key、OAuth token、MCP credential 或其他密钥
保存为无租户归属的全局值。保管箱的逻辑主键至少包含：

```text
(tenant_id, scope, credential_name)
```

其中 `scope` 第一版支持 `tenant` 和 `runtime:<runtime_id>`。解析顺序先读取
Runtime scope，再叠加 tenant scope；不允许回退到其他 tenant 或控制面进程的
环境变量。任何内存缓存也必须使用完整三元组作为 key。

SQLite 只保存密文和非敏感元数据：

```text
tenant_credentials
  tenant_id
  scope
  credential_name
  encrypted_value
  created_at
  updated_at
  primary key (tenant_id, scope, credential_name)
```

本地保管箱使用 Pro 专属 master key 加密。控制面 token signing key 使用保留的
system tenant scope 存入同一保管箱，不能明文保存在 settings 表。Runtime 启动
时只注入目标 tenant/runtime 解析出的凭据，并过滤控制面父进程里的 API Key、
token 和 secret 环境变量。

未来 Docker driver 将凭据作为容器 secret 注入，Kubernetes driver 将其映射到
tenant namespace 下的 Secret；控制 API 和 scope 语义保持不变。

Docker driver 的最低契约将是每租户独立容器、非 root、禁止任意 volume、禁止
Docker socket、默认断网、资源配额和 fail-closed。Kubernetes driver 将使用
独立 Pod、ServiceAccount、PVC、NetworkPolicy 和 ResourceQuota。

## 验收标准

- `qwenpaw app` 行为和参数兼容性保持不变。
- `qwenpaw app --pro` 启动 Pro 控制面。
- 能通过控制 API 创建并启动至少两个本地 Runtime。
- 两个 Runtime 使用不同端口和不同数据、密钥、备份、日志目录。
- 停止一个 Runtime 不影响另一个 Runtime。
- 重复创建、非法 Runtime ID、端口冲突和启动失败返回明确错误。
- Windows、Linux 和 macOS 使用相同的路径与进程生命周期语义。
- Runtime driver、registry、API 和 CLI 具有单元测试。
- 首个注册用户成为管理员，后续默认禁止公开注册。
- 普通用户不能列出、启动、停止或删除其他用户的 Runtime。
- 普通用户不能访问用户管理和注册策略接口。
- 禁用账号或修改角色后，旧 token 立即失效。
- tenant A 无法列出、覆盖、解析或删除 tenant B 的任何 credential。
- Runtime 子进程不会继承控制面环境里的 Provider/API Key。

## 实施 checklist

- [x] Fetch `upstream` 并创建独立功能分支/worktree。
- [x] 确认启动命令为 `qwenpaw app --pro`。
- [x] 冻结本地 MVP、安全边界和 RuntimeDriver 契约。
- [x] 将本地安全边界升级为完整进程树 fail-closed 隔离。
- [x] 实现 macOS Seatbelt 和 Linux Bubblewrap Runtime isolator。
- [ ] 实现 Windows AppContainer 长进程 isolator。
- [x] 实现 Runtime 数据模型和 driver protocol。
- [x] 实现 SQLite runtime registry。
- [x] 实现 `LocalProcessRuntimeDriver`。
- [x] 实现 Pro 用户、角色、token 和注册策略。
- [x] 将 Runtime ownership 绑定到稳定 user ID。
- [x] 实现 tenant-scoped CredentialVault 与按 Runtime 注入。
- [x] 实现内部 Runtime token 的 HTTP/WebSocket 强制校验。
- [x] 实现 Pro 控制面 API 与生命周期管理。
- [x] 实现管理员账号管理和 Runtime Console。
- [x] 根路径进入用户自己的完整 QwenPaw，普通 API 透明代理到隔离 Runtime。
- [x] 将管理员管控台收敛到独立 `/pro/admin` 页面。
- [x] 接入 `qwenpaw app --pro`。
- [x] macOS 完整 Runtime 启动/停止和跨 Runtime 读取负向探针通过。
- [x] Pro 注册、创建/启动 Runtime、直接端口 401 和停止端到端测试通过。
- [x] Console TypeScript 检查和 production build 通过。
- [x] conda `QwenPaw` 环境相关测试通过。
- [x] 同步 conda `QwenPaw` 环境到仓库锁定的 AgentScope 版本，并验证
      `InjectionConfig` 可导入。
- [x] 将 Pro 管理页面视觉、布局和交互统一到 QwenPaw 设计语言。
- [x] 补齐 Pro 管理页面暗色模式与桌面、平板、手机响应式布局。
- [x] 定义 `--config`、backend 选择和 tenant quota 配置边界。
- [x] 实现严格、版本化的 Pro YAML 配置加载与字段级持久化导入。
- [x] 将配置中的注册策略回写 SQLite，并保留管理员 UI 修改能力。
- [x] 配置默认/允许 Runtime driver 与 tenant Runtime 准入限制。
- [x] 补齐配置解析、覆盖优先级、quota 和 CLI 单元测试。
- [x] 为 Pro 控制面提供公开只读 `/api/version`，避免 Console 探针 401。
- [x] 验证版本探针不认证、不创建或启动租户 Runtime。
- [x] 完成 UI 回归、后端测试、生产构建和本地端到端验证。
- [x] 整理 scope、用法、安全边界和测试结果并创建 Draft PR。
- [ ] 增加 Windows adapter 和三平台隔离集成测试。
- [x] conda `QwenPaw` 环境完整 unit suite 通过（7325 passed，20 skipped）。

## 参考

- <https://github.com/containers/bubblewrap>
- <https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt_base_policy.sbpl>
- <https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation>
