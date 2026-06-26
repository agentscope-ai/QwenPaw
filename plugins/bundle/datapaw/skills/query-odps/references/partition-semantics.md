# 分区语义

SQL 生成与元数据拉取后写分区谓词。分区选错会导致空结果、全表扫描或口径偏差。

## 分区列名

- 常见列名：`ds`（`yyyymmdd` / `yyyymm`）、`dt`、`pt`。
- **以元数据 `partition_columns` 为准**；不要假设所有表都是 `ds`。
- 写谓词前确认列 **dtype**（STRING vs BIGINT）。

## 快照表 vs 增量表

| 模式 | 含义 | 典型命名 | 查「最新」时的默认 |
|------|------|----------|-------------------|
| **按天全量快照** | 每个分区存当日完整切片 | 表名常以 `_df` 结尾 | `WHERE pt = MAX_PT('<project>.<table>')` 或 `ds = MAX_PT(...)` |
| **按天增量** | 分区只存当日增量 | 一般 `_di` / 业务后缀 | **不能**默认 MAX_PT；需明确日期范围 |

**规则**：

- 表名以 `_df` 结尾且元数据未反对时，用户说「最新数据」且未给日期 → 可优先 `MAX_PT`（分区列用元数据指定列）。
- **非 `_df` 表**：不要默认 `MAX_PT`；用问题 `scope` 的时间范围写 bounded range。
- 快照与增量 **不可互换**；不确定时消歧或查元数据 `description`。

## MAX_PT 用法

```sql
SELECT col1, col2
FROM <project>.some_table_df
WHERE pt = MAX_PT('<project>.some_table_df')
LIMIT 20;
```

- `MAX_PT` 参数用 **与 FROM 一致的全限定表名**。
- 交付聚合 SQL 可无 LIMIT，但须通过执行前自检。

## 显式分区范围（推荐）

业务分析有明确时间窗时，优先 bounded range：

```sql
WHERE ds >= '20250401' AND ds <= '20250430'
```

## 检查近期分区（探针）

```sql
SELECT ds, COUNT(1) AS cnt
FROM <project>.some_table
GROUP BY ds
ORDER BY ds DESC
LIMIT 20;
```

字面量 DISTINCT 探针须带分区谓词，见 `value-discovery.md`。

## 与 performance.md 的关系

任何分区表 **必须有分区谓词**（MAX_PT、等值或 range 均可）。
