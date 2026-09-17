# WeldonAgent Backup Restore and Repository Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供数据库、工作文件和密钥的一致性备份/恢复能力，并阻止本地临时文件和业务数据进入生产镜像或提交范围。

**Architecture:** 新增独立维护工具，在短暂停止 `agent-app` 后生成 PostgreSQL 自定义格式转储、文件归档、脱敏部署信息和 SHA-256 清单；恢复只接受空数据根或新实例，并在启动前完成校验。仓库清理只生成分类报告并加强忽略规则，不自动删除当前开发机文件。

**Tech Stack:** Python 3.11、PostgreSQL `pg_dump/pg_restore`、Docker Compose v2、tar/zip、hashlib、pytest。

## Global Constraints

- 完整备份必须包含 PostgreSQL、`working`、`secrets`、脱敏配置、提交号、镜像摘要、Alembic 版本和备份时间。
- 默认短暂停服以保证数据库和文件一致。
- 清单和日志不得包含数据库密码、令牌、Secret 正文或完整连接串。
- 恢复只写入空数据根或显式新实例；源实例保持不变。
- 跨平台恢复使用容器内逻辑路径；历史绝对路径只报告，不做无条件字符串替换。
- 本阶段不迁移、不归档、不删除当前 `tmp/task-2-1-acceptance/working`。
- 文件清理与部署能力分开执行，任何删除均需再次明确确认。

## File Structure

- Create: `src/qwenpaw/platform_ops/deployment_backup.py` — 备份清单模型、校验和、归档和恢复预检。
- Create: `src/qwenpaw/cli/deployment_backup_cmd.py` — 容器维护 CLI。
- Modify: `src/qwenpaw/cli/main.py` — 注册内部维护命令。
- Modify: `deploy/Dockerfile.multi-user` — 安装 PostgreSQL client 并包含维护命令。
- Modify: `deploy/compose.production.yml` — 增加 `agent-maintenance` profile。
- Modify: `deploy/weldon.sh` — 转发 `backup`/`restore`。
- Modify: `deploy/weldon.ps1` — 转发 `backup`/`restore`。
- Create: `tests/unit/platform_ops/test_deployment_backup.py` — 清单、脱敏、校验和、空目录检查测试。
- Create: `tests/integration/deploy/test_backup_restore_roundtrip.py` — 隔离容器往返测试。
- Create: `scripts/audit_repository_artifacts.py` — 只读分类器。
- Create: `tests/unit/scripts/test_audit_repository_artifacts.py` — 分类规则测试。
- Modify: `.gitignore` — 排除本地清单输出与归档。
- Modify: `.dockerignore` — 排除本地数据和测试证据。
- Modify: `docs/deployment.md` — 备份、恢复和未来迁移操作说明。

---

### Task 1: 备份清单和秘密脱敏

**Files:**
- Create: `src/qwenpaw/platform_ops/deployment_backup.py`
- Create: `tests/unit/platform_ops/test_deployment_backup.py`

**Interfaces:**
- Consumes: 备份目录、Git 提交号、镜像摘要、Alembic 版本、部署环境字典。
- Produces: `DeploymentBackupManifest`、`sanitize_environment(env: Mapping[str, str]) -> dict[str, str]`、`sha256_file(path: Path) -> str`、`write_manifest(root: Path, manifest: DeploymentBackupManifest) -> Path`、`verify_manifest(root: Path) -> VerificationResult`。

- [ ] **Step 1: 写清单序列化、脱敏和篡改检测测试**

```python
def test_environment_manifest_never_contains_secrets(tmp_path):
    clean = sanitize_environment({
        "WELDON_DB_USER": "weldon",
        "WELDON_DB_PASSWORD": "secret-value",
        "API_TOKEN": "token-value",
    })
    payload = json.dumps(clean)
    assert clean["WELDON_DB_USER"] == "weldon"
    assert "secret-value" not in payload
    assert "token-value" not in payload


def test_verify_manifest_detects_changed_archive(tmp_path):
    archive = tmp_path / "working.tar.gz"
    archive.write_bytes(b"before")
    manifest = manifest_for(archive)
    archive.write_bytes(b"after")
    assert verify_manifest(tmp_path).ok is False
```

- [ ] **Step 2: 运行测试并确认模块尚不存在**

Run: `python -m pytest tests/unit/platform_ops/test_deployment_backup.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现版本化清单模型和严格敏感字段过滤**

```python
@dataclass(frozen=True)
class DeploymentBackupManifest:
    format_version: int
    created_at: str
    source_commit: str
    image_digest: str
    alembic_version: str
    files: dict[str, str]
    environment: dict[str, str]


