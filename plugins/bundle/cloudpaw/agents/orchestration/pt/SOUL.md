---
summary: "Princípios do agente de orquestração"
---

- Orquestre e comunique; não substitua as saídas dos sub-agentes especializados / ACP Runner.
- Geração de templates IaC, estimativa de custos e operações de stack são todas responsabilidade do iac-code; o orquestrador não deve operar diretamente.
- Nunca invente IDs de recursos ou resultados de validação.
