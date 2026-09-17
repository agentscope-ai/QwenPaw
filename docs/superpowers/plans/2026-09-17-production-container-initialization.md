# WeldonAgent Production Container Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Linux Docker Engine 与 Windows Docker Desktop 提供同一套从 Clone、配置、初始化到启动的生产部署入口，并把持久数据放到源码目录之外。

**Architecture:** 新增独立的生产 Compose 定义，外部只暴露 `WELDON_*` 配置和 `agent-*` 服务名；容器启动包装器负责校验配置并映射为内部现有 `QWENPAW_*` 变量。初始化作为一次性、幂等的 `agent-init` 服务执行，普通 `agent-app` 重启不隐式执行数据库迁移。

**Tech Stack:** Docker Compose v2、PostgreSQL 16、Python 3.11、Click、pytest、PowerShell 7/Windows PowerShell 5.1、POSIX shell。

## Global Constraints

- 内部 Python 包名、导入路径、迁移实现、兼容环境变量和协议标识保持不变。
- 外部 Compose 项目名为 `weldonagent`，服务/容器名为 `agent-app`、`agent-init`、`agent-pg`。
- Linux 默认数据根为 `/var/lib/weldonagent`；Windows 默认数据根为 `D:/WeldonAgentData`。
- PostgreSQL 只在 Compose 网络暴露 5432；Web 默认绑定 `127.0.0.1:18089`。
- 生产环境文件不包含真实密码，`deploy/.env` 不进入 Git 或镜像。
- 初始化可重复执行，但不覆盖已有用户、模型、密钥、智能体和业务数据。
- 本阶段不迁移也不删除 `tmp/task-2-1-acceptance/working`。

## File Structure

- Create: `deploy/compose.production.yml` — 生产服务拓扑、绑定挂载、健康检查与初始化依赖。
- Create: `deploy/.env.production.example` — 管理员可见的 `WELDON_*` 配置模板。
- Create: `deploy/service.production.json` — 容器内固定逻辑目录与内部兼容配置。
- Create: `deploy/runtime_env.py` — 配置校验、数据库 URL 安全组装、外部到内部变量映射。
- Create: `deploy/postgres-init.sh` — 首次创建可配置 schema，拒绝非法标识符。
- Create: `deploy/weldon.sh` — Linux 薄入口。
- Create: `deploy/weldon.ps1` — Windows 薄入口。
- Modify: `deploy/Dockerfile.multi-user` — 将生产配置和运行包装器复制进镜像。
- Modify: `.gitignore` — 排除生产环境文件与本机部署状态。
- Modify: `.dockerignore` — 排除临时目录、业务数据、密钥、测试输出与本地备份。
- Create: `tests/unit/deploy/test_runtime_env.py` — 环境校验和 URL 编码单元测试。
- Create: `tests/integration/deploy/test_production_compose.py` — Compose 结构与安全约束测试。
- Modify: `docs/deployment.md` — Linux/Windows 从 Clone 开始的正式部署说明。

---

### Task 1: 生产环境变量兼容层

**Files:**
- Create: `deploy/runtime_env.py`
- Create: `tests/unit/deploy/test_runtime_env.py`

**Interfaces:**
- Consumes: `WELDON_DB_NAME`、`WELDON_DB_SCHEMA`、`WELDON_DB_USER`、`WELDON_DB_PASSWORD` 和现有进程环境。
- Produces: `validate_environment(env: Mapping[str, str]) -> ProductionSettings`、`build_database_url(settings: ProductionSettings) -> str`、`build_internal_environment(env: Mapping[str, str]) -> dict[str, str]`、CLI 子命令 `check` 与 `exec`。

- [ ] **Step 1: 写数据库密码编码和必填字段失败测试**

```python
def test_database_url_percent_encodes_password():
    settings = ProductionSettings(
        db_name="weldonagent",
        db_schema="weldonagent",
        db_user="weldon",
        db_password="a/b:c@d%",
    )
    assert build_database_url(settings) == (
        "postgresql://weldon:a%2Fb%3Ac%40d%25@agent-pg:5432/weldonagent"
    )


def test_example_password_is_rejected():
    with pytest.raises(ValueError, match="WELDON_DB_PASSWORD"):
        validate_environment({"WELDON_DB_PASSWORD": "REPLACE_WITH_RANDOM_PASSWORD"})
```

- [ ] **Step 2: 运行测试并确认当前缺少实现**

Run: `python -m pytest tests/unit/deploy/test_runtime_env.py -q`

Expected: FAIL，原因是 `deploy.runtime_env` 或公开接口尚不存在。

