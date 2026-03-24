# CoPaw PipelineSpec v0.1

本文档定义 CoPaw 在 Markdown 大型语料处理场景下的统一抽象契约。
目标是把“四书处理流程”和 shiji-kb 一类知识工程流程映射到同一套产品模型。

## 1. 设计目标

1. 可复用：同一套模板可用于图谱构建、对齐分析、发布渲染等场景。
2. 可追溯：每一步输出都可回溯到输入、参数、规则、证据。
3. 可比较：不同 run 之间可做指标对比和产物差异对比。
4. 可演进：允许增加步骤、替换工具、扩展指标而不破坏旧数据。

## 2. 核心对象

1. Project：项目边界，管理数据集、模板、运行与产物。
2. Dataset：输入数据快照，包含来源、版本、哈希与规模统计。
3. PipelineSpec：流程模板，声明步骤 DAG、输入输出、质检和重试策略。
4. RunManifest：一次执行实例，包含状态机、参数、日志、资源消耗。
5. ArtifactManifest：步骤产物索引，描述文件、格式、角色、依赖与证据。
6. MetricPack：指标快照，支持质量门槛、分组统计和历史对比。

## 3. 标准目录约定（建议）

```text
project-root/
  PROJECT.md
  datasets/
    <dataset-id>/
      dataset_manifest.json
      raw/
      normalized/
  pipelines/
    templates/
      <pipeline-id>.json
    runs/
      <run-id>/
        run_manifest.json
        logs/
        steps/
          <step-id>/
            artifact_manifest.json
            metric_pack.json
            outputs/
  reports/
    compare/
```

## 4. PipelineSpec 模型要点

1. metadata：id/name/version/domain/owners。
2. io_contract：输入类型、输出类型、必填字段。
3. steps：每步定义执行器、依赖、输入映射、输出契约、重试策略。
4. quality_gates：每步和全局的阈值规则。
5. reflection_loop：失败回退、人工复核、自动修正策略。
6. publish_targets：页面、报告、API、导出包。

## 5. Run 状态机

建议状态：

1. pending
2. running
3. blocked
4. failed
5. succeeded
6. cancelled

步骤级状态与 run 状态分离，run 状态由步骤聚合得出。

## 6. 质量门槛（Quality Gate）

每个 gate 至少包含：

1. metric_key
2. comparator（>=、<=、in_range）
3. threshold
4. severity（warn/block）
5. remediation_hint

当存在 block 且未豁免时，run 状态进入 blocked 或 failed。

## 7. 与 /projects 页对接建议

当前三栏可升级为：

1. 左栏：Project + Dataset + Pipeline Template 导航。
2. 中栏：步骤 DAG 与最近 runs（状态、耗时、失败点）。
3. 右栏：Artifact/Metric/Evidence 预览切换。

顶部新增 Run Bar：

1. 选择模板
2. 参数编辑
3. 执行/重跑
4. 比较两次 run

## 8. 与“四书处理流程”的映射示例

books-alignment-v1 可以映射为步骤：

1. ingest
2. normalize
3. extract
4. align
5. build_concept_tree
6. build_relation_matrix
7. review_pack
8. report

每步都生成 artifact_manifest + metric_pack，右栏可直接展示。

## 9. 版本策略

1. 规范版本：spec_version（例如 0.1.0）。
2. 模板版本：pipeline.version（例如 books-alignment-v1.2.0）。
3. 运行版本：run.spec_version + run.pipeline_version 固定写入。

## 10. 兼容性规则

1. 新增字段必须向后兼容（optional + default）。
2. 删除字段前必须提供迁移脚本。
3. 解析器应忽略未知字段（forward compatible）。

## 11. 对应 schema 文件

1. schemas/pipeline-spec.schema.json
2. schemas/run-manifest.schema.json
3. schemas/artifact-manifest.schema.json
4. schemas/metric-pack.schema.json

这些 schema 是下一阶段后端 API 与前端状态管理的统一契约。
