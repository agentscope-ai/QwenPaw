# Title [Feature]: 多 Agent 会议系统 (SACP)

## Summary

实现一个多 Agent 会议协作系统 (CoPaw Meetings)，支持多个 AI Agent 进行结构化会议，包含角色分工发言、决策机制和四文档输出（目标、记录、纪要、推理过程）。系统使用 SACP (Simple Agent Communication Protocol) 进行 Agent 间通信，支持临时会议和例会两种类型。

## Component(s) Affected

- [x] Core / Backend (app, agents, config, providers, utils, local_models)
- [x] Console (frontend web UI)
- [ ] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
- [x] Skills
- [ ] CLI
- [ ] Documentation (website)
- [ ] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## Problem / Motivation

**问题：** CoPaw 目前缺乏多 Agent 协作进行结构化会议并对人类可见的机制。Agent 需要：

1. 与人类进行各种临时会议或例会，以便对齐目标、相互发言、形成共识
2. 会议目标、会议记录、会议纪要对人类可见
3. 为保证 Agent 开好会，需要展示思考过程
4. 由主持 Agent 根据发言轮次触发对应汇报 Agent 发言，最后由决策 Agent 汇总意见并决策
5. 通过简单双向的通信协议沟通：`req(messages) -> rsp(content, reasons)`

**受益用户：**
- 需要多 Agent 协作进行复杂决策的用户
- 使用 CoPaw 进行架构评审、计划会议或定期站会的团队
- 需要透明化 AI 决策过程的用户

## Proposed Solution

### 架构设计

```
src/copaw/
├── meetings/                          # 会议模块
│   ├── manager.py                     # MeetingManager (核心)
│   ├── rpc.py                         # SACP Client
│   ├── storage.py                     # MeetingStorage
│   └── models/                        # 数据模型
│       ├── types.py                   # 枚举类型
│       └── config.py                  # MeetingConfig
│
├── app/routers/
│   ├── sacp.py                        # SACP 通信接口
│   ├── sacp_agents.py                # SACP Agent 配置
│   └── meetings.py                    # 会议管理接口
│
└── console/src/pages/Control/Meetings/ # 前端组件
    ├── index.tsx
    ├── useMeetings.ts
    └── components/
        ├── MeetingTable.tsx
        ├── MeetingDrawer.tsx
        ├── CreateMeetingModal.tsx
        └── EditMeetingModal.tsx
```

### 核心功能

1. **会议类型：**
   - `TEMPORARY`：临时会议，一次性讨论，创建后自动启动
   - `REGULAR`：例会，周期性会议，需手动启动

2. **会议阶段：**
   - `BACKGROUND` → `OPENING` → `ROUND` → `DECISION` → `SUMMARY`

3. **角色类型：**
   - `HOST`：主持人，负责开场和总结
   - `REPORTER`：汇报人，轮流发言
   - `DECIDER`：决策人，最终决策

4. **发言顺序模式：**
   - `raw`：正序发言 (A → B → C)
   - `reverse`：反序发言 (C → B → A)
   - `alphabet`：按字母顺序
   - `random`：随机顺序

5. **四文档输出：**
   - `goals.md`：会议目标/议程
   - `records.md`：发言记录
   - `summary.md`：会议纪要
   - `reasons.json`：推理过程 (Chain of Thought)

