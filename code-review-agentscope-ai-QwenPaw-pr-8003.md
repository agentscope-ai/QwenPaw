# 代码审查：agentscope-ai/QwenPaw PR #8003

**PR：** https://github.com/agentscope-ai/QwenPaw/pull/8003
**Issue：** PR 描述中未关联 Issue。
**审查版本：** 远端及本地 HEAD 为 `9f186644e21a31c390a773460fa865f45228fc52`；本次主要复审 HEAD 之上的本地未提交修复。对比基线为 `6512a635`。
**审查范围：** 原 PR 与本地修复合计 26 个代码/测试文件（含新增的 `_cleanup_logging.py` 和 `test_cleanup_logging.py`），重点检查文件名解析、三种 Windows sandbox 退出清理、ACP 展示路径和跨平台测试。
**审查限制：** 本机为 macOS，未执行 Windows 原生 API。当前 GitHub checks 对应旧 HEAD，不能验证未提交修复。历史问题以用户提供的审查报告为准；另读取了远端 PR 描述、顶层评论、review 摘要和此 SHA 的 workflow 记录。本轮未修改产品代码或远端状态，临时复现用例放在 `/private/tmp`。

## 总体结论

**不是全部修复完成。** 本次 PR 全部 26 个变更文件的适用 pre-commit hooks 均通过，相关现有测试 `1662 passed`，但额外编写的独立边界用例得到 `6 failed`，对应下面 3 类遗漏。

真实 ACL 失败调用链的静默已生效，普通 ACL 失败会保存失败元数据，清理阶段异常也不会阻止后续容器处理。绝对 POSIX 路径中的反斜杠文件名已恢复。然而，相对 POSIX 文件名仍会被误切分，旧会话中的 Windows file URL 再次显示完整路径，而且元数据读取/枚举阶段的异常仍能中断整轮清理。

远端 PR 仍未包含本地修复；没有查询到该 SHA 的 Windows 或 Full Tests Nightly 验证。不能将 lint 和 macOS 测试通过等同于 Windows 验收完成。

## 变更范围

| 子系统 | 当前行为 |
| --- | --- |
| 文件消息、旧会话恢复 | 两处改用 `media_basename()`；模型格式化先解析 file URL，旧会话恢复直接传 URL |
| Windows sandbox | 三种退出回调都使用 `log_progress=False`；ContextVar 与 logger filter 屏蔽清理上下文日志；清理循环加入异常隔离 |
| ACP | NUL 输入在进入 Path 解析前直接返回；有效路径使用宿主原生分隔符 |
| 跨平台测试 | 调整 HOME/USERPROFILE、路径断言、浏览器 fixture、SQLite 平台限定及小艺 asyncio 标记 |
| 测试隔离 | 公共 HOME fixture 增加 USERPROFILE；CLI 测试显式指定 host/port |

## 历史 Review 复核

以下“已修复”均指**本地工作区**，不是远端 PR 已发布代码。

| 历史问题 | 当前状态 | 验证证据 |
| --- | --- | --- |
| 阻塞项 1：AppContainer 静默未覆盖 ACL/失败元数据调用链 | 已修复 | 新测试执行真实 `_cleanup_single_container()`、ACL 重试及失败元数据迁移，底层 handler 抛错时不产生终端写入；正常失败元数据仍保存 |
| 阻塞项 1：逐容器异常隔离 | 部分修复 | 清理调用已被隔离；读取/枚举在隔离范围之外，见 M3 |
| 阻塞项 2：POSIX 反斜杠文件名回归 | 部分修复 | `/tmp/invoice\draft.pdf` 正确；实际存在的相对文件 `invoice\draft.pdf` 仍错误，见 M1 |
| 阻塞项 3：Windows 验证 | 仍然存在 | PR checks 只有 Ubuntu 测试；按 HEAD SHA 查询 workflow 记录，未发现 Full Tests Nightly；本地修复未推送 |
| 原 M1：NUL 守卫测试不足 | 已修复 | 新用例验证 NUL 输入不会交给 Path 解析器；文档把契约限定为保留 NUL 输入，没有宣称所有 ValueError 均返回原字符串 |
| 原 M2：Qoder 编码期望复制实现 | 已修复 | Windows 使用固定 UNC 输入和字面量 `server-share-Some-Dir`；POSIX 也使用固定独立期望 |
| 原 M3：展示分隔符契约不明确 | 部分修复 | ACP `_display_path()` 已明确 native separators；delegate 主要仍由 `Path(...)` 断言表达约定，不构成已证实的行为错误 |
| L1：Windows file URI 非标准形式 | 仍然存在 | `_local_path_to_file_url()` 仍生成 `file://C:/...`；这是既有问题，不新增为 PR 回归 finding |
| L2：无关格式化噪音 | 仍然存在 | 相对基线的 docstring 空行差异仍在；非行为问题、不阻塞合并 |
| L3：HOME fixture 未跨平台/未收敛 | 部分修复 | `temp_copaw_home` 已设置 USERPROFILE；分散的 HOME 设置尚未统一迁移，不应宣称已全仓收敛 |
| L4：另外两个 sandbox 的 atexit 日志 | 已修复静默部分 | 三个模块均注册 `log_progress=False`，共享调用链日志过滤；元数据枚举异常隔离仍见 M3 |
| L5：PR 模板/Evidence 未填写 | 仍然存在 | 远端 Type/Component 未勾选；Testing、Evidence 仍含占位/示例，未补 Windows 结果 |
| 附带发现：CLI 测试读取本机端口 | 已修复 | 流式测试明确指定 `--host 127.0.0.1 --port 8088`，本次扩展测试通过 |

