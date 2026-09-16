# Task 11.5 Agent 可移植导出/导入验收记录

## 结论

Task 11.5 已完成技术验收，等待用户确认。Agent owner 现在可以导出不含有效 Secret 的可移植包；导入始终创建当前用户所有的新草稿，并要求重新授权外部依赖。

## 实现范围

- 新增版本化 `qwenpaw-agent` ZIP 格式，包含 `manifest.json`、脱敏后的 `config/agent.json` 和 `workspace/` 文件。
- 依赖清单记录模型、私有技能、MCP 客户端和频道名称，便于导入后逐项重新授权。
- 递归移除 API key、token、password、credential、cookie、authorization、private key、headers 等敏感字段；MCP 参数、环境变量和 OAuth 状态全部清空。
- 排除 `agent.json`、凭据文件、`.env`、证书/密钥文件、会话、定时任务、媒体、浏览器资料、检查点和内部运行目录；不跟随符号链接。
- ZIP 导入在内存中校验路径穿越、单文件 16 MiB、总展开 64 MiB 和最多 4096 个条目。
- owner 才能调用导出 API；collaborator/user 服务端返回 403，页面不展示导出按钮。
- 导入生成新 Agent ID，注册当前用户为 owner，保存为 `draft`/disabled；清除源 ID、workspace、project、投递身份和显式模型绑定，频道与 MCP 保持禁用。

## 验证证据

- 后端 Agent 路由与隔离组合：`47 passed`。
- 前端 API、Agent 表格和页面组合：`28 passed`。
- TypeScript `tsc -b --noEmit` 通过；目标文件 Prettier 通过。
- 生产构建完成 18,889 个模块，Monaco CSS 校验通过；仅有仓库既有 chunk 提示。
- 真实多用户 API：owner 导出 200，非 owner 导出 403；导入结果为新 ID、当前用户 owner、`draft`/disabled。

## 页面验收与数据影响

- 普通用户 `task42-user` 的“我的”分组显示“导出智能体包”，并提示包不包含有效凭据。
- 浏览器通过隐藏文件输入导入导出的 ZIP，请求返回 201；列表新增“已禁用”的 owner Agent，模型显示“使用全局默认”。
- “可使用”分组的四个非 owner Agent 均不显示导出按钮。
- 截图：`tmp/task-11-5-portable-imported.png`、`tmp/task-11-5-non-owner-no-export.png`。
- API 和浏览器创建的两个验收草稿已软删除；浏览器已关闭。18089 当前 PID `64004`。

## 下一确认门

用户确认后进入 Task 11.6「管理员日志与用户诊断」。完成本项后，分阶段计划还剩 5 项：11.6 和 12.1–12.4。
