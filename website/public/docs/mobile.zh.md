# QwenPaw Mobile

QwenPaw Mobile 是 QwenPaw 的原生移动客户端，面向 Android 和 iOS。它与
Console 连接同一套 QwenPaw 服务和数据，不是一个独立、功能缩水的产品。

当前版本处于开发者预览阶段。Android 已可通过内部 APK 进行真机测试；正式
签名、稳定 OSS 下载地址和自动更新尚未开放。iOS 正在准备 TestFlight 分发，
目前没有公开 IPA 下载地址。

## 能做什么

Mobile 以四个主要入口组织能力：

- **会话**：新建与分组会话、流式回复、运行状态恢复、会话级模型、审批和
  Loop 设置，以及 Approval Inbox。
- **智能体**：浏览、选择和管理当前 QwenPaw 中的 Agent。
- **社区**：访问 QwenPaw 社区内容和相关入口。
- **工作台**：集中查看连接、模型、Skills、MCP、自动化、安全、数据和系统
  设置。

同一个 App 可以保存并切换多个连接，例如 Platform 云端、家中电脑和办公
电脑。移除一个连接不会影响其他已经配对的 QwenPaw。

## 连接 QwenPaw

### AgentScope Platform

在连接页选择 AgentScope Platform，完成安全登录后，App 会查找并连接账户下
的 QwenPaw。Android 使用系统浏览器提供的安全认证会话；认证页面可能显示为
Chrome Custom Tab，但仍属于系统认可的 OAuth 流程。授权完成后应自动回到
QwenPaw App。

如果认证完成后没有返回 App：

1. 确认 Chrome 或其他兼容浏览器没有被停用；
2. 从最近任务中回到 QwenPaw，检查登录是否已经恢复；
3. 关闭认证页后重新发起一次登录；
4. 记录手机型号、Android 版本、默认浏览器和发生时间并反馈。

### 本地或局域网 QwenPaw

手机必须能够访问运行 QwenPaw 的电脑。真机不能使用电脑的
`127.0.0.1` 或 `localhost`，因为这两个地址在手机上指向手机自身。

在电脑上监听局域网地址：

```bash
qwenpaw app --host 0.0.0.0 --port 8088
```

然后在 Mobile 中输入电脑的局域网地址，例如：

```text
http://192.168.1.23:8088
```

手机与电脑需要位于可互访的网络中，电脑防火墙也必须允许该端口。不要把
没有认证保护的 QwenPaw 直接暴露到公网。

### 二维码配对

在 Console 中创建一次性配对二维码，再使用 Mobile 扫描。二维码只包含连接
地址和短期一次性 ticket，不包含密码或长期访问令牌。二维码过期后需要重新
生成。

## 多连接与解除配对

点击会话页顶部的当前 QwenPaw，可以在已保存连接之间切换。连接列表支持
移动端左滑操作；移除当前连接后，如果仍有其他连接，App 会自动切换到剩余
连接，而不是清空整个 App。

退出 AgentScope Platform 登录时，App 也会移除该 Platform 账户发现并配对的
云端 QwenPaw，但不会删除手动添加的本地连接。

## 凭据与隐私

- 连接凭据保存在 iOS Keychain 或 Android Keystore 支持的安全存储中。
- OAuth 授权码和短期状态不写入普通偏好设置。
- 通知 payload 不应携带凭据、服务地址或完整消息正文。
- 使用局域网 HTTP 时，网络内其他设备可能观察流量；敏感环境应使用可信网络
  或 HTTPS。

## 当前分发状态

| 平台    | 当前状态                                   | 计划渠道                            |
| ------- | ------------------------------------------ | ----------------------------------- |
| Android | 内部测试 APK，尚未使用 production keystore | 正式签名 APK 上传 OSS；后续可补 AAB |
| iOS     | 尚无公开安装包                             | TestFlight 内部/外部测试            |

当前 Android 测试 APK 使用测试签名。切换到正式签名后，已安装测试包的用户
可能需要先卸载旧包再安装正式版本。正式签名启用后，后续版本才能稳定覆盖
升级。

## 发布前尚需完成

- 建立 Mobile Pull Request CI：TypeScript、ESLint、单元测试、Android lint/
  build 和 iOS 无签名编译。
- 生成并备份 Android production keystore。
- 建立正式 APK 的版本化 OSS 上传、SHA-256 和 `latest.json`。
- 配置 Apple Developer、App Store Connect、iOS distribution signing 和
  TestFlight 上传。
- 完成 Android/iOS 真机验收矩阵，包括 OAuth、局域网连接、多端切换、通知
  深链和冷启动恢复。

这些项目完成前，官网不会提供“正式版”Mobile 下载按钮。

## 反馈问题

提交 Mobile 问题时，请附上：

- App 版本和 Android versionCode 或 iOS build number；
- 手机型号、操作系统版本和默认浏览器；
- 连接类型：Platform、二维码、本地或局域网；
- 可复现步骤和页面截图；
- 是否可以在手机浏览器中直接访问目标 QwenPaw 地址。

请勿在截图或日志中包含密码、OAuth code、访问令牌或完整 API Key。
