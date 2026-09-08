# QwenPaw-Data Ecosystem Integration

**Status:** Design proposal for review

**Scope:** QwenPaw core, the `qwenpaw-data` PawApp, and their integration with QwenPaw-Data

**Non-goal:** This document does not change QwenPaw-Data's ability to run independently

## Executive summary

QwenPaw-Data already provides the analytical engine needed for graph-grounded BI: governed datasource access, semantic and graph context, analytical skills, an agent runtime, HTTP/SSE APIs, MCP, artifacts, and scheduling. QwenPaw already provides the surrounding personal-agent ecosystem: user and channel interaction, managed agents, web and browser research, MCP clients, tool governance, agent-to-agent delegation, skills, notifications, and PawApps.

The gap is composition. QwenPaw-Data's deepest analysis flow is currently reached through its own Data console or channel middleware. Other QwenPaw apps and agents can call four granular Context tools, but they cannot submit a complete analytical job with external evidence and receive portable, authorized results. QwenPaw also lacks a shared artifact contract, so app-to-app exchange currently devolves into bespoke URLs, embedded payloads, or unsafe file paths.

The promised land is:

> QwenPaw-Data becomes QwenPaw's governed analytical intelligence layer. Any authorized agent or app can contribute evidence, request traceable analysis against governed enterprise data, and consume reusable reports, tables, charts, and datasets. QwenPaw-Data remains a self-sufficient product outside QwenPaw.

The recommended route is deliberately narrow:

1. Expose a complete QPD analysis run as one governed QwenPaw tool.
2. Let the managed `qwenpaw-data` agent use QwenPaw's existing web, browser, MCP, and agent-delegation capabilities for research.
3. Add an immutable, host-owned, opaque artifact primitive for cross-app data exchange.
4. Adapt those artifacts to QPD's existing attachment and generated-artifact APIs.
5. Prove one full research-to-analysis-to-second-app workflow before introducing broader platform abstractions.

MCP remains important, but it is not the inter-app bus. QPD's Context MCP remains its internal analytical tool boundary; QwenPaw's MCP clients remain the way agents access external research systems. Evidence crosses the application boundary as authorized artifacts, not copied MCP credentials.

## Goals

- Make complete QPD analysis reusable from any authorized QwenPaw agent.
- Allow web, browser, MCP, and other-agent research to enrich governed data analysis.
- Allow apps to exchange evidence and analytical outputs without sharing filesystem paths or service credentials.
- Preserve source, datasource, computation, and producer provenance across the workflow.
- Keep all tool calls and data access under QwenPaw and QPD governance.
- Keep QPD packages independent of QwenPaw.
- Reuse working QwenPaw and QPD primitives before creating new infrastructure.

## Non-goals

- Turning QwenPaw into a general data platform or object store.
- Replacing QPD Context MCP, HTTP/SSE APIs, Data console, channel middleware, or engine cron.
- Giving PawApps arbitrary access to each other's HTTP routes, storage, sessions, or files.
- Automatically copying host MCP credentials into QPD sidecars.
- Building a distributed event bus, semantic-memory platform, or general workflow engine.
- Coupling QPD packages to QwenPaw APIs or types.

## Status quo

### QwenPaw capabilities available today

#### PawApp composition

A PawApp can register app-scoped HTTP routes, governed tools, slash commands, middleware, managed services, managed agents, skill providers, prompt sections, dependencies, and lifecycle hooks. Standard PawApp capabilities provide authenticated chat, streamed chat, sessions, storage, toast, and notifications.

References:

- `src/qwenpaw/pawapp/app.py:121-318`
- `src/qwenpaw/pawapp/app.py:334-465`
- `src/qwenpaw/pawapp/app.py:769-806`

PawApp storage and chat sessions are intentionally app-scoped. This is a sound isolation boundary, not an inter-app exchange mechanism.

References:

- `src/qwenpaw/pawapp/context.py:28-80`
- `src/qwenpaw/pawapp/context.py:365-418`

#### Governed tools

Plugins can register globally named tools. Registration claims ownership, enters the governance system, bridges the tool into runtime configuration, and is cleaned up on unload. PawApp code can also invoke registered tools through its context.

