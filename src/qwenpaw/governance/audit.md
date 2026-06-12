# Audit Log 设计文档

## 概述

`AuditLog` 是 QwenPaw governance 层的审计日志系统，负责记录每次 tool call 的策略裁决结果。每次 `ResourceGovernor.assert_and_audit()` 调用都会产生一条审计记录，用于事后追溯和安全分析。

## 存储方案

### 选型：单文件 SQLite

**决策时间**：2026-06-05

**选型理由**：
- **零依赖** — Python 标准库自带 `sqlite3`，无需引入第三方包
- **查询能力强** — SQL 天然支持按 agent / tool / 时间范围 / workspace 过滤、排序、分页
- **持久化简洁** — 单文件，全局共享，所有 workspace 的审计记录集中存储
- **WAL 模式** — 支持多 governor 并发写入

**对比其他方案**：

| 方案 | 优势 | 不选的原因 |
|------|------|-----------|
| JSONL | 文本可读，天然按时间切分 | 查询需逐行扫描，无法索引 |
| DuckDB | 分析型 SQL 极强 | 引入额外依赖，杀鸡用牛刀 |
| TinyDB | 纯 Python 风格 | 引入额外依赖，并发差 |
| 按月分 SQLite | 删文件 = 删数据 | 增加路由复杂度，当前体量不需要 |

**数据清理**：定期 `DELETE + VACUUM`，单文件方案最简单。审计日志体量不大（每天几百到几千条），VACUUM 代价可接受。

### 存储路径

```
~/.qwenpaw/audit.db
```

全局单例，所有 workspace 共享同一个数据库文件。每条记录通过 `workspace_dir` 字段区分来源。

### 表结构

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    ts           TEXT NOT NULL,
    workspace_dir TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    target       TEXT NOT NULL,
    decision     TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    extra        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_dir);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_events(tool_name);
```

| 列 | 类型 | 说明 |
|---|---|---|
| `ts` | TEXT | ISO 8601 UTC 时间戳 |
| `workspace_dir` | TEXT | 所属 workspace 路径 |
| `agent_id` | TEXT | 发起调用的 agent ID |
| `session_id` | TEXT | 当前会话 ID |
| `tool_name` | TEXT | tool 名称 |
| `target` | TEXT | tool 目标参数 |
| `decision` | TEXT | 裁决结果 |
| `reason` | TEXT | 额外说明 |
| `extra` | TEXT | JSON 序列化的扩展字段 |

### SQLite 配置

```python
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row        # 字典式访问
conn.execute("PRAGMA journal_mode=WAL")  # 并发写支持
```

## 核心设计

### 设计原则

- **追加式日志**：只增不改，保证审计完整性
- **立即持久化**：`record()` 直接写库，无内存缓冲，无数据丢失风险
- **5W 记录模型**：who / what / when / outcome / why

### 数据结构

#### `AuditEvent`

一条审计记录，记录 5W 信息：

```python
@dataclass
class AuditEvent:
    ts: str              # when - ISO 8601 UTC 时间戳
    workspace_dir: str   # where - 所属 workspace 路径
    agent_id: str        # who - 发起调用的 agent ID
    session_id: str      # who - 当前会话 ID
    tool_name: str       # what - tool 名称（如 "Bash", "Read", "Write"）
    target: str          # what - tool 目标参数（如 "ls -lh", "src/main.py"）
    decision: str        # outcome - 裁决结果（"allow" | "deny" | "ask" | "sandbox_fallback"）
    reason: str = ""     # why - 额外说明（如 violation 原因）
    extra: dict          # 扩展字段（预留）
```

#### `AuditLog`

审计日志管理器，**全局单例**，所有 workspace/governor 共享：

```python
class AuditLog:
    MAX_RECORDS = 100_000   # 触发自动清理的阈值
    PURGE_COUNT = 10_000    # 每次清理删除的条数

    _instance: Optional[AuditLog] = None

    @classmethod
    def get_instance(cls) -> AuditLog:
        """获取全局单例，首次调用时初始化。"""

    def close(self) -> None                    # 关闭连接，重置单例
    def record(self, workspace_dir, tc_spec, decision) -> None  # 立即写库
    def query(...) -> List[AuditEvent]         # 按条件查询
    def purge(before: str) -> int              # 删除过期记录 + VACUUM
    @property
    def count(self) -> int                     # 当前记录总数
