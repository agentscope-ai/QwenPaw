# QwenPaw Mobile 技术架构概览

> One product experience, one shared client core, native on every platform.

QwenPaw Mobile 是一套面向 iOS 与 Android 的原生体验客户端，基于
React Native 0.86 + Expo 57 + React 19 构建。它不是 Console 的网页套壳，
而是通过共享 API 与状态层，同时连接私有 QwenPaw 和 AgentScope
Platform 云端 QwenPaw 的独立移动端。

```text
┌───────────────────────────────────────────────────────────┐
│                    Native Experience                      │
│      iOS Navigation · Android Back · Light / Dark       │
├───────────────────────────────────────────────────────────┤
│                    Feature Modules                        │
│   Chats · Agents · Community · Workbench · Pairing     │
├───────────────────────────────────────────────────────────┤
│               Shared State & Domain Models                │
│        Zustand · Connection State · Session Lifecycle       │
├───────────────────────────────────────────────────────────┤
│                    Shared API Layer                       │
│ QwenPaw API · Platform API · Gateway Ticket · SSE Stream │
├─────────────────────────────┬─────────────────────────────┤
│   Local / Private QwenPaw   │   AgentScope Platform Cloud │
└─────────────────────────────┴─────────────────────────────┘
```

## 一套代码，多系统原生体验

- iOS 和 Android 共享业务逻辑、API、状态管理、视觉 Token 与组件。
- 平台差异被限制在边界层：iOS 导航与 Keychain、Android 物理返回键与
  Keystore、OAuth 回调、通知权限均使用对应原生能力。
- React Native Web 依赖与响应式尺寸约束已保留，为后续大屏与 Web 端
  复用提供结构基础。

## 共享 API 层，切换 QwenPaw 不切换产品

- `src/api/client.ts` 封装 QwenPaw 会话、消息、附件、配置与实时流。
- `src/api/platform.ts` 负责 Platform 身份、Token 刷新与部署接口。
- `src/api/platformGateway.ts` 将 Platform 短期访问态的续期、单飞刷新与一次安全
  重试收敛在网关边界，业务页无需感知 Cookie 细节。
- `@qwenpaw/api-contract` 作为共享协议包，降低 Console、Server 与 Mobile
  之间的协议漂移。

因此，本地、局域网、私有部署与 Platform 云端都是同一个 `Connection`
域模型。用户切换的是 QwenPaw，而不是一套新 App。

## 模块化与可扩展边界

- `src/app`：Expo Router 路由与页面编排。
- `src/features`：Chat、Agent、Community、Platform、Workbench 等独立能力。
- `src/store`：Zustand 驱动的连接、会话、未读与流式生命周期。
- `src/components`：iOS / WeChat 风格的可复用原生交互组件。
- `src/storage`：SecureStore 敏感凭证与 AsyncStorage 设备偏好的分层存储。
- `src/theme`：QwenPaw 橙色品牌 Token、语义色与深浅色模式。

页面不直接处理底层协议；交互、业务状态、传输与存储各自守住边界，
新增平台或能力时无需复制整套页面逻辑。

## 生产级可靠性

- Platform 限流使用有界退避，网关刷新使用 single-flight，避免请求风暴。
- 云端唤醒、重启和重新检查是显式状态机；失败后停止自动操作，不会
  死循环或重复创建实例。
- SSE 流式响应、中断恢复、长内容折叠、多模态消息与工具结果共享同一
  套消息模型。
- 开发环境检测 Metro 断开并显示可恢复界面，避免用空白屏隐藏真实
  问题。
- Node Test Runner、TypeScript 严格检查与 Expo ESLint 组成快速质量门禁。

## 安全模型

- 配对 Token 与登录凭证保存在 iOS Keychain / Android Keystore。
- Platform 账号与 QwenPaw 配对状态相互独立，避免跨服务传播凭证。
- 私有部署支持局域网直连，本地开发使用 localhost / LAN，不依赖公网
  tunnel。

---

**Engineering signature:** shared core, native edges, explicit state machines,
secure-by-default connections, and measurable quality gates.
