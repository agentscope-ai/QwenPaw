# PR #6744 Review：共享文件系统上的 Agent 配置持久化加固

- PR：<https://github.com/agentscope-ai/QwenPaw/pull/6744>
- 审查分支：`fix/agent-config-ossfs-safety`
- 原始提交：`71c8798d3de9409244188d34c86c336010b71791`
- 基线 merge-base：`f09dd84698592af7c8648e8f1654463d4cd2aadd`
- 审查日期：2026-08-06

## 结论

远端 PR 原始版本不建议直接合并。它覆盖了原子写、缓存指纹、定期内容摘要、
陈旧保存检测和运行态拆分等主要方向，但仍有事件循环阻塞、ACL 外部更新丢失、
降级不兼容和写后摘要错误绑定等实质问题。

这些可修复问题已经在本地 PR 分支完成修正。修正后，PR 描述中的目标基本实现，
但不能把它描述成“彻底消除外部并发覆盖”：不配合锁协议的外部进程仍可在摘要
校验与 `os.replace` 之间写入，普通文件系统 API 无法提供跨进程 compare-and-swap。
当前还必须解决与最新 `upstream/main` 在 `src/qwenpaw/config/config.py` 的合并冲突，
并在推送后重新跑远端 CI，才达到可合并状态。

## Findings 与处理状态

### P1：同步文件 I/O 会阻塞事件循环——已修复

原始实现从异步流程直接调用同步配置和状态 API：

- Agent 配置 watcher 每两秒执行同步 `stat/read/hash`；
- Heartbeat 同步读取配置、`HEARTBEAT.md` 和 `last_dispatch`；
- 回复完成回调同步执行带 `fsync` 的原子状态写；
- ACL 消息门禁和 FastAPI 路由同步读取、重载和原子写 ACL。

OSSFS/FUSE、网络盘或磁盘拥塞时，这些调用会暂停整个事件循环。现已统一通过
`run_sync_io` 在线程中执行完整同步事务；reply callback 同时支持同步和异步实现，
异步回调会被等待，避免应用关闭时丢失状态。相关实现见：

- `src/qwenpaw/app/agent_config_watcher.py:111`
- `src/qwenpaw/app/crons/heartbeat.py:189`
- `src/qwenpaw/app/channels/base.py:487`
- `src/qwenpaw/app/workspace/service_factories.py`
- `src/qwenpaw/app/routers/access_control.py`

说明：仓库中仍有一些早于本 PR 存在的异步代码直接调用同步配置 API；本次修复
覆盖了本 PR 新增或显著加重的持久化热路径，没有借机做全仓异步 API 重构。

### P1：升级后降级会令 `last_dispatch` 失效——已修复

原始迁移成功后删除 `agent.json.last_dispatch`。旧版本只认识该字段，降级后
Heartbeat `target=last` 会失效。

现采用临时兼容策略：

1. 升级时先原子发布 `state/last_dispatch.json`；
2. 保留 `agent.json.last_dispatch`；
3. 新版本优先读取 state 文件，缺失或无效时回退旧字段；
4. `AgentProfileConfig` 显式保留 deprecated 字段，保证后续保存其他配置时不会
   意外删除它；
5. 后续 dispatch 只更新 state 文件，不恢复每次回复重写 `agent.json` 的旧行为。

降级后能读取升级时最后保存的目标，但不会包含新版本运行期间的最新 dispatch。
若要求降级后也绝对最新，只能双写两个文件，这会重新引入本 PR 要消除的配置
热写、事件循环阻塞和竞争问题，因此不建议。

相关实现与测试：

- `src/qwenpaw/config/config.py:1761`
- `src/qwenpaw/config/utils.py:843`
- `tests/unit/config/test_agent_config_persistence.py:147`

### P1：ACL 的 mtime-only 重载会覆盖外部更新——已修复

原始 `AccessControlStore` 仅在 `current_mtime > last_mtime` 时重载，而且写操作前
不重载。相同 mtime 的原子替换、时钟回拨或旧 store 引用都可能令内存状态过期，
随后一次本地写会覆盖外部 ACL 更新。

现已复用跨平台文件指纹和稳定快照读取；所有 ACL 变更在持锁状态下先检查磁盘
指纹并重载。消息门禁合并成一次 `check_access` 事务，减少重复锁与重复 I/O。

- `src/qwenpaw/utils/io_utils.py:55`
- `src/qwenpaw/utils/io_utils.py:77`
- `src/qwenpaw/app/channels/access_control.py:244`
- `tests/unit/app/channels/test_access_control.py:403`

### P1：写后竞争可能把外部摘要绑定到旧模型——已修复

原始 `save_agent_config` 在原子替换后重新读取磁盘，并无条件把读到的摘要记录到
刚保存的模型。如果外部进程在替换后、重读前写入，该旧模型会错误获得外部版本
摘要，下一次保存可能绕过陈旧检测。

