# QwenPaw Hub：部署与管理多租户 QwenPaw

QwenPaw Hub 是面向自托管多用户场景的统一入口。管理员只需维护一个 Hub，每个账户即可使用自己的 QwenPaw 运行环境，并拥有分别存放的工作目录、配置、凭据和会话。

Hub 不会替代或改变原有的单机 QwenPaw App。个人设备仍然可以使用 `qwenpaw app`；只有需要集中管理多个账户时，才需要启动 `qwenpaw hub`。

> **重要安全边界：当前 Hub 不提供每个用户独立的内核。** Linux Local 使用 Bubblewrap namespace，macOS Local 使用 Seatbelt，Windows Local 使用 AppContainer 和 Job Object；三者都是共享宿主机内核的进程沙箱。Docker 使用容器隔离，所有 Hub 容器共享 Docker Engine 所使用的 Linux 内核。在 Windows 或 macOS 的 Docker Desktop/虚拟机环境中，这通常是 Docker Linux VM 的内核，而不是 Windows 或 macOS 宿主内核，但仍不是一租户一内核。以上机制可以限制文件、进程权限和运行环境访问范围，却不能等同于每个用户一台虚拟机或 MicroVM。对于彼此不信任的用户或更高风险的多租户部署，应在 Hub 外增加独立虚拟机、专用节点或其他更强的基础设施隔离。