```

**单例特性**：
- 全局唯一实例，存储在 `~/.qwenpaw/audit.db`
- 多个 `ResourceGovernor` 共享同一个 `AuditLog` 实例
- 通过 `get_instance()` 获取，避免重复初始化
- `record()` 调用时需传入 `workspace_dir` 标识来源

## 工作流程

### 1. 记录事件

每次 tool call 裁决时，`ResourceGovernor.assert_and_audit()` 调用 `AuditLog.record()`：

```python
# resource_governor.py:assert_and_audit
decision = self.policy.evaluate(tc_spec)
...
AuditLog.get_instance().record(str(self.workspace_dir), tc_spec, decision)
return decision
```

`record()` 内部：
1. 生成 ISO 8601 UTC 时间戳
2. 从 `ToolCallSpec`提取 agent_id / session_id / tool_name / target
3. 从 `GovernanceDecision` 提取 action 和 reason
4. 直接 `INSERT INTO` SQLite 并 `COMMIT`
5. 检查总条目数，若达到 `MAX_RECORDS`（10 万条），自动删除最旧的 `PURGE_COUNT`（1 万条）

**无需内存缓冲，无需 flush。**

#### 自动清理策略

当 `record()` 写入后，若总条目数达到阈值，自动触发清理：

```python
def record(self, workspace_dir: str, tc_spec, decision) -> None:
    # ... INSERT (包含 workspace_dir) ...
    self._conn.commit()
    # 自动清理检查
    if self.count >= self.MAX_RECORDS:
        self._auto_purge()

def _auto_purge(self) -> None:
    """删除最旧的 PURGE_COUNT 条记录并 VACUUM。"""
    # 找到第 PURGE_COUNT 旧的时间戳作为截止点
    row = self._conn.execute(
        "SELECT ts FROM audit_events ORDER BY ts ASC LIMIT 1 OFFSET ?",
        (self.PURGE_COUNT - 1,)
    ).fetchone()
    if row:
        self._conn.execute(
            "DELETE FROM audit_events WHERE ts < ?", (row["ts"],)
        )
        self._conn.commit()
        self._conn.execute("VACUUM")
```

**设计考量**：
- **阈值 10 万条**：约 50 MB，VACUUM 耗时 ~1-2s，对运行影响可忽略
- **删除 1 万条**：保留约 9 万条历史，避免频繁触发
- **按时间删除**：保留最新数据，删除最旧数据，符合审计场景直觉
- **自动触发**：对调用方透明，无需额外管理

### 2. 查询

```python
def query(
    self,
    workspace_dir: Optional[str] = None,  # 按 workspace 过滤
    agent_id: Optional[str] = None,       # 按 agent 过滤
    tool_name: Optional[str] = None,      # 按工具名过滤
    decision: Optional[str] = None,       # 按裁决结果过滤
    since: Optional[str] = None,          # 起始时间 (ISO 8601)，含
    until: Optional[str] = None,          # 截止时间 (ISO 8601)，含
    limit: int = 100,                     # 每页条数
    offset: int = 0,                      # 偏移量（翻页用）
) -> tuple[List[AuditEvent], int]:
    """查询审计事件，支持分页。

    Returns:
        (events, total) — 事件列表和符合条件的总条数
    """
```

**翻页示例**：

```python
page_size = 50

# 第 1 页
events, total = audit_log.query(
    workspace_dir="/path/to/workspace",
    decision="deny",
    limit=page_size,
    offset=0,
)
print(f"共 {total} 条，第 1 页显示 {len(events)} 条")

# 第 2 页
events, total = audit_log.query(
    workspace_dir="/path/to/workspace",
    decision="deny",
    limit=page_size,
    offset=page_size,
)
```

### 3. 手动清理

除自动清理外，也提供手动清理接口，供外部按自定义条件清理：

```python
def purge(self, before: str) -> int:
    """删除指定时间之前的记录并 VACUUM 回收空间。

    Args:
        before: 截止时间 (ISO 8601)，不含

    Returns:
        删除的记录数
    """
    cursor = self._conn.execute(
        "DELETE FROM audit_events WHERE ts < ?", (before,)
    )
    self._conn.commit()
    deleted = cursor.rowcount
    if deleted > 0:
        self._conn.execute("VACUUM")
    return deleted
