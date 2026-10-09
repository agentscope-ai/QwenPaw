# QwenPaw 社区登录：复用现有 CLI client

按用户最新确认，使用 `client_id=agentscope-platform-cli`、`scope=platform:control`。无需修改 Java，也无需新增后端 client。平台通用权限不等于社区只读权限，授权页保留完整权限说明。

## 改动

- QwenPaw 默认复用现有 client，自行发起 PKCE 授权并保存凭据，不读取 CLI 的现有凭据。
- 登录链接增加 `source=qwenpaw-community`，平台前端仅用它选择“QwenPaw 社区”中英文文案。登录回跳保留来源，Java 授权请求体不传此参数。
- 原 client ID、scope、PKCE 与回调校验规则保持不变；未知 client 仍被拒绝，普通 CLI 仍显示原文案。
- 已撤回上一版新增的 Java 属性、授权逻辑与测试；后端工作副本 `git status --short` 为空。旧 backend.patch 已移除。

## 前端交付

[frontend.patch](frontend.patch) 基于 agentscope-platform-front master `aa58cd13cdf9f3984311d22568b7d414933f3c61`。工作副本为 `/tmp/qwenpaw-platform-front-audit`，补丁保存在本目录。QwenPaw 改动直接位于当前 asp-dev 工作区。

在前端基线上先执行 `git apply --check <frontend.patch 的绝对路径>`，再应用补丁。

```sh
node --test tests/oauth-clients.test.mjs
npm run build
```

部署平台前端后显示社区文案；未部署时仍可按既有 CLI 页面完成授权。后端无需部署。消息同步能力默认启用；在 QwenPaw 社区设置中选择是否同步及消息类型。部署者可显式设置 `QWENPAW_COMMUNITY_MESSAGES_ENABLED=false` 关闭该能力。

本轮验证：29 条 QwenPaw 社区连接测试通过；Python 适用 pre-commit 检查通过；6 条平台前端协议测试通过；TypeScript 和完整前端构建通过（1 分 21 秒）；前端补丁在干净基线通过应用检查。尚未推送或部署；真实账号授权结果见下方最新验收。

## 直接调用 platform-cli 使用的授权接口

根据官方仓库 commit `1f34df47039801eaae11af3e6dd2b50c0c2f39d8` 的 [browser-login.ts](https://github.com/agentscope-ai/platform-cli/blob/1f34df47039801eaae11af3e6dd2b50c0c2f39d8/src/auth/browser-login.ts)、[session.ts](https://github.com/agentscope-ai/platform-cli/blob/1f34df47039801eaae11af3e6dd2b50c0c2f39d8/src/auth/session.ts) 与 [cli-api.ts](https://github.com/agentscope-ai/platform-cli/blob/1f34df47039801eaae11af3e6dd2b50c0c2f39d8/src/api/cli-api.ts) 对齐 HTTP 协议：

1. 浏览器访问 `/cli/login` 完成 PKCE 授权；这是网页路由，不是 CLI 命令。
2. QwenPaw 直接 POST `/api/cli/v1/oauth/token` 交换授权码。
3. 按 `finalizeLogin` 逻辑，有 refresh token 时先 POST `/api/cli/v1/auth/refresh`，再 GET `/api/cli/v1/me`。刷新请求失败时回退原 token，但必须通过 `/me` 校验才能建立连接。
4. 后续刷新与解绑使用 `/api/cli/v1/auth/refresh`、`/api/cli/v1/oauth/revoke`。

运行时不安装、启动或调用 `asp` / `platform-cli` 可执行程序，不读取其凭据文件；平台 Java 保持无改动。`client_id=agentscope-platform-cli` 是协议中既有的客户端标识，不代表调用 CLI 程序。新增登录后刷新、刷新失败回退和无 refresh token 分支验证，社区连接测试最新 32 条通过（2.33 秒）。

## 真实账号授权与同步验收（2026-09-09）

用户明确确认授权后，已在生产平台网页完成 PKCE 授权，本地 QwenPaw 返回 `connected=true`；通过直接 HTTP 接口完成授权码交换、登录后刷新与 `/me` 账号验证，没有执行 CLI 命令或修改 Java。

在本次 localhost:18891 测试实例启用消息同步，首次同步返回 `inserted=32`、`catching_up=false`；原生收件箱共 32 条唯一消息，其中回复 27 条、提及 1 条、资源反馈 4 条。再次同步返回 `inserted=0`，没有重复项；`last_error=null`。此次远端已有消息均为已读，不将其算作真实新增未读通知测试。

真实浏览器已确认社区设置显示账号与开启的同步开关，收件箱列表和详情可查看，点击“查看讨论”打开对应社区文章。授权后的浏览器回跳页出现 `ERR_BLOCKED_BY_CLIENT`，但本地流程状态为 completed、账号验证成功；未绕过浏览器拦截。凭据仅保存在该本地测试实例中，文档不包含 token 或消息正文。

本次不包含真实发帖、删除远端通知、第二账号切换、Hub 远程授权或原生桌面回跳验收；未提交、推送或部署代码。同步目前保留开启，可在社区设置中暂停或解除连接。