SENSITIVE_NAME_PARTS = ("PASSWORD", "TOKEN", "SECRET", "KEY", "CREDENTIAL", "DATABASE_URL")
```

序列化采用 UTF-8 JSON；文件清单只使用备份根目录内的相对 POSIX 路径。

- [ ] **Step 4: 实现流式 SHA-256 与清单验证**

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 5: 运行单元测试**

Run: `python -m pytest tests/unit/platform_ops/test_deployment_backup.py -q`

Expected: PASS。

- [ ] **Step 6: 在获得用户单独提交确认后创建清单提交**

```bash
git add src/qwenpaw/platform_ops/deployment_backup.py tests/unit/platform_ops/test_deployment_backup.py
git commit -m "feat: 增加部署备份清单与校验"
```

### Task 2: 容器内一致性备份命令

**Files:**
- Create: `src/qwenpaw/cli/deployment_backup_cmd.py`
- Modify: `src/qwenpaw/cli/main.py`
- Modify: `deploy/Dockerfile.multi-user`
- Modify: `deploy/compose.production.yml`
- Modify: `deploy/weldon.sh`
- Modify: `deploy/weldon.ps1`
- Create: `tests/unit/cli/test_deployment_backup_cmd.py`

**Interfaces:**
- Consumes: Task 1 的清单接口，以及 `/data/working`、`/data/secrets`、`/data/backups`。
- Produces: 内部命令 `python -m qwenpaw deployment-backup create --output /data/backups`；外部入口 `weldon backup`。

- [ ] **Step 1: 写命令参数、目录边界和失败清理测试**

```python
def test_backup_output_must_be_inside_backup_root(runner, tmp_path):
    result = runner.invoke(cli, ["create", "--output", str(tmp_path.parent)])
    assert result.exit_code != 0
    assert "backup root" in result.output.lower()


def test_failed_pg_dump_leaves_no_final_archive(monkeypatch, runner, backup_root):
    monkeypatch.setattr(subprocess, "run", raise_called_process_error)
    result = runner.invoke(cli, ["create", "--output", str(backup_root)])
    assert result.exit_code != 0
    assert list(backup_root.glob("*.tar.gz")) == []
```

- [ ] **Step 2: 实现先写临时目录、成功后原子改名的备份流程**

```python
with tempfile.TemporaryDirectory(dir=backup_root, prefix=".creating-") as temp:
    temp_root = Path(temp)
    run_pg_dump(temp_root / "database.dump")
    create_tar(data_root / "working", temp_root / "working.tar.gz")
    create_tar(data_root / "secrets", temp_root / "secrets.tar.gz")
    write_manifest(temp_root, build_manifest(temp_root))
    verify_or_raise(temp_root)
    os.replace(temp_root, final_root)
```

实际实现中临时目录不能由 `TemporaryDirectory` 在 `os.replace` 后再次清理目标路径；使用显式目录和 `try/finally`，只删除尚未发布的临时路径。

- [ ] **Step 3: 增加 `agent-maintenance` profile 并安装 `postgresql-client`**

`agent-maintenance` 与应用使用同一镜像和 `/data` 挂载，但不对外开放端口。入口脚本执行备份前停止 `agent-app`，结束后无论成功失败均尝试恢复应用，并保留原始非零状态。

- [ ] **Step 4: 运行 CLI 和 Compose 契约测试**

Run: `python -m pytest tests/unit/cli/test_deployment_backup_cmd.py tests/integration/deploy/test_production_compose.py -q`

Expected: PASS；失败路径不产生可见最终备份。

- [ ] **Step 5: 在获得用户单独提交确认后创建备份命令提交**

```bash
git add src/qwenpaw/cli/deployment_backup_cmd.py src/qwenpaw/cli/main.py deploy/Dockerfile.multi-user deploy/compose.production.yml deploy/weldon.sh deploy/weldon.ps1 tests/unit/cli/test_deployment_backup_cmd.py
git commit -m "feat: 增加一致性生产备份命令"
```

### Task 3: 安全恢复和历史路径预检

**Files:**
- Modify: `src/qwenpaw/platform_ops/deployment_backup.py`
- Modify: `src/qwenpaw/cli/deployment_backup_cmd.py`
- Modify: `tests/unit/platform_ops/test_deployment_backup.py`
- Create: `tests/integration/deploy/test_backup_restore_roundtrip.py`

**Interfaces:**
- Consumes: 经过 Task 1 验证的备份目录。
- Produces: `preflight_restore(backup_root: Path, target_data_root: Path) -> RestorePreflight`、`scan_legacy_absolute_paths(...) -> list[LegacyPathFinding]`、命令 `restore --source ... --target-data-root ...`。

- [ ] **Step 1: 写非空目标拒绝、校验失败拒绝和绝对路径报告测试**

```python
def test_restore_rejects_non_empty_target(tmp_path, valid_backup):
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(RestoreValidationError, match="empty"):
        preflight_restore(valid_backup, target)


def test_windows_paths_are_reported_without_rewriting(valid_backup, empty_target):
    findings = scan_legacy_absolute_paths(valid_backup)
    assert any(item.kind == "windows_drive" for item in findings)
    assert source_database_bytes(valid_backup) == original_database_bytes