## 发现的问题

### [Medium] M1. 合法 POSIX 相对文件名仍被当作 Windows 路径截断

**位置：** `src/qwenpaw/utils/media_paths.py:58`，`media_basename()`。

**问题：** `"\\" in path and "/" not in path` 将任何含反斜杠的单段字符串都判定为 Windows 路径，无法保留 POSIX 当前目录下合法的反斜杠文件名。历史 POSIX 回归只修复了绝对路径案例。

**证据 / 触发条件：** 在 macOS 临时目录真实创建 `invoice\draft.pdf`，使用同名相对路径构造没有 filename hint 的文件消息。`msg_from_dict()` 和 `_fixup_media_list()` 都输出 `File 'draft.pdf'`，而实际名称是 `invoice\draft.pdf`。两个独立用例均失败。读取原基线 `6512a635` 的兼容函数确认原实现保留完整名称。

**影响：** POSIX 相对文件附件的模型上下文文件名不正确。显式提供 filename 可规避，但不能依赖所有历史消息均带 hint。

**修复建议：** 区分明确 Windows 形式（盘符、UNC 等）和有歧义的相对字符串。有歧义时根据宿主/来源平台或显式 path flavor 决定规则；不要仅凭一个反斜杠认定它是 Windows 目录分隔符。

**建议测试：** 在 POSIX 上创建并引用 `invoice\draft.pdf`，分别验证旧会话恢复与模型格式化；同时保留 Windows drive/UNC 和明确 Windows 相对路径测试。

### [Medium] M2. 新 helper 使旧会话中的 Windows file URL 再次显示完整路径为文件名

**位置：** `src/qwenpaw/_compat/message.py:180`；`src/qwenpaw/utils/media_paths.py:55`。

**问题：** 旧会话分支把 source URL 原样交给仅判断路径语法的 `media_basename()`。URL 前缀遮住盘符/UNC 前缀，且 `file://` 本身含 `/`，导致落入 POSIX 分支。模型格式化分支会先 `_file_url_to_path()`，因此两条链路再次分叉。

**证据 / 触发条件：** `msg_from_dict()` 接收 `{"type":"file","source":{"type":"url","url":"file://C:\\files\\real.png"}}`，当前输出名称为 `C:\files\real.png`。`file://\\server\share\real.png` 也错误。两个独立用例均失败。对比已发布 HEAD `9f186644` 的 `_coerce_block()`，它们曾正确返回 `real.png`；这是最新本地修复引入的回退。当前 `_fixup_media_list()` 仍能提取这两个输入的 `real.png`。

**影响：** 恢复这种旧文件消息时，Windows 文件名显示错误重新出现；原始 `file://` 加原生路径的形式是兼容路径需要处理的输入。

**修复建议：** 在提取名称前解析 `file://`，或让共享 helper 明确接受 URL 并统一处理；保留展示位置文本与文件名提取的职责边界。

**建议测试：** 对盘符及 UNC 的原始 file URL，在 `msg_from_dict()` 层验证名称，并与 `_fixup_media_list()` 对照；同时保留 POSIX 反斜杠名称回归测试。

### [Medium] M3. 损坏元数据仍能在逐容器异常隔离之前终止整轮清理

**位置：** `src/qwenpaw/sandbox/windows_appcontainer_sandbox.py:1228`；`src/qwenpaw/sandbox/windows_unelevated_sandbox.py:1782`、`:1786`；调用点 `windows_elevated_sandbox.py:2717`、`windows_unelevated_sandbox.py:2902`。

**问题：** 新 try/except 仅覆盖清理处理阶段。AppContainer 的 UTF-8 读取异常不属于现有 `JSONDecodeError/OSError` 捕获范围；另外两个后端在进入受保护循环之前先调用 `_iter_orphaned_metadata()`，其 `.get()` 未验证反序列化结果是否为对象。损坏状态仍然能阻止健康条目的处理。

