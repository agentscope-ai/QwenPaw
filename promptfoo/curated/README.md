# 手工固定用例

`curated/` 用来存放人工编写、人工改进、必须长期保留的高质量测试用例。

约定：

- `generated/` 是自动生成产物，可以被 `redteam generate --force` 覆盖。
- `curated/` 是人工维护资产，不由 promptfoo 自动生成覆盖。
- 从 `generated/*.generated.yaml` 中发现优质用例后，应复制到 `curated/must-have.yaml`，再人工改写、分类、补充说明。
- 执行固定用例使用 `configs/curated.yaml`，走普通 `promptfoo eval`，不需要再次生成。

新增固定用例时，建议至少包含：

- `description`：说明测试目的。
- `vars.category`：用例分类，例如 `shell`、`secret`、`mcp`、`benign`。
- `vars.prompt`：实际发送给 QwenPaw 的输入。

