---
title: "QwenPaw Mobile 预览：把你的 QwenPaw 带在身边"
date: 2026-08-28
author: QwenPaw Team
tags: [QwenPaw Mobile, Android, iOS, 多端连接]
excerpt: "QwenPaw Mobile 正在进入开发者预览：一套原生移动体验，可以连接 Platform 云端、本地电脑和其他已配对的 QwenPaw。"
related:
  heading: "了解 QwenPaw Mobile"
  description: "查看当前能力、连接方式、分发状态和测试注意事项。"
  items:
    - label: "文档"
      name: "QwenPaw Mobile 使用文档"
      href: "/docs/mobile"
---

# QwenPaw Mobile 预览：把你的 QwenPaw 带在身边

QwenPaw 一直可以通过浏览器 Console 使用。但当任务在后台运行、Agent 等待
审批，或者你只是想在路上确认进度时，打开一个为桌面设计的网页并不是最自然
的体验。

QwenPaw Mobile 正在进入开发者预览。它是一套面向 Android 和 iOS 的原生
移动客户端，沿用同一套 QwenPaw 服务、会话和 API，而不是另做一套功能受限的
移动产品。

## 一个 App，连接多个 QwenPaw

Mobile 可以保存并切换多个连接：

- AgentScope Platform 上的云端 QwenPaw；
- 家中或办公室电脑上的本地 QwenPaw；
- 通过 Console 二维码完成安全配对的其他实例。

这些连接彼此独立。你可以从会话页顶部切换当前 QwenPaw，也可以用符合移动端
习惯的左滑操作移除连接。移除当前连接后，App 会切换到剩余连接，不会清空
所有配对。

## 会话之外，也要有完整能力

Mobile 不只是一个消息窗口。当前体验以会话、智能体、社区和工作台四个入口
组织：

- 会话支持新增、分组、流式回复和运行状态恢复；
- 会话内可以调整 session 级模型、审批和 Loop 设置；
- Approval Inbox 与会话放在一起，减少审批来回跳转；
- 智能体和工作台承接 Agent、模型、Skills、MCP、自动化、安全与连接设置；
- 浅色和深色模式跟随系统，也可以按用户偏好切换。

少量确实不适合小屏操作的专业能力可以保留为 PC only，但 Mobile 的目标仍然
是让用户无需为了日常管理退回浏览器 Console。

## 为移动端重新考虑交互

把 Console 缩小并不等于移动体验。Mobile 使用底部导航、原生返回行为、
Bottom Sheet、锚定操作菜单、气泡内文本选择和列表左滑操作，让常用动作靠近
拇指，也避免在小屏上堆叠桌面式弹窗。

连接、会话和 Agent 状态仍复用同一套 API contract。后续还会继续抽取纯
TypeScript request/response 类型、解析校验和状态映射，减少 Mobile 与
Console 各自维护协议的成本。

## 当前是预览，不是正式发布

Android 已经能够生成内部测试 APK，并针对 Android 16、不同浏览器发现方式和
Platform OAuth 回跳做了多轮兼容处理。iOS 与 Android 共用业务能力和设计，
正式分发将使用 TestFlight。

不过，当前 Android APK 仍是测试签名。production keystore、自动 CI、稳定
OSS 下载地址和覆盖升级链路尚未完成；iOS 的 distribution signing 和
TestFlight 上传也仍待配置。因此官网暂时不会提供正式下载按钮。

下一阶段会优先完成：

1. Android production signing 和版本化 OSS 发布；
2. Mobile Pull Request CI 和可重复构建；
3. iOS TestFlight 签名与上传；
4. Android/iOS 真机验收矩阵；
5. 前台、后台和冷启动通知深链验证。

如果你正在参加内部测试，请阅读 [QwenPaw Mobile 文档](/docs/mobile)，并在
反馈问题时附上手机型号、系统版本、默认浏览器、连接类型和复现步骤。不要在
截图或日志中提交密码、OAuth code、访问令牌或 API Key。