References:

- `src/qwenpaw/plugins/api.py:762-904`
- `src/qwenpaw/pawapp/context.py:83-98`
- `src/qwenpaw/pawapp/context.py:621-654`

This is the best existing execution seam for exposing QPD analysis to the agent ecosystem. It already carries policy, timeout, cancellation, and runtime behavior. It should be used before inventing a separate capability bus.

#### Research and browsing

QwenPaw provides governed `web_search` and `web_fetch` tools, a browser tool, and configurable search providers. Apps do not need to duplicate provider integrations to gain external research capability.

References:

- `src/qwenpaw/agents/tools/web_search.py:136-198`
- `src/qwenpaw/agents/tools/web_search.py:201-272`
- `src/qwenpaw/agents/tools/browser.py:18-34`
- `src/qwenpaw/agents/tools/websearch/factory.py:15-44`

The Creator PawApp demonstrates a richer app-specific grounding pipeline with normalized provider fallback and durable project assets. It is a useful product example, but its provider code should not be copied into QPD.

References:

- `plugins/apps/qwenpaw-creator/backend/services/web_grounding/providers/search.py:156-263`
- `plugins/apps/qwenpaw-creator/backend/services/web_grounding/providers/adapters.py:118-209`
- `plugins/apps/qwenpaw-creator/backend/services/web_grounding/pipeline.py:180-247`

#### MCP clients

QwenPaw supports stdio, Streamable HTTP, and SSE MCP clients. MCP calls pass through policy authorization, and managed agent profiles retain user-owned MCP configuration.

References:

- `src/qwenpaw/drivers/handlers/mcp.py:64-99`
- `src/qwenpaw/drivers/handlers/mcp.py:118-238`
- `src/qwenpaw/pawapp/agent.py:95-160`

QwenPaw does not currently expose a stable PawApp API for registering or discovering MCP servers. MCP is presently an agent configuration and tool-execution seam, not a PawApp-to-PawApp protocol.

#### Agent-to-agent delegation

Agents can synchronously consult another configured agent or submit a background task and continue it through session/task identifiers.

References:

- `src/qwenpaw/agents/tools/agent_management.py:579-670`
- `src/qwenpaw/agents/tools/agent_management.py:673-714`

The Agent Kanban app demonstrates app-driven agent execution and event streaming, but it relies on private workspace and session internals. Its product behavior is instructive; its implementation should not become the public integration contract.

References:

- `plugins/apps/agent-kanban/backend/main.py:460-505`
- `plugins/apps/agent-kanban/backend/main.py:530-590`

#### Missing QwenPaw platform primitives

No stable public primitive currently exists for:

- a typed app capability registry;
- deterministic app-to-app RPC;
- a shared artifact registry or cross-app file handle;
- a durable inter-app event bus;
- a public PawApp scheduler facade;
- app access to semantic long-term memory.

The absence of these APIs should not be papered over with direct registry access, sibling app routes, workspace internals, or raw paths.

### QwenPaw-Data capabilities available today

#### Context and DataBridge

Context exposes semantic, metric, dataset, dimension, graph, experience, datasource, and governed query capabilities. Its unified Context Management API supports semantic search, event search, entity exploration, read-only SQL, result download, and experience recall.

References:

- `packages/qwenpaw-data-context/src/context_manager/api/server.py:697-738`
- `packages/qwenpaw-data-context/src/context_manager/api/cm_api.py:1378-1535`
- `packages/qwenpaw-data-context/src/context_manager/api/cm_api.py:1764-1914`
- `packages/qwenpaw-data-context/src/context_manager/api/cm_api.py:2074-2135`

Context's FastMCP server is mounted at `/mcp/v1/cm` and includes search, domain, metric, dimension, dataset, entity, experience, and SQL tools.

References:

- `packages/qwenpaw-data-context/src/context_manager/mcp/cm_server.py:260-682`
- `packages/qwenpaw-data-context/src/context_manager/mcp/cm_server.py:686-742`

#### Analysis engine

The engine exposes sessions, chats, SSE events, planning, traces, feedback, steering, clarification, preferences, datasources, cron, settlement, artifacts, files, and attachment-aware console routes.

