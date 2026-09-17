# WeldonAgent 生产部署与运行手册

本手册适用于 Linux Docker Engine 和 Windows Docker Desktop（Linux 容器模式）。两种平台使用同一镜像、同一 Compose 定义和同一初始化逻辑。

正式部署遵循两个目录分离原则：

- 源码目录只存放 Git 跟踪的程序和构建文件；
- 数据目录存放数据库、工作区、知识库、记忆、产物、密钥、日志和备份。

删除源码后重新 Clone，不会删除数据。重建应用容器，也不会覆盖业务数据。

## 1. 部署结构

| 内容 | Linux 默认位置 | Windows 默认位置 | 容器内位置 |
|---|---|---|---|
| 源码 | `/opt/weldonagent` | `D:/Apps/WeldonAgent` | `/app` |
| 数据根 | `/var/lib/weldonagent` | `D:/WeldonAgentData` | `/data` |
| PostgreSQL | `<数据根>/postgres` | `<数据根>/postgres` | `/var/lib/postgresql/data` |
| 工作数据 | `<数据根>/working` | `<数据根>/working` | `/data/working` |
| 密钥 | `<数据根>/secrets` | `<数据根>/secrets` | `/data/secrets` |
| 备份 | `<数据根>/backups` | `<数据根>/backups` | `/data/backups` |
| 日志 | `<数据根>/logs` | `<数据根>/logs` | `/data/logs` |

容器名称：

| 容器 | 作用 |
|---|---|
| `agent-pg` | PostgreSQL 16，只在容器网络开放 5432 |
| `agent-init` | 一次性数据库升级和应用初始化 |
| `agent-app` | Web、智能体、文件、知识库和记忆服务 |
| `agent-maintenance` | 备份和恢复维护任务 |

## 2. 前置要求

Linux：

- 64 位 Linux；
- Git；
- Docker Engine；
- Docker Compose v2；
- 建议至少 4 核 CPU、8 GB 内存和 30 GB 可用空间。

Windows：

- Windows 10/11 或 Windows Server；
- Git；
- Docker Desktop，启用 Linux 容器；
- 数据盘已在 Docker Desktop 中允许文件共享；
- 建议至少 8 GB 分配给 Docker Desktop。

检查版本：

```text
git --version
docker version
docker compose version
```

## 3. 获取源码

Linux：

```bash
sudo mkdir -p /opt/weldonagent
sudo chown "$(id -u):$(id -g)" /opt/weldonagent
git clone <仓库地址> /opt/weldonagent
cd /opt/weldonagent
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "D:/Apps" | Out-Null
git clone <仓库地址> "D:/Apps/WeldonAgent"
Set-Location "D:/Apps/WeldonAgent"
```

生产部署不应 Clone 到临时目录、下载目录或用户缓存目录。

## 4. 创建生产配置

Linux：

```bash
cp deploy/.env.production.example deploy/.env
chmod 600 deploy/.env
```

Windows PowerShell：

```powershell
Copy-Item "deploy/.env.production.example" "deploy/.env"
```

编辑 `deploy/.env`：

```dotenv
WELDON_DATA_ROOT=/var/lib/weldonagent
WELDON_BIND_ADDRESS=127.0.0.1
WELDON_PORT=18089
WELDON_DB_NAME=weldonagent
WELDON_DB_SCHEMA=weldonagent
WELDON_DB_USER=weldon
WELDON_DB_PASSWORD=替换为至少16个字符的随机密码
WELDON_TIMEZONE=Asia/Shanghai
```

Windows 将数据根改为：

```dotenv
WELDON_DATA_ROOT=D:/WeldonAgentData
```

生成随机密码示例：

Linux：

```bash
openssl rand -base64 36
```

