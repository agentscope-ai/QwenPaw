---
name: make-skill
description: "将当前对话中可复用的决策、知识、模板或工作流创建为聚焦的 workspace Skill。适用于带 focus 参数的 /make-skill，以及“保存这个流程”“把它做成 skill”等请求；不适用于一次性总结或普通文件创建。"
metadata:
  builtin_skill_version: "2.1"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

# 创建 Skill

从当前对话创建一个新的 workspace Skill，依次完成规划、用户批准、草稿编写、校验和发布。

从运行时目录上下文获取 `<workspace>`：使用当前 agent workspace 的绝对路径（未单独配置项目时，也是工作目录）。整个生命周期传入同一个值，与任务的 project directory 和脚本 `cwd` 分开确定。生命周期产物归属 `<workspace>/.qwenpaw/make-skill/`，发布后的 Skill 归属 `<workspace>/skills/`。

## 脚本接口

通过 `execute_shell_command` 运行 `python scripts/<script>`，将 `cwd` 设为 available-skills 条目中本 Skill 的 `<dir>`。每个脚本从 stdin（或 `--input <file>`）读取一个 JSON 对象，返回一个 JSON 对象。每次输入均包含 `workspace`；下表列出其余顶层字段。

| 操作 | 脚本 | 其余输入字段 | 成功返回 |
|---|---|---|---|
| 创建计划 | `create_plan.py` | `plan` | `plan_id`、规范化 `plan` |
| 修改该计划 | `create_plan.py` | `plan_id`、完整新 `plan` | 同一个 `plan_id`、规范化 `plan` |
| 批准后初始化 | `init_draft.py` | `plan_id` | `draft_id`、`skill_dir` |
| 校验草稿 | `validate_skill.py` | `draft_id` | `digest` |
| 发布已校验草稿 | `publish_skill.py` | `draft_id`、来自校验结果的 `expected_digest` | 发布结果 |

`plan_id` 标识一份可修改的计划，修订和改名时均沿用。`draft_id` 标识初始化后的草稿，用于校验、测试和发布；`skill_dir` 是其 package 文件的编写位置。原样使用返回值，不根据名称或路径推算 ID。

## 计划

`/make-skill <focus>` 的 focus 必填；自然语言请求则结合请求和当前对话推断。用户较晚的纠正会替换冲突的旧规则。保留会改变未来 agent 行为的稳定指导、契约、模板和流程，排除一次性数据、临时路径、密钥与重试噪声。

阅读[主类型与包结构](references/type-and-package.md)，选择一个主类型和实际需要的文件。计划的测试模式不是 `off` 时，在定义测试目标前阅读[行为测试](references/behavior-testing.md)。

### Batch workflow

存储 Batch 是随 workflow Skill 一起提供的参数化 `run_tool_batch` 程序。当一个可复用区域的动作、分支和成功条件能在执行前说明，并且存储入口能实质减少 agent 与工具往返时，设置 `batch: true`。该区域可以是完整 workflow、一个 substantial helper，或一个语义完整的 tool-native action；action 数量不是判据。只要处理规则已经确定，运行时数据、observation 和最终 agent review 都不妨碍使用 Batch。

只有运行时必须重新发明下一步或成功条件，或者统一入口没有实际复用价值时，才设置 `batch: false`。用户明确要求 Batch 时，将该选择纳入计划，不再争论 eligibility。

只有选择 `batch: true` 后，才在最终确定 workflow 和文件树前阅读[运行 Batch](references/run-batch.md)；`batch: false` 时不要读取。

### 保存并展示计划

计划阶段除通过 `create_plan.py` 保存计划外只读：依据对话证据和已有产物判断，不执行或探测候选工作流，不创建 package 文件，也不初始化 draft。首次创建不传 `plan_id`，传入完整候选计划：

```json
{
  "workspace": "<workspace>",
  "plan": {
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
}
```

修订时，在上述输入的顶层加入返回的 `plan_id`，并将 `plan` 替换为完整修订计划，而非局部 patch。这会更新原计划，不创建副本。更新返回 `missing-plan` 时，返回规划和批准流程，不继续构建。计划已保存不代表用户已批准。

