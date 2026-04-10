---
name: dingtalk_channel_connect
description: "使用可视浏览器自动完成 QwenPaw 的钉钉频道接入。适用于用户提到钉钉、DingTalk、开发者后台、Client ID、Client Secret、机器人、Stream 模式、绑定或配置 channel 的场景；支持遇到登录页时暂停，等待用户登录后继续。"
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🤖"
    requires: {}
---

# 钉钉 Channel 自动连接（可视浏览器）

此 skill 用于通过可视浏览器自动化完成钉钉应用创建与 QwenPaw channel 绑定。

## 强制规则

1. 必须使用可视浏览器模式启动：

```json
{"action": "start", "headed": true}
```

2. 遇到登录关卡必须暂停：
   - 若页面出现登录界面（如 `登录`、扫码登录、手机号/密码登录），立即停止自动操作。
   - 明确提示用户先手动登录，再等待用户回复“登录好了/继续”。
   - 未收到用户确认前，不得继续执行后续步骤。

3. 任何应用配置变更都必须新建版本并发布后才生效：
   - 配置完机器人相关信息后**一定要发布机器人**
   - 不论是新建应用还是修改应用信息（名称、描述、图标、机器人配置等），最终都**必须执行“创建新版本 + 发布”**。
   - 若未完成发布，不得宣称配置已生效。

## 执行前显著确认（必须先做）

在开始自动化点击前，先向用户发起一次“配置确认”，明确告知可自定义项、图片规范、默认值。建议使用如下结构化确认：

1. 让用户可自定义以下字段：
   - 应用名称
   - 应用描述
   - 机器人图标图片链接或本地路径
   - 机器人消息预览图链接或本地路径

2. 明确告知图片规范（显著提示）：
   - 机器人图标：仅支持 JPG/PNG，`240*240px` 以上，`1:1`，`2MB` 以内，无圆角。
   - 机器人消息预览图：格式 `png/jpeg/jpg`，不超过 `2MB`。

3. 明确告知默认值（用户不指定时自动采用）：
   - 应用名称：`QwenPaw`
   - 应用描述：`Your personal assistant`
   - 机器人图标：`https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - 机器人消息预览图：`https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`

4. 若用户未给任何自定义值，必须先明确回复：
   - “将全部采用默认设置（QwenPaw / Your personal assistant / 默认图片）后继续执行。”

## 图片上传策略（link/path 都支持）

1. 若用户提供本地路径，直接用于上传。
2. 若用户提供图片 link，先下载到本地临时文件，再执行上传。
3. 上传动作顺序必须是：
   - 先点击页面上传入口（触发 chooser）
   - 再调用 `file_upload` 传入本地路径数组（`paths_json`）
4. 若上传报错且判断为图片规格不符合（尺寸、比例、大小、格式）：
   - 立即暂停自动化
   - 明确让用户手动上传符合规范的图片
   - 用户确认“已上传/继续”后，从当前步骤继续后续流程

### 上传动作实战经验

1. `file_upload` 的 `paths_json` 必须是“JSON 字符串数组”，注意转义：

```json
{
  "action": "file_upload",
  "paths_json": "[\"xxx.png\"]",
  "frame_selector": "iframe[src*=\"/fe/app?isHideOuterFrame=true\"]"
}
```

2. 若页面在 iframe 内，建议优先带上 `frame_selector`，否则可能出现找不到上传控件或 chooser 未触发。

3. 上传前必须先点击上传入口；若直接 `file_upload` 会报：
   - `No chooser. Click upload then file_upload.`

4. 机器人图标区域的常见结构特征可用于定位（示例）：
   - `text: "* 机器人图标"`
   - `button: "使用应用图标"`
   - `button: "avatar"`（通常内部有 `img "avatar"`）

5. 当 snapshot 中同时出现“使用应用图标”和“avatar”时，优先点击 `avatar` 按钮触发上传，再执行 `file_upload`。

## 自动化流程

### 步骤 1：打开钉钉开发者后台

1. 可视模式启动浏览器（`headed: true`）
2. 打开 `https://open-dev.dingtalk.com/`
3. 调用 `snapshot` 判断是否需要登录

