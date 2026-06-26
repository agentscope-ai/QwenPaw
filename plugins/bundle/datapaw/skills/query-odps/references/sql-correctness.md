# SQL 结构纪律

在方言与性能之外，保证 SELECT 语义正确、可审查。

## 1. 单语句

- 只输出 **一条** `SELECT` 或 `WITH ... SELECT`。
- 禁止多语句、DDL/DML 混入读路径。

## 2. 投影（SELECT 列表）

- 每个输出列应有 **明确别名**：`SUM(gmv) AS gmv_total`。
- 维度列 + 指标列同时出现；避免只输出聚合无 GROUP BY 维度（除非 intentional 大盘）。
- **禁止** `SELECT *`（见 `performance.md`）。

## 3. FROM 主体表

- 明确 **事实表 / 主表** 作为 FROM 第一来源；维表 JOIN 附加。
- 多事实表时，在 prompt 或澄清结论中说明驱动表。

## 4. JOIN 纪律

- 所有 JOIN 带 **ON** 条件；禁止 `CROSS JOIN` 除非行数已证明极小。
- **JOIN 键先对齐再写 ON**（与 `value-discovery.md` 对过滤值的纪律一致）：
  - 左右表连接列是否同一实体（如 `user_id` vs `uid`）、类型是否一致；
  - 格式是否同口径：日期是 `yyyyMMdd` 还是带 `-`、ID 是否一侧有前缀/补零、空串与 NULL 是否混用；
  - 不确定时先用 **小步探针**（`LIMIT`、单表 `DISTINCT`、或中间结果落临时表后 `COUNT`）验证键能否对上，再写完整 JOIN。
- JOIN 键类型不一致时，STRING 与 BIGINT 比较前 `CAST`；禁止靠隐式转换碰运气。
- LEFT JOIN 后对维表字段聚合时注意 NULL。
- 多表 JOIN 优先 **分步落临时表**（见 SKILL 核心原则「分步查询」）：先验证各侧过滤与键格式，再基于临时表 JOIN，避免一步大 SQL 跑很久才发现键对不上。

## 5. GROUP BY 与聚合

- SELECT 中非聚合列必须出现在 `GROUP BY` 或合法窗口用法中。
- 比率类指标：**分子分母口径**与澄清阶段一致（用户数比例：先日比例再日均；次数比例：时段求和相除）。
- **禁止** JOIN 后直接 `COUNT(*)` 当用户数——用 `COUNT(DISTINCT user_id)`。

## 6. 过滤条件位置

- 分区与强选择性条件放 **WHERE**（JOIN 之前能下推则下推）。

## 7. ORDER BY

- 分析交付 SQL 可有 `ORDER BY`；无业务需要时可省略。
- `ORDER BY` 列尽量来自 GROUP BY 维度。

## 8. 执行前自检对应

| 问题类型 | 处理 |
|----------|------|
| 非 ODPS 方言 | 改函数/语法 |
| 无分区谓词 | 加 ds/dt |
| SELECT * | 列裁剪 |
| 多语句 | 合并为一条 |
| 引用元数据外的表 | 重拉元数据或改 SQL |

error 级问题 **必须**修 SQL 后再执行。
