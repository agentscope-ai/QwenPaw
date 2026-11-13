# OpenViking 记忆插件

[English](README.md)

这个插件通过 OpenViking REST API 将 QwenPaw 连接到独立部署的
[OpenViking](https://github.com/volcengine/OpenViking) 服务。

启用自动召回后，插件
会在模型调用前检索相关长期记忆。每轮用户/助手对话完成后，后台队列将尚未获得
OpenViking 写入确认的消息追加到远端会话。提交策略为 `every_turn` 时，插件在
每轮追加成功后请求提交；为 `auto` 时，由 OpenViking 服务端执行插件预设的自动
提交策略。

提交会归档消息并触发后台记忆提取，因此消息追加成功或提交请求成功，不代表记忆
提取已经完成。插件还提供受治理的 `memory_search` 工具。

## 信任与安全边界

- Tenant API Key 由部署者配置，作为插件密钥字段保存；客户端错误和插件日志不会
  直接输出服务端响应正文，因此不会因为服务端回显而泄露密钥。
- 所有 OpenViking 请求均禁用 HTTP 重定向。
- `memory_search` 被登记为网络工具；严格治理策略可要求在它发送远程查询前确认。
- OpenViking 返回的是历史资料，并不是可信指令。自动召回和显式搜索都会加上本地
  固定提示，要求模型不要执行检索内容内的指令。
- QwenPaw 将 OpenViking 身份、安装实例 ID、Agent ID 与 QwenPaw 对话 ID 哈希为
  OpenViking Session ID。这用于隔离会话，不构成权限控制边界。

## 准备 OpenViking 服务

插件需要连接一个已独立部署、能够正常抽取和检索记忆的 OpenViking 服务。插件
本身不负责部署 OpenViking，也不负责配置它使用的模型。

1. 如果自行部署，请参考
   [OpenViking 配置指南](https://github.com/volcengine/OpenViking/blob/main/docs/en/guides/01-configuration.md)，
   在 OpenViking 服务端配置向量模型、向量维度，以及用于记忆抽取的 VLM/LLM。
   确认模型平台凭据、访问权限和额度可用。
2. 启动服务，取得 QwenPaw 能访问的服务 URL，以及目标 account/user 的
   OpenViking 用户 API Key，分别填入插件的 **Server Endpoint** 和
   **Tenant API Key**。
3. 验证真实的记忆抽取和检索。仅 `/health` 返回成功，并不能证明服务端配置的
   模型能够正常调用。

两种 Key 的用途不同：

- **模型平台 API Key**：在 OpenViking 服务端配置，用于调用向量模型和记忆抽取
  模型，具体是否需要取决于模型提供方。
- **OpenViking 用户 API Key**：填写在本插件中，用于验证访问 OpenViking 的
  用户身份。不要在此处填写模型平台 Key。

如果连接的是他人管理的服务，模型配置由服务管理员完成；使用者只需要取得服务
URL 和 OpenViking 用户 Key。

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
- **Tenant API Key**：在 OpenViking 中为目标 account/user 创建的用户 Key，
  不是模型平台 Key。它是必填项，并会以密码框显示。
- **Request Timeout**：1–300 秒。
- **Automatic Recall Token Budget**：64–32,000 个估算 token。该值限制完整的自动
  召回消息，包含安全提示本身。
- **Commit Policy**：`auto` 由 OpenViking 执行插件预设策略；`every_turn` 在每个
  成功写入的对话轮次后请求提交。
- **Auto Memory Search**：开关自动召回，并设置 1–20 个候选结果。

`auto` 预设的消息数量阈值为 20，按该阈值触发提交时保留最近4条消息；这里的
数量均指消息条数，不是对话轮数。预设还包含 300 秒空闲超时和 60 秒最小自动
提交间隔，空闲调度需要服务端启用。空闲超时提交的保留行为可能不同，见下文对
v0.5.2.1 的说明。这些策略参数暂不支持通过 Console 修改。

保存配置后，QwenPaw 会通过正常的插件生命周期重建该 Agent 的记忆后端，不需要
整体重启进程。配置会保存到
`running.memory_backend_configs.openviking`，不要把真实 Key 写入示例文件.

### 启用基于会话的查询扩展

查询扩展会利用当前会话的近期对话，补全搜索问题中省略的信息，例如“它的设备
编号”中的项目名称。插件目前在请求中固定发送 `query_expansion="off"`。前端的
`auto` 提交策略决定何时归档消息，不是查询扩展开关。查询扩展不能通过前端或
Agent 配置开启，下述步骤需要修改源码。关闭查询扩展时，普通长期记忆召回仍可
正常工作。

如需启用，在 [backend/client.py](backend/client.py) 的
`OpenVikingClient.search_context()` 请求 JSON 中，将
`"query_expansion": "off"` 改为 `"query_expansion": "auto"`，其他请求字段保持
原样。使用 `--force` 重新安装修改后的插件，并重新加载 Agent。
使用镜像部署时，需要从修改后的源码
重新构建并重新创建 QwenPaw 容器；仅重启原镜像不会更新代码。恢复为 `"off"`
并按相同步骤重新部署，即可关闭查询扩展。

查询扩展已在 OpenViking v0.5.2.1、`commit_policy="auto"` 下完成验证：追问可以
利用会话历史补全项目名，并跟随项目切换；消息数量触发自动提交、保留近期消息后，
召回仍可正常工作。新会话未借用旧会话历史进行扩展，但用户的长期记忆库仍在不同
会话之间共享。

扩展需要可用的会话消息或归档摘要。在本次验证的 v0.5.2.1 行为中，按消息数量
触发的自动提交按照插件策略保留四条消息，但空闲超时提交会清空当前消息。
插件的 `every_turn` 提交请求也不保留消息。如果没有归档摘要，清空后扩展会退回
原问题检索。这里不宣称其他版本已经通过查询扩展的真实服务验证。验证时应检查
响应中的 `stats.query_expansion` 和 `stats.planned_queries`；`"used"` 只表示
执行过分析，不保证一定新增查询。


## 提交失败后的重试

同一个后台任务会保留待写入的消息批次，对服务错误最多尝试三次，两次重试前分别
等待 1 秒和 2 秒；配置错误不重试。重试期间，宿主任务状态仍为 `running`，成功后
变为 `completed`，重试耗尽后变为 `failed`。关闭时的取消信号正常向上传递。插件
没有持久化队列，重试耗尽或进程重启后不会自动在之后再次尝试。

`every_turn` 模式下，如果追加已确认成功、但随后的提交请求失败，Manager 会保留
待提交消息 ID，重试只提交，不重复追加这些消息。如果服务端已经接收追加、但响应
丢失，重试仍可能重复追加；这不是 exactly-once 保证。提交请求成功也不代表后台
记忆提取已经完成。

## 资源限制

显式搜索将每条格式化结果限制为 2,048 个 UTF-8 字节，完整返回文本限制为 8,192
个 UTF-8 字节。总预算包含完整安全提示、分隔符和裁剪标记。这是返回文本的限制，
不是 HTTP 响应大小限制，也不是精确的 token 预算。

上述上限是插件源码中的固定常量，暂不提供 Console 或 Agent 配置项。

Manager 最多缓存 256 个最近使用的已准备会话，以及 10,000 个最近记录的已完成
消息 ID。淘汰会话缓存只会让该会话下次重新准备，不会删除远端数据。淘汰已完成
消息 ID 后，该旧消息不再受到本地去重保护，重新提交时可能再次追加。待 commit
的 ID 不参与上述缓存淘汰，在 commit 成功后才移除，也不保留空的 pending 条目。
这些缓存限制并没有给所有未完成任务设置全局硬上限。上述进度记录都只保存在内存
中，Manager 重建后会重置。