现对写入 payload 预先计算与原子 JSON 序列化完全一致的摘要，写后磁盘摘要必须
匹配；迁移写入使用同一校验。检测到竞争时清理缓存并要求调用者重载。

- `src/qwenpaw/config/config.py:80`
- `src/qwenpaw/config/config.py:2968`
- `tests/unit/config/test_agent_config_persistence.py:376`

### P2：跨进程校验仍有 TOCTOU 窗口——设计限制，未彻底消除

`save_agent_config` 的流程仍是“读取并校验旧摘要 → `os.replace`”。若一个不遵循
QwenPaw 锁协议的外部写者恰好在两步之间更新文件，本次保存仍可能覆盖它。迁移
回写也存在同类窗口。

进程内锁、写前摘要和写后摘要可以显著缩小并检测部分竞争，但无法实现跨平台、
跨进程、任意外部写者参与的文件 compare-and-swap。若业务要求严格零丢失，需要
所有写者共同使用版本协议/锁服务，或改用支持条件更新的存储后端。PR 描述应将
“preventing”调整为“detects stale versions before save and reduces overwrite risk”。

### P2：PR 与最新 main 冲突——合并前必须解决

`git merge-tree --write-tree HEAD upstream/main` 确认
`src/qwenpaw/config/config.py` 存在内容冲突。不要机械选择 ours/theirs；最新 main
也改动了同一配置模块，需要人工保留双方语义后重跑完整测试。

### P2：远端 website format check 失败——本地已修复，待推送验证

远端日志确认失败文件为 `website/public/docs/config.en.md` 和
`website/public/docs/config.zh.md`。本地已用项目 Prettier 修复，同时格式化本次
更新的 Heartbeat 文档；目标文件的 `prettier --check` 已通过。

## Windows / macOS / Linux 兼容性

总体设计兼容三平台：临时文件与目标文件位于同一目录，使用 `os.replace`，没有
引入 `fcntl`、`flock` 或 POSIX-only 路径拼接；路径均由 `pathlib.Path` 处理。

文件指纹包含 device、inode、size、纳秒 mtime/ctime。部分 Windows/FUSE 文件系统
可能不提供有区分度的 inode/ctime，但五秒一次的 SHA-256 内容校验仍提供有界陈旧
时间。原子替换在 Windows 遇到文件被其他进程以不共享删除权限打开时可以失败；
代码会传播保存错误，迁移则保留源字段以便重试，不会把失败伪装成成功。

本地只在 macOS 执行了测试，尚未获得 Windows runner 的实测证据。建议推送后确保
Windows CI 至少覆盖原子替换、同 mtime 替换和迁移失败重试用例。

## 功能性与模块化评价

修正后的结构比原始 PR 更清晰：文件指纹和稳定快照属于通用 I/O 能力，已从大型
配置模块抽到 `io_utils.py`；ACL 的“检查并登记 pending”是单一事务；异步边界位于
应用层，底层同步模型没有混入 event loop 逻辑；迁移顺序仍是先发布目标状态、再
处理源配置。

仍不建议为一次性场景继续增加抽象。当前缓存 entry、通用快照、原子 writer 和
状态读写职责已足够分离。

## 验证结果

- `Codex-QwenPaw` 环境完整单测：`6283 passed, 15 skipped`；
- 最后新增的配置并发/降级用例：`15 passed`；
- 频道、ACL、Heartbeat 与配置针对性回归：`216 passed, 1 skipped`；
- 修改文件 `pre-commit`：通过；
- 四份修改文档 `prettier --check`：通过；
- `git diff --check`：通过。

现有 warning 主要是仓库原有的 asyncio marker、未 await mock 和第三方弃用警告，
本次没有顺带修改。

## PR 描述逐项核对

- [x] `agent.json` 和 ACL 迁移改为原子写
- [x] ACL 目标状态保存失败时保留旧字段
- [x] Agent 配置缓存使用文件指纹、定期摘要和深拷贝返回
- [x] 保存前检测陈旧内容版本，并增加写后竞争检测
- [x] 每 Agent 的新 `last_dispatch` 更新写入独立 state 文件
- [x] 迁移先发布 state，失败可重试
- [x] Heartbeat 优先读取独立 state 文件
- [x] 中英文配置和 Heartbeat 文档已更新
- [x] PR 新增/加重的持久化热路径不再阻塞事件循环
- [x] 保留旧 `last_dispatch`，支持降级读取
- [ ] 严格消除任意外部写者竞争：普通文件 API 下无法保证
- [ ] 与最新 main 无冲突：当前尚未解决
- [ ] 远端 CI 全绿：需推送本地修正后重新验证

## 最终建议

当前本地修正版结论为 **Changes requested，修复完成后可复审**。下一步应：

1. 人工解决与最新 main 的 `config.py` 冲突；
2. 更新 PR 描述，删除“迁移后移除 legacy last_dispatch”的表述，并说明降级策略；
3. 提交并推送本地修正；
4. 等待 Linux/Windows CI 和 website format check 全绿后再合并。
