---
name: query-odps
description: MaxCompute（ODPS）只读 SELECT 写法与执行纪律。**以下场景必须立即加载**：生成、改写或提交任何 ODPS / MaxCompute SQL（SELECT、WITH、JOIN、子查询、nl2sql）；覆盖方言、分区、结构纪律、优化、字面量取值、执行纪律与失败回退。
---

# query-odps

MaxCompute **只读 SELECT** 的域规则：怎么写对 SQL、怎么优化、怎么自检、怎么执行、失败如何回退。

**禁止**：直连 PyODPS；绕过标准执行通道自写 CSV。

## 规则索引

| 场景 | 读 |
|------|-----|
| 写 SQL（方言） | `references/dialect-rules.md` |
| 分区 / MAX_PT | `references/partition-semantics.md` |
| SELECT 结构 | `references/sql-correctness.md` |
| 性能 / 扫描 | `references/performance.md` |
| 业务字面量 → 库内值 | `references/value-discovery.md` |
| 失败回退 | `references/error-recovery.md` |

## 核心原则

1. **先取证** — 无元数据不臆测表名、列名、口径。
2. **过滤值与 JOIN 键先定再写 SQL** — 时间范围、分区边界、维度筛选、业务字面量对应的库内取值等 **全部确认** 后再生成 SQL；不得在 WHERE 里留臆测的枚举或占位过滤值。未映射的字面量确认参考 `value-discovery.md`。**涉及 JOIN 时同理**：写 ON 之前先对齐左右两边的连接键——列名是否同一实体、类型是否一致、格式是否同口径（如 `user_id` 是否都带前缀、`ds` 是 `yyyyMMdd` 还是 `yyyy-MM-dd`、STRING 是否需 `TRIM`/`CAST`）；禁止在未核实键格式时直接拼 JOIN。
3. **分步查询，勿一次开大 SQL** — 执行结果会落入 **ODPS 临时表**（如 `cm_tmp_*`），应拆成可快速校验的小步：探针 / 单表过滤 / 中间结果落表 → 再基于临时表做下一步。**禁止** 一次性提交超大、多表深 JOIN、长窗口的「一步到位」SQL；一旦口径或 JOIN 键有误，会等非常久才失败，用户无法及时发现问题。
4. **性能纪律 + 执行前自检** — 写 SQL 前 **必须读** `references/performance.md`（分区必过滤、列裁剪、先聚合再 JOIN 等）；定稿后再对照 `performance.md`、`partition-semantics.md` 等 references 自检，明显违规 **不得执行**。ODPS 按扫描量计费，忽视此项会导致超时或严重资源浪费。
5. **只走标准执行通道** — SELECT 仅经平台提供的执行通道提交；禁止 PyODPS 直连或自写 CSV。结果落盘路径由运行环境决定；`truncated` 须在回复中说明；禁止把超大结果全量贴进对话。