Windows PowerShell：

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 36 | ForEach-Object {[char]$_})
```

密码不得保留为示例值，不要把 `deploy/.env` 发送给他人或提交到 Git。

## 5. 首次初始化

Linux：

```bash
chmod +x deploy/weldon.sh
./deploy/weldon.sh init
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File "deploy/weldon.ps1" init
```

初始化会依次执行：

1. 检查 Docker、Compose、密码、数据根和目录权限；
2. 构建当前源码对应的镜像；
3. 启动 `agent-pg` 并等待数据库健康；
4. 运行一次性 `agent-init`，创建 schema、升级数据库并初始化基础配置；
5. 启动 `agent-app`；
6. 输出容器状态。

相同数据根可以重复运行 `init`。重复初始化只补齐数据库版本和缺失基础配置，不会重置已有管理员、模型、智能体、用户或文件。

## 6. 首次登录

默认访问地址：

```text
http://127.0.0.1:18089
```

首次部署建议只从服务器本机访问：

1. 创建首位管理员；
2. 配置模型供应商和默认模型；
3. 创建一个测试普通用户；
4. 创建测试智能体和对话；
5. 验证附件、个人知识库、记忆和产物；
6. 完成验证后再开放局域网或配置反向代理。

## 7. 日常运行

Linux：

```bash
./deploy/weldon.sh up
./deploy/weldon.sh status
./deploy/weldon.sh logs
./deploy/weldon.sh down
```

Windows PowerShell：

```powershell
& "deploy/weldon.ps1" up
& "deploy/weldon.ps1" status
& "deploy/weldon.ps1" logs
& "deploy/weldon.ps1" down
```

`down` 只停止容器，不删除数据库和宿主数据。生产环境不要执行带卷删除参数的 Compose 命令。

修改 `deploy/.env` 后，使用 `up` 重新创建需要更新的容器；单纯重启容器不会读取新的环境变量。

## 8. 局域网和公网访问

默认配置：

```dotenv
WELDON_BIND_ADDRESS=127.0.0.1
```

需要局域网访问时改为：

```dotenv
WELDON_BIND_ADDRESS=0.0.0.0
```

随后运行 `up`。同时需要：

- 防火墙仅允许受信任网段访问 `WELDON_PORT`；
- 确认服务器实际内网 IP；
- 不开放 PostgreSQL 端口；
- 保留平台登录认证。

公网部署应让 `agent-app` 继续监听回环地址，由 Nginx、Caddy 或企业网关提供 HTTPS、证书、访问日志和限流。不要把未加密的 18089 端口直接暴露到互联网。

## 9. 更新源码

更新前先执行完整备份：

```bash
./deploy/weldon.sh backup
```

或 Windows：

```powershell
& "deploy/weldon.ps1" backup
```

然后更新源码并重新构建：

```text
git pull --ff-only
```

Linux：

```bash
./deploy/weldon.sh down
./deploy/weldon.sh init
```

Windows：

```powershell
& "deploy/weldon.ps1" down
& "deploy/weldon.ps1" init
```

数据库升级是 `init` 的显式步骤，不在普通容器重启时自动执行。升级失败时应用不会被报告为就绪。

## 10. 备份和恢复

完整备份包括：

- PostgreSQL 自定义格式转储；
- `working` 文件树；
- `secrets` 密钥目录；
- 脱敏部署配置；
- Git 提交号、镜像摘要、数据库版本和 SHA-256 校验和。

创建备份：

```bash
./deploy/weldon.sh backup
```

备份期间应用会短暂停止，完成或失败后入口会尝试恢复应用。备份文件位于 `<数据根>/backups`，应再复制到另一块磁盘或受控远端存储。

恢复必须使用空数据根或新实例：

```bash
./deploy/weldon.sh restore /data/backups/weldonagent-YYYYMMDDTHHMMSSZ
```

恢复前会验证清单、校验和、空文件目录和空数据库。恢复成功后自动执行数据库升级检查，再启动应用。恢复命令只接受容器内 `/data/backups` 下的完整备份目录，不会改写源备份。

详细操作和失败处置见 [备份与恢复运行手册](backup-restore-runbook.md)。

## 11. 新服务器初始化和未来数据迁移

全新服务器只需执行第 2 至第 6 节。它会创建空数据库和空业务数据，不会引用开发机器的临时目录。

未来需要迁移已有实例时，应在源服务器执行完整备份，把整个备份单元复制到新服务器，再恢复到空数据根。不要只复制 PostgreSQL、只复制工作目录或只复制密钥；三者缺一都可能造成记录与文件不一致。

本仓库当前开发机器的数据不会因为生产部署功能而自动移动、覆盖或删除。

## 12. 故障排查

| 表现 | 检查 |
|---|---|
| 提示缺少 `deploy/.env` | 从 `.env.production.example` 复制后填写 |
| 拒绝示例密码 | 设置至少 16 个字符的随机密码 |
| 数据根不可写 | 检查宿主目录权限和 Docker Desktop 文件共享 |
| `agent-pg` 不健康 | 查看 `docker logs agent-pg`，检查磁盘和环境变量 |
| `agent-init` 失败 | 查看初始化输出；修正配置后重新运行 `init` |
| `agent-app` 不健康 | 执行 `status` 和 `logs`，确认数据库已完成升级 |
| 本机可以访问、局域网不能访问 | 检查绑定地址、防火墙和服务器内网 IP |
| 页面仍是旧资源 | 重新运行 `init` 构建镜像并强制刷新浏览器 |
| 登录后无模型 | 由管理员配置模型供应商、默认模型和用户授权 |

初始化、备份和恢复日志不会输出数据库密码、令牌、Secret 正文或完整连接串。