![Hub 登录页与用户条款弹窗](https://img.alicdn.com/imgextra/i2/O1CN01hhIGAbMm89B6lBsc_!!6000000006867-2-tps-3330-1772.png)

## Hub 与单机 App 的区别

| 能力     | `qwenpaw app`               | `qwenpaw hub`                  |
| -------- | --------------------------- | ------------------------------ |
| 使用场景 | 个人设备、单用户            | 自托管、多用户                 |
| 登录身份 | 当前 QwenPaw 实例的本地认证 | Hub 统一账户                   |
| 运行环境 | 一个本机进程                | 每个账户一个独立运行环境       |
| 数据目录 | 默认 `~/.qwenpaw`           | Hub 根目录下按运行环境隔离     |
| 运维入口 | QwenPaw Console             | Hub 管理中心与个人 QwenPaw     |
| 运行方式 | 本机进程或手工部署的容器    | 管理员统一选择 Local 或 Docker |

登录 Hub 后，普通用户会被转发到自己的 QwenPaw Console。管理员还可以进入 Hub 管理中心，管理账户、运行环境、访问安全和 Docker 策略。

## 系统要求

运行 Hub 前请确认：

- 已安装当前版本的 QwenPaw，Python 版本要求与普通 QwenPaw 相同；
- Console 前端资源已经包含在安装包中，或已在源码目录完成构建；
- 选择 Local 后端时，宿主机具备受支持的操作系统隔离能力；
- 选择 Docker 后端时，Hub 进程能够访问运行 Linux 容器的 Docker Engine；
- 对外提供服务时，已经准备可信网络或 HTTPS 反向代理。

Local 后端和 Docker 后端的具体要求将在本文的运行环境章节中说明。

## 安装

通过 PyPI 安装 Hub 可选依赖：

```bash
pip install "qwenpaw[hub]"
```

`hub` extra 包含 Docker 后端所需的 Docker SDK；普通的 `pip install qwenpaw` 不会安装它，也不会改变原有 QwenPaw App 主链路。即使只准备使用 Local 后端，也建议为运行 Hub 的环境安装该 extra，以便管理中心能够探测和展示 Docker 后端状态。

已有 QwenPaw 安装无需为 Hub 创建另一套环境，可以在原环境补装 `hub` extra，然后确认当前版本已经包含 `hub` 命令：

```bash
pip install -U "qwenpaw[hub]"
```

```bash
qwenpaw hub --help
```

## 初始化第一个管理员

Hub 默认只监听回环地址，而且不会允许一个尚未初始化管理员的实例直接暴露到公网。推荐先在服务器上以回环模式启动：

```bash
qwenpaw hub --host 127.0.0.1 --port 8000
```

如果是在远程服务器上初始化，可以从管理电脑建立 SSH 端口转发：

```bash
ssh -L 8000:127.0.0.1:8000 user@example.com
```

然后打开 `http://127.0.0.1:8000/`。首次注册的账户会自动成为管理员。创建完成后停止当前 Hub，再继续配置正式访问地址。

> 请为第一个管理员使用独立、高强度密码，并确保至少保留一个未禁用的管理员账户。

## 创建启动配置

以下示例使用 Local 后端，并允许管理员在初始化后开启普通用户注册：

```yaml
version: 1

control_plane:
  public_base_url: https://qwenpaw.example.com
  registration:
    enabled: true
    default_role: user
  security:
    ip_blacklist: []
    trusted_proxy_ips:
      - 127.0.0.1/32
    login_rate_limit:
      enabled: true
      max_attempts: 10
      window_seconds: 300
      block_seconds: 900
    registration_rate_limit:
      enabled: true
      max_attempts: 5
      window_seconds: 3600
      block_seconds: 3600
  proxy:
    max_request_size_mb: 1024
    request_idle_timeout_seconds: 60
    response_header_timeout_seconds: 300
    connect_timeout_seconds: 10
    websocket_max_message_size_mb: 16

runtime:
  provisioner: local

capacity:
  max_running_runtimes: 20
```

保存为 `hub.yaml`。完整字段和生效规则将在本文的配置章节中说明。

### YAML 与管理面板的优先级

Hub 是否采用 YAML，取决于启动时有没有显式传入 `--config`：

1. 使用 `--config hub.yaml` 启动时，每次都会读取并校验 YAML，再将完整配置写入数据库；
2. 不传 `--config` 时，Hub 使用数据库中由管理面板保存的配置；
3. 管理面板的修改会立即写入数据库；
4. 如果下一次仍携带 YAML 启动，YAML 会重新覆盖数据库中的对应配置。

因此，部署者可以选择“YAML 托管”或“面板托管”。长期使用 YAML 托管时，应把文件纳入安全的配置管理，并理解面板中的临时修改会在下一次携带 YAML 启动时被覆盖。

## 对外启动 Hub

完成管理员初始化并设置 `public_base_url` 后，可以显式允许非回环监听：

```bash
qwenpaw hub \
  --host 0.0.0.0 \
  --port 8000 \
  --force-public \
  --config hub.yaml
```

`--force-public` 只允许 Hub 监听外部地址，**不会提供 TLS**。不要把未加密的 HTTP 直接暴露到不可信网络。生产或团队环境应在 Hub 前配置 HTTPS 反向代理，并将 `public_base_url` 设置为浏览器实际访问的地址，例如：

```yaml
control_plane:
  public_base_url: https://qwenpaw.example.com
```

这个地址也用于生成 OpenRouter、MCP 等集成的 OAuth 回调地址。协议、域名、端口或路径不正确时，授权提供方可能拒绝回调。

## 首次使用

用户打开 Hub 地址后，需要先阅读并同意用户条款，再登录或注册。登录成功后，Hub 会为该账户查找或创建个人运行环境，并将浏览器请求代理到对应的 QwenPaw Console。

普通用户可以：

- 使用自己的 QwenPaw Console；
- 管理自己的模型与集成凭据；
- 修改自己的密码；
- 在运行环境失败或被普通停止后自行重启；
- 查看运行环境限制和状态提示。

普通用户不能选择运行环境后端、Docker 镜像或资源上限。这些策略由管理员统一设置。

![普通用户的个人运行环境状态与重启入口](https://img.alicdn.com/imgextra/i2/O1CN01q71ewupZntB6lRUM_!!6000000000685-2-tps-3332-1770.png)

## 运行环境模型

一个个人账户对应一个租户和一个默认运行环境。Hub 会保存稳定的所有者关系、工作目录、私密目录、备份目录、当前后端、运行状态和启动权限。

管理中心的“所有者”优先显示用户名，并同时保留完整用户 ID。用户名便于识别和搜索，稳定用户 ID 则用于数据关联；即使账户之后被删除，历史运行环境也会回退显示用户 ID。

普通用户不能选择后端、Docker 镜像或资源限制。管理员在「系统设置 → 运行环境」统一选择 Local 或 Docker，所有新建及重启的运行环境遵循同一策略。

### 切换后端

保存新的全局后端不会直接中断正在工作的运行环境。对某个运行环境执行“重启”时，Hub 会停止旧后端，并按照管理员当前策略重新启动。因此，从 Local 切换到 Docker 后，应重启需要切换的运行环境，并在列表中确认后端已经更新。

## Local 后端：进程级隔离

Local 后端在宿主机上启动 QwenPaw 进程，但不会在隔离能力缺失时退化成普通进程。启动前会执行隔离探测，失败时拒绝启动运行环境。

| 平台    | 隔离方式                  | 要求                                                                                                             |
| ------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Linux   | Bubblewrap                | 已安装并可执行 `bwrap`，内核允许所需 namespace                                                                   |
| macOS   | Seatbelt                  | 系统提供可用的 `sandbox-exec`                                                                                    |
| Windows | AppContainer + Job Object | Windows 10 1507（build 10240）或更高版本；Hub 以管理员权限运行；系统提供 `icacls.exe` 和 `CheckNetIsolation.exe` |

三个平台都采用默认拒绝的文件系统边界，只开放运行所需的只读系统路径和当前运行环境的数据目录。Windows 还使用 Job Object 管理完整进程树，确保停止运行环境时一并终止子进程。

Windows AppContainer 默认不能直接连接宿主机 loopback。Hub 会在运行环境存续期间为对应 AppContainer SID 启用 Windows loopback exemption，由 AppContainer 主动建立到 Hub 的反向 TCP 隧道，Hub 再通过该隧道代理其中的 QwenPaw；运行环境停止时会同时撤销规则并关闭隧道。这项规则也允许 Windows Local 访问宿主机上的其他 loopback 服务，因此它提供的是文件系统和进程边界，不提供独立网络边界。管理员权限、ACL、AppContainer、Job Object、规则配置、反向隧道或真实运行环境健康检查任一失败，Local 后端都会拒绝启动，而不会退化成未隔离进程。

这属于**进程和文件系统访问控制**，不是内核隔离。所有 Local 运行环境仍使用宿主机内核，不能视为虚拟机、MicroVM 或针对恶意租户的强安全边界。

![系统设置中的 Local/Docker 后端选择](https://img.alicdn.com/imgextra/i3/O1CN01IJbgQoGjpaL6lBso_!!6000000000707-2-tps-3330-1784.png)

## Docker 后端：容器级隔离

Docker 后端要求 Hub 能连接运行 Linux 容器的 Docker Engine。Linux、Windows 和 macOS 都必须满足这个要求；Windows/macOS 通常通过 Docker Desktop、WSL2 或 Linux 虚拟机提供 Linux 容器。每个账户使用独立容器，并遵守以下约束：

- 服务端口只随机发布到宿主机 `127.0.0.1`；
- 禁止容器获得新的 Linux privilege；
- 使用用户不可覆盖的内部边界 Token；
- Docker 不自动重启容器，生命周期由 Hub 管理；
- 用户数据从宿主机稳定目录挂载，不写进容器临时层。

Docker 提供容器级进程、文件系统和资源隔离，但同一个 Docker Engine 中的 Hub 容器共享该 Engine 使用的 Linux 内核。在原生 Linux 上通常是宿主机内核；在 Windows/macOS Docker Desktop 环境中通常是 Docker Linux VM 的内核。容器逃逸、Linux 内核漏洞以及 Docker daemon 权限都属于部署者需要管理的风险。需要每个租户独立的内核边界时，应为租户使用独立虚拟机、MicroVM、专用节点或其他基础设施隔离。

### 镜像来源

| 来源              | 镜像仓库                                                                |
| ----------------- | ----------------------------------------------------------------------- |
| Docker Hub 官方源 | `docker.io/agentscope/qwenpaw`                                          |
| 阿里云官方源      | `agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw` |
| 自定义镜像        | 管理员填写完整镜像引用                                                  |

官方源支持对应仓库的发布 Tag。自定义镜像既可以来自远程仓库，也可以使用宿主机已经存在的本地镜像 Tag，例如：

```text
qwenpaw-hub-custom:2026-08
```

使用本地 Tag 时，应选择“从不拉取”，避免 Docker 尝试从远程仓库下载同名镜像。

### 拉取策略

| 策略             | 行为                         |
| ---------------- | ---------------------------- |
| `always`         | 使用前始终拉取               |
| `if_not_present` | 本地存在时直接使用，否则拉取 |
| `never`          | 只使用宿主机已有镜像         |

系统设置会展示最终使用的完整镜像引用、仓库、Tag、本地状态以及 digest 或镜像 ID。管理员可以在镜像详情中立即拉取，并查看任务进度。

Docker 运行环境创建后会记录实际镜像 ID/digest，避免同名 Tag 更新后在普通启动中悄悄改变版本。“重建”会停止当前容器、清除旧固定信息，并按当前全局镜像策略创建新容器，同时继续挂载原有数据。

### 资源限制

| 字段              | 默认值 | 说明                         |
| ----------------- | ------ | ---------------------------- |
| `cpu_limit`       | `2.0`  | 每个容器的 CPU 配额          |
| `memory_limit_mb` | `4096` | 内存上限，最小 256 MiB       |
| `pids_limit`      | `1024` | 进程数量上限，最小 64        |
| `shm_size_mb`     | `512`  | `/dev/shm` 大小，最小 64 MiB |

CPU、内存和 PID 留空表示不设置对应限制。调整限制后，应重启或重建相关运行环境。`capacity.max_running_runtimes` 控制整个 Hub 同时运行的环境数量，并不是为一个租户创建多个环境。

![Docker 镜像详情、立即拉取和资源限制](https://img.alicdn.com/imgextra/i2/O1CN01M5zUCZUwvZG6nhyY_!!6000000002043-2-tps-3350-1784.png)

## 数据目录与持久化

Hub 根目录默认位于 `<QWENPAW_WORKING_DIR>/hub/`。如果没有设置 `QWENPAW_WORKING_DIR`，QwenPaw 工作目录默认是 `~/.qwenpaw`。

```text
<QWENPAW_WORKING_DIR>/hub/
├── control.db
├── secrets/
└── runtimes/
    └── <runtime-id>/
        ├── working/
        ├── secret/
        ├── backups/
        └── logs/
```

管理界面显示的 `/mnt/.../hub/runtimes/.../working` 一类路径，是宿主机上的真实持久化路径。Docker 后端按以下方式挂载：

| 宿主机目录 | 容器内目录             |
| ---------- | ---------------------- |
| `working/` | `/app/working`         |
| `secret/`  | `/app/working.secret`  |
| `backups/` | `/app/working.backups` |

停止、重启、容器重建或 Local/Docker 切换不会主动删除这些目录。删除运行环境只退休注册记录，也会保留磁盘数据，避免一次管理误操作造成不可恢复的数据丢失。

## 生命周期与启动权限

Hub 分别记录观察状态、期望状态和启动权限，避免用户访问或自动恢复覆盖管理员操作。

| 操作            | 结果                       | 用户能否自行启动 |
| --------------- | -------------------------- | ---------------- |
| 停止            | 物理停止进程或容器         | 可以             |
| 禁止启动        | 停止并改为仅管理员可启动   | 不可以           |
| 用户重启        | 按当前全局后端策略重新启动 | 仅未被禁止时可以 |
| 管理员启动/重启 | 按当前全局策略启动         | 可以             |
| Docker 重建     | 按当前镜像策略重建容器     | 仅管理员         |
| 删除            | 删除注册记录，保留磁盘数据 | 不适用           |

运行环境失败时，个人账户页面会提供重启入口。管理员执行“禁止启动”后，用户刷新页面或继续使用都不会让运行环境自动恢复。

## 用户与管理员管理

首次注册的账户自动成为管理员。公开监听要求数据库中至少存在一个未禁用的管理员。

管理员不能修改自己的角色或禁用自己，系统也不允许操作导致 Hub 失去最后一个有效管理员。需要调整管理员权限时，应先创建或提升另一个管理员，并验证其可以登录。

普通用户不能修改用户名和角色，只能修改自己的密码。用户名用于显示和搜索，用户 ID 才是稳定的所有权标识。

## 登录、注册与 IP 防护

团队内部部署建议关闭自助注册，由管理员创建账户。需要开放注册时，应同时启用注册限流。

登录和注册限流按客户端 IP 统计，分别配置最大尝试次数、统计窗口和封禁时间。IP 黑名单支持 IPv4、IPv6 和 CIDR。

只有请求直接来自 `trusted_proxy_ips` 中的地址时，Hub 才信任 `X-Forwarded-For`。不要把 `0.0.0.0/0` 设置为可信代理，否则客户端可能伪造来源 IP 绕过黑名单和限流。

## 配置字段总览

| 字段                                                  | 说明                                   |
| ----------------------------------------------------- | -------------------------------------- |
| `version`                                             | 配置结构版本，当前必须为 `1`           |
| `control_plane.public_base_url`                       | 浏览器实际访问地址和 OAuth 回调基址    |
| `control_plane.registration.enabled`                  | 是否允许自助注册                       |
| `control_plane.registration.default_role`             | 注册账户角色，当前固定为 `user`        |
| `control_plane.security.ip_blacklist`                 | IP 地址或 CIDR 黑名单                  |
| `control_plane.security.trusted_proxy_ips`            | 可以提供真实客户端地址的代理           |
| `control_plane.security.login_rate_limit`             | 登录失败限流                           |
| `control_plane.security.registration_rate_limit`      | 注册限流                               |
| `control_plane.proxy.max_request_size_mb`             | 代理请求体上限，默认 1024 MiB          |
| `control_plane.proxy.request_idle_timeout_seconds`    | 请求体连续无数据超时，默认 60 秒       |
| `control_plane.proxy.response_header_timeout_seconds` | 运行环境响应头超时，默认 300 秒        |
| `control_plane.proxy.connect_timeout_seconds`         | 连接运行环境超时，默认 10 秒           |
| `control_plane.proxy.websocket_max_message_size_mb`   | WebSocket 单条消息上限，默认 16 MiB    |
| `runtime.provisioner`                                 | `local` 或 `docker`                    |
| `runtime.docker.source`                               | `docker_hub`、`aliyun_acr` 或 `custom` |
| `runtime.docker.image`                                | 完整镜像引用                           |
| `runtime.docker.pull_policy`                          | `always`、`if_not_present` 或 `never`  |
| `runtime.docker.*_limit`                              | 容器 CPU、内存和 PID 上限              |
| `runtime.docker.shm_size_mb`                          | 容器共享内存大小                       |
| `capacity.max_running_runtimes`                       | Hub 全局并发运行数量上限               |

配置采用严格校验，未知字段会导致启动或保存失败，避免拼写错误被静默忽略。Local 模式不会应用 Docker 设置，但会保留它们，方便之后切换回 Docker。

代理的请求大小和空闲超时只约束上传方向。运行环境返回响应头后，SSE、Agent 流式响应和流式下载不设置总时长或响应体大小限制，连接会持续到任一端主动断开。

## 凭据隔离

每个租户的模型 API Key 和集成凭据由 Hub 凭据库独立保存，并只注入对应运行环境。内部边界 Token 属于 Hub 系统作用域，用户凭据不能覆盖它。

Hub 会拒绝用户用凭据名覆盖 `PATH`、`PYTHON*`、`QWENPAW_*`、`LD_*` 等控制运行环境或动态加载行为的变量。部署者也不应通过宿主机环境变量无意间向所有租户共享敏感密钥。

## OAuth 回调

Hub 代理运行环境中的 OAuth 流程，使第三方提供方回调到公开 Hub，再路由到正确的用户运行环境。回调地址基于 `public_base_url` 生成：

```text
https://qwenpaw.example.com/api/hub/oauth/callback/<runtime-id>/<route>
```

OpenRouter 或其他 OAuth 授权失败时，应确认：

1. `public_base_url` 与浏览器实际地址完全一致；
2. HTTPS 反向代理保留 Host、Scheme 和 WebSocket 升级头；
3. 第三方应用允许该回调地址；
4. 运行环境属于当前用户且可以访问；
5. 第三方没有因重复应用或账户策略拒绝创建授权码。

部分 MCP 服务没有发布 OAuth Protected Resource Metadata，Hub 无法自动发现授权服务器。这种情况下，需要按服务运营方提供的信息手工填写 `auth_endpoint` 和 `token_endpoint`。

## 审计与监控

Hub 提供轻量运维数据：用户和运行环境数量、状态分布、后端可用性、分页筛选以及经过清理的管理操作审计。

这些数据不等同于完整的指标、日志、追踪和告警平台。生产部署仍应监控 Hub 与反向代理日志、主机 CPU/内存/磁盘、Docker 状态、HTTP 延迟、错误率、WebSocket 断开以及备份结果。

## 备份与升级

至少备份：

```text
<QWENPAW_WORKING_DIR>/hub/control.db*
<QWENPAW_WORKING_DIR>/hub/secrets/
<QWENPAW_WORKING_DIR>/hub/runtimes/
```

`control.db` 保存账户、配置、运行环境注册和审计；`secrets/.vault_key` 是解密凭据与系统密钥所需的关键材料；`runtimes/` 保存用户工作区、私密配置、备份和日志。三者必须作为一套备份。

升级前应停止 Hub，创建整个 `hub/` 根目录的一致性备份，记录当前版本，升级后验证管理员登录、用户分页、运行环境代理、WebSocket 和 OAuth 回调。数据表预留了版本、修订、JSON 扩展和软删除字段，以减少未来增加属性时的破坏性变更，但这不能替代升级前备份。

## 常见问题

### Hub 拒绝公开监听

确认已经通过 loopback 创建未禁用的管理员，配置了 `public_base_url`，并显式传入 `--force-public`。

### 页面长时间白屏

检查 `index.html`、JS/CSS chunk 是否都返回正确内容，反向代理是否缓存了旧入口，以及部署是否同时更新了新的静态资源。入口 HTML 与带 hash 的静态资源不能使用同一套长期缓存策略。

### 选择 Docker 后仍显示 Local

保存设置不会直接中断正在运行的实例。对该运行环境执行重启，再确认列表中的后端和安全级别。

### 本地镜像提示无法拉取

选择自定义镜像，填写 `docker image ls` 中存在的完整 Repository:Tag，并把拉取策略设为 `never`。

### 登录后个人页面加载失败

在运行环境列表确认所有者、状态和后端。失败状态会保留最近错误；普通停止允许用户重启，禁止启动需要管理员恢复。

### 聊天页面可以打开但流式连接失败

确认反向代理支持 WebSocket Upgrade。客户端不应直接访问宿主机 `127.0.0.1` 上的运行环境端口。

### OAuth 回调仍指向 `127.0.0.1`

检查当前生效的 `public_base_url`。如果使用 YAML 托管，修改 YAML 后需携带 `--config` 重启；如果不使用 YAML，则在管理面板保存。

## 管理员的下一步

初始化完成后，建议按以下顺序检查：

1. 在「系统设置 → 访问安全」确认注册、限流、IP 黑名单和可信代理；
2. 在「系统设置 → 运行环境」选择 Local 或 Docker；
3. 如果选择 Docker，确认镜像、拉取策略和资源限制；
4. 在「用户管理」创建或审核账户；
5. 在「运行环境」确认每个账户的状态和后端；
6. 在「审计」检查关键管理操作。

## 部署边界

QwenPaw Hub 是自托管软件。部署者能够控制服务器、数据库、备份和进程，也可能接触用户在该实例中保存的数据。用户只应登录本人或可信组织运营的 Hub。

Hub 中的 QwenPaw 运行在受约束的进程或容器中，文件、进程、设备和网络能力可能不同于个人电脑上的完整 QwenPaw。Linux、macOS 和 Windows 的 Local 运行环境共享各自的宿主机内核；Docker 运行环境共享 Docker Engine 使用的 Linux 内核。Hub 不提供每个用户独立的内核沙箱。这些机制可以降低账户之间相互影响的风险，但不能替代虚拟机级租户隔离、主机加固、网络隔离、HTTPS、备份、监控和组织自身的安全制度。