References:

- `packages/qwenpaw-data-host-core/src/qwenpaw_data/host/core/api/app.py:225-266`
- `packages/qwenpaw-data-host-core/src/qwenpaw_data/host/core/api/routers/console.py:41-128`
- `packages/qwenpaw-data-host-core/src/qwenpaw_data/host/core/api/routers/artifacts.py:17-76`
- `packages/qwenpaw-data-host-core/src/qwenpaw_data/host/core/api/routers/cron.py:29-134`

The runtime combines orchestration, workspace tools, MCP, skills, and optional subagents. Context MCP is provisioned into the engine workspace as the `databridge` client.

References:

- `packages/qwenpaw-data-host-core/src/qwenpaw_data/host/core/agent/toolkit.py:213-302`
- `plugins/apps/qwenpaw-data/backend/runtime.py:121-178`

QPD therefore does not need QwenPaw to perform analysis. QwenPaw adds ecosystem composition and delivery.

### Current qwenpaw-data PawApp integration

The PawApp currently provides:

- managed Context and engine services;
- an app-owned managed agent;
- skills and an analysis prompt;
- Context and engine gateways;
- `/data` and `/datasource` channel controls;
- channel-to-engine session mapping and SSE translation;
- four governed Context tools:
  - `qwenpaw_data_search_context`;
  - `qwenpaw_data_list_domains`;
  - `qwenpaw_data_explore_entity`;
  - `qwenpaw_data_execute_sql`.

References:

- `plugins/apps/qwenpaw-data/backend/main.py:92-272`
- `plugins/apps/qwenpaw-data/backend/main.py:384-416`
- `plugins/apps/qwenpaw-data/backend/main.py:1030-1105`
- `plugins/apps/qwenpaw-data/backend/bridge/middleware.py:78-228`

The browser-facing gateways are intentionally allowlisted and inject server-held credentials. They must not become arbitrary service proxies.

References:

- `plugins/apps/qwenpaw-data/backend/context_gateway.py:17-47`
- `plugins/apps/qwenpaw-data/backend/context_gateway.py:148-241`
- `plugins/apps/qwenpaw-data/backend/engine_gateway.py:17-44`
- `plugins/apps/qwenpaw-data/backend/engine_gateway.py:228-279`

The bridge client already supports engine session creation, chat, clarification, datasource listing, artifact download, and SSE consumption.

Reference:

- `plugins/apps/qwenpaw-data/backend/bridge/engine_client.py:90-203`

### Present integration gaps

1. The complete QPD analysis runtime is not exposed as one governed QwenPaw tool.
2. The managed `qwenpaw-data` agent is not explicitly designed to orchestrate QwenPaw web, browser, MCP, and other-agent research before QPD analysis.
3. External evidence cannot be passed to the engine through a stable host-owned artifact reference.
4. Engine artifacts remain engine-session paths, downloads, or message blocks rather than portable cross-app objects.
5. QwenPaw, QPD engine, and Context session identities are separate; no common transaction or provenance envelope spans them.
6. Other apps have no stable way to receive QPD tables, charts, reports, or datasets while preserving authorization and provenance.

## Architectural boundaries

### QwenPaw core owns

- Authenticated user, agent, app, channel, and session context.
- Tool and MCP governance.
- Agent-to-agent delegation.
- PawApp lifecycle and app-scoped SDKs.
- Host-owned cross-app artifact custody, grants, download, retention, and audit.
- User-facing web, browser, and general research integrations.

QwenPaw core must not own analytical semantics, datasource logic, metric definitions, or QPD orchestration.

### The qwenpaw-data PawApp owns

- Adapting QwenPaw requests and artifacts to QPD HTTP/SSE APIs.
- Exposing complete QPD analysis as a governed QwenPaw tool.
- The managed QwenPaw-Data agent persona and orchestration policy.
- Mapping QwenPaw correlations to QPD sessions privately.
- Republishing QPD outputs as host artifacts with sanitized provenance.
- Data-app UI that connects ecosystem workflows to the embedded analytical cockpit.

The PawApp must not expose sidecar tokens, paths, internal session IDs, or unrestricted proxies.

