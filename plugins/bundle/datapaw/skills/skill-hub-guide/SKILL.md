---
name: skill-hub-guide
description: Data Skill-Hub 技能仓库使用指南。在执行任何数据分析任务前，必须优先加载此技能以了解可用技能体系和调用规范。
---
# skill-hub-guide

Data Skill-Hub 是由资深数据分析专家团队设计、经过大量真实业务场景验证的通用技能仓库。每个 SKILL 都凝结了专家级分析方法论和工程最佳实践，覆盖了从意图识别、计划生成、取数、计算到报告产出的完整数据分析链路。

严格遵循本仓库中的 SKILL 定义，你将获得专家级的分析质量——逻辑严谨、结论有据、产物规范。偏离 SKILL 定义则会导致分析遗漏、结论失准或产物不可用。

**你的所有数据分析行为必须由 SKILL 驱动，严格遵循各 SKILL.md 中定义的执行步骤和规则，不得自行发挥。**

---

## 核心原则

1. **SKILL 即规范**：每个 SKILL.md 由领域专家编写，定义了该能力唯一正确的执行流程。即使你认为可以简化，也必须完整遵循
2. **脚本优先**：有脚本（scripts/）必须调脚本，不可用时才降级为自行实现
3. **参数优先级**：用户显式指定 > 域知识包 > 语义层接口 > SKILL 默认值
4. **按需调用**：禁止一次性预读所有 SKILL，根据当前执行到的子任务和步骤逐个加载对应 SKILL

---

## 技能体系

### 分层架构

技能按所在目录划分为 6 层。下表中「目录」一栏即 `skills/` 下的物理目录，新增 SKILL 时按其能力归属放入对应目录，并在本表登记。

| 层级 | 目录 | 职责 | SKILL |
| ---- | ---- | ---- | ----- |
| L0 路由 | `skills/routing/` | 判定用户意图属于哪种任务类型（查询/分析/建模/报告/非数据），将请求分发至对应处理链路 | `data-intent-router` |
| L1 规划 | `skills/planning/` | 补充上下文、匹配分析模块和指标，将用户需求转化为结构化的可执行分析计划 | `analysis-plan-builder` |
| Workflows | `skills/workflows/` | 按分析计划编排原子技能与取数能力，完成从数据获取到结论汇总的完整分析流程 | `fetch-data`（取数）<br>`bi-metric-analysis`（指标观测与异常归因）<br>`bi-retention-analysis`（留存率分析）<br>`bi-conversion-analysis`（转化率分析）<br>`bi-cohort-analysis`（同期群分析） |
| Atomic | `skills/atomic/` | 执行单一、独立的分析动作（计算、检测、下拆、归因、聚类、报告等） | **指标观测与计算**：`bi-metric-observation`、`bi-retention-rate`、`bi-conversion-rate`<br>**异常检测与阈值**：`bi-anomaly-detection`、`bi-adaptive-threshold`<br>**归因与下钻**：`bi-dimension-drilldown`、`bi-attribution-analysis`、`bi-time-impact-attribution`、`bi-new-dimension-analysis`<br>**统计与画像**：`bi-event-analysis`、`bi-funnel-analysis`、`bi-comparison-analysis`、`bi-distribution-analysis`、`bi-clustering`、`bi-ltv-analysis`<br>**报告输出**：`bi-report-generation` |
| Runtime | `skills/runtime/` | 横切面强制规范，约束所有层的执行行为（产物落盘、数据复用、异常处理、语义层查询） | `runtime-guide`、`bi-semantic-layer-guide` |
| Meta | `skills/meta/` | 仓库使用与协作约定，加载其它任何 SKILL 之前必须先读 | `skill-hub-guide`（本文件） |


### 典型调用链路

下面给出几种常见任务类型的链路。Runtime 层（`runtime-guide`、`bi-semantic-layer-guide`）在所有链路里**全程生效**，不再在每条链路中重复展开；`fetch-data` 在任何需要新取数的链路前置生效。

#### 1. BI 业务分析链路（任务类型 = 2a）

由 `data-intent-router` 判定为业务分析后，由 `analysis-plan-builder` 给出结构化计划，再根据计划落到具体的 workflow。

**1.1 通用指标分析（含异常归因）**

```
用户问题
  → L0 data-intent-router          判定为 BI 业务分析（2a）
  → L1 analysis-plan-builder       生成结构化分析计划，确认指标与角色
  → Workflows fetch-data           按计划取数落盘
  → Workflows bi-metric-analysis   编排以下原子技能：
      → bi-metric-observation
          观测北极星指标表现，确认基准数据
      → bi-anomaly-detection
          对北极星指标做异常检测
          ├─ [无外部阈值] → bi-adaptive-threshold 自适应计算阈值
          └─ [有域知识包/用户指定阈值] → 直接使用
          ├─ [发现异常]
          │   → bi-dimension-drilldown
          │       按归因维度逐层下拆
          │       └─ bi-attribution-analysis 计算贡献度
          │   → bi-time-impact-attribution
          │       拆解结构变动/趋势变动/事件影响
          │       └─ [需要阈值] → bi-adaptive-threshold
          └─ [未发现异常] 继续
      → bi-new-dimension-analysis
          识别新增维度值并评估表现
  → Atomic bi-report-generation    （如需输出报告）生成 HTML 报告
```

