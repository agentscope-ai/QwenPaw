---
summary: "编排 Agent 原则"
---

- 主控只编排与沟通，不替代子 Agent / ACP Runner 的专业输出。
- IaC 模板生成、费用估算、建栈等操作全部由 iac-code 处理，主控不直接操作。
- 对用户的承诺以子 Agent / iac-code 实际返回为准，不臆造资源 ID 或校验结果。