### QwenPaw-Data owns

- Context/DataBridge semantics and graph retrieval.
- Datasource governance and read-only query enforcement.
- Analytical planning, execution, skills, and subagents.
- Engine sessions, events, attachments, artifacts, traces, and cron.
- Context MCP and independent CLI/headless/HTTP operation.

QPD packages must not import QwenPaw SDK types or require QwenPaw at runtime.

## Key design decisions

### 1. MCP is a tool transport, not the universal app bus

MCP is appropriate when an agent needs to discover and invoke tools. It is not sufficient by itself for app-owned binary artifacts, user/app grants, immutable provenance, or UI lifecycle. Treating every app as an MCP server would duplicate application APIs and force data exchange into tool payloads.

The intended split is:

- QPD engine → Context MCP for governed analytical context.
- QwenPaw agent → research MCP for external systems.
- App/agent → artifact references for evidence and outputs.
- Agent → governed QwenPaw tool for complete QPD analysis.

### 2. Use existing tools and agents before a capability bus

A new typed capability registry would add ownership, discovery, schema, versioning, policy, invocation, unload, and error semantics. QwenPaw's governed global tools and agent delegation already cover the first valuable workflows.

A capability broker should be added only after a concrete non-agent, deterministic app-to-app invocation cannot reasonably use the tool/agent contract.

### 3. Artifacts, not paths, are the data-interchange boundary

Cross-app exchange must use opaque immutable references. Raw filesystem paths leak topology, bypass ownership, fail across sandboxes, and create lifetime ambiguity. Signed QPD share URLs are useful for QPD delivery but are not the host-wide ownership contract.

### 4. Copy across trust boundaries

When an artifact enters QPD, the PawApp copies authorized bytes into a QPD attachment. When QPD emits an artifact, the PawApp copies those bytes into host custody. This costs I/O but gives each system a clear ownership, lifecycle, and integrity boundary.

### 5. Provenance is first-class

An analytical artifact must retain enough information to answer:

- Who and which app produced it?
- Which input artifacts and source digests contributed?
- Which datasource was used?
- Which tool/schema version produced it?
- When was it produced?
- Which parts are external evidence, retrieved organizational facts, computed results, or inference?

Secrets, local paths, tokens, and private URLs are never provenance.

## Target workflows

### Research to governed analysis

```text
User
  │
  ▼
QwenPaw research agent
  ├── web_search / web_fetch / browser
  ├── configured research MCPs
  └── delegated research agents
  │
  ▼
Cited evidence artifact
  │
  ▼
qwenpaw_data_run_analysis
  ├── QPD Context MCP / graph grounding
  ├── governed datasource queries
  └── QPD analytical skills and subagents
  │
  ▼
Summary + report/table/chart artifacts
```

### App to analysis

1. A producer PawApp publishes an artifact and grants `qwenpaw-data` read access.
2. Its agent or backend invokes the governed analysis tool with the artifact ID.
3. The PawApp resolves and copies the bytes into the QPD engine attachment API.
4. QPD performs analysis without knowing the source PawApp.

### Analysis to app

1. QPD emits `artifact.registered` events.
2. The PawApp downloads each artifact through the authenticated engine client.
3. QwenPaw stores immutable bytes and returns opaque references.
4. Authorized apps render, download, import, or analyze those references.

### Scheduled analysis

- Data-console-native recurring analysis remains on QPD engine cron.
- Ecosystem workflows initially use QwenPaw's agent scheduling.
- A PawApp scheduler facade is considered only after another app needs to create governed jobs programmatically.

## Proposed contracts

The following contracts describe intent. Exact field names may change during implementation review.

### Full analysis request v1

```json
{
  "schema": "qwenpaw-data.analysis-request/v1",
  "question": "Compare current conversion performance with external market evidence",
  "datasource_id": "sales-production",
  "evidence_artifact_ids": ["art_..."],
  "options": {
    "max_runtime_seconds": 1800
  },
  "correlation_id": "caller-generated-idempotency-key"
}
```

Rules:

