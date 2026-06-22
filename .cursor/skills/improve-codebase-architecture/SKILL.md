---
name: improve-codebase-architecture
description: 在不引入功能需求的前提下，先为意图设计阶段梳理代码库中的架构优化候选，再把选中的方向交给现有 grill-me 流程继续深挖。
disable-model-invocation: true
---

# Improve Codebase Architecture

把这个 SKILL 当作 Intent Design 阶段的前置探索步骤，而不是新的主流程或新的真相来源。

目标是先识别真正值得深挖的 architecture improvement candidates，把 shallow module、泄漏的 seam、不必要的间接层、测试面失焦的问题显性化，再把选中的方向交给现有 grill-me 流程逐步收敛。

## 何时使用

只在以下场景使用：
- 目标是架构优化、重构机会梳理、模块深挖、接缝修复、可测试性提升、AI 可导航性提升
- 当前迭代明确“不做功能修改”或至少不以功能新增为主目标

## 参考文件

详细术语、判别原则、流程和 Argo 适配规则，分别见：

- `LANGUAGE.md` - 统一术语和判别原则
- `DEEPENING.md` - deepening 策略、依赖分类和测试迁移原则
- `PROCESS.md` - 实际执行步骤、候选输出结构和后续交接方式
- `REPOSITORY-MAPPING.md` - 参考 skill 概念如何映射到 Argo 当前 ontology 与 workflow

## 核心约束

- 保持在当前仓库的 truth sources 内工作
- 除非用户明确要求进入实现，否则不要修改代码、测试、脚本或设计资产
- 如果最终判断只是 Implementation Design 或 Coding/Repair 问题，要明确说明“不需要改 intent”
- 用户选中候选后，交回现有 `grill-me` 流程继续按设计树逐支路确认
- 如果用户最终批准修改 intent graph，不能直接编辑 `design/KG/SystemArchitecture.json`；必须将候选转成 Intent Design mutation request，并由统一 `argo` MCP mutation tools preview/apply。
