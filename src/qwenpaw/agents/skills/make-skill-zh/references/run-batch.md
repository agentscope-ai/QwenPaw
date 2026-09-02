# 构建存储 Batch

只在选择 `batch: true` 后阅读本 reference。把批准的可复用区域写入 `scripts/<name>.batch.json`。默认提供一个存储主入口；只有中间确实需要用户或 agent 判断来分隔独立 phases 时才拆分。好的 Batch 是小而自洽的程序；第一次看到它的 agent 也能明确理解输入、动作、输出和失败含义。

## 编译可复用区域

写 JSON 前先说明四件事：调用者输入、预先已知的动作与分支、生成的 artifacts，以及什么条件代表成功。真正开放式的用户或 agent 判断留在边界外。运行时数据和 observation 可以留在内部，只要处理它们的规则已经确定。

- 同一工具的共享状态放在一个完整 tool-native action 中；不要回放原对话中的每次 snapshot、click 或中间调用。
- 只有 substantial 的确定性解析、转换、排序、去重或 assertion 才增加聚焦 helper。
- 小值通过 step result 传递；大文本和二进制通过明确的 artifact 文件传递。
- 结尾返回紧凑结果或 assertion，让调用者能区分成功与部分运行。
- 优先直接实现；只有 workflow 确实需要时才增加 retry 或 compatibility path。

## Batch 文件

使用非空 `actions` 数组。每个 action 指定已注册工具及其参数。make-skill 通过 `.batch.json` 后缀识别并校验文件。

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

## 数据与控制流

shell `command`、code body、script source 等自由可执行字段必须保持静态，其中不得出现任何 `${args.*}`、`${steps.*}` 或 `${vars.*}` binding。其他动态值优先独占一个有文档契约的数据参数；若所在文本随后会被另一层 parser 当作结构解析，也只有在工具明确负责所需编码时才能插入。request/config 文件必须由工具结构化写入，或让动态值作为完整数据传递；手工拼接序列化文本仍然是模板。没有紧凑的数据边界时，把参数准备或该阶段留给 agent。

- `${args.name}` 提供运行输入；调用时必须传入所有被引用的参数。
- `${steps.N.path}` 读取更早的零基 action 字段；循环中读取该 action 最近一次执行的结果。
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

`file_path` 使用绝对路径并调用存储文件，不要 inline 重建 actions。`args` 只包含真实 Batch 所需的值，并在调用中提供每个被引用的 `${args.*}`。只有最终 action 保留有用结果时才使用 `last_only=true`。测试是独立的计划选择：`batch: true` 不要求 `smoke` 或 `eval`。