**证据 / 触发条件：**

- AppContainer 首个元数据含不完整 UTF-8 字节，后面跟一个合法容器：`shutdown_cleanup(log_progress=False)` 抛出 `UnicodeDecodeError`，后续清理未执行。
- 共用枚举目录同时包含 `null` 和合法 JSON 对象：`_iter_orphaned_metadata()` 在 `meta.get()` 抛出 `AttributeError`，无法返回健康条目。两个后端都在新 try/except 之前调用它。

两个独立用例均失败。此问题是**历史“逐 metadata 异常隔离”目标的遗漏**；读取/枚举缺陷本身不是本轮新引入，不能写成新的安全回归。

**影响：** 有损坏或非预期 schema 的持久化状态时，后续容器的 ACL/账户/配置文件清理可能不会执行，留待未来退出再次尝试，但坏条目会持续阻塞。

**修复建议：** 将读取、解析、结构检查、owner PID 检查和清理一起纳入逐条隔离；至少捕获解码错误并拒绝非 dict JSON。保留坏文件或隔离归档供诊断，同时继续后续条目。

**建议测试：** 真实临时目录中按序放置坏 UTF-8、`null`/数组和合法元数据，验证所有后端均继续处理合法条目；quiet 模式不触发 handler，坏状态仍可排查。

## 测试与验证结果

| 命令或检查项 | 结果 | 说明 |
| --- | --- | --- |
| `pre-commit run --files`（PR 全部 26 个变更文件，含两个新增文件） | 通过 | AST、编码、尾逗号、mypy、Black、Flake8、Pylint 等适用 hooks 全部 Passed；无对应文件的 hooks 正常 Skipped |
| 相关现有测试：全部 sandbox、PR 修改的测试模块、消息格式化、safe-swap、install-lock | 通过 | 本轮重新执行，`1662 passed in 11.88s`，macOS；因宿主隔离探测测试需要真实宿主边界，使用沙箱外执行 |
| `.venv/bin/pytest /private/tmp/test_pr8003_review_edges.py -q --tb=short` | 失败 | `6 failed in 2.14s`；分别为相对 POSIX 名称 2 项、legacy Windows URI 2 项、损坏元数据 2 项 |
| 基线/HEAD/工作区兼容函数对比 | 已执行 | 用 `git show` 读取源码，在独立 namespace 执行；没有切换或修改工作区代码，确认 M1/M2 的回归归属 |
| GitHub PR metadata、comments/reviews、按 HEAD SHA 查询 runs | 已执行 | head 仍为 `9f186644`；无关联 Issue、无该 SHA 的 Full Tests Nightly，PR 模板仍未补齐 |
| Windows 原生单测和清理 API | 未运行 | 当前主机不是 Windows，且本地修复未推送；不把 mock 测试当作 Windows 端到端证据 |
| 全仓 `pre-commit run --all-files`、全量 pytest | 未运行 | 本轮保证的是本 PR 全部变更文件和相关测试，不宣称全仓检查结果 |

临时复现脚本：`/private/tmp/test_pr8003_review_edges.py`。
现有测试输出：`/private/tmp/pr8003-reviewed-tests.log`。
独立边界用例输出：`/private/tmp/pr8003-review-edges.log`。

## 测试覆盖缺口

- 当前 POSIX 名称测试只覆盖含反斜杠的绝对路径，缺少实际相对文件名。
- 旧会话测试覆盖原生 Windows 路径，但缺少反斜杠形式的 `file://` 输入。
- AppContainer 测试覆盖清理内部异常，未覆盖元数据读取/解码异常；其他后端新增的循环隔离也未覆盖前置枚举损坏状态。
- Windows 平台上的原生 API、路径和 HOME 行为仍需真实 Windows runner 验证。

## 待确认问题

- 未携带来源平台的相对路径究竟应按哪个平台解析？必须明确定义歧义处理，无法仅凭字符串同时完美识别两种语义。
- Windows nightly 应运行在包含本地修复的提交上；旧 HEAD 的 Linux 成功 checks 不能替代。
- L1 的 URI 标准化可独立处理，避免与本次文件名兼容性修复混为一个大改动。
- 静默上下文当前覆盖进入时已经加载的 sandbox loggers。已检查现有清理调用链均满足此前提，未将理论上的未来新 logger 情况列为缺陷。

## 合并建议

**建议：** 请求修改。

先修复 M1、M2，并补齐 M3 的隔离范围及测试；随后提交本地修改，在真实 Windows CI 上验证并完善 PR Evidence。当前 pre-commit 已通过，但不足以说明这些运行时边界问题已解决。
