---
name: distill-agent-rules
description: 在会话过程中，当 coding agent 的行为偏离预期时，提炼可复用的原则、约束、触发条件和落地位置。Use when user wants to retro agent behavior drift, distill rules, extract constraints, or turn a bad session into reusable guidance.
disable-model-invocation: true
---

# Distill Agent Rules

把这个 SKILL 当作一次会话偏航后的治理工作流，而不是情绪化复盘。

目标不是重复抱怨“哪里不对”，而是把偏差稳定转写成：

- 可判定的原则
- 可执行的约束
- 合适的承载位置
- 最小必要的指令改动

## 何时使用

只在以下场景使用：

- 用户明确表示 agent 的行为偏离预期
- 用户希望把这次不满意提炼成长期规则、约束、守卫或 workflow
- 用户希望判断该把规则放进 memory、instructions、skill、prompt、agent 还是 hook
- 用户希望减少同类偏差在后续会话中重复发生

以下情况不要硬套本 SKILL：

- 只是一次性的任务偏好，不值得沉淀为长期规则
- 实际问题是模型能力、工具缺失或仓库事实不明，而不是缺少指令
- 需要的是立即修当前代码问题，而不是先治理 agent 行为

## 核心工作方式

1. 先把“期望行为”和“实际行为”拆开，不要混写
2. 只提炼可证伪、可执行的规则，不写空泛价值观
3. 优先选择最小作用域的承载位置，不要把局部偏好升级成全局宪法
4. 先检查当前仓库和现有 instructions/skills 中是否已经有相同规则，避免重复和冲突
5. 如果问题本质上需要 deterministic enforcement，明确指出应使用 hook，而不是继续堆自然语言指令
6. 如果问题只对某类任务成立，优先做 skill、prompt 或 file instructions，而不是污染全局 instructions

## 必须产出

执行本 SKILL 时，至少给出以下结果：

- 1 到 3 条经过提炼的规则
- 每条规则的适用范围和触发条件
- 推荐的落地位置及理由
- 一段可以直接写入目标文件的候选文本
- 一段简短说明，解释为什么这不是过拟合或重复约束

## 核心约束

- 不要把一次偶发不满直接升级为跨仓库永久规则
- 不要把仓库事实、当前任务约束和用户长期偏好混为一谈
- 不要用模糊措辞代替可观察行为，例如“更聪明一点”“更主动一点”
- 不要建议同时修改多个承载层，除非确有分层必要
- 如果现有 instructions 已覆盖问题，应优先建议收紧触发语句或补充例子，而不是新建平行机制
- 如果最终结论是“这不是 skill 问题，而是应该改 instructions 或 hook”，必须明确说出

## 执行流程

按下面顺序执行，不要跳步。

### 1. 固定事故边界

先把本次偏航写成一个最小事故记录：

- 用户原本想要什么
- agent 实际做了什么
- 哪一部分偏离了预期
- 证据是什么

如果能从当前会话、仓库文件或工具结果中直接确认，就不要再问用户。

输出模板：

```md
Incident:
- Expected:
- Actual:
- Drift:
- Evidence:
```

### 2. 从抱怨改写成规则

把“我不喜欢这样”改写成“当出现 X 条件时，应执行 Y，而不是 Z”。

优先提炼以下类型：

- 探索顺序
- 编辑前证据门槛
- 编辑后的验证顺序
- 输出结构
- 作用域控制
- 何时停下来提问
- 何时使用哪种 customization primitive

坏例子：

- 更贴近用户意图
- 不要跑偏

好例子：

- 当任务已有具体文件或符号锚点时，先围绕该锚点形成一个可证伪假设，再编辑，不要先广泛扫仓
- 首次实质修改后，下一步必须先做一个聚焦验证，而不是继续扩面搜索或连续补丁

### 3. 做作用域分类

对每条规则判断它属于哪一类：

- 用户长期偏好
- 当前仓库共享约束
- 某类任务 workflow
- 某个文件域或目录域约束
- deterministic enforcement 需求
- 单次任务提醒

如果一条规则无法清晰归类，说明它还不够具体。

### 4. 选择承载位置

默认选择最小足够层级。每条规则都要回答：

- 为什么放这里
- 为什么不放到更高层
- 为什么不放到更低层

放置原则：

- 跨仓库、跨任务、长期稳定的个人偏好：放到 user memory 或用户级 instructions
- 当前仓库大多数任务都应遵守的共享约束：放到 `.cursor/rules/`
- 只在一类多步任务中才需要的工作流：做成 skill（`.cursor/skills/`）
- 只对某些文件、目录或语言域生效的约束：做成 file instructions
- 需要确定性拦截、批准或自动执行的规则：做成 hook
- 需要上下文隔离或不同工具权限的流程：做成 custom agent
- 只在当前一次任务中成立的提醒：留在当前会话，不要沉淀

快速判别问题：

1. 这是长期稳定偏好吗，还是这次任务的情境需求？
2. 它适用于这个仓库的大多数任务吗？
3. 它只在某类工作流里才成立吗？
4. 它是否需要 deterministic enforcement？
5. 如果把它提升到更高层，会不会误伤正常任务？

只要第 5 个问题回答为“会”，就不要上提层级。

常见映射：

- “不要在这个仓库里绕过 architecture reading order” -> 仓库级 instructions
- “做架构候选梳理时，先找 candidate 再进入 grill-me” -> skill
- “修改 tests 目录前必须先确认 control point 和 observation point” -> 仓库级 instructions 或相关 skill
- “提交前必须运行 formatter” -> hook
- “Python 文件默认遵循某种导入顺序” -> file instructions
- “这次回答请先列 findings 再总结” -> 如果是长期 review 规范，写入 instructions；如果只针对当前任务，不沉淀

### 5. 做去重和冲突检查

检查以下风险：

- 与现有 instructions 或 skills 重复
- 与现有规则冲突
- 描述太宽，容易误伤正常场景
- 描述太窄，只对当前一次事故成立

如果发现冲突，先提出收敛方案，再给补丁建议。

### 6. 产出最小落地建议

最终输出应使用以下结构：

```md
Distilled Rules:
1. ...

Placement:
- Recommended target:
- Why here:
- Why not elsewhere:

Candidate Text:
<可直接写入目标文件的文本>

Risk Check:
- Not duplicated because:
- Not overfit because:
```

如果用户明确要求你直接落文件，再据此修改对应的 instructions、skill、prompt、agent 或 hook。
