# 频道配置

**频道** = 你和 CoPaw 在「哪里」对话：接钉钉就在钉钉里回，接 QQ 就在 QQ 里回。不熟悉这个词的话可以先看 [项目介绍](./intro)。

配置频道有两种方式：

- **控制台**（推荐）— 在 [控制台](./console) 的 **Control → Channels** 页面，点击频道卡片，在抽屉里启用并填写鉴权信息，保存即生效。
- **手动编辑 `config.json`** — 默认在 `~/.copaw/config.json` （由 `copaw init` 生成），将需要的频道设 `enabled: true` 并填好鉴权信息；保存后自动重载，无需重启。

所有频道都有如下通用字段:

- **enabled** — 是否启用
- **bot_prefix** — 机器人回复前缀（如 `[BOT]`），方便区分
- **filter_tool_messages** — （可选，默认 `false`）过滤工具调用和输出消息，不发送给用户。设为 `true` 可隐藏工具执行详情。
- **filter_thinking** — （可选，默认 `false`）过滤模型的思考/推理内容，不发送给用户。设为 `true` 可隐藏 thinking 内容。
- **dm_policy** — （可选，默认 `"open"`）私聊访问策略。`"open"` 允许所有用户；`"allowlist"` 仅允许 `allow_from` 中的用户。
- **group_policy** — （可选，默认 `"open"`）群聊访问策略。`"open"` 允许所有用户；`"allowlist"` 仅允许 `allow_from` 中的用户。
- **allow_from** — （可选，默认 `[]`）允许与机器人交互的用户 ID 列表。仅当 `dm_policy` 或 `group_policy` 设为 `"allowlist"` 时生效。
- **deny_message** — （可选，默认 `""`）被白名单拒绝的用户收到的自动回复消息。留空则不回复。
- **require_mention** — （可选，默认 `false`）设为 `true` 时，机器人在群聊中仅响应被 @提及 的消息。白名单检查（`allow_from`）优先执行，通过后再检查是否被提及。

下面按频道说明如何获取凭证并填写配置。

---

## 钉钉（推荐）

### 创建钉钉应用

视频操作流程：

