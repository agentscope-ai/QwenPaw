# ODPS 性能纪律

ODPS 按扫描量计费；违反下列规则易导致超时、失败或费用过高。

## 1. 分区必过滤

- 分区表 **必须** 在 WHERE（或 JOIN ON 的可裁剪分支）中包含分区列等值或 bounded range。
- 探索未知表时：见 `partition-semantics.md`（`_df` 可用 `MAX_PT`；否则用元数据 range）。
- **禁止** `SELECT * FROM partitioned_table` 无分区条件。

## 2. 列裁剪

- **禁止** `SELECT *` 上生产宽表；只选分析所需列。
- JOIN 两侧只投影 JOIN key + 聚合所需列，再外层聚合。

## 3. 先过滤、先聚合、再 JOIN

- 大表 JOIN 前各分支先 `WHERE` 分区 + 业务过滤 + `GROUP BY` 到所需粒度，再 JOIN 汇总。
- **禁止** 两张大宽表直接 JOIN 后再 `GROUP BY`（除非明确小表 MapJoin）。

## 4. MapJoin 提示

```sql
SELECT /*+ MAPJOIN(b) */ a.ds, COUNT(DISTINCT a.user_id)
FROM fact a
JOIN dim b ON a.user_id = b.user_id
WHERE a.ds = '20250501'
GROUP BY a.ds;
```

不要对未知行数的大表滥用 MapJoin。

## 5. 探索与调试 LIMIT

- 新 SQL 首次验证可加 `LIMIT 100`。
- 最终交付 SQL **可以** 无 LIMIT（全量聚合），但须通过执行前自检；探索阶段不得无 LIMIT 扫全表。

## 6. DISTINCT 与 COUNT

- `COUNT(DISTINCT user_id)` 昂贵时，考虑先按天/按分区去重子查询再汇总。

## 7. UNION ALL vs UNION

- 默认 `UNION ALL`；仅确需去重用 `UNION`。

## 8. 多次扫描同一表

- 同一分区范围内多次读同一大表，合并为一次扫描 + CASE / GROUP BY，或用 CTE（仍计费）。

## 失败时

| 现象 | 处理 |
|------|------|
| 缺分区 / 扫全表 | 加分区、减列、先聚合 |
| 超时或扫描过大 | 优化 SQL |
| 执行成功 | 正常落 CSV |
