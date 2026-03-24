# CoPaw Projects Workbench 路线图（基于四书流程 + shiji-kb 抽象）

## 目标

将 /projects 从“项目文件浏览页”升级为“知识工程生产工作台”。

## 迭代计划

## Phase 1：契约与可视化骨架（当前阶段）

1. 固化 PipelineSpec/Run/Artifact/Metric 契约（已完成文档与 schema）。
2. 在 /projects 中栏增加 Pipeline Steps 面板（先展示 mock run 数据）。
3. 在 /projects 右栏增加三标签：Artifact、Metric、Evidence（先本地状态）。
4. 顶栏新增 Run Bar（模板选择 + 参数入口 + 运行按钮）。

验收：

1. 可切换模板。
2. 可查看步骤状态。
3. 可查看 mock 指标与产物预览。

## Phase 2：后端运行模型与最小执行器

1. 新增 API：
- GET /agents/{agentId}/projects/{projectId}/pipelines/templates
- GET /agents/{agentId}/projects/{projectId}/pipelines/runs
- POST /agents/{agentId}/projects/{projectId}/pipelines/runs
- GET /agents/{agentId}/projects/{projectId}/pipelines/runs/{runId}

2. 最小执行器：串行执行 + step checkpoint + run manifest 写盘。
3. 每步输出 artifact_manifest.json 和 metric_pack.json。

验收：

1. 可在 UI 发起 run。
2. 可查看 run 实时状态。
3. run 结束后可重开查看历史。

## Phase 3：四书模板产品化（books-alignment-v1）

步骤建议：

1. ingest
2. normalize
3. extract
4. align
5. build_concept_tree
6. build_relation_matrix
7. review_pack
8. report

每步明确：输入、输出、质量门槛、失败修复建议。

验收：

1. 一键运行四书模板。
2. 出具标准报告。
3. 支持 run 对比。

## Phase 4：shiji-kb 场景映射（classics-kg-v1）

映射能力：

1. 结构分析（section/anchor）。
2. 实体索引与别名消歧。
3. 事件与关系抽取。
4. 本体与 SKU 组装。
5. 发布层（索引页/阅读器/报告）。

验收：

1. 同一工作台可运行 books 与 classics-kg 两类模板。
2. 产物契约一致。
3. 指标可跨模板对比。

## 横切能力（所有阶段共通）

1. Evidence Trace：每个结论可回溯。
2. Quality Gate：每步可阻断/预警。
3. Reflection Loop：失败步骤支持复盘重跑。
4. Compare：支持 run-to-run 指标与产物 diff。

## /projects UI 信息架构（最终态）

1. 左栏（导航）：Project / Dataset / Pipeline Template / Run History。
2. 中栏（执行）：步骤 DAG + 状态 + 耗时 + 重试操作。
3. 右栏（结果）：Artifact 预览 / Metric 面板 / Evidence 链接。

## 开发优先级

1. 先做契约（schema）再做 UI。
2. 先做串行执行再做并行调度。
3. 先做可追溯再做高级智能。
