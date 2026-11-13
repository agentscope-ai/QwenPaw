---
title: "QwenPaw Driver: A Unified Capability Access Layer"
date: 2026-07-01
author: QwenPaw Team
tags: [CapabilityIntegration, ProtocolAdapters, AccessControl, MCP]
excerpt: "Agent systems are evolving rapidly. Today's Agent no longer calls just a few built-in tools — it needs to interface with MCP Servers, remote Agents (A2A), ACP services, and potentially more protocols in the future."
---

# QwenPaw Driver: A Unified Capability Access Layer

## Why We Built the Driver Layer

Agent systems are evolving rapidly. Today's Agent no longer calls just a few built-in tools — it needs to interface with MCP Servers, remote Agents (A2A), ACP services, and potentially more protocols in the future.

These capabilities differ in **communication modes** (stdio / HTTP / WebSocket), **authentication mechanisms** (static tokens / OAuth2 / AK/SK), and **protocol formats** (JSON-RPC / REST / gRPC). If the Agent is tightly coupled to these differences, every new external capability requires modifying core Agent code. This violates the Open-Closed Principle and fragments security governance.

We need to answer a fundamental question: **How should an Agent system perceive and manage heterogeneous external capabilities?**

## What is a Driver

> **Driver abstracts external capability access into a unified, protocol-agnostic resource model, enabling the Agent system to uniformly declare, invoke, and govern them.**

Three keywords define Driver's value:

- **Declarative** — The system knows which external capabilities exist and how to reach them
- **Invocable** — Calls are made through a standard interface, hiding underlying protocol differences
- **Governable** — Controls who can invoke what, under which conditions, down to individual tools

Driver does not own external services. External services exist independently, are deployed independently, and have their own lifecycle. Driver abstracts **connection and invocation**, not the services themselves.

MCP is our first concrete protocol implementation. A2A, ACP, and future protocols can be extended via `register_handler_type()`.

## Architecture Overview

The Driver Layer consists of five core components:

| Component            | Responsibility                                                                       |
| -------------------- | ------------------------------------------------------------------------------------ |
| **DriverCard**       | Driver's profile: identity, protocol, endpoint, credential references, access policy |
| **DriverHandler**    | Driver's executor: policy adjudication → protocol execution                          |
| **DriverCapability** | Unified abstraction of protocol operations as Agent-consumable descriptions          |
| **Access Policy**    | Multi-dimensional adjudication: Subject × Principal × Target × Condition → Effect    |
| **DriverManager**    | Central manager: type registration + instance building + capability routing          |

```
┌────────────────────────────────────────────────────────────────┐
│                        Driver Layer                             │
│                                                                │
│  DriverManager ──builds──▶ DriverHandler                       │
│       │                         │                              │
│       │ reads/persists          │ holds ref                    │
│       ▼                         ▼                              │
│  ┌─────────────────────────────────────────────────────────────┐
│  │ DriverCard (YAML)                                            │
│  │ name · protocol · endpoint · credentials · policy            │
│  └─────────────────────────────────────────────────────────────┘
│                                                                │
│  Capability: capability_id + kind + action + schema            │
│  Access Policy: ABAC (Subject × Principal × Target → Effect)   │
└────────────────────────────────────────────────────────────────┘
                          ▲ invoke_capability()
                          │
┌─────────────────────────┴──────────────────────────────────────┐
│ Agent Runtime                                                   │
│   build_agent() → Toolkit: [DriverCapabilityTool(cap, invoker)] │
│   LLM → tool_call → invoker → Handler → protocol exec → result │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Card-Handler Separation

DriverCard is a pure static declaration (YAML file); the Handler is its runtime instance. This separation brings three benefits:

- Cards are version-controllable and human-auditable
- Handlers can be rebuilt independently without losing configuration
- The same Card format can support different Handler implementations

### 2. Mandatory Governance Pipeline

Every invocation must pass through the `_authorize_invocation()` governance pipeline — policy adjudication first, protocol execution second. This is not an optional middleware but an **enforced constraint embedded in the Handler invocation path**.

```
invoke_capability()
  └─ _authorize_invocation()     ← mandatory
       ├─ evaluate_policy(ctx)   → allow / deny / ask
       └─ _request_approval(ctx) → delegates to ApprovalGate (on ask)
  └─ protocol_execute(...)       ← executes only after policy passes
```

### 3. Capability URI as Stable Identifier

Every capability is uniquely identified by a URI, persistently referenceable across sessions:

```
driver://{protocol}/{driver_name}/{kind_plural}/{name}#{action}
```

Examples:

- `driver://mcp/github-mcp/tools/create_issue#invoke`
- `driver://a2a/translate-agent/agents/translate#invoke`

The Agent doesn't need to know whether a capability comes from MCP or A2A — it only sees a unified `DriverCapability` description and a single `invoke_capability()` entry point.

