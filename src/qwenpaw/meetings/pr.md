# Title [Feature]: Multi-Agent Meeting System (SACP)

## Summary

Implement a multi-agent meeting collaboration system (CoPaw Meetings) that enables multiple AI agents to conduct structured meetings with role-based speaking, decision-making, and four-document output (goals, records, summary, reasons). The system uses the Simple Agent Communication Protocol (SACP) for inter-agent communication and supports both temporary and recurring meeting types.

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

**Problem:** CoPaw currently lacks a mechanism for multiple agents to collaborate in structured meetings with human visibility. Agents need to:

1. Conduct temporary or recurring meetings with humans to align on goals and form consensus
2. Make meeting proceedings (goals, records, summary, reasoning) visible to humans
3. Display agent thinking processes during meetings to ensure quality discussions
4. Enable role-based speaking where a host triggers reporters in sequence, followed by a decider summarizing and making decisions
5. Communicate via a simple bidirectional protocol: `req(messages) -> rsp(content, reasons)`

**Who benefits:**
- Users who need multi-agent deliberation for complex decisions
- Teams using CoPaw for architecture reviews, planning meetings, or regular standups
- Anyone requiring transparent AI decision-making processes

## Proposed Solution

### Architecture

```
src/copaw/
├── meetings/                          # Meeting module
│   ├── manager.py                     # MeetingManager (core)
│   ├── rpc.py                         # SACP Client
│   ├── storage.py                     # MeetingStorage
│   └── models/                        # Data models
│       ├── types.py                   # Enums (MeetingType, MeetingState, PhaseType, RoleType)
│       └── config.py                  # MeetingConfig
│
├── app/routers/
│   ├── sacp.py                        # SACP communication interface
│   ├── sacp_agents.py                # SACP Agent configuration
│   └── meetings.py                    # Meeting management interface
│
└── console/src/pages/Control/Meetings/ # Frontend components
    ├── index.tsx
    ├── useMeetings.ts
    └── components/
        ├── MeetingTable.tsx
        ├── MeetingDrawer.tsx
        ├── CreateMeetingModal.tsx
        └── EditMeetingModal.tsx
```

### Key Features

1. **Meeting Types:**
   - `TEMPORARY`: One-time discussion, auto-starts on creation
   - `REGULAR`: Recurring meeting, requires manual start

2. **Meeting Phases:**
   - `BACKGROUND` → `OPENING` → `ROUND` → `DECISION` → `SUMMARY`

3. **Role Types:**
   - `HOST`: Presides over opening and summary phases
   - `REPORTER`: Speaks during ROUND phase
   - `DECIDER`: Makes final decisions during DECISION phase

4. **Speaking Order Modes:**
   - `raw`: Sequential (A → B → C)
   - `reverse`: Reversed (C → B → A)
   - `alphabet`: Alphabetical order
   - `random`: Random order

5. **Four Document Outputs:**
   - `goals.md`: Meeting agenda/objectives
   - `records.md`: Speaking records
   - `summary.md`: Meeting minutes
   - `reasons.json`: Chain of thought reasoning

6. **SACP Protocol:**
   - HTTP JSON-RPC 2.0 for external agents
   - Channel callback pattern for internal agents
   - Security detection (money, keys, privilege escalation, self-modification)

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/meetings` | Create meeting |
| `GET` | `/meetings` | List meetings (paginated) |
| `GET` | `/meetings/{id}` | Get meeting details |
| `PATCH` | `/meetings/{id}` | Update meeting |
| `DELETE` | `/meetings/{id}` | Delete meeting |
| `POST` | `/meetings/{id}/start` | Start meeting |
| `POST` | `/meetings/{id}/stop` | Stop meeting |
| `POST` | `/meetings/{id}/restart` | Restart meeting |
| `GET` | `/meetings/{id}/status` | Get meeting status |
| `GET` | `/meetings/{id}/goals` | Get meeting goals |
| `GET` | `/meetings/{id}/records` | Get speaking records |
| `GET` | `/meetings/{id}/summary` | Get meeting summary |
| `GET` | `/meetings/{id}/reasons` | Get reasoning process |

## Alternatives Considered

1. **Using existing MCP/A2A protocols**: Rejected because SACP is simpler and specifically designed for CoPaw's internal multi-agent collaboration needs without external dependencies.

2. **Single-agent with tool calls**: Would not provide the same level of structured deliberation and visibility into multi-agent reasoning.

3. **Real-time streaming only (no persistence)**: Rejected because human users need to review meeting outcomes after the fact, and persistent documentation is essential for accountability.

4. **External message queue (RabbitMQ/Kafka)**: Over-engineered for the use case; Channel callback pattern is sufficient and avoids additional infrastructure.

## Additional Context

- **Design Document:** `src/copaw/meetings/DESIGN.md`
- **User Documentation:** `src/copaw/meetings/README.md`
- **Agent Skill:** `src/copaw/agents/skills/meetings/SKILL.md`
- **Status:** Implemented (v0.4.0 as of 2026-04-01)

### UI Screenshots (2-Step Create Meeting Dialog)

**Step 1: Basic Information**

![Create Meeting - Step 1](https://minimax-algeng-chat-tts.oss-cn-wulanchabu.aliyuncs.com/ccv2%2F2026-04-01%2FMiniMax-M2.7-highspeed%2F2025472901515321815%2F10c93a51e24eca5334736ec123829d86314f8ffcd86ea155537879b736b1dfcc..png?Expires=1775144426&OSSAccessKeyId=LTAI5tGLnRTkBjLuYPjNcKQ8&Signature=7jO%2Fxjh95sZO5R6cixy5dY%2Btr1o%3D)

**Step 2: Meeting Details**

![Create Meeting - Step 2](https://minimax-algeng-chat-tts.oss-cn-wulanchabu.aliyuncs.com/ccv2%2F2026-04-01%2FMiniMax-M2.7-highspeed%2F2025472901515321815%2F3d552ef969c0fab990be7db2ea17dd5a4d922226f2fbe05c160db3e68d70773e..png?Expires=1775144427&OSSAccessKeyId=LTAI5tGLnRTkBjLuYPjNcKQ8&Signature=g7MlTg8DiT2GXvpmPMHGNm5lPD0%3D)

### UI Mockup (Meeting Creation Modal)

**Step 1: Basic Information**
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

**Step 2: Meeting Details**
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

- [x] I am willing to open a PR for this feature (after discussion).
