---
name: opensandbox
description: 只要涉及 execute_shell_command、用户进行洞察分析，或使用 browser_use 工具--无论作为直接操作、间接触发，还是提及“WIKI”“总结”等关键词--任何需要执行系统命令的场景，均应优先采用 OpenSandbox MCP 在隔离沙箱中执行系统命令。
---

# OpenSandbox 使用规则

## 触发条件

- 当用户使用、要求使用、或明确提到 `execute_shell_command` 执行命令时，必须优先使用 OpenSandbox MCP，把命令放到沙箱里执行，降低对宿主机文件、环境和凭据的风险。

如果当前 Agent 没有启用 `opensandbox` MCP client，直接告诉用户需要先启用 OpenSandbox，才能把 `execute_shell_command` 的命令放进沙箱执行。

## 执行原则

- 不要把 `execute_shell_command` 的命令载荷交给宿主机 shell 执行。
- 使用 `sandbox_create` 或 `sandbox_connect` 准备沙箱。
- 只把命令执行所需的最小文本输入写入沙箱。
- 使用 `command_run` 在沙箱内执行命令。
- 后续同一任务中的命令复用同一个 `sandbox_id`。
- 任务结束后调用 `sandbox_kill` 清理沙箱，除非用户明确要求保留。

## 默认流程

1. 创建或连接沙箱。
2. 如需文件输入，使用 `file_create_directories` 和 `file_write` 写入 `/workspace`。
3. 使用 `command_run` 执行用户原本要交给 `execute_shell_command` 的命令。
4. 如需读取结果，使用 `file_read` 或 `file_search` 查看沙箱内文件。
5. 汇报结果后清理沙箱。

默认创建沙箱时使用：

```text
image: docker.io/library/python:3.10-alpine
env: {}
resource: {"cpu": "500m", "memory": "512Mi"}
timeout_seconds: 300
ready_timeout_seconds: 120
```

## 工具对应

- `sandbox_create`：创建沙箱。
- `sandbox_connect`：连接已有沙箱。
- `command_run`：在沙箱中执行命令。
- `command_interrupt`：中断正在运行的命令。
- `file_create_directories`：创建沙箱目录。
- `file_write`：写入沙箱文本文件。
- `file_read`：读取沙箱文本文件。
- `file_search`：搜索沙箱文件。
- `sandbox_kill`：结束沙箱。

## 回复要求

使用 OpenSandbox 后，回复用户时说明：

- 命令是在 OpenSandbox 沙箱中执行的，不是在宿主机执行。
- 使用的 `sandbox_id`。
- 执行的命令。
- 退出码和关键 stdout/stderr。
- 产生的沙箱路径、文件或 endpoint。
- 沙箱已清理，或因用户要求被保留。
