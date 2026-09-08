# Primary type and package

Choose what the Skill primarily provides. Supporting files do not create extra types.

| Type | Core value | Usual shape |
|---|---|---|
| `instruction` | Rules, knowledge, a checklist, or judgment guidance | `SKILL.md`, with focused `references/` when useful |
| `template` | A reusable output skeleton that still needs agent judgment | `SKILL.md` plus `templates/` or `assets/` |
| `workflow` | A repeatable operation with ordered actions or stages | `SKILL.md`, with resources required by the flow |

Choose `instruction` when there is no distinct runnable flow. Choose `template` when removing the reusable skeleton removes the Skill's core value. Otherwise choose `workflow`.

## Package only what is used

- `SKILL.md`: required entrypoint and essential contract.
- `scripts/`: stored batch files and deterministic helpers.
- `templates/`: text or structured skeletons filled or copied at runtime.
- `references/`: substantial or conditional knowledge, policies, schemas, and tool contracts.
- `assets/`: binary or static resources used in output.
- `evals/`: durable fixtures or assertions maintained with the Skill.
- `agents/openai.yaml`: optional metadata with a concrete consumer.

```text
instruction-skill/       template-skill/
├── SKILL.md             ├── SKILL.md
└── references/policy.md └── templates/report.md

workflow (batch: false)  workflow (batch: true)
├── SKILL.md             ├── SKILL.md
└── references/policy.md └── scripts/
                            ├── run.batch.json
                            └── transform.py      # only when needed
```

Do not create empty directories, placeholders, duplicated documents, or an unused README. Keep a generalized example only when it clarifies a non-obvious boundary.