- `question` is required and bounded.
- Datasource authorization is resolved by QPD, not implied by artifact access.
- Evidence artifacts must be owned by the user and granted to `qwenpaw-data`.
- Supported media types and byte limits are explicit.
- Correlation IDs are scoped to user, caller app/agent, tool version, and request digest.
- Caller identity never comes from this payload.

### Full analysis result v1

```json
{
  "schema": "qwenpaw-data.analysis-result/v1",
  "status": "completed",
  "summary": "...",
  "warnings": [],
  "artifacts": [
    {
      "id": "art_...",
      "schema": "qwenpaw.artifact-ref/v1"
    }
  ],
  "provenance": {
    "datasource_id": "sales-production",
    "input_artifact_ids": ["art_..."],
    "producer": "qwenpaw-data",
    "tool": "qwenpaw_data_run_analysis",
    "tool_version": "1"
  }
}
```

Other terminal statuses include `clarification_required`, `cancelled`, `failed`, and `timed_out`. Internal engine paths, URLs, tokens, and session IDs are excluded.

### PawArtifactRef v1

```json
{
  "schema": "qwenpaw.artifact-ref/v1",
  "id": "art_...",
  "owner_user_id": "...",
  "producer_app_id": "qwenpaw-data",
  "name": "conversion-analysis.csv",
  "media_type": "text/csv",
  "size": 4812,
  "sha256": "...",
  "content_schema": "qwenpaw.tabular/csv-v1",
  "created_at": "...",
  "expires_at": null,
  "consumer_app_ids": ["qwenpaw-data", "qwenpaw-creator"],
  "provenance": {}
}
```

Storage and authorization rules:

- The ID is opaque and non-enumerable.
- Bytes are immutable and content-addressed internally.
- Core stores bytes under host custody; the public reference contains no path.
- Reads require the authenticated owner and an app grant.
- Unauthorized lookups do not reveal whether an artifact exists.
- Publication enforces streaming size/quota limits and verifies the digest.
- Metadata is bounded and sanitized against secrets, paths, and credential-bearing URLs.
- Revocation blocks future reads; retention cleanup removes unreferenced expired bytes.

## Phased roadmap

### Phase 1: Reusable complete analysis

Add one PawApp application service around the existing engine API and expose it as `qwenpaw_data_run_analysis`.

Critical files:

- New `plugins/apps/qwenpaw-data/backend/analysis_service.py`
- `plugins/apps/qwenpaw-data/backend/bridge/engine_client.py`
- `plugins/apps/qwenpaw-data/backend/bridge/events.py`
- `plugins/apps/qwenpaw-data/backend/main.py`

The service will create a datasource-pinned session, start a chat, consume events, handle clarification/cancellation, and return a structured result. The existing Data console and channel bridge remain unchanged.

### Phase 2: Ecosystem-aware managed agent

Update the managed agent to orchestrate:

1. Context/KG retrieval for organizational meaning.
2. QwenPaw web, browser, and research MCP tools for external evidence.
3. Other QwenPaw agents for focused research.
4. The complete QPD analysis tool for governed synthesis.

Critical files:

- `plugins/apps/qwenpaw-data/agents/qwenpaw-data/en/SOUL.md`
- `plugins/apps/qwenpaw-data/agents/qwenpaw-data/en/PROFILE.md`
- `plugins/apps/qwenpaw-data/backend/main.py`

Existing user MCP, model, channel, tool, and security configuration remains untouched.

### Phase 3: Host artifact exchange

Add the minimal immutable artifact primitive.

Critical files:

- New `src/qwenpaw/pawapp/artifact.py`
- `src/qwenpaw/pawapp/context.py`
- `src/qwenpaw/pawapp/app.py`
- `src/qwenpaw/pawapp/__init__.py`
- `console/src/plugins/pawapp-sdk/types.ts`
- the corresponding PawApp SDK implementation

This phase includes storage, grants, authenticated metadata/download, revocation, retention, quotas, and security tests. It does not include a catalog, event bus, or mutable documents.

### Phase 4: QPD artifact adapter

Connect host artifacts to QPD's existing APIs:

- Resolve authorized inputs.
- Upload bounded evidence as engine attachments.
- Use attachment IDs in engine chat.
- Download generated QPD artifacts.
- Publish outputs into host custody with provenance.

