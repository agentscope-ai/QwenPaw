# PostgreSQL 容器与本地服务部署手册

本手册适用于以下部署结构：

- PostgreSQL 16 运行在 Docker 容器 `agent-pg` 中；
- WeldonAgent 应用、前端静态资源和智能体运行时直接运行在 Windows 或 Linux 宿主机；
- PostgreSQL 默认只监听 `127.0.0.1:5432`，不向局域网或公网开放；
- 源码目录、业务数据目录和 PostgreSQL 数据目录彼此分离。

这种模式适合需要直接使用宿主机浏览器、桌面能力、GPU、文件系统或调试工具，同时希望用 Docker 管理 PostgreSQL 的场景。数据库容器和应用应部署在同一台服务器上。

以下步骤用于全新部署。先 Clone 项目并进入源码根目录，再执行命令；Windows 使用 PowerShell，逐条确认成功后再继续，不要复制 `PS ...>` 或 `>>` 提示符。已有实例更新时保留原配置和数据，不要重复覆盖 `.env` 或重新执行首次初始化。

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

Windows 还应确认解释器来源：

```powershell
Get-Command python -All
python -c "import sys; print(sys.executable)"
```

`python --version` 必须实际输出受支持版本。若只找到 `Microsoft/WindowsApps/python.exe` 或运行无输出，当前命令没有指向可用的 Python。使用安装好的 Python 绝对路径，或从开始菜单打开 Anaconda Prompt，执行 `python --version`。Conda 当前版本不符合要求时，可执行 `conda create -n weldon-build python=3.11 -y` 和 `conda activate weldon-build`，再在项目目录执行 `python -m venv .venv`，创建后回到 PowerShell 继续。作为虚拟环境基础的 Python/Conda 环境需要保留。

`py -3.11` 仅适用于已安装 Windows Python Launcher 的情况；不要写成 `python -3.11`。如果 PowerShell 显示 `>>` 等待续行，按 Ctrl+C 后重新逐条执行。

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

密码包含 `$`、`#` 等字符时，在 `.env` 中用单引号包裹，避免 Compose 插值；例如 `WELDON_DB_PASSWORD='实际随机密码'`。应用配置会使用 Compose 解析后的值并自动进行 URL 编码。数据库名、用户名、密码仅在空数据目录首次初始化时生效；修改 `.env` 再重启不会自动修改已有数据库账户或密码。

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

若自定义了 `WELDON_DB_PORT`，以后连接和验收应使用该端口。`healthy` 只表示 PostgreSQL 已响应，应用凭据、schema 和表结构仍由后续迁移与 `check` 验证。容器内的 `.sh` 脚本必须使用 LF 换行；仓库已通过 `.gitattributes` 固定此规则。

## 5. 在宿主机安装应用

在源码根目录创建虚拟环境。以下 `python3.11` 或 `python` 必须是前一步确认的受支持解释器；Linux 如果缺少 `venv` 模块，先安装发行版对应版本的 venv 包。

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
python -m venv ".venv"
& ".venv/Scripts/python.exe" --version
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

全新实例执行以下命令。`--env-file` 调用 Docker Compose 解析第 3 节配置，自动填入数据库用户名、编码后的密码、数据库名、schema、映射端口以及外置数据目录；不会打印密码。`--fresh` 明确声明没有旧业务数据需要迁移，并配置所有领域使用 PostgreSQL。

Linux：

```bash
.venv/bin/python -m qwenpaw service --config deploy/service.local.json init --env-file deploy/.env --fresh
```

Windows PowerShell：

```powershell
& ".venv/Scripts/python.exe" -m qwenpaw service --config "deploy/service.local.json" init --env-file "deploy/.env" --fresh
```

