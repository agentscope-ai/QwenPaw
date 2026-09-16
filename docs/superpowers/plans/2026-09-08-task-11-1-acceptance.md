# Task 11.1 部署环境变量不可回读验收记录

## 结论

Task 11.1 已完成技术验收，等待用户确认。部署环境变量只允许管理员管理，已保存值无法通过 API 或页面回读；增量更新采用显式 `keep / replace / delete` 语义，不再使用缺键即删除的整表替换。

## 实现范围

- 后端新增 `platform.settings.manage` capability，并在 `/api/envs` 路由统一执行服务端管理员授权。
- `GET /api/envs` 和所有写入响应只返回 `key` 与 `configured`。
- `PUT /api/envs` 接收显式操作数组，拒绝重复键、非法键和携带歧义字段的操作；未提及的键保持不变。
- 前端已保存行从空值开始编辑，仅显示 `********` 占位符，不提供查看旧值按钮；只有实际编辑时才发送 `replace`。
- 页面明确提示此处只管理部署级环境变量，Agent Secret、工具和 MCP 凭据在各自配置页面维护。

## 自动化证据

- 后端：`25 passed`，覆盖管理员/普通用户权限、明文不可回读、keep/replace/delete、即时进程环境同步和原集成行为。
- 前端：`9 passed`，覆盖 API DTO、保存值占位、无查看控件、空值显式替换与 capability。
- `npx tsc -b --noEmit`：通过。
- `uvx ruff check --select E9,F63,F7,F82 ...`：通过。
- `git diff --check ...`：通过。
- `npm run build:prod`：通过，Vite 完成 18,889 个模块构建，Monaco CSS 校验通过；仅有仓库既有的 chunk 体积和动态/静态导入提示。

## 浏览器与部署证据

- 验收地址：`http://127.0.0.1:18089`，多用户模式，当前 PID `70036`。
- 管理员页面完成 `TASK111_WRITE_ONLY` 新增和替换；每次保存后输入框为空，仅显示 `********`，页面无旧值查看按钮。
- 网络记录显示新增与替换均使用 `operations:[{action:"replace"}]`；对应响应长度均为 48 字节，仅包含键名和配置状态。
- 管理员已通过显式删除操作清理临时键，隔离验收 Secret Store 最终为 `{}`。
- 普通用户 `task42-user` 的设置菜单没有环境变量入口；携带其有效令牌直接请求 `GET /api/envs` 返回 `403 {"detail":"forbidden"}`。
- 页面截图：`tmp/task111-admin-write-only.png`。

## 数据影响

没有数据库结构迁移。浏览器写入仅发生在 `tmp/task-2-1-acceptance/working.secret` 隔离验收目录，临时键已删除；用户默认 Secret Store `C:/Users/nidi/.qwenpaw.secret/envs.json` 未被本次页面验收读写。

## 下一确认门

用户确认 Task 11.1 后进入 Task 11.2「工具后台默认策略」。
