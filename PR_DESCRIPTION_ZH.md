## 描述

实现 Mission Mode——面向复杂长周期任务的自治迭代 Agent 系统。

灵感来源于 [snarktank/ralph](https://github.com/snarktank/ralph)（MIT 许可证）、Anthropic 发布的 [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) 设计模式，以及 Claude Code 的 verification agent 机制。

核心设计哲学：**代码级控制 + prompt 指引 + 独立验证**。可靠性关键路径（迭代控制、工具限制、PRD 校验、最大轮次）由代码保证；需要判断力的路径（任务拆解、调度策略、错误恢复）由 prompt 指引；每个 story 的验收由独立的**对抗性验证 agent** 完成，而非 worker 自证。

**Related Issue:** N/A

**Security Considerations:**
- Mission Mode 在 Phase 2 通过 Toolkit group 机制禁用 master agent 的实现类工具（shell/write/edit），防止 master 越界自行实现
- Verifier agent 被严格限制为只读——禁止修改任何项目文件

## Type of Change

- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Refactoring

## Component(s) Affected

- [x] Core / Backend (app, agents, config, providers, utils, local_models)
- [x] Console (frontend web UI)
- [ ] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
- [ ] Skills
- [x] CLI
- [ ] Documentation (website)
- [ ] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## 变更概览

### 新增文件（8 个）

| 文件 | 说明 |
|---|---|
| `src/qwenpaw/agents/mission/__init__.py` | 模块初始化，含 snarktank/ralph 版权声明 |
| `src/qwenpaw/agents/mission/handler.py` | `/mission` 命令解析器，会话绑定状态初始化 |
| `src/qwenpaw/agents/mission/prompts.py` | Master/Worker/Verifier prompt 模板 |
| `src/qwenpaw/agents/mission/mission_runner.py` | 两阶段执行引擎：代码级迭代循环 + Toolkit group 工具限制 |
| `src/qwenpaw/agents/mission/state.py` | 文件化状态管理（prd.json, progress.txt, loop_config.json, task.md） |
| `src/qwenpaw/app/runner/mission_dispatch.py` | Runner 集成层，支持会话级自动跟踪路由 |
| `src/qwenpaw/cli/mission_cmd.py` | CLI 入口（`qwenpaw mission start/status/list`） |

### 修改文件（7 个）

| 文件 | 说明 |
|---|---|
| `src/qwenpaw/app/runner/runner.py` | 集成 Ralph 两阶段执行分发，后续消息自动路由 + 轻量上下文刷新 |
| `src/qwenpaw/cli/main.py` | 注册 `ralph` CLI 子命令组 |
| `console/src/locales/{en,zh,ja,ru}.json` | 添加 `/mission` 斜杠命令的 i18n 描述 |
| `console/src/pages/Chat/index.tsx` | 前端注册斜杠命令建议 |

### 架构设计

```
用户: /mission 实现用户认证系统
        │
        ▼
   handler.py ── 解析命令 ──▶ 创建 loop_dir + 状态文件
        │                      写入 loop_config.json (phase=prd_generation)
        │                      注入 MASTER_PROMPT 到 agent 消息
        ▼
   mission_dispatch.py ──▶ 返回 {mission_phase:1, loop_dir, max_iterations}
        │
        ▼
   runner.py ── 检测到 mission_info ──▶ 分发到 mission_runner
        │
        ▼
   mission_runner.py
        ├── Phase 1 (run_mission_phase1)
        │     Agent 生成 prd.json → 代码校验 schema → 报告给用户
        │     用户确认后 agent 写 current_phase=execution_confirmed
        │     代码检测到 → 无缝过渡到 Phase 2
        │
        └── Phase 2 (run_mission_phase2)
              代码级: set_phase2_tool_restrictions() 禁用实现类工具
              代码级: for 循环 (max_iterations)
                Master 调度当前 batch:
                  Worker(s) ──实现──▶ Verifier(s) ──对抗性验证──▶ VERDICT
                  PASS → Master 更新 prd.json passes=true
                  FAIL → Master 重试 worker（附带错误上下文）
                代码检查 prd.json stories.passes
                全部 pass → 完成 ✅
                否则 → 注入 continuation msg → 下一轮
              代码级: finally → restore_tools()
```

### Worker → Verifier 管线

每个 story 的完成流程：

```
┌─────────┐     ┌──────────┐     ┌─────────────┐
│  Master  │────▶│  Worker  │────▶│  Verifier   │
│ (总控)   │     │ (实现)   │     │ (对抗验证)  │
└─────────┘     └──────────┘     └─────────────┘
                     │                   │
                     │ 实现 story         │ VERDICT: PASS/FAIL/PARTIAL
                     │ 跑质量检查         │ 附带命令证据
                     │ 不标记 passes      │ Master 据此更新 prd.json
                     ▼                   ▼
```

**关键设计**：
- Worker **不再自行标记 `passes: true`**——消除"裁判兼球员"问题
- Verifier 是**对抗性角色**，目标是"尝试破坏实现"而非确认正确
- Verifier **严格只读**——禁止修改项目文件，只能读代码、运行验证命令
- 每个 check 必须包含 **Command run + Output observed**——不能只读代码就标 PASS
- Verifier prompt 参考 Claude Code 的 `verificationAgent.ts`

### 代码级保证（非 prompt 依赖）

| 维度 | 实现 |
|---|---|
| 迭代循环 | `mission_runner.py` 中 `for` 循环，agent 停 → 代码检查 prd.json → 注入续行消息 |
| 工具限制 | Phase 2 通过 `Toolkit.update_tool_groups("mission_impl", active=False)` 禁用 shell/write/edit |
| PRD 校验 | `validate_prd()` 在 Phase 1→2 转换前校验 schema |
| 最大轮次 | 代码硬限制，非 LLM 自律 |
| 阶段转换 | agent 写 loop_config 信号 → 代码检测并执行转换 |
| 会话绑定 | loop_config 存储 session_id，防止跨会话干扰 |
| 验证隔离 | Worker 和 Verifier 是独立 session，Verifier 只读 |

### 用户体验

- 第一次输入带 `/mission` 触发，后续消息自动路由到活跃的任务
- 支持 `/mission status` 和 `/mission list` 子命令
- 支持 `--verify <command>` 指定验证命令（如 `pytest`），传递给 Verifier
- CLI: `qwenpaw mission start "任务描述"`
- Agent 自动匹配用户输入语言

## Checklist

- [x] I ran `pre-commit run --all-files` locally and it passes
- [x] If pre-commit auto-fixed files, I committed those changes and reran checks
- [ ] I ran tests locally (`pytest` or as relevant) and they pass
- [ ] Documentation updated (if needed)
- [x] Ready for review

## Testing

1. **基本流程**: 输入 `/mission 创建一个简单的 TODO 应用` → 验证 Phase 1 生成 prd.json → 确认后进入 Phase 2 自动迭代
2. **Worker→Verifier 管线**: Worker 完成后 Master 应自动 dispatch Verifier → Verifier 输出 VERDICT → Master 据此更新 prd.json
3. **Worker 不自证**: Worker 完成后 prd.json 中对应 story 的 `passes` 应仍为 `false`
4. **Verifier 只读**: Verifier session 不应修改任何项目文件
5. **工具限制**: Phase 2 中 master agent 不应直接执行 shell 命令或写文件
6. **会话绑定**: 另一个会话不应干扰当前活跃的 Ralph Loop
7. **自动路由**: 第二条消息不带 `/mission` 前缀也应被正确路由
8. **子命令**: `/mission status` 和 `/mission list` 正确返回状态信息
9. **CLI**: `qwenpaw mission start "test task"` 正确触发
10. **--verify**: `qwenpaw mission start "task" --verify pytest` 应将 `pytest` 传递给 Verifier prompt

## Local Verification Evidence

```bash
pre-commit run --all-files
# Passed (all hooks green)

pytest
# TODO: 需要添加 Ralph Loop 单元测试
```

## Additional Notes

- Prompt 模板改编自 [snarktank/ralph](https://github.com/snarktank/ralph)（MIT 许可证），已在 `__init__.py` 中注明版权
- Verifier prompt 参考 [Claude Code](https://github.com/anthropics/claude-code) 的 `verificationAgent.ts` 设计
- 设计文档详见 `design/agentic-ralph-loop.md`（未包含在本次提交中）