```

**使用示例**：

```python
# 删除 30 天前的记录
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
deleted = audit_log.purge(cutoff)
```

**注意事项**：
- VACUUM 会短暂锁库，但审计日志体量小，影响可忽略
- 建议低频调用（每周/每月一次），或放在 session 结束时执行

### 4. 生命周期

| 阶段 | 操作 |
|------|------|
| 首次使用 | `AuditLog.get_instance()` → 懒初始化，建库建表 |
| 运行中 | 每次 `assert_and_audit()` → `record(workspace_dir, ...)` 立即写库 |
| 进程退出 | `AuditLog.get_instance().close()` → 关闭连接，重置单例 |

**单例管理**：
- `ResourceGovernor` 不再持有 `AuditLog` 实例，改为每次通过 `get_instance()` 获取
- 首个 governor 调用时自动初始化数据库连接
- 进程退出时关闭连接（可在 atexit 或 main 中调用 `close()`）

**对比旧方案（JSONL）的变化**：
- 删除 `_flush_audit_log()` — 不再需要内存缓冲 + 批量写文件
- 删除 `drain_events()` — 不再有内存事件列表
- 删除 governor 对 `AuditLog` 的持有关系 — 改为全局单例
- `stop()` 不再负责 flush 或 close

## 示例

### 查询某 agent 最近 100 条记录

```python
events, total = audit_log.query(agent_id="coder", limit=100)
print(f"共 {total} 条")
for e in events:
    print(f"{e.ts} [{e.workspace_dir}] {e.tool_name}({e.target}) → {e.decision}")
```

### 查询某 workspace 的拒绝操作（翻页）

```python
page_size = 50
events, total = audit_log.query(
    workspace_dir="/path/to/workspace",
    decision="deny",
    limit=page_size,
    offset=0,
)
print(f"第 1 页: {len(events)}/{total}")

# 第 2 页
events, total = audit_log.query(
    workspace_dir="/path/to/workspace",
    decision="deny",
    limit=page_size,
    offset=page_size,
)
```

### 清理 30 天前的旧数据

```python
cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
deleted = audit_log.purge(cutoff)
print(f"清理了 {deleted} 条旧记录")
```

## 实现注意事项（Review 2026-06-05）

### 1. 线程安全 — 最关键

SQLite 连接默认不能跨线程共享（`check_same_thread=True`）。但 `react_agent.py:142` 显示多个 agent 各自创建 `ResourceGovernor`，如果它们在不同线程运行，单例的连接就会出问题。

**解决方案**：`sqlite3.connect()` 时加 `check_same_thread=False`，配合 WAL 模式（SQLite 自身锁机制处理并发写）。

```python
self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
```


### 2. `target` 可能非常长

`Bash` 命令的 target 可能是一整段 shell 脚本（几百甚至上千字符）。SQLite TEXT 类型没有长度限制，不会报错，但：
- 影响索引效率（虽然 target 没建索引，但行变大会拖慢全表扫描）
- 自动清理按条数算，不控制体积

**解决方案**：考虑截断 target（如 500 字符），或保持现状但意识到这个可能性。

### 3. 自动清理里 `count` 每次 SELECT 有开销

`record()` 每次写完后都 `SELECT COUNT(*)` 检查是否触发清理。10 万条时这个查询虽然走索引但也非零开销。

**解决方案**：维护一个内存计数器，或者每 N 次 record（如每 1000 次）检查一次，避免每次都 count。

```python
# 简单方案：内存计数
self._insert_count = 0

def record(self, ...):
    # ... INSERT ...
    self._insert_count += 1
    if self._insert_count >= 1000:
        if self.count >= self.MAX_RECORDS:
            self._auto_purge()
        self._insert_count = 0
```


### 4. `close()` 后单例状态

如果某个 governor 调用了 `close()`，其他 governor 再调 `get_instance()` 拿到的是已关闭的连接。

**解决方案**：`close()` 应该重置 `_instance = None`，下次 `get_instance()` 重新初始化。

```python
def close(self) -> None:
    """关闭连接，重置单例。"""
    if self._conn:
        self._conn.close()
        self._conn = None
    AuditLog._instance = None
```

### 5. governor 的 `audit_log` property 需要清理

`resource_governor.py:222-226` 有个 `audit_log` property，单例化后这个属性要么删除，要么改为 `return AuditLog.get_instance()`。

**建议**：改为返回单例，保持向后兼容。

```python
@property
def audit_log(self) -> AuditLog:
    """获取全局 AuditLog 单例。"""
    return AuditLog.get_instance()
```