用中文渲染规范化计划，并把已选值和全部可选项一起展示，让用户无需了解 schema 也能修改。用户可见计划必须包含下列紧凑选项表，不得用散文或批准提示代替；非 workflow 省略 `Batch` 行：

| 选项 | 当前值 | 全部可选 |
|---|---|---|
| 类型 | 当前中文值 | 指令 / 模板 / 工作流 |
| Batch（仅 workflow） | 启用或关闭 | 启用 / 关闭 |
| 执行方式 | 前台或后台 | 前台 / 后台 |
| 行为测试 | 当前中文值 | 关闭 / 冒烟测试 / 完整评测 |

传给脚本的值仍分别使用 `instruction/template/workflow`、`true/false`、`foreground/background` 和 `off/smoke/eval`。同时展示名称、目标、工作流、完整文件树、适用时的测试目标和警告。不得发明脚本 schema 之外的选项；不展示 Batch 关闭理由、schema、revision 或内部 enum。请用户批准、修改或取消，然后结束当前响应，不再调用工具。

只有后续新的用户消息明确批准最近一次已展示的 `create_plan.py` 返回计划，才可进入构建。`/make-skill` 发起的是规划；此前的任务讨论或手写方案不能替代这次计划展示与批准。

- 用户修改后合并反馈、增加 `revision`，更新同一份计划。在当前会话中串行修订，然后展示完整返回计划，等待批准；旧批准不适用于修改后的计划。
- 取消时停止，保留计划，不创建 draft。区分知悉与批准；用户意图不明确时，只追问一次简短确认并等待回复。
- execution 和 test 已在计划中，不再单独询问。

本版本只创建新 Skill；名称冲突时通过新 revision 重新批准名称，不覆盖已有 Skill。

## 构建

批准后，将已保存的 `plan_id` 传给 `init_draft.py`。初始化会将当前计划快照保存到新 draft；后续修改 plan 不会更新该 draft。不接受内联替代计划。计划缺失或无效时返回规划阶段，不继续构建。

`execution` 决定由当前 agent 还是后台 subagent 完成 Skill 创建。选择 `background` 时，初始化后调用 `spawn_subagent` 并设置 `background: true`，将完整批准计划、最新纠正、`workspace`、`draft_id` 和 `skill_dir` 交给通用 subagent，由其编写文件、校验、执行已批准的行为测试并发布，不再请求批准。完成后报告创建结果；除已批准的行为测试外，运行生成的 Skill 需用户另行要求。

只在返回的 `skill_dir` 中创建批准文件。生成的 `SKILL.md` 使用合法 frontmatter：

```yaml
---
name: lowercase-hyphen-name
description: 简要说明能力及适用场景。
---
```

正文只保留必要流程和约束，不重复 description；无需 type metadata。

校验前，从“未来 agent 看不到原始对话”的视角通读 package。除非资源确实随包提供且可复用，否则删除对原任务目录、旧输出、临时 ID、当前 case 示例或 make-skill draft/publish 话术的引用。复用已有 helper 时，要泛化路径、docstring 和结果说明，并确认实现仍符合最终可复用规则。这只是一轮作者自查，不增加 case-specific lifecycle 检查。

## 校验、测试并发布

执行任何 draft script 或 batch 前，先对初始化后的草稿运行 `validate_skill.py`。

按静态或安全错误修复 draft 并重新校验。测试与 Batch 相互独立：按[行为测试](references/behavior-testing.md)只运行已批准的测试，`off` 不执行 draft。测试或 Batch 运行失败时保留 draft，报告具体错误；如果修正方向明确，就修改 Skill 后重新校验，不用 fallback 隐藏失败。

通过 `publish_skill.py` 发布未经改动且已校验的 draft，将校验结果中的 `digest` 作为 `expected_digest` 传入。

成功后报告 package tree、校验摘要、已执行的测试结果和调用命令 `/<name>`；冲突或失败时保留 draft 并报告错误。发布 Skill 已经完成持久化；除非用户另行明确要求，不再写入 `MEMORY.md` 或 daily memory。
