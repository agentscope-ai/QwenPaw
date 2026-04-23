---
name: agent_audit
description: "面向 agent 运行时、包装层、记忆层、工具路由和交付链路的证据优先审计流程。当 agent 比基础模型更不可靠、跳过工具、复用陈旧记忆或在重试/渲染中改坏答案时使用。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🩺"
    requires: {}
---

# Agent Audit

审计 agent 系统本身，而不是完成用户的业务任务。

当助手、包装层、通道适配器、浏览器 agent 或长期运行的 runtime 出现以下问题时使用：

- 表现比底层模型更差
- 跳过本该使用的工具
- 复用陈旧会话或记忆证据
- 在重试、格式化或传输过程中把正确答案改坏
- 隐藏了修复、重试、摘要或回顾层
- 在没有当前证据的情况下自信回答运行状态

## 核心规则

证据优先，JSON 优先。

不要直接写自由文本结论。先构造结构化产物，再从结构化产物渲染给用户看的诊断。

必须按顺序构造：

1. `agent_check_scope.json`
2. `evidence_pack.json`
3. `failure_map.json`
4. `agent_check_report.json`

## 审计对象

审计完整 agent 栈：

1. system prompt 与角色塑形
2. 会话历史注入
3. 长期记忆检索
4. 摘要或蒸馏
5. 主动回忆或 recap 层
6. 工具路由与选择
7. 工具执行
8. 工具输出解释
9. 最终答案塑形
10. 平台渲染或传输
11. fallback 或 repair loop
12. 持久化与陈旧状态

## 工作方式

- 优先使用直接证据：代码、配置、日志、payload、数据库行、截图和测试。
- 如果故障发生在历史窗口，不要只看当前干净状态。
- 优先给代码和配置级修复，不要只给 prompt 补丁。
- 明确置信度和反证。
- 除非已经排除包装层问题，否则不要直接责怪基础模型。

## 参考资料

审计前或审计中阅读：

- `references/report-schema.json`
- `references/rubric.md`
- `references/playbooks.md`
- `references/advanced-playbooks.md`
- `references/example-report.json`
- `references/trigger-prompts.md`

## 标准流程

1. 创建 `agent_check_scope.json`。
2. 收集直接证据到 `evidence_pack.json`。
3. 在 `failure_map.json` 中映射失败模式。
4. 从结构化产物生成 `agent_check_report.json`。
5. 先输出按严重程度排序的 findings，再给架构诊断，最后给修复顺序。

## 输出规则

- 先给 findings，不要先夸。
- 不要隐藏不确定性。
- 生成报告后，不要再临场编一个新理论。
- 如果主要问题是包装层设计，请直接说。
- 如果用户要求 JSON，提供 `agent_check_report.json`。
