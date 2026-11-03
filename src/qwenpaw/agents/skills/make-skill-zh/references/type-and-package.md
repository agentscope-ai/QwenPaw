# 主类型与包结构

先判断 Skill 主要提供什么。支撑文件不会产生额外类型。

| 类型 | 核心价值 | 常见形态 |
|---|---|---|
| `instruction` | 规则、知识、checklist 或判断方法 | `SKILL.md`，按需加入聚焦的 `references/` |
| `template` | 仍需 agent 判断的可复用输出骨架 | `SKILL.md` + `templates/` 或 `assets/` |
| `workflow` | 由有序动作或阶段组成的可重复操作 | `SKILL.md`，以及流程真正需要的资源 |

没有独立可执行流程时选择 `instruction`；删除可复用骨架就失去核心价值时选择 `template`；其余选择 `workflow`。

## 只打包实际使用的文件

- `SKILL.md`：必需入口与核心契约。
- `scripts/`：存储的 batch 文件和确定性 helper。
- `templates/`：运行时填写或复制的文本与结构化骨架。
- `references/`：较长或按需加载的知识、policy、schema 和工具契约。
- `assets/`：输出会使用的二进制或静态资源。
- `evals/`：随 Skill 长期维护的 fixture 或 assertion。
- `agents/openai.yaml`：有实际消费者时使用的可选 metadata。

```text
instruction-skill/       template-skill/
├── SKILL.md             ├── SKILL.md
└── references/policy.md └── templates/report.md

workflow (batch: false)  workflow (batch: true)
├── SKILL.md             ├── SKILL.md
└── references/policy.md └── scripts/
                            ├── run.batch.json
                            └── transform.py      # 仅在确有需要时加入
```

不要创建空目录、placeholder、重复文档或无用 README。只有泛化 example 能解释非显然边界时才保留。
