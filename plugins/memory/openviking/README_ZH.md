# OpenViking 记忆插件

[English](README.md)

这个插件通过 OpenViking REST API 将 QwenPaw 连接到独立部署的
[OpenViking](https://github.com/volcengine/OpenViking) 服务。它会在模型调用前
召回相关长期记忆，在一轮用户/助手对话完成后提交可处理的消息，并提供受治理的
`memory_search` 工具。

## 信任与安全边界

- Tenant API Key 由部署者配置，作为插件密钥字段保存；客户端错误和插件日志不会
  直接输出服务端响应正文，因此不会因为服务端回显而泄露密钥。
- 所有 OpenViking 请求均禁用 HTTP 重定向。
- `memory_search` 被登记为网络工具；严格治理策略可要求在它发送远程查询前确认。
- OpenViking 返回的是历史资料，并不是可信指令。自动召回和显式搜索都会加上本地
  固定提示，要求模型不要执行检索内容内的指令。
- QwenPaw 将 OpenViking 身份、安装实例 ID、Agent ID 与 QwenPaw 对话 ID 哈希为
  OpenViking Session ID。这用于隔离会话，不构成权限控制边界。

## 安装

先构建插件前端：

```bash
cd plugins/memory/openviking/frontend
npm install
npm run build
cd ../../../../
```

再安装本地插件：

```bash
qwenpaw plugin install plugins/memory/openviking
```

重新安装已修改的插件时使用 `--force`。宿主 QwenPaw 版本需满足
`plugin.json` 所声明的插件 API 版本。

## 配置 Agent

在 Console 的长期记忆后端中选择 **OpenViking**，填写：

- **Server Endpoint**：QwenPaw 进程可访问的 OpenViking URL。本机原生运行通常
  是 `http://127.0.0.1:1933`；Docker Compose 中通常是
  `http://openviking:1933`。
- **Tenant API Key**：在 OpenViking 中为目标 account/user 创建的 Key。它是必填
  项，并会以密码框显示。
- **Request Timeout**：1–300 秒。
- **Automatic Recall Token Budget**：64–32,000 个估算 token。该值限制完整的自动
  召回消息，包含安全提示本身。
- **Commit Policy**：`auto` 交由 OpenViking 的服务端策略提交；`every_turn` 在每个
  成功写入的对话轮次后请求提交。
- **Auto Memory Search**：开关自动召回，并设置 1–20 个候选结果。

保存配置后，QwenPaw 会通过正常的插件生命周期重建该 Agent 的记忆后端，不需要
整体重启进程。配置会保存到
`running.memory_backend_configs.openviking`，不要把真实 Key 写入示例文件或提交
到 Git。

## 验证

1. 为一个 Agent 配置插件，在一个对话中写入不敏感且有辨识度的信息。
2. 新建该 Agent 的另一对话，询问该信息，确认自动召回提供了相关上下文。
3. 请求 Agent 使用 `memory_search`；严格治理策略下，它应被识别为需要确认的网络
   工具。

插件单元测试使用 `httpx.MockTransport` 和 `AsyncMock`，不需要真实 OpenViking
服务或真实密钥。

## 提交失败后的重试

`every_turn` 模式下，如果服务端已经成功接收消息、但随后的提交请求失败，下一次
生命周期调用只会重试提交，不会再次追加这批“已知成功”的消息。OpenViking v0.4.x
未声明可用于“追加请求中断、无法确认服务端是否收到”的幂等键协议；这种不确定交付
场景仍取决于服务端 API 后续提供的保证。