```

- [ ] **Step 2: 实现恢复预检并要求显式目标实例**

预检顺序固定为：读取清单版本、校验全部 SHA-256、确认目标数据根为空、确认数据库目标无业务表、输出历史路径报告、确认镜像/数据库版本兼容。任何一步失败均不写目标。

- [ ] **Step 3: 实现恢复顺序和中断清理**

恢复顺序固定为：创建目标目录 → 解包 `working`/`secrets` 到临时兄弟目录 → 创建空数据库/schema → `pg_restore --clean --if-exists` 到空目标 → 显式数据库升级检查 → 原子发布文件目录 → 启动应用 → 业务验证。失败时保持源备份不变，并移除仅由本次恢复创建的空目标。

- [ ] **Step 4: 在隔离 Compose 项目做备份恢复往返**

测试建立用户、智能体、知识库、记忆和产物；备份后恢复到第二个空数据根和第二个 Compose 项目名；验证对象数量、文件 SHA-256 和作用域一致。

Run: `python -m pytest tests/integration/deploy/test_backup_restore_roundtrip.py -q`

Expected: PASS；源实例数据无修改。

- [ ] **Step 5: 在获得用户单独提交确认后创建恢复提交**

```bash
git add src/qwenpaw/platform_ops/deployment_backup.py src/qwenpaw/cli/deployment_backup_cmd.py tests/unit/platform_ops/test_deployment_backup.py tests/integration/deploy/test_backup_restore_roundtrip.py
git commit -m "feat: 增加空实例恢复与路径预检"
```

### Task 4: 仓库临时文件只读审计

**Files:**
- Create: `scripts/audit_repository_artifacts.py`
- Create: `tests/unit/scripts/test_audit_repository_artifacts.py`
- Modify: `.gitignore`
- Modify: `.dockerignore`

**Interfaces:**
- Consumes: 仓库根目录和 `git ls-files` 结果。
- Produces: `classify_path(path: Path, tracked: bool) -> Classification`；JSON 报告分类为 `business_data`、`evidence_or_backup`、`regenerable`、`tracked_maintenance_asset`。

- [ ] **Step 1: 写分类规则测试**

```python
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tmp/task-2-1-acceptance/working/history.db", "business_data"),
        ("playwright-report/index.html", "regenerable"),
        ("test-results/chat.png", "evidence_or_backup"),
        ("tests/unit/test_example.py", "tracked_maintenance_asset"),
    ],
)
def test_classification(path, expected):
    assert classify_path(Path(path), tracked=path.startswith("tests/")) == expected
```

- [ ] **Step 2: 实现只读扫描器**

扫描器只调用 `stat`、`git ls-files` 和哈希/大小统计，不调用 `unlink`、`rmdir`、`Remove-Item` 或移动操作。报告包括相对路径、类别、文件数、总大小和推荐动作，不读取 Secret 文件正文。

- [ ] **Step 3: 运行分类测试并生成本机报告**

Run: `python -m pytest tests/unit/scripts/test_audit_repository_artifacts.py -q`

Run: `python scripts/audit_repository_artifacts.py --root . --output build/repository-artifact-audit.json`

Expected: PASS；当前工作目录数据归类为 `business_data`，报告不会建议自动删除。

- [ ] **Step 4: 完善忽略规则**

`.gitignore` 与 `.dockerignore` 加入审计确认的可再生目录和本地归档扩展名；正式 tests、迁移脚本和项目文档仍受 Git 管理，仅从生产镜像上下文排除。

- [ ] **Step 5: 在获得用户单独提交确认后创建审计提交**

```bash
git add scripts/audit_repository_artifacts.py tests/unit/scripts/test_audit_repository_artifacts.py .gitignore .dockerignore
git commit -m "chore: 增加仓库临时文件只读审计"
```

### Task 5: 运维文档和灾难恢复演练

**Files:**
- Modify: `docs/deployment.md`
- Create: `docs/backup-restore-runbook.md`
- Modify: `docs/deployment-acceptance.md`

**Interfaces:**
- Consumes: Tasks 1-4 的命令和清单格式。
- Produces: 可由另一位管理员独立执行的备份恢复手册。

- [ ] **Step 1: 编写备份运行手册**

写明停服窗口、空间预估、`weldon backup`、清单校验、异地复制、保留策略和失败恢复应用步骤。示例输出使用假提交号和脱敏目录，不包含真实用户路径。

- [ ] **Step 2: 编写恢复运行手册**

写明只能恢复到空数据根、新实例环境文件、校验和检查、历史路径报告、数据库升级检查、业务验证和流量切换。明确禁止在源实例上原地覆盖。

- [ ] **Step 3: 执行一次隔离灾难恢复演练**

验证用户登录、智能体访问范围、对话、个人知识库检索、记忆、产物预览和密钥引用。记录恢复点、恢复耗时、对象计数和文件校验，不记录业务正文或密钥。

- [ ] **Step 4: 运行完整相关测试**

Run: `python -m pytest tests/unit/platform_ops/test_deployment_backup.py tests/unit/cli/test_deployment_backup_cmd.py tests/unit/scripts/test_audit_repository_artifacts.py tests/integration/deploy/test_backup_restore_roundtrip.py -q`

Expected: PASS。

- [ ] **Step 5: 在获得用户单独提交确认后创建文档提交**

```bash
git add docs/deployment.md docs/backup-restore-runbook.md docs/deployment-acceptance.md
git commit -m "docs: 增加 WeldonAgent 备份恢复手册"
```