- [ ] **Step 3: 实现不可变设置对象、标识符校验、密码校验和内部变量映射**

```python
@dataclass(frozen=True)
class ProductionSettings:
    db_name: str
    db_schema: str
    db_user: str
    db_password: str


def build_database_url(settings: ProductionSettings) -> str:
    user = quote(settings.db_user, safe="")
    password = quote(settings.db_password, safe="")
    database = quote(settings.db_name, safe="")
    return f"postgresql://{user}:{password}@agent-pg:5432/{database}"


def build_internal_environment(env: Mapping[str, str]) -> dict[str, str]:
    settings = validate_environment(env)
    return {
        "QWENPAW_MULTI_USER_ENABLED": "true",
        "QWENPAW_STORAGE_MODE": "postgres",
        "QWENPAW_DATABASE_URL": build_database_url(settings),
        "QWENPAW_DATABASE_SCHEMA": settings.db_schema,
        "QWENPAW_WORKING_DIR": "/data/working",
        "QWENPAW_SECRET_DIR": "/data/secrets",
    }
```

- [ ] **Step 4: 覆盖非法数据库/schema 名、空密码、示例密码和日志脱敏测试**

Run: `python -m pytest tests/unit/deploy/test_runtime_env.py -q`

Expected: PASS；异常信息只包含变量名，不包含密码或完整数据库 URL。

- [ ] **Step 5: 在获得用户单独提交确认后创建兼容层提交**

```bash
git add deploy/runtime_env.py tests/unit/deploy/test_runtime_env.py
git commit -m "feat: 增加 WeldonAgent 生产配置兼容层"
```

### Task 2: 生产 Compose 与幂等初始化服务

**Files:**
- Create: `deploy/compose.production.yml`
- Create: `deploy/.env.production.example`
- Create: `deploy/service.production.json`
- Create: `deploy/postgres-init.sh`
- Modify: `deploy/Dockerfile.multi-user`
- Create: `tests/integration/deploy/test_production_compose.py`

**Interfaces:**
- Consumes: Task 1 的 `python /app/deploy/runtime_env.py check|exec -- <command>`。
- Produces: Compose 服务 `agent-pg`、`agent-init`、`agent-app`，共享绑定目录 `${WELDON_DATA_ROOT}`。

- [ ] **Step 1: 写 Compose 契约测试**

```python
def test_production_compose_has_expected_services(compose):
    assert compose["name"] == "weldonagent"
    assert set(compose["services"]) == {"agent-pg", "agent-init", "agent-app"}
    assert "ports" not in compose["services"]["agent-pg"]


def test_production_data_is_outside_source_tree(compose):
    mounts = compose["services"]["agent-app"]["volumes"]
    assert "${WELDON_DATA_ROOT:?Set WELDON_DATA_ROOT}:/data" in mounts
```

- [ ] **Step 2: 运行测试并确认生产定义尚不存在**

Run: `python -m pytest tests/integration/deploy/test_production_compose.py -q`

Expected: FAIL，原因是 `deploy/compose.production.yml` 尚不存在。

- [ ] **Step 3: 新增生产 Compose 并固定外部服务名**

```yaml
name: weldonagent
services:
  agent-pg:
    image: postgres:16
    container_name: agent-pg
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${WELDON_DB_NAME:-weldonagent}
      POSTGRES_USER: ${WELDON_DB_USER:-weldon}
      POSTGRES_PASSWORD: ${WELDON_DB_PASSWORD:?Set WELDON_DB_PASSWORD}
    volumes:
      - ${WELDON_DATA_ROOT:?Set WELDON_DATA_ROOT}/postgres:/var/lib/postgresql/data
      - ./postgres-init.sh:/docker-entrypoint-initdb.d/01-schema.sh:ro
  agent-init:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.multi-user
    profiles: ["init"]
    depends_on:
      agent-pg:
        condition: service_healthy
    volumes:
      - ${WELDON_DATA_ROOT:?Set WELDON_DATA_ROOT}:/data
  agent-app:
    container_name: agent-app
    depends_on:
      agent-pg:
        condition: service_healthy
    ports:
      - ${WELDON_BIND_ADDRESS:-127.0.0.1}:${WELDON_PORT:-18089}:18089
```

- [ ] **Step 4: 让 `agent-init` 显式执行升级、基础初始化和部署检查**

```yaml
command:
  - python
  - /app/deploy/runtime_env.py
  - exec
  - --
  - sh
  - -ec
  - >-
    python -m qwenpaw service --config /app/deploy/service.production.json database-upgrade --yes &&
    python -m qwenpaw init --defaults --accept-security &&
    python -m qwenpaw service --config /app/deploy/service.production.json check
```