6. **SACP 通信协议：**
   - HTTP JSON-RPC 2.0，用于外部 Agent
   - Channel 回调模式，用于内部 Agent
   - 安全检测（金钱相关、密钥相关、权限变更、自我修改）

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/meetings` | 创建会议 |
| `GET` | `/meetings` | 会议列表查询（分页） |
| `GET` | `/meetings/{id}` | 会议详情查询 |
| `PATCH` | `/meetings/{id}` | 更新会议 |
| `DELETE` | `/meetings/{id}` | 删除会议 |
| `POST` | `/meetings/{id}/start` | 启动会议 |
| `POST` | `/meetings/{id}/stop` | 停止会议 |
| `POST` | `/meetings/{id}/restart` | 重启会议 |
| `GET` | `/meetings/{id}/status` | 会议状态查询 |
| `GET` | `/meetings/{id}/goals` | 获取会议目标 |
| `GET` | `/meetings/{id}/records` | 获取发言记录 |
| `GET` | `/meetings/{id}/summary` | 获取会议纪要 |
| `GET` | `/meetings/{id}/reasons` | 获取推理过程 |

## Alternatives Considered

1. **使用现有 MCP/A2A 协议**：放弃，因为 SACP 更简单，专为 CoPaw 内部多 Agent 协作设计，无外部依赖。

2. **单 Agent + 工具调用**：无法提供同等水平的结构化协作和多 Agent 推理可见性。

3. **纯实时流式（无持久化）**：放弃，因为用户需要会后查看会议结果，持久化文档对问责制至关重要。

4. **外部消息队列（RabbitMQ/Kafka）**：对于该场景过于复杂；Channel 回调模式已足够，且无需额外基础设施。

## Additional Context

- **设计文档：** `src/copaw/meetings/DESIGN.md`
- **用户文档：** `src/copaw/meetings/README.md`
- **Agent Skill：** `src/copaw/agents/skills/meetings/SKILL.md`
- **状态：** 已实现 (v0.4.0，截至 2026-04-01)

### UI 截图（2 步创建会议对话框）

**第一步：基本信息**

![新建会议 - 第一步](https://minimax-algeng-chat-tts.oss-cn-wulanchabu.aliyuncs.com/ccv2%2F2026-04-01%2FMiniMax-M2.7-highspeed%2F2025472901515321815%2F10c93a51e24eca5334736ec123829d86314f8ffcd86ea155537879b736b1dfcc..png?Expires=1775144426&OSSAccessKeyId=LTAI5tGLnRTkBjLuYPjNcKQ8&Signature=7jO%2Fxjh95sZO5R6cixy5dY%2Btr1o%3D)

**第二步：会议详情**

![新建会议 - 第二步](https://minimax-algeng-chat-tts.oss-cn-wulanchabu.aliyuncs.com/ccv2%2F2026-04-01%2FMiniMax-M2.7-highspeed%2F2025472901515321815%2F3d552ef969c0fab990be7db2ea17dd5a4d922226f2fbe05c160db3e68d70773e..png?Expires=1775144427&OSSAccessKeyId=LTAI5tGLnRTkBjLuYPjNcKQ8&Signature=g7MlTg8DiT2GXvpmPMHGNm5lPD0%3D)

### UI 界面设计（创建会议弹窗）

**第一步：基本信息**
```
┌─────────────────────────────────────────────────────────────┐
│ 新建会议                                            [×]     │
├─────────────────────────────────────────────────────────────┤
│ 1 基本信息 ●────────────────────────── 2 会议详情 ○        │
│                                                             │
│ * 议题标题: [破冰会议：介绍和确认对接流程标准____]        │
│                                                             │
│ * 参会人员: [产品经理] [研发经理] [测试经理]  [+ 添加]     │
│                                                             │
│ * 主持人:    [产品经理 ▼]                                   │
│ * 决策人:   [研发经理 ▼]                                   │
│                                                             │
│ 流程描述 ⓘ:                                                │
│ [基于产品经理、研发经理、测试经理的讨论，就...________]    │
│                                          [自动生成 ✨]      │
│                                                             │
│                      [取消]  [下一步 →]                     │
└─────────────────────────────────────────────────────────────┘
```

**第二步：会议详情**
```
┌─────────────────────────────────────────────────────────────┐
│ 新建会议                                            [×]     │
├─────────────────────────────────────────────────────────────┤
│ 1 基本信息 ✓────────────────────────── 2 会议详情 ●        │
│                                                             │
│ 会议概述                                                    │
│ 议题: 破冰会议：介绍和确认对接流程标准                     │
│ 描述: 基于产品经理、研发经理、测试经理的讨论...             │
│ 参会人员: 产品经理, 研发经理, 测试经理                      │
│ 会议类型: (●) 临时会议  ( ) 例会                          │
│                                                             │
│ 议题详情                                                    │
│ 议题背景: [____________________________]                    │
│ 决策原则: [充分讨论后达成共识________________]              │
│           [尊重各方意见________________]                    │
│                                                             │
│ 轮次与顺序                                                  │
│ 第 1 轮: (●)原始顺序  ()反序  ()随机  ()字母序    [删除] │
│ 第 2 轮: ()原始顺序  (●)反序  ()随机  ()字母序    [删除] │
│                                              [+ 添加轮次]   │
│                                                             │
│  [生成详情 ✨]           [返回]  [取消]  [创建]            │
└─────────────────────────────────────────────────────────────┘
```

## Willing to Contribute

- [x] 我愿意为这个功能提交 PR（讨论后）。