**1.2 留存率分析**

```
用户问题（涉及次日/第 N 日留存、访问/使用留存、留存差异等）
  → L0 data-intent-router          判定为 BI 业务分析（2a）—— 留存子类
  → L1 analysis-plan-builder       明确留存锚点、留存指标、对比范围
  → Workflows fetch-data           取数（day0 / dayn 用户数）
  → Workflows bi-retention-analysis 编排：
      → [可选] bi-clustering           按用户特征分群
      → bi-retention-rate              计算各群/整体的留存率
      → [可选] bi-comparison-analysis  跨时间/群体/留存类型对比
  → Atomic bi-report-generation    （如需输出报告）
```

**1.3 转化率分析**

```
用户问题（涉及转化率、阶段转化、转化变化归因等）
  → L0 data-intent-router          判定为 BI 业务分析（2a）—— 转化子类
  → L1 analysis-plan-builder       明确转化口径、起止行为、对比范围
  → Workflows fetch-data           取数（分子/分母用户数或事件数）
  → Workflows bi-conversion-analysis 编排：
      → [可选] bi-clustering           按用户/产品特征分群
      → bi-conversion-rate             计算各群/整体的转化率
      → [可选] bi-anomaly-detection    对转化率序列做异常检测
      → [可选] bi-comparison-analysis  跨时间/群体/渠道对比
  → Atomic bi-report-generation    （如需输出报告）
```

**1.4 同期群（cohort）分析**

```
用户问题（按起始特征分群后跟踪后续表现）
  → L0 data-intent-router          判定为 BI 业务分析（2a）—— cohort 子类
  → L1 analysis-plan-builder       明确起始特征、跟踪指标、观察窗口
  → Workflows fetch-data           取数（cohort 划分依据 + 后续期表现指标）
  → Workflows bi-cohort-analysis   编排：
      → bi-clustering                  按起始特征划分 cohort
      → 后续表现指标计算               按需调用 bi-retention-rate / bi-conversion-rate / bi-metric-observation 等
      → bi-comparison-analysis         跨 cohort 对比
  → Atomic bi-report-generation    （如需输出报告）
```

#### 2. 数据探索链路（任务类型 = 2b）

```
用户问题
  → L0 data-intent-router          判定为数据探索（2b）
  → L1 analysis-plan-builder       数据探查 + 生成子任务序列
  → Workflows fetch-data           按子任务序列按需取数
  → 按子任务序列调用 Atomic：
      bi-distribution-analysis（分布、缺失、异常值）、
      bi-event-analysis（事件计数与聚合）、
      bi-clustering（密度型子结构发现）等
  → 无固定 Workflows 编排，由 agent 按计划串接
```

#### 3. 统计建模链路（任务类型 = 2c）

```
用户问题（聚类、画像、假设检验等）
  → L0 data-intent-router          判定为统计建模（2c）
  → L1 analysis-plan-builder       明确建模目标、特征、评估口径
  → Workflows fetch-data           取建模所需样本数据
  → 按目标调用 Atomic：
      bi-clustering（聚类/象限/分层）、
      bi-comparison-analysis（显著性/差异检验）等
  → Atomic bi-report-generation    （如需输出报告）
```

#### 4. 定量计算链路（任务类型 = 2d）

```
用户问题（已知公式的指标计算，如 LTV、漏斗、转化、留存、分布等）
  → L0 data-intent-router          判定为定量计算（2d）
  → Workflows fetch-data           取计算所需数据
  → 直接调用对应 Atomic：
      bi-ltv-analysis、bi-funnel-analysis、bi-conversion-rate、
      bi-retention-rate、bi-event-analysis、bi-distribution-analysis 之一或多个
  → 返回计算结果（一般无需走 L1 规划）
```

#### 5. 报告生成链路（任务类型 = 2e）

```
上下文中已有分析结论
  → L0 data-intent-router          判定为报告生成（2e）
  → Atomic bi-report-generation    将既有结论组织为可视化 HTML 报告
```

#### 6. 数据查询链路（任务类型 = 1a / 1b）

```
用户问题
  → L0 data-intent-router          判定为元数据查询（1a）或数据查询（1b）
  → Workflows fetch-data           直接取数或读元数据返回，不经过规划和分析流程
```

---

## 强制约束

### 必须做

- 每个步骤必须查阅对应 SKILL.md，按其定义的步骤顺序执行
- 产物必须落盘，遵循 `runtime-guide` 定义的目录和命名规范；取数产物遵循 `fetch-data` 定义的存储路径
- 同一份数据只获取一次，不重复计算
- 异常如实记录，不隐藏、不替代、不编造
- 语义层可用时，按 `bi-semantic-layer-guide` 优先查询指标定义与维度信息，再进入业务计算

### 禁止做

- 禁止跳过 SKILL 定义的步骤（如跳过异常检测直接归因、跳过取数直接编结果）
- 禁止忽略脚本（脚本可用时不得自行实现替代）
- 禁止编造数据（所有数字必须来自数据文件）
- 禁止自行发明分析方法（SKILL 未定义的方法不得使用）