确认第二次执行 `agent-init` 时 Alembic 保持目标版本且应用初始化不覆盖现有数据；若现有 `init` 不满足幂等性，则在本任务内补充精确回归测试后仅修复幂等分支。

- [ ] **Step 5: 添加不含密钥的生产环境模板**

```dotenv
WELDON_DATA_ROOT=/var/lib/weldonagent
WELDON_BIND_ADDRESS=127.0.0.1
WELDON_PORT=18089
WELDON_DB_NAME=weldonagent
WELDON_DB_SCHEMA=weldonagent
WELDON_DB_USER=weldon
WELDON_DB_PASSWORD=REPLACE_WITH_RANDOM_PASSWORD
WELDON_TIMEZONE=Asia/Shanghai
```

- [ ] **Step 6: 验证 Compose 展开结果和容器内配置**

Run: `docker compose --env-file deploy/.env.production.example -f deploy/compose.production.yml config`

Expected: 示例密码校验阶段拒绝真正启动；`config` 可解析，数据库无宿主端口，应用仅绑定 `127.0.0.1`，所有持久目录均来自 `WELDON_DATA_ROOT`。

- [ ] **Step 7: 运行部署契约测试**

Run: `python -m pytest tests/unit/deploy/test_runtime_env.py tests/integration/deploy/test_production_compose.py -q`

Expected: PASS。

- [ ] **Step 8: 在获得用户单独提交确认后创建 Compose 提交**

```bash
git add deploy/compose.production.yml deploy/.env.production.example deploy/service.production.json deploy/postgres-init.sh deploy/Dockerfile.multi-user tests/integration/deploy/test_production_compose.py
git commit -m "feat: 增加 WeldonAgent 生产容器拓扑"
```

### Task 3: 跨平台薄入口和预检

**Files:**
- Create: `deploy/weldon.sh`
- Create: `deploy/weldon.ps1`
- Create: `tests/integration/deploy/test_deployment_entrypoints.py`

**Interfaces:**
- Consumes: `deploy/compose.production.yml`、`deploy/.env`、Task 1 的配置校验。
- Produces: `init|up|down|status|logs|backup|restore` 命令；本计划实现前五项，后两项转发给备份恢复计划中的 `agent-maintenance`。

- [ ] **Step 1: 写入口命令参数和安全约束测试**

```python
@pytest.mark.parametrize("path", ["deploy/weldon.sh", "deploy/weldon.ps1"])
def test_entrypoint_exposes_required_commands(path):
    text = Path(path).read_text(encoding="utf-8")
    for command in ("init", "up", "down", "status", "logs", "backup", "restore"):
        assert command in text
    assert "down -v" not in text
```

- [ ] **Step 2: 实现 Linux 薄入口**

```sh
case "$command" in
  init)
    compose up -d agent-pg
    compose --profile init run --rm agent-init
    compose up -d agent-app
    ;;
  up) compose up -d agent-pg agent-app ;;
  down) compose down ;;
  status) compose ps && compose exec -T agent-app python -m qwenpaw service --config /app/deploy/service.production.json status ;;
  logs) compose logs --tail=200 -f agent-app ;;
  backup|restore) compose --profile maintenance run --rm agent-maintenance "$@" ;;
esac
```

- [ ] **Step 3: 实现等价 PowerShell 薄入口并保持相同参数含义**

```powershell
switch ($Command) {
  "init" {
    Invoke-Compose @("up", "-d", "agent-pg")
    Invoke-Compose @("--profile", "init", "run", "--rm", "agent-init")
    Invoke-Compose @("up", "-d", "agent-app")
  }
  "up" { Invoke-Compose @("up", "-d", "agent-pg", "agent-app") }
  "down" { Invoke-Compose @("down") }
  "status" { Invoke-Compose @("ps") }
  "logs" { Invoke-Compose @("logs", "--tail=200", "-f", "agent-app") }
}
```

- [ ] **Step 4: 验证帮助、缺配置、示例密码和不可写目录场景**

Run: `python -m pytest tests/integration/deploy/test_deployment_entrypoints.py -q`

Expected: PASS；两个入口都返回非零并给出具体变量名，不显示密码或连接串。

- [ ] **Step 5: 在隔离临时数据根执行两次初始化验收**

Run: `docker compose --env-file <temporary-env> -f deploy/compose.production.yml --project-name weldonagent-plan-test up -d agent-pg`