### 4. Four-Layer Credential Decoupling

Credential management uses a four-layer architecture that completely separates declaration from secrets:

```
Layer 1: CredentialRef (reference declaration in Card)
Layer 2: AsyncCredentialStore (encrypted storage)
Layer 3: CredentialProvider (resolution + refresh)
Layer 4: ResolvedCredential (runtime credential injected into Handler)
```

Cards never contain plaintext secrets — only references. The Provider layer supports dynamic registration; non-standard OAuth flows (DingTalk, Feishu, etc.) are adapted by injecting custom `TokenExchanger` implementations.

### 5. True Open-Closed Extension

Adding a new protocol requires only three steps:

1. Implement `XxxDriverHandler` — override `_setup`/`_teardown` + `list_capabilities`/`invoke_capability`
2. Register: `manager.register_handler_type("xxx", XxxDriverHandler)`
3. Declare: create a YAML file (`protocol: xxx`)

No existing code needs modification. `protocol` is a string (not an enum), ensuring true Open-Closed compliance.

## Access Policy: Per-Tool Access Control

Access Policy employs an ABAC (Attribute-Based Access Control) model with four-dimensional adjudication:

| Dimension | Mapping         | Description                                   |
| --------- | --------------- | --------------------------------------------- |
| Subject   | Caller identity | `user:xxx`, `session:xxx`, `channel:xxx`, `*` |
| Resource  | Target          | `{ kind: "tool", name: "search_issues" }`     |
| Principal | Request source  | Which channel/app the request originates from |
| Condition | Environment     | Time window constraints                       |

Three adjudication effects:

- **allow** — Execute immediately
- **deny** — Block and return error
- **ask** — Suspend awaiting human approval (implemented via injected `ApprovalGate` protocol)

**Priority resolution**: When multiple rules match, they are sorted by Target specificity > Principal specificity > Subject specificity > Strictness, with the most specific rule winning.

This means you can:

- Default `ask` all invocations, but `allow` admin users from Console
- `deny` everyone for specific dangerous tools, even when the default policy is `allow`
- `allow` during business hours on weekdays, `ask` otherwise

## Quick Start: MCP Driver

Here's a complete MCP Driver configuration demonstrating credential binding and per-tool access policy:

```yaml
# drivers/mcp/hello-mcp.yaml
name: hello-mcp
protocol: mcp
endpoint:
  transport: stdio
  command: python
  args: ["./mcp_servers/hello_server.py"]
  env:
    ECHO_SECRET:
      source: credential
      credential: static
      field: ECHO_SECRET
config:
  display_name: Hello MCP
  description: Local stdio MCP demo with print_content and get_secret_status tools
enabled: true
policy:
  default_effect: ask
  rules:
    - subject: "*"
      effect: deny
      target: { kind: tool, name: get_secret_status }
```

This configuration does three things:

1. **Declares connection** — Launches a local Python MCP Server via stdio
2. **Binds credentials** — The `ECHO_SECRET` env var is resolved from the credential store; no plaintext in the Card
3. **Defines access policy** — All invocations require approval by default (`ask`), but `get_secret_status` is completely forbidden (`deny`)

### Console Management

In the Console under **Agent → MCP**, click **Tools & Access** on any MCP client card to visually manage access policies:

![Access Policy Console Panel](https://img.alicdn.com/imgextra/i3/O1CN01tpnV8w1XnOfo2bOIE_!!6000000002968-0-tps-3840-2080.jpg)

- Set client-level default effect (Ask / Allow / Deny)
- Add override rules for specific source channels and users
- Set independent access policies for individual tools
- Changes take effect immediately upon save — no restart required

## End-to-End Invocation Flow

A complete Driver invocation traverses the following stages:

```
User request → list_capabilities() → build_agent(toolkit)
→ LLM decides to call a tool
→ DriverCapabilityTool.__call__()
→ DriverManager.invoke_capability()
  → parse capability_id → route to correct Handler
  → Handler._authorize_invocation()  [policy adjudication]
  → Handler.protocol_execute()       [protocol execution]
→ DriverInvocationResult → Agent continues reasoning
```

Driver connections are persistent at the Workspace level (MCP client sessions stay alive in-process), while Agents and Toolkits are rebuilt per-request. This ensures the right balance between **resource reuse** and **isolation safety**.

## Looking Ahead

The Driver module establishes a unified external capability access foundation for the QwenPaw Agent system. MCP protocol support is now shipped; A2A and ACP Handler skeletons are ready. Future directions include:

- **More protocols** — Full A2A (Agent-to-Agent) and ACP protocol implementations
- **Observability** — Invocation chain tracing and policy adjudication audit logs

Driver's design philosophy: **Let Agents focus on reasoning; let Drivers handle the complexity of connection.** No matter how external protocols evolve, Agents always see a unified Capability model.
