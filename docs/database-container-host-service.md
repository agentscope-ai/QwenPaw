# PostgreSQL 容器与本地服务部署手册

本手册适用于以下部署结构：

- PostgreSQL 16 运行在 Docker 容器 `agent-pg` 中；
- WeldonAgent 应用、前端静态资源和智能体运行时直接运行在 Windows 或 Linux 宿主机；
- PostgreSQL 默认只监听 `127.0.0.1:5432`，不向局域网或公网开放；
- 源码目录、业务数据目录和 PostgreSQL 数据目录彼此分离。

这种模式适合需要直接使用宿主机浏览器、桌面能力、GPU、文件系统或调试工具，同时希望用 Docker 管理 PostgreSQL 的场景。数据库容器和应用应部署在同一台服务器上。

## 1. 目录规划

| 内容 | Linux 示例 | Windows 示例 |
|---|---|---|
| 源码 | `/opt/weldonagent` | `D:/Apps/WeldonAgent` |
| 应用数据 | `/var/lib/weldonagent/working` | `D:/WeldonAgentData/working` |
| PostgreSQL 数据 | `/var/lib/weldonagent/postgres` | `D:/WeldonAgentData/postgres` |
| 密钥 | `/var/lib/weldonagent/secrets` | `D:/WeldonAgentData/secrets` |
| 日志与运行状态 | `/var/lib/weldonagent/logs`、`run` | `D:/WeldonAgentData/logs`、`run` |

不要把业务数据放进源码目录。更新代码、重建 Python 虚拟环境或重新 Clone 时，不应影响数据目录。

## 2. 前置要求

- Python 3.11、3.12 或 3.13；
- Node.js 22 和 npm；
- Git；
- Docker Engine 或 Docker Desktop；
- Docker Compose v2。

检查命令：

```text
python --version
node --version
npm --version
docker version
docker compose version
```

## 3. 创建环境配置

从项目根目录执行：

Linux：

```bash
cp deploy/.env.production.example deploy/.env
chmod 600 deploy/.env
```

Windows PowerShell：

```powershell
Copy-Item "deploy/.env.production.example" "deploy/.env"
```

编辑 `deploy/.env`。Linux 示例：

```dotenv
WELDON_DATA_ROOT=/var/lib/weldonagent
WELDON_DB_NAME=weldonagent
WELDON_DB_SCHEMA=weldonagent
WELDON_DB_USER=weldon
WELDON_DB_PASSWORD=替换为至少16个字符的随机密码
WELDON_DB_BIND_ADDRESS=127.0.0.1
WELDON_DB_PORT=5432
WELDON_TIMEZONE=Asia/Shanghai
```

Windows 只需将数据根改为可供 Docker Desktop 访问的路径，例如：

```dotenv
WELDON_DATA_ROOT=D:/WeldonAgentData
```

`WELDON_DB_BIND_ADDRESS` 应保持为 `127.0.0.1`。只有数据库与应用确实位于不同服务器，并且已经配置专用网络、TLS、数据库访问控制和防火墙时，才应改变这个值。

## 4. 只启动 PostgreSQL

Linux 先创建数据目录：

```bash
sudo mkdir -p /var/lib/weldonagent/postgres
sudo chown -R "$(id -u):$(id -g)" /var/lib/weldonagent
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "D:/WeldonAgentData/postgres" | Out-Null
```

两种平台使用相同的 Compose 命令：

```text
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml up -d agent-pg
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml ps
```

健康状态应显示为 `healthy`。需要查看数据库日志时执行：

```text
docker logs --tail 200 agent-pg
```

该 Compose 文件只有 `agent-pg` 一个服务，不会构建或启动应用容器。PostgreSQL 端口映射为 `127.0.0.1:5432:5432`。

## 5. 在宿主机安装应用

首先 Clone 项目并进入源码目录，然后创建虚拟环境。