Initially support text, Markdown, CSV, JSON, and agreed tabular formats. Unsupported or oversized data fails at the PawApp boundary.

### Phase 5: Prove a vertical slice

Use a small fixture producer/consumer PawApp to demonstrate:

1. Research creates a cited Markdown artifact.
2. QwenPaw-Data analyzes it against the demo datasource.
3. QPD generates a table/report/chart.
4. The output is published as a host artifact.
5. An authorized second app consumes it.
6. An unauthorized app and user are denied.

The fixture avoids prematurely coupling the foundation to Creator or Kanban.

### Phase 6: Data-app experience

Add an “Ecosystem research” entry that opens standard PawApp chat with the managed `qwenpaw-data` agent. Keep the embedded Data console as the deep analytical cockpit.

Critical files:

- `plugins/apps/qwenpaw-data/ui/src/App.tsx`
- `plugins/apps/qwenpaw-data/ui/src/sdk.ts`
- focused new UI components under `plugins/apps/qwenpaw-data/ui/src/`

The UI should render artifact actions and provenance, and visually distinguish external research, organizational context, computed data, and inference.

### Phase 7: Ecosystem adoption

Only after the vertical slice is stable:

- Creator imports QPD reports, charts, and data into projects.
- Kanban delegates and tracks QPD work through public agent/tool APIs.
- Other apps publish datasets or evidence with explicit grants.
- A scheduler facade or typed capability broker is evaluated against concrete second-consumer requirements.

## MCP strategy

### Context MCP

Keep Context MCP internal to QPD. It already exposes the correct analytical vocabulary and allows QPD to remain independently deployable.

### Research MCPs

Configure research MCP clients on QwenPaw agents. Those calls remain visible to QwenPaw governance and approval. Their outputs are normalized into evidence artifacts before entering QPD analysis.

### Why not mirror all QwenPaw MCPs into the engine?

- It leaks credentials and provider configuration across runtime boundaries.
- It bypasses QwenPaw's user and tool policy context.
- It makes QPD behavior depend on host-specific MCP naming and lifecycle.
- It blurs provenance between external research and governed organizational data.

### When a tool relay would be justified

A narrow QwenPaw-to-engine tool relay should be considered only if direct Data-console runs must call QwenPaw-governed research tools during an active QPD turn. It would require:

- an explicit per-tool allowlist;
- propagated authenticated identity and correlation;
- QwenPaw policy evaluation for every call;
- bounded payloads and timeouts;
- no credential disclosure to the engine;
- auditable distinction between relayed research and Context MCP calls.

That requirement is not yet proven. The managed QwenPaw agent should be tried first.

## Security and trust model

- User identity comes from authenticated QwenPaw request state.
- Caller app identity comes from the registered PawApp context.
- Datasource authorization remains QPD's responsibility.
- Tool authorization remains QwenPaw's responsibility.
- Artifacts require both user ownership and app grants.
- Sidecar credentials remain server-side.
- Gateways remain allowlisted.
- Raw local paths never cross app boundaries.
- Shared metadata contains no tokens, passwords, connection strings, signed private URLs, or local paths.
- Every cross-boundary byte stream is size-bounded and digest-verified.
- Cancellation propagates from QwenPaw tool execution to the active QPD chat.

## Risks and mitigations

### Duplicate orchestration layers

**Risk:** QwenPaw agents and QPD agents both plan, research, and delegate.

**Mitigation:** QwenPaw owns ecosystem research and routing; QPD owns analytical execution against governed data. The complete-analysis tool is the explicit handoff.

### Artifact store scope creep

**Risk:** The artifact primitive becomes a general document database.

**Mitigation:** Keep v1 immutable, opaque, byte-oriented, quota-bound, and grant-based. Defer search, mutation, collaboration, and domain catalogs.

### Long-running tool behavior

**Risk:** Full analysis exceeds normal tool timeouts or disconnects.

**Mitigation:** Reuse QwenPaw cancellation/offload behavior, preserve correlation IDs, and define explicit terminal states. Do not hide a detached engine run behind a synchronous success response.

### Session and identity mismatch

**Risk:** QwenPaw, engine, and Context session identifiers are confused or leaked.