若需要登录，使用如下话术暂停：

> 检测到需要登录钉钉开发者后台。我已暂停自动操作，请先在弹出的浏览器中完成登录。完成后回复“继续”，我再从当前页面接着执行。

### 步骤 2：创建企业内部应用

用户确认登录后继续：

1. 进入创建路径：
   - 应用开发 -> 企业内部应用 -> 钉钉应用 -> 创建应用
2. 填写应用信息（优先使用用户自定义，否则使用默认值）：
   - 应用名称：默认 `QwenPaw`
   - 应用描述：默认 `Your personal assistant`
3. 保存并创建应用

若页面文案或结构与预期不一致，重新 `snapshot`，按可见文本语义重新定位元素。

### 步骤 3：添加机器人能力并发布

1. 点击**应用能力**中的**添加应用能力**，找到**机器人**并添加
2. 将**机器人配置**右侧的switch按钮切换为打开
3. 填写**机器人名称**，**机器人简介**和**机器人描述**
4. 上传**机器人图标**（用户自定义或默认图）：
   - 点击机器人图标下面的图片
   - 默认图链接：`https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - 若为 link，先下载到本地再上传
   - 若提示图片不合规，暂停并让用户手动上传合规图片后继续
5. 上传**机器人消息预览图**（用户自定义或默认图）：
   - 点击机器人消息预览图下面的图片
   - 默认图链接：`https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - 若为 link，先下载到本地再上传
   - 若提示图片不合规，暂停并让用户手动上传合规图片后继续
6. 确认消息接收模式设置为 `Stream 模式`
7. 选择**发布**，此时会有进一步弹出的确认页面，选择发布。注意：**一定要发布机器人**之后再进行下一步

### 步骤 4：创建版本并发布

1. 打开 `应用发布 -> 版本管理与发布`
2. 创建新版本（每次配置变更后都要创建）
3. 填写版本描述，应用可见范围选择全部员工
4. 按页面提示完成发布，此时会有新的弹窗出现，选择确认发布
5. 只有看到发布成功状态，才可继续执行后续步骤/给用户“已生效”结论

### 步骤 5：获取凭证

1. 打开 `基础信息 -> 凭证与基础信息`
2. 告知用户`Client ID`（AppKey）和`Client Secret`（AppSecret）在该页面上。不主动进行修改，引导用户自行绑定

## QwenPaw 绑定方式

拿到凭证后，引导用户选择以下任一方式：

1. 控制台前端配置：
   - QwenPaw console 中进入 `控制 -> 频道 -> DingTalk`
   - 填入 `Client ID` 与 `Client Secret`

2. 配置文件方式：

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "你的 Client ID",
  "client_secret": "你的 Client Secret"
}
```

路径：`~/.qwenpaw/config.json`，位于 `channels.dingtalk` 下。

### 凭证交付要求（强制）

1. agent 只负责引导用户进入凭证页、获取并展示 `Client ID` 与真实 `Client Secret`。
2. agent 不主动改 `console` 配置、不主动改 `~/.qwenpaw/config.json`。
3. 必须提示用户按以下两种方式之一手动填写：
   - 控制台前端：`控制 -> 频道 -> DingTalk`
   - 配置文件：编辑 `~/.qwenpaw/config.json` 的 `channels.dingtalk` 字段

## Browser 工具调用模式

默认按以下顺序执行：

1. `start` with `headed: true`
2. `open`
3. `snapshot`
4. `click` / `type` / `select_option` / `press_key` as needed
5. frequent `snapshot` after page transitions
6. `stop` when done

## 稳定性与恢复策略

- 优先使用最新 `snapshot` 的 `ref`；仅在必要时使用 `selector`。
- 每次关键点击或跳转后，使用短等待（`wait_for`）并立即重新 `snapshot`。
- 若中途会话失效或要求重新登录，必须再次暂停，待用户登录后从当前步骤继续。
- 若因租户权限、管理员审批等阻塞自动化，明确说明卡点，并请用户手动完成该步骤后再续跑。
