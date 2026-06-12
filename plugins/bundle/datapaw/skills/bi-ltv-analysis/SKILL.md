---
name: bi-ltv-analysis
description: 评估单个用户或用户群体在生命周期内创造的收益。触发条件：当需要用户生命周期价值计算与分析时触发，如对话中涉及“LTV”、“LTV 分析”、“用户生命周期价值”、“人均收益测算”等等相近词语时调用。
---

# bi-ltv-analysis

评估**单个用户**或**用户群体**在整个生命周期内创造的收入（或利润），典型用途。

## 执行步骤

### Step 1：准备数据

根据分析任务需求与所给数据结构，明确 LTV 分析涉及的指标，即**分析粒度**（用户级 / 群体级）、**收益口径**（如购买、升级等行为产生的收入、利润等）以及**生命周期**（如时间窗口、某阶段流失率等），将取数结果保存为 CSV。

整理数据为 CSV 格式，采用“分组（用户/群体） × N天（生命周期与收益数据）”，数据应至少包括分析粒度对应的对象列、收益口径对应的收入数据列以及生命周期对应的数据列。

例如，对于用户级的 LTV 分析，分析数据示例如下，

```csv
用户ID,事件时间a,收入金额a,事件时间b,收入金额b
1,2025-04-25,26.0,2025-04-26,6.5
2,2025-04-25,6.5,NaN,NaN
```

对于群体级的 LTV 分析，数据示例如下，

```csv
群体类别,a阶段流失率,a阶段收入金额,b阶段流失率,b阶段收入金额
group_1,0.366,26.0,0.121,6.5
group_2,0.253,6.5,0.754,2.0
```

若上游步骤已产出可用汇总表则直接使用，否则按口径从明细聚合（按用户求和、按队列求和等）。

注意：若数据包含留存率、流失率等指标可以用于 LTV 分析，则统一使用**流失率**进行计算，若数据中仅包含留存率，则转化为流失率进行 LTV 计算和分析，一般情况，流失率=1-留存率。

### Step 2：计算 LTV

**LTV 计算公式一**：

\(LTV = ARPU \times 生命周期\)

**LTV 计算公式二**：

\(LTV = ARPU \times \frac{1}{流失率}\)

**ARPU**（Average Revenue Per User）：单位用户在**指定统计范围**内的平均收入。若 CSV 中收入列为阶段合计、且另有用户数列，则脚本按 \(ARPU = 收入 / 用户数\) 计算；若收入列已是人均口径，则无需 `--users-col`。

**群体多阶段**（含多列「阶段流失率 + 阶段收入金额」）：按阶段顺序，用存活率对收入加权求和：

\[
LTV = \sum_{j} 收入_j \times \prod_{k<j}(1 - 流失率_k)
\]

#### 方式一：使用脚本

使用 `<skill-dir>/scripts/ltv_calc.py` 计算 LTV。结果写入 `--output-file` 指定的 CSV：**第一列为输入中的分析对象列**（`--object-col`），**第二列为 LTV**（默认列名 `ltv`）。

**用户级（观测窗口内各阶段收入累计）**：

```bash
python <skill-dir>/scripts/ltv_calc.py \
  --input-file "<输入 CSV 路径>" \
  --object-col "用户ID" \
  --revenue-cols "收入金额a" "收入金额b" \
  --output-file "<输出 CSV 路径>"
```

**群体级（多阶段流失率 + 收入）**：

```bash
python <skill-dir>/scripts/ltv_calc.py \
  --input-file "<输入 CSV 路径>" \
  --object-col "群体类别" \
  --revenue-cols "a阶段收入金额" "b阶段收入金额" \
  --churn-cols "a阶段流失率" "b阶段流失率" \
  --output-file "<输出 CSV 路径>"
```

**公式一（单列收入 + 生命周期 T）**：

```bash
python <skill-dir>/scripts/ltv_calc.py \
  --input-file "<输入 CSV 路径>" \
  --object-col "群体类别" \
  --revenue-col "a阶段收入金额" \
  --users-col "用户数" \
  --lifecycle 12 \
  --formula lifecycle \
  --output-file "<输出 CSV 路径>"
```

**公式二（单列收入 + 单列流失率）**：

```bash
python <skill-dir>/scripts/ltv_calc.py \
  --input-file "<输入 CSV 路径>" \
  --object-col "群体类别" \
  --revenue-col "a阶段收入金额" \
  --churn-col "a阶段流失率" \
  --formula churn \
  --output-file "<输出 CSV 路径>"
```

若数据列为**留存率**而非流失率，增加 `--rate-is-retention`（按 流失率 = 1 − 留存率 转换）。

**参数说明**：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--input-file` | 输入数据文件路径（CSV） | （必填） |
| `--object-col` | 分析对象列名（用户 ID、群体类别等） | （必填） |
| `--output-file` | 输出 CSV 路径（两列：分析对象、LTV） | （必填） |
| `--ltv-col` | 输出中 LTV 列名 | `ltv` |
| `--formula` | `cumulative` / `lifecycle` / `churn` / `stage_weighted`；省略时按其它参数自动推断 | 自动推断 |
| `--revenue-cols` | 多阶段收入列名（可多个） | — |
| `--churn-cols` | 多阶段流失率列名，与 `--revenue-cols` 顺序一一对应 | — |
| `--revenue-col` | 单列收入（公式一、二） | — |
| `--churn-col` | 单列流失率（公式二） | — |
| `--lifecycle` | 生命周期数值 T（公式一） | — |
| `--users-col` | 用户数列（收入为合计时计算 ARPU） | — |
| `--rate-is-retention` | 将流失率列按留存率处理并转换为流失率 | 否 |