![视频操作流程](https://cloud.video.taobao.com/vod/Fs7JecGIcHdL-np4AS7cXaLoywTDNj7BpiO7_Hb2_cA.mp4)

图文操作流程：

1. 打开 [钉钉开发者后台](https://open-dev.dingtalk.com/)

2. 进入"应用开发→企业内部应用→钉钉应用→创建 **应用**"

   ![钉钉开发者后台](https://img.alicdn.com/imgextra/i1/O1CN01KLtwvu1rt9weVn8in_!!6000000005688-2-tps-2809-1585.png)

3. 在"应用能力→添加应用能力"中添加 **「机器人」**

   ![添加机器人](https://img.alicdn.com/imgextra/i2/O1CN01AboPsn1XGQ84utCG8_!!6000000002896-2-tps-2814-1581.png)

4. 配置机器人基础信息，设置消息接收模式为 **Stream 模式**（流式接收），点击发布

   ![机器人基础信息](https://img.alicdn.com/imgextra/i3/O1CN01KwmNZ61GwhDhKxgSv_!!6000000000687-2-tps-2814-1581.png)

   ![Stream模式+发布](https://img.alicdn.com/imgextra/i2/O1CN01tk8QW11NqvXYqcoPH_!!6000000001622-2-tps-2809-1590.png)

5. 在"应用发布→版本管理与发布"中创建新版本，填写基础信息后保存

   ![创建新版本](https://img.alicdn.com/imgextra/i3/O1CN01lRCPuf1PQwIeFL4AL_!!6000000001836-2-tps-2818-1590.png)

   ![保存](https://img.alicdn.com/imgextra/i1/O1CN01vrzbIA1Qey2x8Jbua_!!6000000002002-2-tps-2809-1585.png)

6. 在"基础信息→凭证与基础信息"中获取：

   - **Client ID**（即 AppKey）
   - **Client Secret**（即 AppSecret）

   ![client](https://img.alicdn.com/imgextra/i3/O1CN01JsRrwx1hJImLfM7O1_!!6000000004256-2-tps-2809-1585.png)

7. （可选） **将服务器 IP 加入白名单** — 调用钉钉开放平台 API（如下载用户发送的图片和文件）时需要此配置。在应用设置中进入 **"安全设置→服务器出口 IP"**，添加运行 CoPaw 的机器的公网 IP。可在终端执行 `curl ifconfig.me` 查看公网 IP。若未配置白名单，图片和文件下载将报 `Forbidden.AccessDenied.IpNotInWhiteList` 错误。

### 绑定应用

可以在console前端配置，或者修改`~/.copaw/config.json`。

**方法1**: 在console前端配置

从“控制→频道”找到**DingTalk**，点击后填入刚刚获取的**Client ID**和**Client Secret**

![console](https://img.alicdn.com/imgextra/i1/O1CN01uXrlyQ25Zpr5eVksk_!!6000000007541-2-tps-3451-1778.png)

**方法2**: 修改`~/.copaw/config.json`

在 `config.json` 里找到 `channels.dingtalk`，填入对应信息，例如：

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "你的 Client ID",
  "client_secret": "你的 Client Secret",
  "message_type": "markdown",
  "card_template_id": "",
  "card_template_key": "content",
  "robot_code": "",
  "filter_tool_messages": false
}
```

- 若希望隐藏工具执行详情，可设置 `filter_tool_messages: true`。
- AI Card 模式：将 `message_type` 设为 `card`，并填写 `card_template_id`；`card_template_key` 必须与钉钉模板变量名完全一致（默认 `content`）。
- 群聊场景建议显式配置 `robot_code`；留空时 CoPaw 会回退使用 `client_id`。

保存后若服务已运行会自动重载；未运行则执行 `copaw app` 启动。

### 找到创建的应用

视频操作流程：

![视频操作流程](https://cloud.video.taobao.com/vod/e0icQREdiZ1LI0b1mWdBDQI94KdJSaJxO09X5BPaWvk.mp4)

图文操作流程：

1. 点击钉钉【消息】栏的“搜索框”

![机器人名称](https://img.alicdn.com/imgextra/i4/O1CN019tRcAi1IIy630Kttu_!!6000000000871-2-tps-2809-2241.png)

2. 搜索刚刚创建的 “机器人名称”，在【功能】下找到机器人

![机器人](https://img.alicdn.com/imgextra/i3/O1CN01Ha69lm23sx9kLX8eD_!!6000000007312-2-tps-2809-2236.png)

3. 点击后进入对话框

![对话框](https://img.alicdn.com/imgextra/i1/O1CN01zjnc7J23hxeOJGYiO_!!6000000007288-2-tps-2046-1630.png)

> 注：可以在钉钉群中通过**群设置→机器人→添加机器人**将机器人添加到群聊。需要注意的是，从与机器人的单聊界面中创建群聊，会无法触发机器人的回复。

---

## 飞书

飞书频道通过 **WebSocket 长连接** 接收消息，无需公网 IP 或 webhook；发送走飞书开放平台 Open API。支持文本、图片、文件收发；群聊场景下会将 `chat_id`、`message_id` 放入请求消息的 metadata，便于下游去重与群上下文识别。

### 创建飞书应用并获取凭证

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，创建企业自建应用

![飞书](https://img.alicdn.com/imgextra/i1/O1CN01awX3Nc1WjRc43kDSk_!!6000000002824-2-tps-4082-2126.png)

![build](https://img.alicdn.com/imgextra/i3/O1CN01OXSFsM1EDh4Xa2aOz_!!6000000000318-2-tps-4082-2126.png)

2. 在「凭证与基础信息」中获取 **App ID**、**App Secret**

![id & secret](https://img.alicdn.com/imgextra/i2/O1CN01tWGGEE1PAuR7APQcs_!!6000000001801-2-tps-4082-2126.png)

3. 在 `config.json` 中填写上述 **App ID** 和 **App Secret**（见下方「填写 config.json」），保存

4. 执行 **`copaw app`** 启动 CoPAW 服务

5. 回到飞书开放平台，在「能力」中启用 **机器人**

![bot](https://img.alicdn.com/imgextra/i1/O1CN01eFPe0d1wU2IY4Fyvt_!!6000000006310-2-tps-4082-2126.png)

6. 选择「权限管理」中的「批量导入/导出权限」，将以下JSON代码复制进去

```json
{
  "scopes": {
    "tenant": [
      "aily:file:read",
      "aily:file:write",
      "aily:message:read",
      "aily:message:write",
      "corehr:file:download",
      "im:chat",
      "im:message",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:message.reactions:read",
      "im:resource",
      "contact:user.base:readonly"
    ],
    "user": []
  }
}
```

![in/out](https://img.alicdn.com/imgextra/i4/O1CN01CpUMJn1ey7E6FIpOU_!!6000000003939-2-tps-4082-2126.png)

![json](https://img.alicdn.com/imgextra/i3/O1CN01idxezh1G04WY9SYZR_!!6000000000559-2-tps-4082-2126.png)

![confirm](https://img.alicdn.com/imgextra/i3/O1CN017nCNTC1Lj1TVH1OIt_!!6000000001334-2-tps-4082-2126.png)

![confirm](https://img.alicdn.com/imgextra/i3/O1CN01hwOxur1EV67a7clee_!!6000000000356-2-tps-4082-2126.png)

7. 在「事件与回调」中，点击「事件配置」，选择订阅方式为**长连接（WebSocket）** 模式（无需公网 IP）

> 注：**操作顺序**为先配置 App ID/Secret → 启动 `copaw app` → 再在开放平台配置长连接，如果此处仍显示错误，尝试先暂停 CoPaw 服务并重新启动 `copaw app`。

![websocket](https://img.alicdn.com/imgextra/i2/O1CN01LQwKON1x7QMNP41kC_!!6000000006396-2-tps-4082-2126.png)

8. 选择「添加事件」，搜索**接收消息**，订阅**接收消息 v2.0**

![reveive](https://img.alicdn.com/imgextra/i3/O1CN01svBdl41HTDLCtKFed_!!6000000000758-2-tps-4082-2126.png)

![click](https://img.alicdn.com/imgextra/i4/O1CN01Rat93U1sLYV9f5dhe_!!6000000005750-2-tps-4082-2126.png)

![result](https://img.alicdn.com/imgextra/i2/O1CN015GPfGr1BsxuoOXbYC_!!6000000000002-2-tps-4082-2126.png)

9. 在「应用发布」的「版本管理与发布」中，**创建版本**，填写基础信息，**保存**并**发布**

![create](https://img.alicdn.com/imgextra/i1/O1CN01zOqMGk1lhoREn9Lip_!!6000000004851-2-tps-4082-2126.png)

![info](https://img.alicdn.com/imgextra/i1/O1CN01SQg28h1nAUrLKTH1J_!!6000000005049-2-tps-4082-2126.png)

![save](https://img.alicdn.com/imgextra/i1/O1CN01ebVPlq1lzDUM1Mwej_!!6000000004889-2-tps-4082-2126.png)

### 填写 config.json

在`config.json`（默认在 `~/.copaw/config.json`）中找到`channels.feishu`，只需填 **App ID** 和 **App Secret**（在开放平台「凭证与基础信息」里复制）：

```json
"feishu": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "cli_xxxxx",
  "app_secret": "你的 App Secret"
}
```

其他字段（encrypt_key、verification_token、media_dir）可选，WebSocket 模式可不填，有默认值。依赖：`pip install lark-oapi`，然后 `copaw app`。如果你使用 SOCKS 代理联网，还需安装 `python-socks`（例如 `pip install python-socks`），否则可能报错：`python-socks is required to use a SOCKS proxy`。

> 注: **App ID** 和 **App Secret** 信息也可以在Console前端填写，但需重启 CoPaw 服务，才能继续配置长链接的操作。
> ![console](https://img.alicdn.com/imgextra/i2/O1CN01k7UVrP1E2hZBAn0oF_!!6000000000294-2-tps-4082-2126.png)

### 机器人权限建议

第6步中的json文件为应用配备了以下权限（应用身份、已开通），以保证收发消息与文件正常：

| 权限名称                       | 权限标识                       | 权限类型     | 说明           |
| ------------------------------ | ------------------------------ | ------------ | -------------- |
| 获取文件                       | aily:file:read                 | 应用身份     | -              |
| 上传文件                       | aily:file:write                | 应用身份     | -              |
| 获取消息                       | aily:message:read              | 应用身份     | -              |
| 发送消息                       | aily:message:write             | 应用身份     | -              |
| 下载文件                       | corehr:file:download           | 应用身份     | -              |
| 获取与更新群组信息             | im:chat                        | 应用身份     | -              |
| 获取与发送单聊、群组消息       | im:message                     | 应用身份     | -              |
| 获取群组中所有消息（敏感权限） | im:message.group_msg           | 应用身份     | -              |
| 读取用户发给机器人的单聊消息   | im:message.p2p_msg:readonly    | 应用身份     | -              |
| 查看消息表情回复               | im:message.reactions:read      | 应用身份     | -              |
| 获取与上传图片或文件资源       | im:resource                    | 应用身份     | -              |
| **以应用身份读取通讯录**       | **contact:user.base:readonly** | **应用身份** | **见下方说明** |

> **获取用户昵称（推荐）**：若希望会话和日志中显示**用户昵称**（如「张三#1d1a」）而非「unknown#1d1a」，需额外开通通讯录只读权限 **以应用身份读取通讯录**（`contact:user.base:readonly`）。未开通时，飞书仅返回 open_id 等身份字段，不返回姓名，CoPAW 无法解析昵称。开通后需重新发布/更新应用版本，权限生效后即可正常显示用户名称。

### 将机器人添加到常用

1. 在**工作台**点击**添加常用**

![添加常用](https://img.alicdn.com/imgextra/i2/O1CN01bSKw0t1tCgReoZNRr_!!6000000005866-2-tps-2614-1488.png)

2. 搜索刚刚创建的机器人名称并**添加**

![添加](https://img.alicdn.com/imgextra/i1/O1CN01aNNTI51IZSM4TYqis_!!6000000000907-2-tps-3785-2158.png)

3. 可以看到机器人已添加到常用中，双击可进入对话界面

![已添加](https://img.alicdn.com/imgextra/i1/O1CN01Kulh7i1Hfa2Dnfpa4_!!6000000000785-2-tps-2614-1488.png)

![对话界面](https://img.alicdn.com/imgextra/i4/O1CN01vsnwn71UMQTaEa0XX_!!6000000002503-2-tps-2614-1488.png)

---

## iMessage（仅 macOS）

> ⚠️ iMessage 频道仅支持 **macOS**，依赖本地「信息」应用与 iMessage 数据库，无法在 Linux / Windows 上使用。

通过本地 iMessage 数据库轮询新消息并代为回复。

1. 确保本地 **「信息」(Messages)** 已登录 Apple ID（系统设置里打开「信息」并登录）。

2. 安装 **imsg**（用于访问 iMessage 数据库）：

   ```bash
   brew install steipete/tap/imsg
   ```

   > 如果 Intel 芯片 Mac 用户通过上述方式无法安装成功，需要先克隆源码再编译
   >
   > ```bash
   > git clone https://github.com/steipete/imsg.git
   > cd imsg
   > make build
   > sudo cp build/Release/imsg /usr/local/bin/
   > cp ./bin/imsg /usr/local/bin/
   > ```

3. 为了使 iMessage 中的信息能被获取，需要 **终端** （或你用来运行 CoPaw 的 app） 和 **消息** 有 **完全磁盘访问权限**（系统设置 → 隐私与安全性 → 完全磁盘访问权限）。

   ![权限](https://img.alicdn.com/imgextra/i2/O1CN01gCbMWX1S2c77mcoPo_!!6000000002189-2-tps-958-440.png)

4. 填写 iMessage 数据库路径。默认路径为 `~/Library/Messages/chat.db`，若你改过系统路径，请填实际路径。有以下两种填写方案：

   - 进入 **控制台 → 频道**，点击 **iMessage** 卡片，将 **Enable** 开关打开，在 **DB Path**中填写上面的路径，点击 **保存**。

     ![控制台](https://img.alicdn.com/imgextra/i3/O1CN01ut2ooB1mxDNNtz1Qc_!!6000000005020-2-tps-3814-1954.png)

   - 填写 config.json（路径通常为~/.copaw/config.json）：

     ```json
     "imessage": {
     "enabled": true,
     "bot_prefix": "[BOT]",
     "db_path": "~/Library/Messages/chat.db",
     "poll_sec": 1.0
     }
     ```

     **db_path** — iMessage 数据库路径

     **poll_sec** — 轮询间隔（秒），默认 1 即可

5. 填写完成后，使用你的手机，给当前电脑登录的 iMessage 账号（与电脑Apple ID一致）发送任意一条消息，可以看到回复。

   ![聊天](https://img.alicdn.com/imgextra/i4/O1CN01beScxi1rBBvSFeIbz_!!6000000005592-2-tps-1206-2622.png)

---

## Discord

### 获取 Bot Token

1. 打开 [Discord 开发者门户](https://discord.com/developers/applications)

![Discord开发者门户](https://img.alicdn.com/imgextra/i2/O1CN01oV68yZ1sb7y3nGoQN_!!6000000005784-2-tps-4066-2118.png)

2. 新建应用（或选已有应用）

![新建应用](https://img.alicdn.com/imgextra/i2/O1CN01eA9lA71kMukVCWR4y_!!6000000004670-2-tps-3726-1943.png)

3. 左侧进入 **Bot**，新建 Bot，复制 **Token**

![token](https://img.alicdn.com/imgextra/i1/O1CN01iuPiUe1lJzqEiIu23_!!6000000004799-2-tps-2814-1462.png)

4. 下滑，给予 Bot “Message Content Intent” 和 “Send Messages” 的权限，并保存

![权限](https://img.alicdn.com/imgextra/i4/O1CN01EXH4w51FSdbxYKLG9_!!6000000000486-2-tps-4066-2118.png)

5. 在 **OAuth2 → URL 生成器** 里勾选 `bot` 权限，给予 Bot “Send Messages” 的权限，生成邀请链接

![bot](https://img.alicdn.com/imgextra/i2/O1CN01B2oXx71KVS7kjKSEm_!!6000000001169-2-tps-4066-2118.png)

![send messages](https://img.alicdn.com/imgextra/i3/O1CN01DlU9oi1QYYVBPoUIA_!!6000000001988-2-tps-4066-2118.png)

![link](https://img.alicdn.com/imgextra/i2/O1CN01ljhh1j1OZLxb2mAkO_!!6000000001719-2-tps-4066-2118.png)

6. 在浏览器中访问该链接，会自动跳转到discord页面。将 Bot 拉进你的服务器

![服务器](https://img.alicdn.com/imgextra/i1/O1CN01ivgmOA1JuM2i9WNqm_!!6000000001088-2-tps-2806-1824.png)

![服务器](https://img.alicdn.com/imgextra/i2/O1CN01ecRCVa1UeHvFUP0XQ_!!6000000002542-2-tps-2806-1824.png)

7. 在服务器中可以看到 Bot已被拉入

![博天](https://img.alicdn.com/imgextra/i2/O1CN014HOCCJ1fsuL2RQiB5_!!6000000004063-2-tps-2806-1824.png)

### 绑定 Bot

可以在console前端配置，或者修改`~/.copaw/config.json`。

**方法1**: 在console前端配置

从“控制→频道”找到**Discord**，点击后填入刚刚获取的**Bot Token**

![console](https://img.alicdn.com/imgextra/i2/O1CN01kP657n1XK5IXfPLAv_!!6000000002904-2-tps-4082-2126.png)

**方法2**: 修改`~/.copaw/config.json`

在 `config.json` 里找到 `channels.discord`，填入对应信息，例如：

```json
"discord": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "bot_token": "你的 Bot Token",
  "http_proxy": "",
  "http_proxy_auth": ""
}
```

国内网络访问 Discord API 可能需代理。如需代理：

- **http_proxy** — 例如 `http://127.0.0.1:7890`
- **http_proxy_auth** — 若代理需鉴权，填 `用户名:密码`，否则留空

---

## QQ

### 获取 QQ 机器人凭证

1. 打开 [QQ 开放平台](https://q.qq.com/)

![开放平台](https://img.alicdn.com/imgextra/i4/O1CN01OjCvUf1oT6ZDWpEk5_!!6000000005225-2-tps-4082-2126.png)

2. 创建 **机器人应用**，点击进入编辑页面

![bot](https://img.alicdn.com/imgextra/i3/O1CN01xBbXWa1pSTdioYFdg_!!6000000005359-2-tps-4082-2126.png)

![confirm](https://img.alicdn.com/imgextra/i3/O1CN01zt7w0V1Ij4fjcm5MS_!!6000000000928-2-tps-4082-2126.png)

3. 选择**回调配置**，首先在**单聊事件**中勾选**C2C消息事件**，再在**群事件**中勾选**群消息事件AT事件**，确认配置

![c2c](https://img.alicdn.com/imgextra/i4/O1CN01HDSoX91iOAbTVULZf_!!6000000004402-2-tps-4082-2126.png)

![at](https://img.alicdn.com/imgextra/i4/O1CN01UJn1AK1UKatKkjMv4_!!6000000002499-2-tps-4082-2126.png)

4. 选择**沙箱配置**中的**消息列表配置项**，点击**添加成员**，选择添加**自己**

![1](https://img.alicdn.com/imgextra/i4/O1CN01BSdkXl1ckG0dC7vH9_!!6000000003638-2-tps-4082-2126.png)

![1](https://img.alicdn.com/imgextra/i4/O1CN01LGYUMe1la1hmtcuyY_!!6000000004834-2-tps-4082-2126.png)

5. 在**开发管理**中获取**AppID**和**AppSecret**（即 ClientSecret），填入config，方式见下方填写config.json。在**IP白名单**中添加一个IP。

   > **提示：** 如果使用魔搭创空间部署CoPaw，QQ频道的IP白名单应填写：`47.92.200.108`

![1](https://img.alicdn.com/imgextra/i4/O1CN012UQWI21cnvBAUcz54_!!6000000003646-2-tps-4082-2126.png)

6. 在沙箱配置中，使用QQ扫码，将机器人添加到消息列表

![1](https://img.alicdn.com/imgextra/i3/O1CN01r1OvPy1kcwc30w32K_!!6000000004705-2-tps-4082-2126.png)

### 填写 config.json

在 `config.json` 里找到 `channels.qq`，把上面两个值分别填进 `app_id` 和 `client_secret`：

```json
"qq": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "你的 AppID",
  "client_secret": "你的 AppSecret"
}
```

注意：这里填的是 **AppID** 和 **AppSecret** 两个字段，不是拼成一条 Token。

或者也可以在console前端填写

![1](https://img.alicdn.com/imgextra/i1/O1CN01kK9tSJ1MHpZmGR2o9_!!6000000001410-2-tps-4082-2126.png)

---

## 企业微信

### 创建新企业

个人使用者可以访问[企业微信官网](https://work.weixin.qq.com)注册账号，创建新企业，成为企业管理员。

![创建企业](https://img.alicdn.com/imgextra/i2/O1CN01Xg8B3i1EQWAKt5xj0_!!6000000000346-2-tps-2938-1588.png)

填写企业信息与管理员信息，并绑定微信账号

![新建账号](https://img.alicdn.com/imgextra/i4/O1CN01uRF1Mv1TX87bOQ045_!!6000000002391-2-tps-1538-905.png)

注册成功之后即可登陆企业微信开始使用。

若已经有企业微信账号或是企业普通员工，可以直接在当前企业创建API模式机器人。

### 创建机器人

可在工作台点击智能机器人-创建机器人，选择API模式创建-通过长链接配置

![创建机器人1](https://img.alicdn.com/imgextra/i3/O1CN01lcA2rX1fm2P19SLcB_!!6000000004048-2-tps-1440-814.png)

![新建机器人2](https://img.alicdn.com/imgextra/i1/O1CN014R3a0f1mnb3qbycMV_!!6000000004999-2-tps-1440-814.png)

![新建机器人3](https://img.alicdn.com/imgextra/i4/O1CN01kZDNVk1ugHf73ybs2_!!6000000006066-2-tps-2938-1594.png)

获取`Bot ID`和`Secret`

![新建机器人4](https://img.alicdn.com/imgextra/i1/O1CN01Znm7aQ1Tfpe5Ha9WL_!!6000000002410-2-tps-1482-992.png)

### 绑定bot

可以在Console或是`config.json`填写Bot ID和Secret绑定bot

**方法一**在console填写

![绑定机器人](https://img.alicdn.com/imgextra/i2/O1CN01X8NcEj1NrqL0e3AMS_!!6000000001624-2-tps-2732-1390.png)

**方法二**在`config.json`填写(默认文件路径为`~/.copaw/config.json`)
找到`wecom`，填写对应信息，例如：

```json
"wecom": {
      "enabled": true,
      "dm_policy": "open",
      "group_policy": "open",
      "bot_id": "your bot_id",
      "secret": "your secret",
      "media_dir": "~/.copaw/media",
      "max_reconnect_attempts": -1
    }
```

### 在企业微信开始与机器人聊天

![开始使用](https://img.alicdn.com/imgextra/i3/O1CN01ZsmpYr1tq4ViIbO80_!!6000000005952-2-tps-1308-1130.png)

---

## Telegram

### 获取 Telegram 机器人凭证

1. 打开 Telegram 并搜索 `@BotFather` 添加 Bot（注意需要是官方 @BotFather，有蓝色认证标识）。
2. 打开与 @BotFather 的聊天，根据对话中的指引创建新机器人

   ![创建机器人](https://img.alicdn.com/imgextra/i1/O1CN01wVVmbY1qkcxBn8Oc0_!!6000000005534-0-tps-817-1279.jpg)

3. 在对话框中创建 bot_name，复制 bot_token

   ![复制token](https://img.alicdn.com/imgextra/i3/O1CN01KUMvBW1UnuF599tNX_!!6000000002563-0-tps-1209-1237.jpg)

### 绑定 Bot

可以在console前端配置，或者修改`~/.copaw/config.json`。

**方法1**: 在console前端配置

从"控制→频道"找到**Telegram**，点击后填入刚刚获取的**Bot Token**

![console](https://img.alicdn.com/imgextra/i4/O1CN01utJvvg1dmNSiFOOJi_!!6000000003778-0-tps-1920-993.jpg)

**方法2**: 修改`~/.copaw/config.json`

在 `config.json` 里找到 `channels.telegram`，填入对应信息，例如：

```json
"telegram": {
    "enabled": true,
    "bot_prefix": "[BOT]",
    "bot_token": "你的 Bot Token",
    "http_proxy": "",
    "http_proxy_auth": ""
}
```

国内网络访问 Telegram API 可能需代理。如需代理：

- **http_proxy** — 例如 `http://127.0.0.1:7890`
- **http_proxy_auth** — 若代理需鉴权，填 `用户名:密码`，否则留空

### 备注

可使用本页顶部介绍的通用访问控制字段（`dm_policy`、`group_policy`、`allow_from`、`deny_message`、`require_mention`）控制谁可以与机器人交互。仍建议不要将 bot username 暴露到公共环境中。

建议在 `@BotFather` 设置：

```
/setprivacy -> ENABLED # 设置bot回复权限
/setjoingroups -> DISABLED # 拦截Group邀请
```

---

## Mattermost

Mattermost 频道通过 WebSocket 实时监听事件，并使用 REST API 发送回复。支持私聊和群聊场景，在群聊中基于 **Thread（盖楼）** 划分会话上下文。

### 获取凭证

1. 在 Mattermost 中创建 **Bot 账号** (System Console → Integrations → Bot Accounts)。
2. 给予机器人必要的权限（如 `Post all`），并获取 **Access Token**。
3. 在控制台或 `config.json` 中配置 **URL** 和 **Token**。

### 核心配置

| 字段                              | 说明                                                      | 默认值   |
| --------------------------------- | --------------------------------------------------------- | -------- |
| **url**                           | Mattermost 实例的完整地址                                 | -        |
| **bot_token**                     | 机器人的 Access Token                                     | -        |
| **show_typing**                   | 是否开启「正在输入...」状态指示                           | `true`   |
| **thread_follow_without_mention** | 在群聊已参与的 Thread 中，是否在后续无 @ 消息时也触发回复 | `false`  |
| **dm_policy**                     | 私聊策略：`open` (全部允许) 或 `allowlist` (仅白名单)     | `"open"` |
| **group_policy**                  | 群聊策略：`open` (全部允许) 或 `allowlist` (仅白名单)     | `"open"` |
| **allow_from**                    | 允许的用户 ID 列表 (仅在策略为 `allowlist` 时生效)        | `[]`     |
| **deny_message**                  | 被拒绝访问时的自动回复消息                                | `""`     |

> **提示**：Mattermost 的 `session_id` 在私聊中固定为 `mattermost_dm:{mm_channel_id}`，在群聊中按 Thread ID 隔离回话。仅在 Session 首次触发时会自动拉取最近的历史记录作为上下文补全。

---

## MQTT

### 介绍

当前仅支持了文本和JSON格式消息。

JSON消息格式

```
{
  "text": "...",
  "redirect_client_id": "..."
}
```

### 基础配置

| 描述                    | 属性            | 必须项 | 举例                    |
| ----------------------- | --------------- | ------ | ----------------------- |
| 连接地址                | host            | Y      | 127.0.0.1               |
| 连接端口                | port            | Y      | 1883                    |
| 协议                    | transport       | Y      | tcp                     |
| 清除会话                | clean_session   | Y      | true                    |
| 服务质量 / 消息投递等级 | qos             | Y      | 2                       |
| 用户名                  | username        | N      |                         |
| 密码                    | password        | N      |                         |
| 订阅主题                | subscribe_topic | Y      | server/+/up             |
| 推送主题                | publish_topic   | Y      | client/{client_id}/down |
| 开启加密                | tls_enabled     | N      | false                   |
| CA 根证书               | tls_ca_certs    | N      | /tsl/ca.pem             |
| 客户端 证书文件         | tls_certfile    | N      | /tsl/client.pem         |
| 客户端私钥文件          | tls_keyfile     | N      | /tsl/client.key         |

### 主题

1. 简单订阅和推送

   | subscribe_topic | publish_topic |
   | --------------- | ------------- |
   | server          | client        |

2. 模糊匹配订阅和自动推送

   模糊订阅全server/+/up主题，根据客户端的client_id自动推送到对应的主题，例如客户端向`/server/client_a/up`推送，OpenClaw处理完后，将会向`/client/client_b/down`推送消息。

   | subscribe_topic | publish_topic           |
   | --------------- | ----------------------- |
   | server/+/up     | client/{client_id}/down |

3. 重定向主题推送

   发送消息为JSON格式，订阅主题为`server/client_a/up`，推送主题为`client/client_a/down`

   ```json
   {
     "text": "讲个笑话，直接回复文本即可。",
     "redirect_client_id": "client_b"
   }
   ```

   消息会根据redirect_client_id属性，推送至 `client/client_b/down`，从而实现跨主题推送。在物联网场景，可以做到以OpenClaw为核心，根据个人需求，多设备间自主推送消息。

---

## Matrix

Matrix 频道通过 [matrix-nio](https://github.com/poljar/matrix-nio) 库将 CoPaw 接入任意 Matrix 服务器，支持私聊和群聊房间中的文本消息收发。

### 创建机器人账号并获取 Access Token

1. 在任意 Matrix 服务器上注册机器人账号（例如 [matrix.org](https://matrix.org)，可在 [app.element.io](https://app.element.io/#/register) 注册）。

2. 获取机器人的 **Access Token**，最简便的方式是通过 Element：

   - 以机器人账号登录 [app.element.io](https://app.element.io)
   - 前往 **设置 → 帮助与关于 → 高级 → Access Token**
   - 复制 Token（以 `syt_...` 开头）

   也可以直接调用 Matrix Client-Server API：

   ```bash
   curl -X POST "https://matrix.org/_matrix/client/v3/login" \
     -H "Content-Type: application/json" \
     -d '{"type":"m.login.password","user":"@yourbot:matrix.org","password":"yourpassword"}'
   ```

   响应中的 `access_token` 即为所需 Token。

3. 记录机器人的 **User ID**（格式：`@用户名:服务器`，例如 `@mybot:matrix.org`）和 **Homeserver URL**（例如 `https://matrix.org`）。

### 配置频道

**方式一：** 在 Console 中配置

前往 **控制 → 频道**，点击 **Matrix**，启用后填写：

- **Homeserver URL** — 例如 `https://matrix.org`
- **User ID** — 例如 `@mybot:matrix.org`
- **Access Token** — 上面复制的 Token（以密码框形式显示）

**方式二：** 编辑 `~/.copaw/config.json`

在 `config.json` 中找到 `channels.matrix`：

```json
"matrix": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "homeserver": "https://matrix.org",
  "user_id": "@mybot:matrix.org",
  "access_token": "syt_..."
}
```

保存后，若 CoPaw 已在运行，频道会自动重载。

### 开始聊天

从任意 Matrix 客户端（如 Element）邀请机器人进入房间或发起私聊。机器人会监听其已加入的所有房间中的消息。

### 注意事项

- Matrix 频道当前**仅支持文本消息**（不支持图片/文件附件）。
- 机器人只能接收已加入房间的消息，发消息前请先邀请机器人进入对应房间。
- 如使用自建服务器，将 `homeserver` 设置为你的服务器地址（例如 `https://matrix.example.com`）。

---

## 小艺（XiaoYi）

小艺通道通过 **A2A (Agent-to-Agent) 协议** 基于 WebSocket 连接华为小艺平台。

### 获取凭证

1. 在小艺开放平台创建Agent。
2. 获取 **AK** (Access Key)、**SK** (Secret Key) 和 **Agent ID**。

### 核心配置

| 字段         | 说明           | 默认值                                           |
| ------------ | -------------- | ------------------------------------------------ |
| **ak**       | 访问密钥       | -                                                |
| **sk**       | 密钥           | -                                                |
| **agent_id** | 代理唯一标识   | -                                                |
| **ws_url**   | WebSocket 地址 | `wss://hag.cloud.huawei.com/openclaw/v1/ws/link` |

---

## 附录

### 配置总览

| 频道       | 配置键     | 必填/主要字段                                                                           |
| ---------- | ---------- | --------------------------------------------------------------------------------------- |
| 钉钉       | dingtalk   | client_id, client_secret, message_type, card_template_id, card_template_key, robot_code |
| 飞书       | feishu     | app_id, app_secret；可选 encrypt_key, verification_token, media_dir                     |
| iMessage   | imessage   | db_path, poll_sec（仅 macOS）                                                           |
| Discord    | discord    | bot_token；可选 http_proxy, http_proxy_auth                                             |
| QQ         | qq         | app_id, client_secret                                                                   |
| Telegram   | telegram   | bot_token；可选 http_proxy, http_proxy_auth                                             |
| Mattermost | mattermost | url, bot_token; 可选 show_typing, dm_policy, allow_from                                 |
| Matrix     | matrix     | homeserver, user_id, access_token                                                       |
| 小艺       | xiaoyi     | ak, sk, agent_id；可选 ws_url                                                           |

所有频道均支持本页顶部「通用字段」中介绍的访问控制字段（`dm_policy`、`group_policy`、`allow_from`、`deny_message`、`require_mention`）。

各频道字段与完整结构见上文表格及 [配置与工作目录](./config)。

### 多模态消息支持

不同频道对「文本 / 图片 / 视频 / 音频 / 文件」的**接收**（用户发给机器人）与**发送**（机器人回复用户）支持程度如下。
「✓」= 已支持；「🚧」= 施工中（可实现但尚未实现）；「✗」= 不支持（该频道本身无法支持）。

| 频道       | 接收文本 | 接收图片 | 接收视频 | 接收音频 | 接收文件 | 发送文本 | 发送图片 | 发送视频 | 发送音频 | 发送文件 |
| ---------- | -------- | -------- | -------- | -------- | -------- | -------- | -------- | -------- | -------- | -------- |
| 钉钉       | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        |
| 飞书       | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        |
| Discord    | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | 🚧       | 🚧       | 🚧       | 🚧       |
| iMessage   | ✓        | ✗        | ✗        | ✗        | ✗        | ✓        | ✗        | ✗        | ✗        | ✗        |
| QQ         | ✓        | 🚧       | 🚧       | 🚧       | 🚧       | ✓        | 🚧       | 🚧       | 🚧       | 🚧       |
| 企业微信   | ✓        | ✓        | 🚧       | ✓        | ✓        | ✓        | 🚧       | 🚧       | 🚧       | 🚧       |
| Telegram   | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        |
| Mattermost | ✓        | ✓        | 🚧       | 🚧       | ✓        | ✓        | ✓        | 🚧       | 🚧       | ✓        |
| Matrix     | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        | ✓        |
| 小艺       | ✓        | 🚧       | 🚧       | 🚧       | 🚧       | ✓        | 🚧       | 🚧       | 🚧       | 🚧       |

说明：

- **钉钉**：接收支持富文本与单文件（downloadCode），发送通过会话 webhook 支持图片 / 语音 / 视频 / 文件。
- **飞书**：WebSocket 长连接收消息，Open API 发送；支持文本 / 图片 / 文件收发；群聊时在消息 metadata 中带 `feishu_chat_id`、`feishu_message_id` 便于下游去重与群上下文。
- **Discord**：接收时附件会解析为图片 / 视频 / 音频 / 文件并传入 Agent；回复时真实附件发送为 🚧 施工中，当前仅以链接形式附在文本中。
- **iMessage**：基于本地 imsg + 数据库轮询，仅支持文本收发；平台/实现限制，无法支持附件（✗）。
- **QQ**：接收侧附件解析为多模态、发送侧真实媒体均为 🚧 施工中，当前仅文本 + 链接形式。
- **Telegram**：接收时附件会解析为文件并传入，可在telegram对话界面以对应格式打开（图片 / 语音 / 视频 / 文件）
- **企业微信**：WebSocket 长连接接收，markdown/template_card 发送；支持接收文本、图片、语音和文件；发送媒体暂不支持（SDK 限制，仅支持通过 markdown 发送文本）。
- **Matrix**：接收图片 / 视频 / 音频 / 文件（通过 `mxc://` 媒体 URL）；发送时将文件上传至服务器后以原生 Matrix 媒体消息（`m.image`、`m.video`、`m.audio`、`m.file`）发出。
- **小艺**：当前仅支持文本。

### 通过 HTTP 修改配置

服务运行时可读写频道配置，修改会写回 `config.json` 并自动生效：

- `GET /config/channels` — 获取全部频道
- `PUT /config/channels` — 整体覆盖
- `GET /config/channels/{channel_name}` — 获取单个（如 `dingtalk`、`imessage`）
- `PUT /config/channels/{channel_name}` — 更新单个

---

## 扩展渠道

如需接入新平台（如企业微信、Slack 等），可基于 **BaseChannel** 实现子类，无需改核心源码。

### 数据流与队列

- **ChannelManager** 为每个启用队列的 channel 维护一个队列；收到消息时 channel 调用 **`self._enqueue(payload)`**（由 manager 启动时注入），manager 在消费循环中再调用 **`channel.consume_one(payload)`**。
- 基类已实现 **默认 `consume_one`**：把 payload 转成 `AgentRequest`、跑 `_process`、对每条完成消息调用 `send_message_content`、错误时调用 `_on_consume_error`。多数渠道只需实现「入口→请求」和「回复→出口」，不必重写 `consume_one`。

### 子类必须实现

| 方法                                                    | 说明                                                                                                                                       |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `build_agent_request_from_native(self, native_payload)` | 将渠道原生消息转为 `AgentRequest`（使用 runtime 的 `Message`/`TextContent`/`ImageContent` 等），并设置 `request.channel_meta` 供发送使用。 |
| `from_env` / `from_config`                              | 从环境变量或配置构建实例。                                                                                                                 |
| `async start()` / `async stop()`                        | 生命周期（建连、订阅、清理等）。                                                                                                           |
| `async send(self, to_handle, text, meta=None)`          | 发送一条文本（及可选附件）。                                                                                                               |

### 基类提供的通用能力

- **消费流程**：`_payload_to_request`（payload→AgentRequest）、`get_to_handle_from_request`（解析发送目标，默认 `user_id`）、`get_on_reply_sent_args`（回调参数）、`_before_consume_process`（处理前钩子，如保存 receive_id）、`_on_consume_error`（错误时发送，默认 `send_content_parts`）、可选 **`refresh_webhook_or_token`**（空实现，子类需刷新 token 时覆盖）。
- **辅助**：`resolve_session_id`、`build_agent_request_from_user_content`、`_message_to_content_parts`、`send_message_content`、`send_content_parts`、`to_handle_from_target`。

需要不同消费逻辑时（如控制台打印、钉钉合并去抖）再覆盖 **`consume_one`**；需要不同发送目标或回调参数时覆盖 **`get_to_handle_from_request`** / **`get_on_reply_sent_args`**。

### 示例：最简渠道（仅文本）

只处理文本、使用 manager 队列时，不必实现 `consume_one`，基类默认即可：

```python
# my_channel.py
from agentscope_runtime.engine.schemas.agent_schemas import TextContent, ContentType
from copaw.app.channels.base import BaseChannel
from copaw.app.channels.schema import ChannelType

class MyChannel(BaseChannel):
    channel: ChannelType = "my_channel"

    def __init__(self, process, enabled=True, bot_prefix="", **kwargs):
        super().__init__(process, on_reply_sent=kwargs.get("on_reply_sent"))
        self.enabled = enabled
        self.bot_prefix = bot_prefix

    @classmethod
    def from_config(cls, process, config, on_reply_sent=None, show_tool_details=True):
        return cls(process=process, enabled=getattr(config, "enabled", True),
                   bot_prefix=getattr(config, "bot_prefix", ""), on_reply_sent=on_reply_sent)

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(process=process, on_reply_sent=on_reply_sent)

    def build_agent_request_from_native(self, native_payload):
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        text = payload.get("text", "")
        content_parts = [TextContent(type=ContentType.TEXT, text=text)]
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id, sender_id=sender_id, session_id=session_id,
            content_parts=content_parts, channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, to_handle, text, meta=None):
        # 调用你的 HTTP API 等发送
        pass
```

收到消息时组一个 native 字典并入队（`_enqueue` 由 manager 注入）：

```python
native = {
    "channel_id": "my_channel",
    "sender_id": "user_123",
    "text": "你好",
    "meta": {},
}
self._enqueue(native)
```

### 示例：多模态（文本 + 图片/视频/音频/文件）

在 `build_agent_request_from_native` 里把附件解析成 runtime 的 content，再调用 `build_agent_request_from_user_content`：

```python
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent, ImageContent, VideoContent, AudioContent, FileContent, ContentType,
)

def build_agent_request_from_native(self, native_payload):
    payload = native_payload if isinstance(native_payload, dict) else {}
    channel_id = payload.get("channel_id") or self.channel
    sender_id = payload.get("sender_id") or ""
    meta = payload.get("meta") or {}
    session_id = self.resolve_session_id(sender_id, meta)
    content_parts = []
    if payload.get("text"):
        content_parts.append(TextContent(type=ContentType.TEXT, text=payload["text"]))
    for att in payload.get("attachments") or []:
        t = (att.get("type") or "file").lower()
        url = att.get("url") or ""
        if not url:
            continue
        if t == "image":
            content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=url))
        elif t == "video":
            content_parts.append(VideoContent(type=ContentType.VIDEO, video_url=url))
        elif t == "audio":
            content_parts.append(AudioContent(type=ContentType.AUDIO, data=url))
        else:
            content_parts.append(FileContent(type=ContentType.FILE, file_url=url))
    if not content_parts:
        content_parts = [TextContent(type=ContentType.TEXT, text="")]
    request = self.build_agent_request_from_user_content(
        channel_id=channel_id, sender_id=sender_id, session_id=session_id,
        content_parts=content_parts, channel_meta=meta,
    )
    request.channel_meta = meta
    return request
```

### 自定义渠道目录与 CLI

- **目录**：工作目录下的 `custom_channels/`（默认 `~/.copaw/custom_channels/`）用于存放自定义渠道模块。Manager 启动时会扫描该目录下的 `.py` 文件与包（含 `__init__.py` 的子目录），加载其中的 `BaseChannel` 子类，并按类的 `channel` 属性注册。
- **安装**：`copaw channels install <key>` 会在 `custom_channels/` 下生成名为 `<key>.py` 的模板文件，可直接编辑实现；也可用 `--path <本地路径>` 或 `--url <URL>` 从本地/网络复制渠道模块。`copaw channels add <key>` 等价于安装后并写入 config 默认项，且可加 `--path`/`--url`。
- **删除**：`copaw channels remove <key>` 会从 `custom_channels/` 中删除该渠道模块（仅支持自定义渠道，内置渠道不可删）；加 `--no-keep-config`（默认）会同时从 `config.json` 的 `channels` 中移除对应 key。
- **Config**：`ChannelConfig` 使用 `extra="allow"`，`config.json` 的 `channels` 下可写任意 key；自定义渠道的配置会保存在 extra 中。配置方式与内置一致：`copaw channels config` 交互式配置，或直接编辑 config。

---

## 相关页面

- [项目介绍](./intro) — 这个项目可以做什么
- [快速开始](./quickstart) — 安装与首次启动
- [心跳](./heartbeat) — 定时自检/摘要
- [CLI](./cli) — init、app、cron、clean
- [配置与工作目录](./config) — config.json 与工作目录