Linux：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
npm --prefix console ci
npm --prefix console run build
mkdir -p src/qwenpaw/console
cp -a console/dist/. src/qwenpaw/console/
.venv/bin/python -m pip install -e .
.venv/bin/python -m playwright install chromium
```

Windows PowerShell：

```powershell
py -3.11 -m venv ".venv"
& ".venv/Scripts/python.exe" -m pip install --upgrade pip
npm --prefix console ci
npm --prefix console run build
New-Item -ItemType Directory -Force "src/qwenpaw/console" | Out-Null
Copy-Item "console/dist/*" "src/qwenpaw/console" -Recurse -Force
& ".venv/Scripts/python.exe" -m pip install -e .
& ".venv/Scripts/python.exe" -m playwright install chromium
```

Linux 服务器缺少 Chromium 系统依赖时，可以由管理员执行 `.venv/bin/python -m playwright install --with-deps chromium`。

## 6. 创建本地服务配置

生成配置文件：

Linux：

```bash
.venv/bin/python -m qwenpaw service --config deploy/service.local.json init
```

Windows PowerShell：

```powershell
& ".venv/Scripts/python.exe" -m qwenpaw service --config "deploy/service.local.json" init
```

编辑 `deploy/service.local.json`，确认以下字段使用真实绝对路径：

```json
{
  "python": "宿主机虚拟环境中的Python绝对路径",
  "project_dir": "源码根目录绝对路径",
  "host": "127.0.0.1",
  "port": 18089,
  "timeout": 120,
  "working_dir": "外置数据根/working",
  "secret_dir": "外置数据根/secrets",
  "backup_dir": "外置数据根/backups",
  "state_dir": "外置数据根/run",
  "log_dir": "外置数据根/logs",
  "environment": {
    "QWENPAW_MULTI_USER_ENABLED": "true",
    "QWENPAW_STORAGE_MODE": "postgres",
    "QWENPAW_DATABASE_URL": "postgresql://weldon:URL编码后的数据库密码@127.0.0.1:5432/weldonagent",
    "QWENPAW_DATABASE_SCHEMA": "weldonagent",
    "QWENPAW_CUTOVER_VALIDATED_DOMAINS": "",
    "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS": "",
    "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS": ""
  }
}
```

`QWENPAW_*` 是程序内部兼容配置名，不能自行改名。数据库密码如果包含 `@`、`:`、`/`、`%` 等字符，必须先进行 URL 编码。`service.local.json` 包含数据库凭据，不能提交到 Git，并应限制为仅服务运行账户可读。

如果需要从局域网访问 Web 服务，可以把 `host` 改为 `0.0.0.0`，同时通过操作系统防火墙限制 18089 端口的来源网段。数据库绑定地址仍保持 `127.0.0.1`。

## 7. 初始化数据库和应用

首次部署按以下顺序执行。Linux：

```bash
.venv/bin/python -m qwenpaw service --config deploy/service.local.json database-upgrade --yes
.venv/bin/python -m qwenpaw service --config deploy/service.local.json exec init --defaults --accept-security
.venv/bin/python -m qwenpaw service --config deploy/service.local.json check
.venv/bin/python -m qwenpaw service --config deploy/service.local.json start
.venv/bin/python -m qwenpaw service --config deploy/service.local.json status
```

Windows PowerShell：

```powershell
$python = ".venv/Scripts/python.exe"
& $python -m qwenpaw service --config "deploy/service.local.json" database-upgrade --yes
& $python -m qwenpaw service --config "deploy/service.local.json" exec init --defaults --accept-security
& $python -m qwenpaw service --config "deploy/service.local.json" check
& $python -m qwenpaw service --config "deploy/service.local.json" start
& $python -m qwenpaw service --config "deploy/service.local.json" status
```

初始化完成后访问 `http://127.0.0.1:18089`。普通重启不会自动升级数据库；更新到包含数据库迁移的新版本时，应先备份并再次显式执行 `database-upgrade --yes`。

## 8. 日常运行

应用服务：

```text
python -m qwenpaw service --config deploy/service.local.json start
python -m qwenpaw service --config deploy/service.local.json status
python -m qwenpaw service --config deploy/service.local.json logs --follow
python -m qwenpaw service --config deploy/service.local.json stop
```

数据库容器：

```text
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml ps
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml logs --tail 200 agent-pg
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml stop agent-pg
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml up -d agent-pg
```

停止数据库前应先停止应用。不要执行 `down -v`，也不要删除 `<WELDON_DATA_ROOT>/postgres`。

## 9. 开机自启动

Windows 可以使用仓库中的任务计划安装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File "deploy/install-windows-task.ps1" `
  -Python "D:/Apps/WeldonAgent/.venv/Scripts/python.exe" `
  -Config "D:/Apps/WeldonAgent/deploy/service.local.json"
```

Linux 可以复制并按实际账户、源码路径和配置路径调整 `deploy/qwenpaw.service`，随后安装为 systemd 服务。Docker 的 `agent-pg` 使用 `restart: unless-stopped`，Docker 服务启动后会自动恢复。

## 10. 验证边界

执行以下检查：

1. `docker ps` 中只有 `agent-pg`，没有 `agent-app`；
2. `docker port agent-pg` 显示 `127.0.0.1:5432`；
3. 本地服务 `status` 返回 `ready`；
4. 登录后验证用户、智能体、对话、附件、知识库、记忆和产物；
5. 重启应用后数据仍存在；
6. 重启数据库容器后数据仍存在；
7. 从另一台机器不能直接连接服务器的 5432 端口。

如果本地服务报告数据库连接失败，依次检查 `agent-pg` 健康状态、端口占用、用户名/数据库名/schema 是否一致，以及连接串中的密码是否已正确进行 URL 编码。
