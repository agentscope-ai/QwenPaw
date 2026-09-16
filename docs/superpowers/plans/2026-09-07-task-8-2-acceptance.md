# Task 8.2 Agent 工具配置与运行验收记录

状态：实现、自动化回归、独立 PostgreSQL 与真实 Chrome 技术验收通过；用户已于 2026-09-07 确认，并授权进入 Task 8.3。未启用原环境 Browser，未迁移原工具 Secret。

## 交付行为

- owner、collaborator 可以启停工具、修改异步执行和配置；user 页面只读，服务端写请求返回 403。
- 密码字段改为 `keep / replace / delete`；读取接口只返回 `credential_status`，明文保存在 Agent 范围的 PostgreSQL Credential Binding，Agent 文件只保存非敏感字段。
- Agent 启动或重载时从绑定重新装载运行凭据；插件同步读取只合并进程内缓存，不把密码写回文件。
- 多用户 Browser 默认由平台锁定。只有平台显式许可时才强制使用 managed Chromium、guest、incognito、headless；外部 CDP、真实 Chrome profile 和自定义可执行文件均被覆盖。
- Browser 会话按实际用户和工作区限流，默认全局 2、每用户 1；聊天关闭、工作区关闭和空闲超时释放资源。Agent 工具页不能修改平台 Browser 策略。
- 单用户模式保留原 Browser 实验开关和现有行为；工具列表、批量开关、后台执行按钮与 ToolCards 协议未改名。

## 验证结果

| 范围 | 结果 |
| --- | --- |
| 后端权限、DTO、Credential、Browser、Agent 路由与 MCP 回归 | 50 passed，1 skipped；跳过项是未注入 PG fixture 的普通运行 |
| 独立 PostgreSQL Credential Store | 8 passed；真实创建、解析、作用域与绑定撤销通过 |
| 前端 Tools API、Hook、凭据动作 | 3 files / 23 tests passed |
| 后台工具生命周期与 ToolCards | 后端 50 passed；前端 3 files / 18 tests passed |
| TypeScript | `npx tsc -b --noEmit` 通过 |
| 生产构建 | `npm run build` 通过；Monaco CSS 校验通过，保留既有 chunk 警告 |
| 格式与语法 | 本次前端文件 Prettier 通过，Python compileall 与限定 diff check 通过 |
| 真实 Chrome + 独立 PG | 4 个合成账号、1 个隔离密码工具、9 项检查通过 |
| Secret 扫描 | 验收输出目录没有合成工具 Secret 命中 |
| 原环境保真 | 25 个文件、9 张表哈希无变化，schema revision 不变；18089 仍由 PID 60212 监听 |

真实浏览器证据位于 `tmp/task82-browser-20260907-013011/`：

- `acceptance.json`：9 项检查与隔离 schema 已删除记录。
- `browser-policy-locked.png`：owner 工具页显示 Browser“平台策略已关闭”。
- `user-read-only.png`：user 工具页无批量写入口。
- `app.log`：隔离服务 API 与热重载日志，不包含合成工具 Secret。

真实页面曾发现只读标题显示翻译键、首次选择 Agent 前发出无作用域请求两个问题；补齐公共文案并延迟到 Agent 已选中后加载，最终截图和日志确认标题正常且没有 Tools 403 加载错误。

独立 PG pytest 在 Windows asyncio 清理线程中仍输出既有 access violation 诊断，但进程返回 0 且 8 项测试通过；本记录保留该诊断，不称日志干净。

## 前端验收步骤

1. 以 owner 打开“工作区 → 工具”，确认 Browser 位于“可用”区并显示“平台策略已关闭”，不可点击；批量开关不会把它启用。
2. 找一个普通工具，执行启用/禁用；对 `execute_shell_command` 或 `delegate_external_agent` 切换异步执行，刷新后状态保持。
3. 打开已安装且含 API Key 的工具配置。确认密码项先显示动作选择，不出现旧密码或 `***`；分别验证“保留”“替换”“删除”。刷新后只显示“已配置/未配置”。
4. 以 collaborator 重复普通工具启停和配置，确认可写。
5. 以 user 打开同一 Agent 的工具页，确认页面只读且没有批量开关、配置或禁用按钮。

平台许可 Browser 属于管理员部署设置。若以后启用，服务按需启动无头 Chromium 会话，不会为每个登录用户常驻打开一个可见浏览器；建议先保留默认关闭，仅在确有网页自动化需求时设置容量后启用。

## 未改变的生产状态

- 原 18089 服务未重启，Browser 平台策略未切换。
- 原工具配置、原 Secret、原 MCP 数据未迁移或重写。
- 没有执行 git commit、push、reset、建分支或清理工作区。
