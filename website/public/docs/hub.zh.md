# QwenPaw Hub

QwenPaw Hub 用于在一台服务器上为团队提供 QwenPaw。团队成员通过同一个地址登录，但每个人使用自己的 QwenPaw，工作区、配置、凭据和会话分别保存。

如果只是自己在电脑上使用 QwenPaw，请继续使用桌面版 App。只有需要在服务器上统一管理多个用户时，才需要部署 Hub。

> QwenPaw Hub 从 QwenPaw 2.2.0 版本开始在非桌面版中提供。桌面版是面向个人的 App，不包含 Hub；旧版本也没有 `qwenpaw hub` 命令。

> Hub 2.2.0 是一个早期版本，目前只面向成员彼此信任的内部团队。即使配置了 HTTPS 和公网访问，也不应将当前版本作为面向陌生用户的公网多租户服务。

![Hub 登录页与用户条款弹窗](https://img.alicdn.com/imgextra/i2/O1CN01hhIGAbMm89B6lBsc_!!6000000006867-2-tps-3330-1772.png)

## Hub 适合什么场景

Hub 适合公司、实验室或小型团队在自己的服务器上为可信成员提供 QwenPaw。管理员可以：

- 创建和管理账户；
- 统一选择 Local 或 Docker 运行方式；
- 查看、停止和重启用户的运行环境；
- 设置 Docker 镜像、资源上限和访问规则；
- 保留用户数据，并集中完成备份和升级。

Hub 是自托管软件，不是 QwenPaw 团队代为运营的云服务。服务器管理员能够访问服务器、数据库和备份，因此用户应只使用自己或可信组织部署的 Hub。

## 安装

Hub 需要非桌面版 QwenPaw 2.2.0 或更高版本。通过 Python 包安装或升级 QwenPaw，并启用 Hub 可选依赖：

```bash
pip install -U "qwenpaw[hub]"
```

确认命令已经可用：

```bash
qwenpaw hub --help
```

## 第一次启动

先让 Hub 只监听本机地址：

```bash
qwenpaw hub --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/` 并注册账户。第一个注册的账户会自动成为管理员。

如果 Hub 运行在远程服务器上，可以通过 SSH 端口转发完成初始化：

```bash
ssh -L 8000:127.0.0.1:8000 user@example.com
```

随后在自己的电脑上打开 `http://127.0.0.1:8000/`。

> 请为第一个管理员设置高强度密码。添加其他管理员后，也应始终保留至少一个可登录的管理员账户。

## 选择运行方式

进入「系统设置 → 运行环境」，选择 Local 或 Docker。这个选择由管理员统一管理，普通用户无需了解端口、容器或宿主机路径。

|              | Local                          | Docker                         |
| ------------ | ------------------------------ | ------------------------------ |
| 适合场景     | 内部团队、快速部署             | 长期运行、需要明确资源限制     |
| 运行方式     | 每个用户一个宿主机进程         | 每个用户一个容器               |
| 环境要求     | 操作系统具备对应的进程隔离能力 | 可访问运行 Linux 容器的 Docker |
| 资源限制     | 依赖宿主机                     | 可限制 CPU、内存和进程数       |
| 用户数据位置 | Hub 数据目录                   | Hub 数据目录，通过挂载进入容器 |

### Local

Local 直接使用宿主机上的 QwenPaw 和 Python 环境：

- Linux 需要安装并启用 Bubblewrap（`bwrap`）；
- macOS 需要系统提供可用的 `sandbox-exec`；
- Windows 需要 Windows 10 1507 或更高版本，并以管理员权限运行 Hub。

Hub 会在启动用户环境前检查隔离能力。如果检查失败，环境不会以无隔离的普通进程继续运行。

### Docker

Docker 模式要求 Hub 能访问运行 Linux 容器的 Docker Engine。Windows 和 macOS 通常通过 Docker Desktop 提供该环境。

管理员可以使用官方镜像，也可以填写自己的镜像地址。仅使用宿主机已有镜像时，将拉取策略设置为 `never`。默认资源限制为：

| 资源       | 默认值   |
| ---------- | -------- |
| CPU        | 2 核     |
| 内存       | 4096 MiB |
| 进程数     | 1024     |
| `/dev/shm` | 512 MiB  |

修改运行方式、镜像或资源限制后，已经在运行的环境不会立即中断。重启对应环境后，新设置才会应用；更换镜像版本时使用“重建”。

当前 Docker 资源限制是由管理员为所有容器统一设置的上限。Hub 尚未支持按用户配置不同配额、资源用量统计、多机容量调度或弹性扩缩容；Local 也没有与容器相同的资源限制能力。

![系统设置中的 Local/Docker 后端选择](https://img.alicdn.com/imgextra/i3/O1CN01IJbgQoGjpaL6lBso_!!6000000000707-2-tps-3330-1784.png)

## 让可信团队远程访问 Hub

需要让内部成员从其他设备或网络访问时，建议使用 HTTPS 反向代理，并把浏览器实际访问的地址配置为 `public_base_url`。

创建 `hub.yaml`：

```yaml
version: 1

control_plane:
  public_base_url: https://qwenpaw.example.com
  registration:
    enabled: false
    default_role: user

runtime:
  provisioner: local

capacity:
  max_running_runtimes: 20
```

然后启动 Hub：

```bash
qwenpaw hub \
  --host 0.0.0.0 \
  --port 8000 \
  --force-public \
  --config hub.yaml
```

`--force-public` 只允许 Hub 监听外部地址，不会自动配置 TLS。不要把未加密的 HTTP 服务直接暴露到不可信网络。

这里的“外部地址”只表示允许可信成员远程连接，不代表 Hub 已经适合开放注册或面向陌生用户运营。HTTPS、登录限流和 IP 黑名单能够保护入口，但不会增强用户运行环境之间的内核隔离。

如果启动时传入 `--config`，YAML 会成为本次启动的配置来源，并覆盖管理面板中对应的设置。如果希望以后只在管理面板修改设置，后续启动时不要再传入 `--config`。

### 反向代理需要支持什么

反向代理需要：

- 将请求转发到 Hub 的监听地址；
- 保留正确的 Host 和协议；
- 支持 WebSocket Upgrade；
- 为入口页面和带 hash 的静态资源设置合适的缓存策略。

`public_base_url` 也用于生成 OpenRouter、MCP 等集成的 OAuth 回调地址，因此必须与用户在浏览器中访问的地址一致。

## 管理用户

团队内部使用时，建议关闭自助注册，由管理员在「用户管理」中创建账户。如果希望可信成员自行注册，应先限制入口访问范围并启用注册限流；不要向陌生用户开放注册。

普通用户登录后会直接进入自己的 QwenPaw Console，可以管理自己的对话、文件、模型配置和集成凭据。用户不能选择运行方式、Docker 镜像或资源限制。

管理员可以查看每个用户的运行状态，并执行以下操作：

| 操作        | 效果                                 |
| ----------- | ------------------------------------ |
| 停止        | 停止进程或容器，用户之后可以自行启动 |
| 禁止启动    | 停止环境，并阻止用户自行恢复         |
| 重启        | 使用当前全局设置重新启动             |
| Docker 重建 | 使用当前镜像策略重新创建容器         |
| 删除        | 删除运行环境记录，但保留磁盘数据     |

运行环境失败或被普通停止后，用户可以在个人页面自行重启。管理员执行“禁止启动”后，只能由管理员恢复。

![普通用户的个人运行环境状态与重启入口](https://img.alicdn.com/imgextra/i2/O1CN01q71ewupZntB6lRUM_!!6000000000685-2-tps-3332-1770.png)

## 数据保存在哪里

Hub 数据默认保存在 `~/.qwenpaw/hub/`。如果设置了 `QWENPAW_WORKING_DIR`，则保存在 `<QWENPAW_WORKING_DIR>/hub/`。

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

停止、重启、Docker 重建或切换 Local/Docker 不会删除用户数据。删除运行环境记录时，磁盘目录也会保留，管理员确认不再需要后再手工清理。

## 备份和升级

备份时应把整个 `hub/` 目录作为一套数据处理，其中至少包括：

```text
control.db*
secrets/
runtimes/
```

数据库保存账户、配置和运行环境记录；`secrets/` 包含解密凭据所需的密钥；`runtimes/` 保存用户工作区和私密配置。只备份其中一部分可能无法完整恢复。

升级前建议：

1. 停止 Hub；
2. 备份完整的 `hub/` 目录；
3. 记录当前 QwenPaw 版本；
4. 升级并重新启动；
5. 检查管理员登录、用户环境、聊天流式响应和 OAuth 集成。

## 常见问题

### Hub 拒绝监听外部地址

先通过 `127.0.0.1` 完成第一个管理员注册，然后配置 `public_base_url`，并在启动时添加 `--force-public`。

### 选择 Docker 后，已有环境仍显示 Local

切换全局设置不会中断正在运行的用户环境。重启对应环境后再查看运行方式。

### 使用本地 Docker 镜像时提示拉取失败

填写 `docker image ls` 中存在的完整 `Repository:Tag`，并将拉取策略设为 `never`。

### 登录成功，但个人 QwenPaw 无法打开

在「运行环境」中查看该用户的状态和最近错误。确认所选的 Local 或 Docker 环境可用，并尝试重启。

### 页面能打开，但聊天无法持续输出

检查反向代理是否支持 WebSocket Upgrade，以及是否对长连接设置了过短的超时。

### OAuth 回调地址仍然是 `127.0.0.1`

检查当前生效的 `public_base_url`。使用 YAML 启动时修改 `hub.yaml` 并重启；不使用 YAML 时在管理面板中保存。

## 安全边界

Hub 会隔离不同用户的工作目录、凭据、进程或容器，但不会为每个用户提供独立内核。Local 环境共享宿主机内核；Docker 环境共享 Docker Engine 使用的 Linux 内核。

Local 当前使用 Linux Bubblewrap、macOS Seatbelt 或 Windows AppContainer + Job Object；Docker 为每个用户创建单独容器。这些方式可以减少可信团队成员之间的相互影响，但不构成面向陌生用户的强多租户边界。

对于彼此不信任的用户、高风险代码或有严格合规要求的场景，不应直接使用当前版本对外提供服务。此类场景需要虚拟机、MicroVM、专用节点或其他更强的基础设施隔离。

可信团队长期运行 Hub 时，还应配置 HTTPS、主机与网络访问控制、日志监控和定期备份。

后续版本计划继续完善按用户配额、资源用量统计、Kubernetes、多机调度、弹性扩缩容和更强的租户隔离。后续进展敬请期待，也欢迎阅读[贡献指南](/docs/contributing)，直接参与实现。
