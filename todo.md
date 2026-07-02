# Issue Todo

## Selected Issue

- [x] #5705 Secret safety and env-var config references
  - Source: https://github.com/agentscope-ai/QwenPaw/issues/5705
  - Scope: implement the independent `${ENV_VAR}` config reference layer for root config and `agent.json`.
  - Validation: focused unit tests for recursive expansion and agent config loading.

## Notes

- Skipped issues already covered by open PRs or assigned to other contributors.
- This PR intentionally addresses the env-var reference part of #5705; dialog/ReMe log redaction can follow separately.
