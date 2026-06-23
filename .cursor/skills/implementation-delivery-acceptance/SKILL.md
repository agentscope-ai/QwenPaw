---
name: implementation-delivery-acceptance
description: audit the implementation delivery against the intention architecture contract, and identify any gaps or next steps if not met
disable-model-invocation: true
---

本次迭代计划的产品特性已实现，请展开验收，判断当前实现是否和意图架构的设计要求一致。如果不一致，需要给出实现GAP写入handoff中，并给实现架构设计师提供下一步实现建议。

当验收范围涉及 `design/KG/SystemArchitecture.json` 的变更时，必须额外检查该变更是否通过统一 `argo` MCP mutation tools 完成，并且是否有成功的 preview/apply 与 `validateSystemArchitecture` 结果。只有最终 JSON 通过 validator 但缺少 MCP 写入证据时，应判定为治理流程缺口。