命令不会覆盖已有配置。检查生成的 `deploy/service.local.json`，确认路径、数据库目标和应用监听地址正确。下方仅用于说明字段，不要直接用其中的占位符覆盖已生成的配置：

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
    "QWENPAW_CUTOVER_VALIDATED_DOMAINS": "all",
    "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS": "all",
    "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS": "all"
  }
}
```

不带 `--fresh` 时，三个 `QWENPAW_CUTOVER_*` 值保持为空，`check` 会拒绝启动。已有文件存储实例必须先完成旧数据迁移、核验并停止旧存储写入，再设置这些声明，不能仅为通过检查而改为 `all`。数据库仍需按下一节执行 `database-upgrade --yes`，这些声明不会代替数据库迁移。

`QWENPAW_*` 是程序内部兼容配置名，不能自行改名。数据库密码如果包含 `@`、`:`、`/`、`%` 等字符，必须先进行 URL 编码。`service.local.json` 包含数据库凭据，不能提交到 Git，并应限制为仅服务运行账户可读。

如果需要从局域网访问 Web 服务，可以把 `host` 改为 `0.0.0.0`，同时通过操作系统防火墙限制 18089 端口的来源网段。数据库绑定地址仍保持 `127.0.0.1`。远程正式访问应配置 HTTPS，以支持默认启用 Secure 的登录刷新 Cookie。

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

`database-upgrade --yes` 会幂等创建目标 schema 并升级表结构；即使容器初始化脚本没有执行，也不需要手工建 schema。已有非空且没有 Alembic 版本记录的 schema 会被拒绝，避免误当作空库初始化。

首次访问网页后注册管理员，服务会在返回登录凭据前登记内置智能体，随后配置模型，再用 `default` 新建对话，无需额外重启。如果显示 `admin_initialization_incomplete`，管理员账户已保存，请修复数据库问题后重新登录；登录会重试未完成的登记，不要重复注册。旧版本遗留的本地会话元数据由启动流程补登记。

`check` 通过和服务 `ready` 表示基础运行条件满足，不代表模型 API 已配置或已验证。`No default model` 提示需要在网页配置模型；`Unified browser experimental beta` 是信息提示。内置 QA 技能若提示 `authorized_lifecycle_required`，表示多用户模式要求经过技能授权流程，请在管理员技能管理中按需授权、安装；不要关闭权限校验来绕过它。

## 8. 日常运行

应用服务（Windows PowerShell；每个新终端都先设置 `$python`）：

```powershell
$python = ".venv/Scripts/python.exe"
& $python -m qwenpaw service --config deploy/service.local.json start
& $python -m qwenpaw service --config deploy/service.local.json status
& $python -m qwenpaw service --config deploy/service.local.json logs --follow
& $python -m qwenpaw service --config deploy/service.local.json stop
```

Linux 将 `& $python` 替换为 `.venv/bin/python`。不要直接使用未激活环境的全局 `python`。上述命令从源码根目录运行。

数据库容器：

```text
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml ps
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml logs --tail 200 agent-pg
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml stop agent-pg
docker compose --project-name weldonagent-database --env-file deploy/.env --file deploy/compose.database.yml up -d agent-pg
```

停止数据库前应先停止应用。不要执行 `down -v`，也不要删除 `<WELDON_DATA_ROOT>/postgres`。

## 9. 开机自启动

Windows 可以使用仓库中的任务计划安装脚本（默认为当前用户登录后启动）：

```powershell
powershell -ExecutionPolicy Bypass -File "deploy/install-windows-task.ps1" `
  -Python "D:/Apps/WeldonAgent/.venv/Scripts/python.exe" `
  -Config "D:/Apps/WeldonAgent/deploy/service.local.json"
```

无人登录时就要启动的 Windows 服务器，需在任务计划程序中另行配置运行账户和开机触发器，同时保证 Docker 已运行。Linux 可以复制并按实际账户、源码路径和配置路径调整 `deploy/qwenpaw.service`，随后安装为 systemd 服务。Docker 的 `agent-pg` 使用 `restart: unless-stopped`，Docker 服务启动后会自动恢复。使用任务计划或 systemd 前先停止手动启动的应用，避免两个管理器竞争同一端口。

## 10. 验证边界

执行以下检查：

1. 本次部署启动了 `agent-pg`，没有启动 `agent-app`（服务器上的其他无关容器不受影响）；
2. `docker port agent-pg` 显示 `127.0.0.1:5432`；
3. 本地服务 `status` 返回 `ready`；
4. 登录后验证用户、智能体、对话、附件、知识库、记忆和产物；
5. 重启应用后数据仍存在；
6. 重启数据库容器后数据仍存在；
7. 从另一台机器不能直接连接服务器的 5432 端口。

如果本地服务报告数据库连接失败，依次检查 `agent-pg` 健康状态、端口占用、用户名/数据库名/schema 是否一致，以及连接串中的密码是否已正确进行 URL 编码。

## 11. 常见错误与更新

| 提示 | 检查与处理 |
|---|---|
| `py` 不可识别或 `python` 无输出 | 按第 2 节确认真实解释器；`python -m venv .venv` 不带 `-3.11` |
| `.venv/Scripts/python.exe` 不存在 | 上一步创建虚拟环境失败，先处理其错误再继续安装 |
| `InvalidPasswordError` / `28P01` | 核对实际数据库用户和密码；旧模板中的 `qwenpaw` 不等于本手册的 `weldon`。改 `.env` 不会修改已有数据库密码 |
| `schema_not_initialized` 或 schema 不存在 | 对正确的实例配置执行 `database-upgrade --yes` |
| `domain_migration_not_validated` | 全新部署使用 `init --env-file deploy/.env --fresh`；已有配置需按第 6 节核验后填写声明，命令不会覆盖旧配置 |
| `conversation_not_found` | 升级到包含首次管理员登记修复的代码；旧实例重启可补登记智能体和本地会话，再刷新网页 |
| 数据库权限不足 | 确认迁移账户有数据库建 schema 权限及目标 schema 的 DDL 权限，运行账户有相应读写权限 |

更新已有实例：先停服、备份数据库和外置数据，更新源码及依赖、重新构建前端，使用原 `service.local.json` 执行 `database-upgrade --yes`、`check`，再启动。不要重建数据库数据目录，不要用 `--fresh` 代替已有数据迁移，也不要为更新而覆盖原配置。