**Mitigation:** Keep an app-private correlation record; public contracts expose only host artifact IDs and correlation IDs.

### Provenance inflation

**Risk:** Metadata becomes unbounded or leaks confidential context.

**Mitigation:** Define a small schema, field and byte limits, allowlisted keys, and private diagnostic records separate from shared provenance.

### Premature platform work

**Risk:** A capability bus or event system is built without real consumers.

**Mitigation:** Require the governed tool + artifact vertical slice and a second concrete consumer before adding either abstraction.

## Explicit deferrals

The following are not part of the initial implementation:

- general capability discovery and app-to-app RPC;
- arbitrary cross-app HTTP calls;
- a durable inter-app event bus;
- cross-app mutable files or filesystem mounts;
- automatic MCP credential propagation;
- shared semantic-memory APIs;
- a distributed job system;
- replacement of QPD cron or QwenPaw agent scheduling;
- direct QPD dependencies on QwenPaw;
- rewrites of the Data console or channel bridge.

## Success criteria

### Product outcome

A user can ask a QwenPaw agent a question requiring current external evidence and governed enterprise data. The ecosystem gathers cited research, QPD grounds and computes the answer, and another authorized app can reuse the resulting report, table, or chart without downloading and re-uploading files manually.

### Functional proof

1. QwenPaw web search or a configured MCP source produces a cited evidence dossier.
2. The dossier is published as an artifact and granted to `qwenpaw-data`.
3. `qwenpaw_data_run_analysis` completes a real QPD engine run against a selected datasource.
4. QPD-generated artifacts are republished byte-for-byte with correct MIME type, digest, and provenance.
5. A second authorized fixture app opens or downloads an output.
6. An unauthorized app and another user cannot discover or read it.
7. Cancellation stops an active QPD chat.
8. Artifact references remain valid after a host restart.
9. Existing Data-console analysis and `/data` channel takeover still work.

### Engineering gates

- Unit tests cover analysis completion, clarification, cancellation, timeout, malformed SSE, engine failure, and datasource pinning.
- Artifact tests cover immutability, ownership, grants, expiry, revocation, quota, traversal, symlink handling, metadata sanitization, and digest validation.
- Existing qwenpaw-data gateway, datasource, bridge, console snapshot, packaging, and runtime tests remain green.
- Runtime verification observes the real browser, engine SSE, artifact download, and authorization denial paths.

## Open review questions

1. **Artifact retention:** Should v1 default to permanent user-owned retention, a bounded TTL, or retention inherited from the producing app?
2. **Grant model:** Is an explicit consumer-app allowlist sufficient for v1, or must artifacts also support one-time delegation tokens?
3. **Size boundary:** What default and maximum artifact sizes fit local QwenPaw operation without turning the host into bulk storage?
4. **Supported inputs:** Should v1 stop at text/Markdown/CSV/JSON, or include PDF and spreadsheet ingestion immediately?
5. **Long-running UX:** Should complete analysis initially use foreground tool offload, a first-class background task handle, or both?
6. **Clarification ownership:** When QPD requests clarification, should the managed QwenPaw agent relay it conversationally, or should the tool return a structured interruption requiring a second invocation?
7. **Datasource selection:** Should callers always specify a datasource, inherit a user/app default, or be prompted when more than one is available?
8. **First real consumer:** After the fixture proves the contract, should Creator import analytical media first, or should Kanban schedule and track analyses first?
9. **Audit visibility:** Which provenance and cross-app grant events need a user-visible audit UI in the first release?
10. **Core placement:** Should artifact custody live specifically under PawApp core, or as a broader QwenPaw service usable by channels and non-PawApp agents from day one?

## Recommended delivery order

1. Reusable complete-analysis application service and governed tool.
2. Ecosystem-aware managed-agent behavior using existing research tools and MCP clients.
3. Minimal host artifact exchange and frontend SDK.
4. QPD input/output artifact adapter.
5. Producer → QPD → consumer vertical slice.
6. Data-app ecosystem research UI.
7. Creator, Kanban, scheduler, or capability-broker follow-ups based on demonstrated demand.

Each phase should include focused tests and runtime observation before the next platform layer is added.