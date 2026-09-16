# Task 8.1 MCP 与凭据验收记录

状态：代码、独立复核与隔离技术验收通过，待用户验收。未迁移或重启原环境，不进入8.2。

## 已确认范围

用户已确认具体设计；本轮连续实现凭据、MCP配置、OAuth和原页面闭环，不进入8.2。原6项MCP的数据写入和切换另行确认。

## 基线

- 原环境25份配置文件和9张相关表记录哈希，不输出秘密，schema仍0015。
- 只读预览发现6项MCP，Agent所有者映射和引用检查均通过；还需导入器的加密处理与最终等价核验，不能把结构检查当作迁移完成。
- 原MCP/Driver首次集成22passed、10failed，10项在创建Agent时因无活动模型失败。补用已有隔离模型fixture后32passed，exit0。未使用真实模型或凭据。
- 本机协议服务已通过实际MCP客户端连接/工具发现；后续浏览器将验证真实HTTP、界面、PG与审批链，不代表商业OAuth服务实测。

## 证据位置

本任务独立记录：`.superpowers/sdd/2026-09-06-task-8-1-mcp-credentials/`。

基线日志：`tmp/task81-baseline-backend.log`、`tmp/task81-baseline-with-model.log`（脚本第一次补fixture未实际生效）、`tmp/task81-baseline-with-model-02.log`（32通过）。协议客户端探测：`tmp/task81-protocol-smoke.log`。

## 实施结果

- PostgreSQL 保存 MCP 配置、修订、凭据绑定及 OAuth 会话。配置与绑定同事务提交，编辑使用 expected_revision；凭据密文保存，API只返回字段名。
- 运行时从 PostgreSQL Card Store 读取；YAML仅物化缓存。缺失、篡改或遗留缓存不会改变PG事实；调用前及审批后的凭据解析再次核对修订。
- 原 MCP 页面支持凭据 keep/replace/delete、并发冲突、仅使用者权限、白名单、策略及 OAuth。授权完成后阻断旧修订弹窗，失败和过期可重试。
- OAuth state与发起用户关联、单次消费、权限复核；精确GET callback公开，其他接口继续认证。Token绑定与配置引用同事务保存，提交后重载，自动刷新受Agent/Driver/当前绑定约束。
- 权限候选来自有效Owner和成员，不读取或返回私人会话标题/会话ID。
- 复用现有仓储、DriverCard和审批链，业务事务、公共DTO及运行时适配职责分开；未新增表、凭据管理中心或双写模式。

## 验证

| 范围 | 结果与证据 |
| --- | --- |
| Runtime/Driver | 184 passed；`tmp/task81-runtime-final.log` |
| 已连接HTTP凭据轮换 | RED复现旧Token；修复后179 passed，真实HTTP初始化后轮换并调用通过；`runtime-refresh-report.md` |
| 原 MCP 集成 | 32 passed；`tmp/task81-legacy-final02.log` |
| 前端 MCP | 49 passed；`task3-fix3-test-report.md`；TypeScript、生产构建、Monaco CSS校验通过 |
| OAuth与认证中间件 | fix4 30 passed含真实隔离PG；fix5定向49 passed，`task2-fix5-report.md` |
| 权限/凭据与OAuth编辑 | 10 passed，聚焦15 passed / 3 skipped；`task1-fix4-diff.md` |
| 真实 Chrome + PG + 本机协议 | 最终run14的12项检查全部通过；`tmp/task81-browser-20260907-000524/acceptance.json` |
| 原环境保真 | 25份文件、9张表哈希无变化，schema0015；`preservation-latest.json` |

上述套件有重复测试，不把计数相加冒充独立用例总数。数据库专用测试需要显式开启PG fixture，普通集合中的skipped不算通过。

浏览器使用独立schema `qwenpaw_test_5d95db41c5253d1013e1`、5个合成账号、真实Chrome、本机MCP/OAuth/模型协议服务。隔离服务已关闭，证据和schema保留。验证覆盖：

1. 浏览器创建MCP，配置实际入PG，真实MCP initialize/tools/list。
2. 配置修订无秘密，credential_records保存密文。
3. 页面keep/replace后刷新与真实新Authorization连接。
4. 协作者修改后旧草稿保存409；user不能编辑、另一Agent与无权用户拒绝。
5. 白名单空列表与null不同；普通用户可发现slash工具。
6. 真实 `/mcp` 调用按实际用户产生审批；Owner无法代批，用户本人批准后收到工具结果与completed SSE。
7. Owner及有效成员候选存在，不含私人chat字段。
8. 浏览器PKCE回调、1秒Token自动refresh、刷新Bearer实际连接、重开页面授权弹窗并撤销200。
9. 静态凭据delete、禁用及软删除，列表与GET不再出现旧Driver。
10. 浏览器storage、应用日志和SSE未出现合成秘密。

页面证据：`owner-created.png`、`stale-editor-conflict.png`、`oauth-revoked.png`。协议记录：`protocol-requests.json`；完整审批事件：`approved-chat-stream.txt`，均位于run14目录。

## 审查与修复记录

独立审查覆盖仓储、OAuth、前端和Runtime。浏览器进一步定位并修复了公开DTO参与内部合并导致keep丢失、OAuth callback被middleware401、PG OAuth缺少运行绑定与重载等整合缺陷。失败日志run01至run11完整保留，具体环境/脚本原因与产品缺陷见SDD progress.md，不包装为通过。

分项最终报告：`task1-final-review.md`、`task1-principals-final-review.md`、`task1-oauth-edit-final-review.md`、`task3-acceptance-review.md`、`runtime-final-review.md`、`task2-conflict-final-review.md`。OAuth遇到已有非系统Authorization（包括大小写别名）时在start返回400，提示先移除冲突；事务内再次检查，不覆盖原配置。撤销只删除完整匹配的自动绑定。

长连接检查额外发现并修复了初始化后的Token轮换：HTTP请求前重新解析凭据，变化时重连并使用新header，未变化不重连。同一Driver的HTTP请求用局部锁避免刷新与调用交错；STDIO路径不变。真实HTTP smoke与最终run14均通过，最后限定复核见`runtime-refresh-review.md`。

## 原数据与未完成部署事项

- 原6项MCP仍使用Legacy来源，未静默导入。只读预览6项所有者映射、引用与冲突检查通过；`migration-preview.json`保留每文件哈希。
- 原MCP数据的解密演练、导入器最终映射等价性、正式导入和原服务切换仍未执行，不能把结构预览当迁移验收。必须先准备具体导入/恢复步骤，再依用户AGENTS.md的数据操作确认规则申请正式写入。
- 本轮不宣称已在真实商业OAuth供应商或原6项MCP服务完成授权/调用。
- 真实PG专用pytest曾在Windows asyncio清理阶段输出access violation诊断但返回0；保留原日志，不称输出干净。最终浏览器独立进程完整通过。
- 原集成32项通过，但日志保留测试子程序WinError2诊断；生产构建保留既有大chunk警告。
- Task1初始只有事前哈希，未保存完整字节；无法重建原始脏工作树精确diff。后续每轮fix及root runtime交接有精确before/diff，最终交付哈希见`delivery-sha256.json`。
- 未提交Git、建分支、清理历史数据或更换原主密钥。
- 原服务仍为127.0.0.1:18089 / PID60212；最终保真检查为2026-09-07 00:07（Asia/Shanghai），未发现文件或表哈希变化。