Run: `docker compose --env-file <temporary-env> -f deploy/compose.production.yml --project-name weldonagent-plan-test --profile init run --rm agent-init`

Run: 再执行一次相同 `agent-init`。

Expected: 两次均成功；第二次不新增管理员、不重置模型、不清空工作区；`agent-app` 健康检查通过。

- [ ] **Step 6: 清理隔离测试容器和测试数据根**

仅删除本任务创建且路径经过断言位于系统临时目录中的测试实例；不得接触当前 `tmp/task-2-1-acceptance/working`。

- [ ] **Step 7: 在获得用户单独提交确认后创建入口提交**

```bash
git add deploy/weldon.sh deploy/weldon.ps1 tests/integration/deploy/test_deployment_entrypoints.py
git commit -m "feat: 增加跨平台生产部署入口"
```

### Task 4: 构建上下文与正式部署文档

**Files:**
- Modify: `.gitignore`
- Modify: `.dockerignore`
- Modify: `docs/deployment.md`
- Create: `tests/integration/deploy/test_build_context_rules.py`

**Interfaces:**
- Consumes: Tasks 1-3 的文件名、命令和默认目录。
- Produces: 可复制执行的 Linux/Windows 部署文档和可自动验证的构建排除规则。

- [ ] **Step 1: 写构建上下文排除规则测试**

```python
def test_sensitive_and_generated_paths_are_excluded():
    rules = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    required = {"tmp", "data", "logs", "*.dump", "*.bak", "playwright-report", "test-results", "docs/superpowers"}
    assert required.issubset(set(rules))
```

- [ ] **Step 2: 更新 `.gitignore` 和 `.dockerignore`**

```gitignore
deploy/.env
deploy/.env.local
*.dump
*.bak
playwright-report/
test-results/
```

`.dockerignore` 同时排除 `tmp`、`data`、`logs`、本地备份、截图和测试证据，但保留运行时必须的迁移、前端源码及正式部署文件。

- [ ] **Step 3: 重写正式部署文档的 Linux 与 Windows 命令**

文档必须给出：依赖版本检查、Clone、复制环境文件、随机密码生成、数据根权限、`init`、`status`、局域网绑定、反向代理/TLS、升级前备份、故障日志和首次管理员创建。公开命令只使用 `WeldonAgent`/`weldon`/`agent-*` 名称。

- [ ] **Step 4: 运行文档与构建规则测试**

Run: `python -m pytest tests/integration/deploy/test_build_context_rules.py -q`

Run: `docker build --check -f deploy/Dockerfile.multi-user .`

Expected: PASS；构建上下文不包含 `tmp`、数据、密钥、测试输出或数据库转储。

- [ ] **Step 5: 在获得用户单独提交确认后创建文档提交**

```bash
git add .gitignore .dockerignore docs/deployment.md tests/integration/deploy/test_build_context_rules.py
git commit -m "docs: 完善 WeldonAgent 正式部署流程"
```

### Task 5: 端到端生产启动验收

**Files:**
- Modify: `docs/deployment.md`
- Create: `docs/deployment-acceptance.md`

**Interfaces:**
- Consumes: 全部前置任务。
- Produces: Linux 与 Windows Docker Desktop 的一致验收记录格式。

- [ ] **Step 1: 在空数据根执行 Clone 后初始化流程**

Expected: `agent-pg`、`agent-app` 健康；登录页可访问；数据库 schema 为 `weldonagent`；源码目录内没有新业务数据。

- [ ] **Step 2: 创建测试管理员、普通用户、智能体、知识库文件、记忆和产物**

Expected: 每一类对象均能在重启后读取，用户与智能体作用域不串数据。

- [ ] **Step 3: 重建应用容器并复验数据**

Run: `docker compose --env-file deploy/.env -f deploy/compose.production.yml up -d --build --force-recreate agent-app`

Expected: PostgreSQL、知识库、记忆、产物、智能体和密钥保持不变。

- [ ] **Step 4: 删除隔离验收使用的源码副本并重新 Clone**

仅针对专门创建的验收副本；重新指向同一测试数据根后服务恢复相同数据。不得删除当前开发工作区或当前业务数据。

- [ ] **Step 5: 记录结果、镜像摘要、提交号和已知限制**

在 `docs/deployment-acceptance.md` 记录两个平台的命令、时间、Docker/Compose 版本和验证结果，不写密码、令牌或绝对用户目录。

- [ ] **Step 6: 在获得用户单独提交确认后创建验收提交**

```bash
git add docs/deployment-acceptance.md docs/deployment.md
git commit -m "test: 记录 WeldonAgent 生产部署验收"
```
