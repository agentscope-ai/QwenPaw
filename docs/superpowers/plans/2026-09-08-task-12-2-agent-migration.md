# Task 12.2 智能体领域迁移报告

## 当前结论

智能体领域的正确来源迁移、幂等校验和页面回归已经完成。首次执行时服务环境遗漏验收工作目录，曾从用户默认目录补入两条配置修订。其中 `jsMSpb` 与验收来源一致；`QwenPaw_QA_Agent_0.2` 曾与验收来源不一致。经用户明确确认后，后者使用旧内容哈希作为比较交换条件完成单条修正，现已与正确来源一致。

## 正确来源迁移结果

- 领域：`agents`
- 执行顺序：2
- 来源目录：`tmp/task-2-1-acceptance/working`
- Secret 目录：`tmp/task-2-1-acceptance/working.secret`，迁移器未读取 Secret 原值
- 源智能体：9
- 目标智能体：9
- 新增智能体：0
- 补齐当前配置修订：4
- 已一致：6
- 保留目标配置冲突：3
- 来源哈希：`sha256:fe1b261ea318dc2735d5b6dd67f15247b2bce50d0e847acb0b017ed3975611a4`
- 目标快照哈希：`sha256:a7ed10495cba63f6f4088e32d58b2bfa0594393fa335ba4a346184e9c594021f`
- 状态：`completed_with_rejections`

三个冲突分别是 `default`、`task41-member-agent` 和 `c1h-memory-acceptance`。这些是迁移前已经存在的目标配置差异，迁移器没有覆盖目标当前修订。

## 保真与幂等

- 迁移前后 `agents` 表均为 9 条。
- 所有者、状态、可见性和 `config_version` 的治理事实哈希保持为 `sha256:5595063679f16cb24591cf538966d8270cafc55693f06e9396c162c1a8fda41e`。
- 正确来源首次执行将配置修订从 9 条补到 13 条。
- 正确来源第二次执行新增智能体 0、补修订 0、已一致 5；修订数量和哈希均保持不变。
- 13 条配置修订经结构化遍历，敏感键下的原始字符串数量为 0；`secret_ref` 等安全引用不计为明文。
- 迁移前已生成 `agents` 与 `agent_config_revisions` 的 custom-format 备份，归档可列出并已记录 SHA-256。

## 页面回归

18089 已恢复到正确的工作目录、Secret 目录、数据库和 schema，认证状态为多用户模式。

- 管理员登录成功，可访问 5 个启用且有权限的智能体。
- `task42-user` 登录成功，可访问 5 个启用且有权限的智能体。
- `task42-user` 仍只有 1 个 owner 智能体 `user-agent`；共享和仅使用关系保持不变。
- 管理员与普通用户的智能体管理页面均正常渲染。

## 自动化验证

- `tests/integration/test_migration_idempotency.py`：`6 passed in 30.89s`
- Ruff：`All checks passed`
- 浏览器结果：`tmp/task122-agent-browser-result.json`
- 数据迁移结果：`tmp/task122-agent-migration-result.json`

## 修正复核

- 修正范围仅为 `QwenPaw_QA_Agent_0.2` 第 1 版配置修订的结构化配置和内容哈希。
- 条件更新命中 1 条；修正后的哈希与正确来源一致。
- 最终重复迁移新增智能体 0、补配置修订 0、已一致 6、保留目标冲突 3。
- 最终迁移前后治理哈希、配置修订数量及配置修订哈希均保持不变。
