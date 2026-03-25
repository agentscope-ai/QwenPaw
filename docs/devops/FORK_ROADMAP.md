# Fork 扩展路线图

> 本文档用于记录 fork 侧的明确特性路线，主路线图继续跟随 upstream。

## 协同原则（upstream 与 fork）

- upstream 的「多模态记忆融合增强」当前为计划中，和我们的知识沉淀方向存在部分重合。
- 当前重合范围暂定在“沉淀”层，其他 fork 能力继续独立推进。
- 若 upstream 后续推出可用的沉淀能力，按以下原则决策：
  - 优先评估是否迁移到 upstream 方案。
  - 若迁移成本高或能力不满足 fork 目标，可继续保留 fork 实现。
  - 发生功能冲突时，按“可迁移优先迁移；不可迁移则保留 fork 实现”的原则处理。

## 路线图一览

| 方向 | 事项 | 状态 |
| --- | --- | --- |
| **技能市场** | Skills Marketplace（Git-backed 聚合、Console 市场管理、覆盖前确认） | 已完成 |
|  | 子项：已集成 [futuremeng/editor-skills](https://github.com/futuremeng/editor-skills) | 已完成 |
| **知识库** | 知识沉淀能力（本地持续演进） | 进行中 |
| **知识库增强** | 引入 cognee 作为知识库增强项 | 进行中 |
| **MCP 方向** | 内置 jiulu_mcp | 计划中 |
| | 内置 mineru_mcp | 计划中 |

_状态说明：**已完成** — 已交付并可用；**进行中** — 正在推进；**计划中** — 已进入待排期/设计阶段。_

## 备注

- 本路线图仅描述 fork 自有能力，不替代 upstream 主路线图。
- 与 upstream 重合能力的演进与取舍，统一按本文“协同原则”执行。
