# 构建存储 Batch

把批准的可复用区域写入 `scripts/<name>.batch.json`。默认提供一个存储主入口；只有中间确实需要用户或 agent 判断来分隔独立 phases 时才拆分。好的 Batch 是小而自洽的程序；第一次看到它的 agent 也能明确理解输入、动作、输出和失败含义。

## 编译可复用区域

写 JSON 前先说明四件事：调用者输入、预先已知的动作与分支、生成的 artifacts，以及什么条件代表成功。真正开放式的用户或 agent 判断留在边界外。运行时数据和 observation 可以留在内部，只要处理它们的规则已经确定。

- 同一工具的共享状态放在一个完整 tool-native action 中；不要回放原对话中的每次 snapshot、click 或中间调用。
- 只有 substantial 的确定性解析、转换、排序、去重或 assertion 才增加聚焦 helper。
- 小值通过 step result 传递；大文本和二进制通过明确的 artifact 文件传递。
- 结尾返回紧凑结果或 assertion，让调用者能区分成功与部分运行。
- 优先直接实现；只有 workflow 确实需要时才增加 retry 或 compatibility path。

## Batch 文件与工具契约

使用非空 `actions` 数组。每个 action 包含静态 `tool_name` 和 `arguments` 对象。工具必须在 workflow 运行时可用；make-skill 不要求它在校验阶段已全局注册，因此插件、MCP 和会话工具仍然有效。make-skill 通过 `.batch.json` 后缀识别并校验文件。

```json
{
  "actions": [
    {
      "tool_name": "read_file",
      "arguments": {"file_path": "${args.source_file}"}
    },
    {
      "tool_name": "write_file",
      "arguments": {
        "file_path": "${args.output_file}",
        "content": "${steps.0.text}"
      }
    }
  ]
}
```

工具名、参数和结果字段必须基于真实工具契约或已成功的调用。不确定时查看工具说明或近期结果；未知细节直接省略，不发明 schema。

## 占位符展开

占位符是 Batch 参数值中的数据绑定，可递归出现在对象和列表内。只使用下列带大括号的形式。在 shell `command` 中，普通 shell 变量使用 `$NAME` 而不是 `${NAME}`，因为 `${...}` 保留给 Batch 占位符。

| 形式 | 值来源 | 展开时机 |
|---|---|---|
| `${args.name}` | `run_tool_batch(args=...)` 提供的调用者输入；点号路径可读取嵌套对象 | 文件加载后、任何 action 执行前统一展开 |
| `${steps.N.path}` | 更早的零基 action 结果字段；循环中读取该 action 最近一次结果 | 使用它的 action 执行前 |
| `${vars.name}` | 此前由 `set_var` 创建的标量 Batch 状态 | 使用它的 action 执行前 |

执行模型如下：

```text
actions = resolve_args(load(file_path), args or {})  # 缺少已引用参数：停止
for action in actions:
    arguments = resolve_steps_and_vars(action.arguments)
    执行控制 action 或 Toolkit.call_tool(action.tool_name, arguments)
```

每个被引用的 `${args.*}` 路径都是必填项；文件不含 `${args.*}` 时，调用者可以省略 `args`。要使用目标工具的可选参数或默认值，就省略该字段；要给 Batch 固定默认值，就直接写字面量而不是占位符。

占位符独占整个字符串值时保留展开后的 JSON 类型；嵌入更长字符串时则变成文本，其中非字符串值使用 JSON 编码。因此 shell `command`、code body 或 script source 都可以包含占位符，但 Batch 不做引用或转义。应自行编写周边语法，确保展开值具有预期含义。

展开后的 action 仍通过目标工具的正常调用路径执行，并继续接受该工具既有的 policy 检查、审批流程和 sandbox 边界约束。

## 控制流与限制

- `set_var` 通过 `arguments.expr` 创建或更新标量 `${vars.name}`，例如 `i=0` 或 `i=${vars.i}+1`。
- `label` 定义跳转目标；`goto` 无条件跳转，或在 `arguments.condition` 为真时跳转。用它们表达有界分支、循环或重试。
- action 顺序执行，Batch 不代表并行。静态 action 最多 50 个，Batch 内不得调用 `run_tool_batch`。

## 失败与生成 Skill 的契约

Batch 失败是普通且可操作的反馈。保留并报告失败 action 与工具错误；调用 agent 可以检查当前状态、修正输入或 Skill，并在适合时重跑。不得把失败包装成成功，也不要维护一套静默绕过 Batch 的逐步 fallback。

`SKILL.md` 只承诺 Batch 和 helper 实际保证的行为。若失败后留下正式产物会违背该契约，就把相关检查放在最终写入之前，或降低承诺。只为已知环境差异保留 fallback，并准确说明降级行为；不要把不等价检查描述成等价。

生成的 `SKILL.md` 应说明 Batch 承担什么、哪些部分仍由 agent 完成、任务输入、输出以及成功或失败契约。把一次完整调用放在叙述性步骤之前，使存储文件成为主入口：

```text
run_tool_batch(
  file_path="<absolute-skill-dir>/scripts/<name>.batch.json",
  args={"source_file": "...", "output_file": "..."},
  stop_on_error=true
)
```

`file_path` 使用绝对路径并调用存储文件，不要 inline 重建 actions。`args` 只包含真实 Batch 所需的值。只有最终 action 保留有用结果时才使用 `last_only=true`。测试是独立的计划选择：`batch: true` 不要求 `smoke` 或 `eval`。
