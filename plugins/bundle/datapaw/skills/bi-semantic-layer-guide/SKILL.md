---
name: bi-semantic-layer-guide
description: 语义层工具使用规范。在发现语义层工具可用、需要查询指标定义/维度信息、验证业务口径、处理指标歧义时，必须优先调用此技能。无语义层工具时不调用。
---
# bi-semantic-layer-guide

## 概述

语义层是统一管理业务语义元数据的服务，包括指标定义、维度定义、指标维度绑定和数据集映射。

---

## 可用工具

语义层暴露三类工具：

- **全局**：`list_domains()`
- **指标查询**：`list_metrics(domain)`、`search_metrics(query, domain)`、`get_metric_info(metric_name, domain)`、`get_north_star_metrics(domain)`
- **维度查询**：`list_dimensions(domain)`、`get_dimension_info(dim_name, domain)`、`get_dimensions_for_metric(metric_name, domain)`、`get_dimension_hierarchy(dim_name, domain)`、`get_dimension_values(dim_name, domain)`
- **数据集查询**：`list_datasets(domain)`、`get_dataset_columns(name, domain)`、`get_dataset_schema(name, domain)`

具体参数和返回格式参见工具自身描述。

---

## 查询策略

### 指标匹配

在语义层中查找指标，可选策略：

- 语义检索（`search_metrics`），语义层会自动匹配同义词
- 查看具体业务域的北极星指标列表（`get_north_star_metrics`），从中选择最相关的
- 若以上均未命中，列出该域全部指标（`list_metrics`），逐一判断和分析条目的相关性。

### 指标属性确认

通过 `get_metric_info` 获取指标属性，重点属性：

- **是否是北极星指标**（`is_north_star`）：用于角色分配
- **是否展示指标**（`is_display`）：该指标是否应出现在展示面板中
- **是否展示分布**（`is_display_distribution`）：展示指标时是否同时展示分布图
- **维度绑定**（`dimensions`）：指标可拆解的维度列表，含 `is_display_dimension`、`is_contribution_dimension` 标记。

### 维度信息获取

通过 `get_dimensions_for_metric` 获取指标可拆解的维度列表（`is_contribution_dimension=true` 的维度才可用于贡献度拆解），通过 `get_dimension_hierarchy` 获取维度间的父子层级关系。

---

## 消歧规则

搜索指标时可能遇到歧义，按以下规则处理：

- **匹配到多个指标**：优先选北极星指标（`is_north_star=true`）。若仍有多个候选，结合指标类型和标签综合判断，必要时向用户确认。
- **精确名称 vs 同义词**：若同时出现精确名称匹配和同义词匹配，精确名称优先。例如搜索"DAU"，若同时命中指标名为"DAU"的指标和同义词含"DAU"的"访问用户数"，取前者。
- **同名指标跨业务域**：若同一指标名出现在多个业务域中，用当前分析任务的业务域限定范围。
