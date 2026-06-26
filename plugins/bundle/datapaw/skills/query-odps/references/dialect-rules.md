# ODPS 方言规则

生成 ODPS SQL 前对照本表；禁止把 MySQL / PostgreSQL / Hive 习惯直接搬进 MaxCompute。

## 函数与语法对照

| 错误写法（常见） | ODPS 正确写法 | 说明 |
|------------------|---------------|------|
| `NOW()` | `GETDATE()` | 当前时间 |
| `CURDATE()` | `TO_CHAR(GETDATE(), 'yyyy-mm-dd')` 或 `DATETRUNC(GETDATE(), 'dd')` | 当前日期 |
| `IFNULL(a, b)` | `NVL(a, b)` 或 `COALESCE(a, b)` | 空值替换 |
| `IIF(cond, a, b)` | `IF(cond, a, b)` 或 `CASE WHEN cond THEN a ELSE b END` | SQLite 风格 |
| `DATE_FORMAT(d, '%Y%m%d')` | `TO_CHAR(d, 'yyyymmdd')` | 日期格式化 |
| `STRFTIME(...)` | `TO_CHAR(...)` | 不支持 SQLite strftime |
| `REGEXP` / `REGEXP_LIKE` | `RLIKE` 或 `REGEXP`（优先 `RLIKE`） | 正则匹配 |
| `LIMIT x OFFSET y` | `LIMIT y, x` 或子查询 + `ROW_NUMBER()` | 分页因版本而异 |
| `INTERVAL '7' DAY` | `DATEADD(GETDATE(), -7, 'dd')` | 日期间隔 |
| `YEAR(col)` / `MONTH(col)` | 对 DATE 类型可用；**STRING 日期列先 `TO_DATE`** | 类型不匹配会静默 NULL |
| `CAST(x AS VARCHAR)` | `CAST(x AS STRING)` | 字符串类型名 |

## 日期与分区字段

分区列命名与谓词写法见 **`partition-semantics.md`**。写谓词前确认元数据中的 `dtype`（STRING vs BIGINT）。

## 字符串与 JSON

- 字符串字面量用单引号 `'...'`。
- `LIKE` 通配：`%`、`_`；正则用 `RLIKE 'pattern'`。
- JSON：`GET_JSON_OBJECT(col, '$.path')`；不要用 PostgreSQL 的 `->>`。

## 聚合与窗口

- `COUNT(DISTINCT x)` 支持；超大规模时注意资源。
- 窗口函数与标准 SQL 接近。
- **禁止**在 WHERE 中直接引用 SELECT 列表别名；用子查询或 HAVING。

## 子查询与 CTE

- `WITH cte AS (...)` 支持；最终须输出 **一条** `SELECT`。
- 相关子查询能改 JOIN 则改 JOIN。

## 会话级 SET（可选）

仅在类型或输出格式失败时，在 **WITH 之前** 添加：

```sql
SET odps.sql.type.system.odps2=true;
SET odps.sql.hive.compatible=true;
```

默认 **不写 SET**，除非排错需要。

## 自检清单

- [ ] 无 MySQL / SQLite 专有函数
- [ ] 分区表已写分区谓词
- [ ] 日期列类型与字面量格式一致
- [ ] 正则用 `RLIKE`
- [ ] 仅一条可执行 SELECT（或 WITH + SELECT）
