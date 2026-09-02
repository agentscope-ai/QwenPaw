---
name: make-skill
description: "将当前对话中可复用的决策、知识、模板或工作流创建为聚焦的 workspace Skill。适用于带 focus 参数的 /make-skill，以及“保存这个流程”“把它做成 skill”等请求；不适用于一次性总结或普通文件创建。"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

# 创建 Skill

从当前原始对话创建一个新的 workspace Skill。按以下生命周期使用本目录脚本，不依赖 make-skill 专属的 core tool、mode 或状态存储。

## 计划

`/make-skill <focus>` 的 focus 必填；自然语言请求则结合请求和当前对话推断。用户较晚的纠正会替换冲突的旧规则。保留会改变未来 agent 行为的稳定指导、契约、模板和流程，排除一次性数据、临时路径、密钥与重试噪声。

阅读[主类型与包结构](references/type-and-package.md)，选择一个主类型和实际需要的文件。计划的测试模式不是 `off` 时，在定义测试目标前阅读[行为测试](references/behavior-testing.md)。

### Batch workflow

存储 Batch 是随 workflow Skill 一起提供的参数化 `run_tool_batch` 程序。应根据未来实现判断，而不是照搬当前 transcript。只要下一步动作、分支和成功条件能在执行前说明，并且统一入口能实质减少 agent 与工具往返，就设置 `batch: true`。运行时 observation、数据依赖、perception 和最终 agent review 本身都不排除 Batch。

Batch 可以覆盖全部流程，也可以只覆盖一个可编译区域。一个 substantial helper 或一个语义完整的 tool-native action 也可能值得保存；顶层 action 数量不是判据。只有运行时必须重新发明下一步或成功条件，或者统一入口没有实际复用价值时，才设置 `batch: false`。用户明确要求 Batch 时，把它视为已批准的计划修订，直接修改计划，不再争论 eligibility。

选择 `batch: true` 后，在最终确定 workflow 和文件树前阅读[运行 Batch](references/run-batch.md)。实现保持小而清楚：依照真实工具契约，明确暴露失败；运行失败时让未来 agent 据此调整，不预建推测性的 fallback 层。

计划阶段除运行 `scripts/create_plan.py` 外只读：依据对话证据和已有产物判断，不执行或探测候选工作流，不创建文件，也不初始化 draft。通过 stdin 传入候选计划：

```json
{
  "revision": 1,
  "focus": "一句话说明提炼范围",
  "name": "lowercase-hyphen-name",
  "goal": "未来 agent 要达成的结果",
  "type": "workflow",
  "batch": true,
  "steps": ["用户可判断的流程步骤"],
  "package": ["SKILL.md", "scripts/run.batch.json"],
  "execution": "foreground",
  "test": {"mode": "off", "target": ""},
  "warnings": []
}
```

用中文渲染规范化计划，并把已选值和全部可选项一起展示，让用户无需了解 schema 也能修改。用户可见计划必须包含下列紧凑选项表，不得用散文或批准提示代替；非 workflow 省略 `Batch` 行：

| 选项 | 当前值 | 全部可选 |
|---|---|---|
| 类型 | 当前中文值 | 指令 / 模板 / 工作流 |
| Batch（仅 workflow） | 启用或关闭 | 启用 / 关闭 |
| 执行方式 | 前台或后台 | 前台 / 后台 |
| 行为测试 | 当前中文值 | 关闭 / 冒烟测试 / 完整评测 |

传给脚本的值仍分别使用 `instruction/template/workflow`、`true/false`、`foreground/background` 和 `off/smoke/eval`。同时展示名称、目标、工作流、完整文件树、适用时的测试目标和警告。不得发明脚本 schema 之外的选项；不展示 Batch 关闭理由、schema、revision 或内部 enum。请用户批准、修改或取消，然后结束当前响应，不再调用工具。只有后续新的用户消息明确批准已展示的 revision，才继续执行。

- 用户修改后合并最新反馈、增加 `revision`、重跑 `create_plan.py` 并展示完整返回结果。
- 取消时停止；模糊回复只追问一次简短确认。
- execution 和 test 已在计划中，不再单独询问。

本版本只创建新 Skill；名称冲突时通过新 revision 重新批准名称，不覆盖已有 Skill。

## 构建

批准后通过 stdin 调用 `scripts/init_draft.py`：

```json
{"workspace": "/workspace/path", "plan": {"...": "完整规范化计划"}}
```

只在返回的 `skill_dir` 中创建批准文件。生成的 `SKILL.md` 使用合法 frontmatter：

```yaml
---
name: lowercase-hyphen-name
description: 简要说明能力及适用场景。
---
```

正文只保留必要流程和约束，不重复 description；无需 type metadata。

校验前，从“未来 agent 看不到原始对话”的视角通读 package。除非资源确实随包提供且可复用，否则删除对原任务目录、旧输出、临时 ID、当前 case 示例或 make-skill draft/publish 话术的引用。复用已有 helper 时，要泛化路径、docstring 和结果说明，并确认实现仍符合最终可复用规则。这只是一轮作者自查，不增加 case-specific lifecycle 检查。

选择后台执行时，把完整批准计划、最新纠正、draft 路径和剩余 gates 交给通用 subagent；subagent 不再请求批准。

## 校验、测试并发布

执行任何 draft script 或 batch 前，先通过 stdin 调用 `scripts/validate_skill.py`：

```json
{"workspace": "/workspace/path", "draft_id": "returned-draft-id"}
```

按静态或安全错误修复 draft 并重新校验。测试与 Batch 相互独立：按[行为测试](references/behavior-testing.md)只运行已批准的测试，`off` 不执行 draft。测试或 Batch 运行失败时保留 draft，报告具体错误；如果修正方向明确，就修改 Skill 后重新校验，不用 fallback 隐藏失败。

通过 stdin 调用 `scripts/publish_skill.py`，发布未经改动且已校验的 draft：

```json
{"workspace": "/workspace/path", "draft_id": "returned-draft-id", "expected_digest": "digest-from-validation"}
```

成功后报告 package tree、校验摘要、已执行的测试结果和调用命令 `/<name>`；冲突或失败时保留 draft 并报告错误。发布 Skill 已经完成持久化；除非用户另行明确要求，不再写入 `MEMORY.md` 或 daily memory。
