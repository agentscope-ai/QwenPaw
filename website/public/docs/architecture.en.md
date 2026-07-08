# Architecture

This page gives a high-level view of how QwenPaw is built: the **Agent OS** it implements and the **AgentScope** foundation it runs on. It sticks to the parts of the design that stay stable and avoids naming individual modules and classes, which change often. Anything not yet built is called out and linked to the [Roadmap](./roadmap).

If you only want to _use_ QwenPaw, start with [Introduction](./intro) and [Quick start](./quickstart). This page is for contributors and anyone who wants to understand what runs under the hood.

---

## The Agent OS in one picture

QwenPaw runs entirely in your own environment as a long-lived service. One installation hosts **multiple independent agents**. Each agent owns an isolated **workspace**, and a **runtime** executes every request, wiring together the agent's model, tools, memory, skills, and connectors under a governance and sandbox layer.

Think of QwenPaw as a small operating system for agents. The "kernel" is [AgentScope 2.0](https://github.com/agentscope-ai/agentscope), which provides the agent loop, session store, event stream, and tool layer in-process. QwenPaw is the OS layer on top. It owns the **resource axes** an agent works with — workspace files, memory, skills, drivers (connectors), and models — plus the trust spine that controls access to them.

<svg viewBox="0 0 900 684" width="100%" role="img" aria-label="QwenPaw Agent OS at a glance: a runtime scheduling tier on top; below it a per-agent workspace holding colour-coded resource lanes (memory, skills, tools, others), a governance panel, and a sandbox execution base, next to a separate drivers (connectors) column; the whole thing sits on the AgentScope foundation." xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpMapArrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="currentColor" fill-opacity="0.45"/>
    </marker>
  </defs>
  <!-- Title -->
  <text x="450" y="30" text-anchor="middle" font-size="16" font-weight="700" fill="currentColor">QwenPaw Agent OS — one picture</text>
  <text x="450" y="49" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">Runtime on top · Workspace ‖ Drivers below · built on the AgentScope foundation</text>
  <!-- Surfaces strip -->
  <rect x="20" y="60" width="860" height="40" rx="9" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.18"/>
  <text x="34" y="84" font-size="10" letter-spacing="1.2" font-weight="700" fill="currentColor" fill-opacity="0.7">SURFACES</text>
  <g font-size="11" fill="currentColor">
    <rect x="170" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="254" y="84" text-anchor="middle">Channels (IM)</text>
    <rect x="348" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="432" y="84" text-anchor="middle">Console (Web)</text>
    <rect x="526" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="610" y="84" text-anchor="middle">Terminal UI</text>
    <rect x="704" y="68" width="168" height="24" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="788" y="84" text-anchor="middle">CLI</text>
  </g>
  <line x1="450" y1="100" x2="450" y2="112" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" marker-end="url(#qpMapArrow)"/>
  <!-- Runtime tier -->
  <rect x="20" y="114" width="860" height="118" rx="10" fill="#a855f7" fill-opacity="0.05" stroke="#a855f7" stroke-opacity="0.45"/>
  <rect x="30" y="124" width="12" height="12" rx="3" fill="#a855f7"/>
  <text x="50" y="134" font-size="11.5" font-weight="700" fill="#a855f7">RUNTIME · request scheduling · top layer</text>
  <text x="30" y="153" font-size="10" fill="currentColor" fill-opacity="0.62">One installation hosts many agents — orchestrate · route · assemble · run · stream.</text>
  <g>
    <rect x="40" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="136" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">Request router</text><text x="136" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">to the addressed agent</text>
    <rect x="249" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="345" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">Runtime lifecycle</text><text x="345" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">hook stages · modes</text>
    <rect x="458" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="554" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">Agent — ReAct loop</text><text x="554" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">context strategy · per request</text>
    <rect x="667" y="164" width="193" height="54" rx="7" fill="#a855f7" fill-opacity="0.1" stroke="#a855f7" stroke-opacity="0.55"/><text x="763" y="188" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">Harness adapters</text><text x="763" y="205" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">external agents · ACP</text>
  </g>
  <line x1="450" y1="232" x2="450" y2="246" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" marker-end="url(#qpMapArrow)"/>
  <text x="462" y="244" font-size="9" fill="currentColor" fill-opacity="0.55">route to a workspace</text>
  <!-- Workspace container -->
  <rect x="20" y="248" width="690" height="336" rx="10" fill="currentColor" fill-opacity="0.02" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="34" y="272" font-size="12" font-weight="700" fill="currentColor">WORKSPACE · one isolated space per agent</text>
  <text x="34" y="288" font-size="10" fill="currentColor" fill-opacity="0.6">= resources · governance · sandbox  (governance + sandbox = the trust spine)</text>
  <!-- Resources sub-box -->
  <rect x="32" y="300" width="456" height="192" rx="8" fill="currentColor" fill-opacity="0.02" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="44" y="320" font-size="10.5" font-weight="700" fill="currentColor" fill-opacity="0.82">RESOURCES · what an agent works with</text>
  <!-- memory lane -->
  <rect x="44" y="330" width="102" height="140" rx="7" fill="#2fb26b" fill-opacity="0.07" stroke="#2fb26b" stroke-opacity="0.4"/>
  <text x="95" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#2fb26b">memory</text>
  <rect x="52" y="358" width="86" height="42" rx="6" fill="#2fb26b" fill-opacity="0.1" stroke="#2fb26b" stroke-opacity="0.5"/><text x="95" y="384" text-anchor="middle" font-size="10" fill="currentColor">Recall / write</text>
  <rect x="52" y="408" width="86" height="42" rx="6" fill="#2fb26b" fill-opacity="0.1" stroke="#2fb26b" stroke-opacity="0.5"/><text x="95" y="434" text-anchor="middle" font-size="10" fill="currentColor">Markdown files</text>
  <!-- skills lane -->
  <rect x="154" y="330" width="102" height="140" rx="7" fill="#e0a021" fill-opacity="0.07" stroke="#e0a021" stroke-opacity="0.4"/>
  <text x="205" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#e0a021">skills</text>
  <rect x="162" y="358" width="86" height="42" rx="6" fill="#e0a021" fill-opacity="0.1" stroke="#e0a021" stroke-opacity="0.5"/><text x="205" y="384" text-anchor="middle" font-size="10" fill="currentColor">Skill folders</text>
  <rect x="162" y="408" width="86" height="42" rx="6" fill="#e0a021" fill-opacity="0.1" stroke="#e0a021" stroke-opacity="0.5"/><text x="205" y="434" text-anchor="middle" font-size="10" fill="currentColor">Shared pool</text>
  <!-- tools lane -->
  <rect x="264" y="330" width="102" height="140" rx="7" fill="#12b0c6" fill-opacity="0.07" stroke="#12b0c6" stroke-opacity="0.4"/>
  <text x="315" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#12b0c6">tools</text>
  <rect x="272" y="358" width="86" height="42" rx="6" fill="#12b0c6" fill-opacity="0.1" stroke="#12b0c6" stroke-opacity="0.5"/><text x="315" y="384" text-anchor="middle" font-size="10" fill="currentColor">Files · shell</text>
  <rect x="272" y="408" width="86" height="42" rx="6" fill="#12b0c6" fill-opacity="0.1" stroke="#12b0c6" stroke-opacity="0.5"/><text x="315" y="434" text-anchor="middle" font-size="10" fill="currentColor">Search · web</text>
  <!-- others lane -->
  <rect x="374" y="330" width="102" height="140" rx="7" fill="#9d8579" fill-opacity="0.07" stroke="#9d8579" stroke-opacity="0.4"/>
  <text x="425" y="348" text-anchor="middle" font-size="11" font-weight="700" fill="#9d8579">others</text>
  <rect x="382" y="358" width="86" height="42" rx="6" fill="#9d8579" fill-opacity="0.1" stroke="#9d8579" stroke-opacity="0.5"/><text x="425" y="384" text-anchor="middle" font-size="10" fill="currentColor">Models</text>
  <rect x="382" y="408" width="86" height="42" rx="6" fill="#9d8579" fill-opacity="0.1" stroke="#9d8579" stroke-opacity="0.5"/><text x="425" y="434" text-anchor="middle" font-size="10" fill="currentColor">Sessions</text>
  <text x="260" y="484" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">All transparent on disk — Markdown, JSON, folders.</text>
  <!-- Governance sub-box -->
  <rect x="500" y="300" width="198" height="192" rx="8" fill="#4f8cf7" fill-opacity="0.06" stroke="#4f8cf7" stroke-opacity="0.5"/>
  <text x="512" y="320" font-size="11" font-weight="700" fill="#4f8cf7">GOVERNANCE</text>
  <text x="512" y="335" font-size="9.5" fill="currentColor" fill-opacity="0.6">every action passes through</text>
  <rect x="512" y="344" width="174" height="40" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="361" text-anchor="middle" font-size="10.5" font-weight="600" fill="currentColor">Governance policy</text><text x="599" y="376" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">allow · deny · ask · sandbox</text>
  <rect x="512" y="390" width="174" height="26" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="407" text-anchor="middle" font-size="10" fill="currentColor">Tool guard — content screening</text>
  <rect x="512" y="422" width="174" height="26" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="439" text-anchor="middle" font-size="10" fill="currentColor">Approvals · skill scanner</text>
  <rect x="512" y="454" width="174" height="26" rx="6" fill="#4f8cf7" fill-opacity="0.1" stroke="#4f8cf7" stroke-opacity="0.5"/><text x="599" y="471" text-anchor="middle" font-size="10" fill="currentColor">Encrypted secrets</text>
  <!-- Sandbox band -->
  <rect x="32" y="504" width="666" height="62" rx="8" fill="#f0921f" fill-opacity="0.08" stroke="#f0921f" stroke-opacity="0.5"/>
  <rect x="44" y="514" width="12" height="12" rx="3" fill="#f0921f"/>
  <text x="62" y="524" font-size="11" font-weight="700" fill="#f0921f">SANDBOX · execution base</text>
  <text x="250" y="524" font-size="9.5" fill="currentColor" fill-opacity="0.6">a fresh sandbox per tool call, destroyed after</text>
  <text x="365" y="548" text-anchor="middle" font-size="10.5" fill="currentColor">Native OS isolation — macOS seatbelt · Linux bubblewrap/landlock · Windows AppContainer · or none</text>
  <!-- Drivers column -->
  <rect x="722" y="248" width="158" height="336" rx="10" fill="#eb5545" fill-opacity="0.05" stroke="#eb5545" stroke-opacity="0.45"/>
  <rect x="734" y="266" width="12" height="12" rx="3" fill="#eb5545"/>
  <text x="752" y="276" font-size="11.5" font-weight="700" fill="#eb5545">DRIVERS</text>
  <text x="734" y="294" font-size="9.5" fill="currentColor" fill-opacity="0.6">reach external systems</text>
  <rect x="734" y="304" width="134" height="50" rx="7" fill="#eb5545" fill-opacity="0.1" stroke="#eb5545" stroke-opacity="0.55"/><text x="801" y="326" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">Connectors</text><text x="801" y="342" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">protocol-neutral layer</text>
  <rect x="734" y="362" width="134" height="50" rx="7" fill="#eb5545" fill-opacity="0.1" stroke="#eb5545" stroke-opacity="0.55"/><text x="801" y="384" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">MCP servers</text><text x="801" y="400" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">external tools → agent</text>
  <rect x="734" y="420" width="134" height="50" rx="7" fill="#eb5545" fill-opacity="0.1" stroke="#eb5545" stroke-opacity="0.55"/><text x="801" y="442" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">Credential + policy</text><text x="801" y="458" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.62">gated per call</text>
  <text x="801" y="500" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.6">Distinct from channels —</text>
  <text x="801" y="513" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.6">how people reach the agent.</text>
  <line x1="450" y1="584" x2="450" y2="596" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" marker-end="url(#qpMapArrow)"/>
  <!-- Foundation -->
  <rect x="20" y="596" width="860" height="48" rx="10" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/>
  <text x="450" y="618" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">FOUNDATION · AgentScope 2.0</text>
  <text x="450" y="634" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.62">agent loop · session · event stream · tool layer — used in-process as a library</text>
  <!-- Legend -->
  <text x="20" y="669" font-size="10" font-weight="700" fill="currentColor" fill-opacity="0.7">Legend</text>
  <g font-size="10" fill="currentColor">
    <rect x="76" y="659" width="12" height="12" rx="3" fill="#4f8cf7"/><text x="92" y="669">governance</text>
    <rect x="168" y="659" width="12" height="12" rx="3" fill="#2fb26b"/><text x="184" y="669">memory</text>
    <rect x="244" y="659" width="12" height="12" rx="3" fill="#e0a021"/><text x="260" y="669">skills</text>
    <rect x="308" y="659" width="12" height="12" rx="3" fill="#12b0c6"/><text x="324" y="669">tools</text>
    <rect x="370" y="659" width="12" height="12" rx="3" fill="#9d8579"/><text x="386" y="669">others</text>
    <rect x="440" y="659" width="12" height="12" rx="3" fill="#f0921f"/><text x="456" y="669">sandbox</text>
    <rect x="522" y="659" width="12" height="12" rx="3" fill="#eb5545"/><text x="538" y="669">drivers</text>
    <rect x="596" y="659" width="12" height="12" rx="3" fill="#a855f7"/><text x="612" y="669">runtime</text>
  </g>
  <text x="690" y="669" font-size="9" fill="currentColor" fill-opacity="0.5">colours group the OS by concern</text>
</svg>

---

## The foundation: AgentScope

QwenPaw is built on **AgentScope 2.0** and uses it as a library. AgentScope provides its runtime in-process, so there is no separate runtime service. QwenPaw reuses:

- the **reason-and-act (ReAct) agent loop** that QwenPaw builds on;
- the **message and serializable-state contracts** used for streaming and for saving and restoring a session;
- the **tool-calling layer** every QwenPaw tool plugs into;
- a **working-directory abstraction** QwenPaw extends with its own tools;
- the **streaming event model** the agent emits as it thinks and calls tools.

Everything else here — the workspace boundary, the request lifecycle, the resource axes, the trust spine — is QwenPaw's own design on top of these primitives.

---

## Workspace — the per-agent boundary

A **workspace** is the unit of isolation. One installation can run many agents, and each agent gets exactly one workspace: an on-disk directory plus the live services that operate on it. Workspaces load lazily the first time an agent is addressed, and shut down cleanly on stop. No agent can see another's files, memory, or conversations unless it explicitly messages the other.

Each workspace bundles two things: the **services** an agent needs at runtime (session and history, memory, connectors, channels, chats, scheduling), and a set of **extension registries** for tools, hooks, commands, and prompt fragments. Third-party **plugins** add to these registries — model providers, tools, hooks, slash commands, prompt sections, HTTP routes, and agent middleware — so you can extend the platform without forking it. See [Plugins](./plugins).

<svg viewBox="0 0 860 420" width="100%" role="img" aria-label="Workspace anatomy: a registry holds multiple isolated per-agent workspaces; each workspace bundles services and an on-disk directory." xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpWsArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- Registry -->
  <rect x="20" y="40" width="220" height="320" rx="10" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="130" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#ff9d4d">Agent registry</text>
  <text x="130" y="86" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">lazy-loads one workspace per agent</text>
  <g font-size="12.5" fill="currentColor">
    <rect x="44" y="104" width="172" height="40" rx="7" fill="#ff9d4d" fill-opacity="0.14" stroke="#ff9d4d" stroke-opacity="0.55"/><text x="130" y="129" text-anchor="middle" font-weight="600">Agent A (active)</text>
    <rect x="44" y="156" width="172" height="40" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="130" y="181" text-anchor="middle">Agent B</text>
    <rect x="44" y="208" width="172" height="40" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="130" y="233" text-anchor="middle">Agent C</text>
  </g>
  <text x="130" y="300" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6" font-style="italic">No shared state between</text>
  <text x="130" y="316" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6" font-style="italic">workspaces unless an agent</text>
  <text x="130" y="332" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6" font-style="italic">explicitly messages another.</text>
  <line x1="240" y1="124" x2="300" y2="124" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpWsArrow)"/>
  <!-- Expanded workspace -->
  <rect x="304" y="40" width="536" height="320" rx="10" fill="currentColor" fill-opacity="0.03" stroke="#ff9d4d" stroke-opacity="0.5"/>
  <text x="324" y="66" font-size="12.5" font-weight="700" fill="#ff9d4d">Workspace (Agent A)</text>
  <!-- Services column -->
  <text x="324" y="92" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">SERVICES</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="324" y="102" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="119" text-anchor="middle">Session &amp; history</text>
    <rect x="324" y="134" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="151" text-anchor="middle">Memory</text>
    <rect x="324" y="166" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="183" text-anchor="middle">Connectors (MCP)</text>
    <rect x="324" y="198" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="215" text-anchor="middle">Channels</text>
    <rect x="324" y="230" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="247" text-anchor="middle">Chats · scheduler</text>
    <rect x="324" y="262" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="440" y="279" text-anchor="middle">Tools · hooks · commands · prompts</text>
  </g>
  <!-- Disk column -->
  <text x="588" y="92" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">ON DISK · the workspace folder</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="588" y="102" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="119" text-anchor="middle">Config (plain JSON)</text>
    <rect x="588" y="134" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="151" text-anchor="middle">MEMORY.md · memory/*.md</text>
    <rect x="588" y="166" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="183" text-anchor="middle">Digests · skills</text>
    <rect x="588" y="198" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="215" text-anchor="middle">Connectors + credentials</text>
    <rect x="588" y="230" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="247" text-anchor="middle">Durable chat history</text>
    <rect x="588" y="262" width="232" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="704" y="279" text-anchor="middle">Shared skill pool</text>
  </g>
  <text x="572" y="324" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">Files stay human-readable and portable — the whole workspace can be backed up and restored.</text>
</svg>

The on-disk layout is transparent: configuration is plain JSON, memory is Markdown, and skills are folders. You can read, edit, and version-control any of it without QwenPaw running. The [Backup &amp; Restore](./backup) feature packs a workspace into a signed archive you can move between machines.

---

## Runtime — the request lifecycle

The runtime turns one incoming request into a stream of UI events. It runs as a fixed **lifecycle with hook points between stages**, so features can attach behavior without changing the core loop. A request is routed to the addressed agent's workspace, where the agent is **assembled for that request**, run, and streamed back.

<svg viewBox="0 0 820 600" width="100%" role="img" aria-label="The request lifecycle: hook stages interleaved with fixed steps for command dispatch, agent assembly, and execution, with error and cleanup handlers always running." xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpFlowArrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- legend -->
  <rect x="556" y="20" width="20" height="14" rx="3" fill="#ff9d4d" fill-opacity="0.14" stroke="#ff9d4d" stroke-opacity="0.55"/>
  <text x="582" y="31" font-size="10.5" fill="currentColor" fill-opacity="0.7">hook stage</text>
  <rect x="664" y="20" width="20" height="14" rx="3" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/>
  <text x="690" y="31" font-size="10.5" fill="currentColor" fill-opacity="0.7">fixed step</text>
  <!-- short flow arrows, one in each gap between consecutive boxes -->
  <g stroke="#ff9d4d" stroke-width="1.4">
    <line x1="250" y1="75" x2="250" y2="91" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="121" x2="250" y2="137" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="167" x2="250" y2="183" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="213" x2="250" y2="229" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="259" x2="250" y2="275" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="305" x2="250" y2="321" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="351" x2="250" y2="367" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="397" x2="250" y2="413" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="459" x2="250" y2="475" marker-end="url(#qpFlowArrow)"/>
    <line x1="250" y1="505" x2="250" y2="521" marker-end="url(#qpFlowArrow)"/>
  </g>
  <!-- rows -->
  <g font-size="12">
    <!-- input -->
    <rect x="90" y="44" width="320" height="30" rx="15" fill="#ff9d4d" fill-opacity="0.18" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="250" y="63" text-anchor="middle" font-weight="600" fill="currentColor">Incoming request (from a channel or schedule)</text>
    <rect x="90" y="92" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="110" text-anchor="middle" fill="currentColor">Before dispatch</text>
    <rect x="90" y="138" width="320" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="250" y="156" text-anchor="middle" fill="currentColor">Command dispatch</text>
    <text x="424" y="156" font-size="10.5" fill="currentColor" fill-opacity="0.6">/command → reply &amp; skip the agent</text>
    <rect x="90" y="184" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="202" text-anchor="middle" fill="currentColor">After dispatch</text>
    <rect x="90" y="230" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="248" text-anchor="middle" fill="currentColor">Before build</text>
    <text x="424" y="248" font-size="10.5" fill="currentColor" fill-opacity="0.6">load session · media · request context</text>
    <rect x="90" y="276" width="320" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="250" y="294" text-anchor="middle" fill="currentColor" font-weight="600">Assemble the agent</text>
    <text x="424" y="290" font-size="10.5" fill="currentColor" fill-opacity="0.6">model · tools · prompt</text>
    <text x="424" y="303" font-size="10.5" fill="currentColor" fill-opacity="0.6">memory · context strategy · policy</text>
    <rect x="90" y="322" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="340" text-anchor="middle" fill="currentColor">After build</text>
    <text x="424" y="340" font-size="10.5" fill="currentColor" fill-opacity="0.6">inject active-mode context</text>
    <rect x="90" y="368" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="386" text-anchor="middle" fill="currentColor">Before execute</text>
    <text x="424" y="386" font-size="10.5" fill="currentColor" fill-opacity="0.6">bootstrap · prompt refresh</text>
    <rect x="90" y="414" width="320" height="44" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="250" y="432" text-anchor="middle" fill="currentColor" font-weight="600">Run the agent</text><text x="250" y="448" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.65">ReAct loop, bounded by a max-iterations limit</text>
    <rect x="90" y="476" width="320" height="28" rx="7" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="250" y="494" text-anchor="middle" fill="currentColor">After response</text>
    <text x="424" y="494" font-size="10.5" fill="currentColor" fill-opacity="0.6">save session · scheduled-job writeback</text>
    <rect x="90" y="522" width="320" height="30" rx="15" fill="#ff9d4d" fill-opacity="0.18" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="250" y="541" text-anchor="middle" font-weight="600" fill="currentColor">Stream the response out</text>
  </g>
  <!-- error / cleanup bracket -->
  <path d="M70,92 q-14,0 -14,14 v384 q0,14 14,14" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.5"/>
  <text x="30" y="298" font-size="11" fill="currentColor" fill-opacity="0.7" transform="rotate(-90 30 298)" text-anchor="middle">On error · cleanup (always run)</text>
  <text x="250" y="576" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">Cleanup always runs: cancel the reply, close connectors, reset request state.</text>
</svg>

### Hooks, modes, and assembling the agent

**Hooks** are small units bound to a stage of the lifecycle. They can let a request continue, short-circuit it with a direct reply, or skip the agent entirely. Built-in hooks handle session load/save, first-run bootstrap, skill-environment setup, media processing, and optional tracing.

**Modes** bundle related commands, tools, hooks, and prompt fragments behind a single on/off switch. Two modes ship today:

- **Coding mode** adds project-aware tools (code search, inline diff editing) and a coding system prompt, scoped to a project directory. See [Coding Mode](./coding-mode).
- **Mission mode** runs long tasks as a two-phase loop: the agent first writes a plan, then iterates with implementation tools until every checkpoint passes.

**Assembling the agent** happens once per request: the agent config, model, tools, system prompt, memory, and context strategy come together, and every tool is wrapped so the governance layer always sees it. Building fresh each time keeps provisioning and policy out of the agent itself.

---

## The agent and its tools

QwenPaw's agent runs a **ReAct (reason-then-act) loop** bounded by a max-iterations limit, and receives all of its dependencies ready-made from the assembly step.

Tools carry **activation conditions** — which modes, skills, features, or sandbox resources they need — so each request sees only the tools it is allowed to use. Built-in tools cover file I/O, code and text search, shell execution, browser control and screenshots, media viewing, and multi-agent coordination.

Multiple agents coordinate two ways (see [Multi-Agent](./multi-agent)):

- **Internally** — one QwenPaw agent can message or spawn another in the same installation.
- **Externally** — through **ACP** (Agent Client Protocol), QwenPaw can spawn an external agent process and stream its work back as tool results, including handing a permission request back to the host for approval. See [ACP Integration](./acp-integration).

---

## Memory and context

QwenPaw separates two things that are easy to conflate: **memory** (what the agent remembers across conversations) and **context** (what fits in the model's window right now).

<svg viewBox="0 0 860 372" width="100%" role="img" aria-label="Memory is a pluggable backend over transparent Markdown files; context management is either summarizing compaction or the Scroll strategy with a durable store and a recall tool." xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpMemArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- MEMORY side -->
  <rect x="20" y="24" width="400" height="324" rx="10" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="40" y="50" font-size="12.5" font-weight="700" fill="#ff9d4d">MEMORY · across conversations</text>
  <rect x="40" y="64" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="83" text-anchor="middle" font-size="12" fill="currentColor">Memory integration (recall · write)</text>
  <line x1="220" y1="94" x2="220" y2="108" stroke="#ff9d4d" stroke-width="1.4" marker-end="url(#qpMemArrow)"/>
  <rect x="40" y="110" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="129" text-anchor="middle" font-size="12" fill="currentColor">Pluggable memory backend</text>
  <rect x="40" y="152" width="174" height="30" rx="7" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="127" y="171" text-anchor="middle" font-size="11.5" fill="currentColor">ReMe (default)</text>
  <rect x="226" y="152" width="174" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="313" y="171" text-anchor="middle" font-size="11.5" fill="currentColor">Plain Markdown</text>
  <text x="40" y="208" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">TRANSPARENT FILES IN THE WORKSPACE</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="40" y="218" width="360" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="235" text-anchor="middle">MEMORY.md — long-term notes</text>
    <rect x="40" y="250" width="360" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="267" text-anchor="middle">memory/YYYY-MM-DD.md — daily notes</text>
    <rect x="40" y="282" width="360" height="26" rx="6" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="220" y="299" text-anchor="middle">consolidated digests</text>
  </g>
  <text x="220" y="330" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">Recall, write, and consolidation run as background work.</text>
  <!-- CONTEXT side -->
  <rect x="440" y="24" width="400" height="324" rx="10" fill="currentColor" fill-opacity="0.03" stroke="currentColor" stroke-opacity="0.2"/>
  <text x="460" y="50" font-size="12.5" font-weight="700" fill="#ff9d4d">CONTEXT · the live window</text>
  <rect x="460" y="64" width="360" height="44" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="82" text-anchor="middle" font-size="12" fill="currentColor" font-weight="600">Summarizing compaction (default)</text><text x="640" y="98" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.65">older turns summarized once the window fills</text>
  <text x="460" y="132" font-size="11" letter-spacing="1" font-weight="700" fill="currentColor" fill-opacity="0.75">OR — SCROLL STRATEGY (opt-in)</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="460" y="142" width="360" height="30" rx="7" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="640" y="161" text-anchor="middle">Scroll strategy</text>
    <rect x="460" y="180" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="199" text-anchor="middle">Durable store — every turn kept</text>
    <rect x="460" y="218" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="237" text-anchor="middle">Index of turns scrolled out of the window</text>
    <rect x="460" y="256" width="360" height="30" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="640" y="275" text-anchor="middle">Recall tool — replay any earlier span</text>
  </g>
  <text x="640" y="318" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">Nothing is lost: evicted turns stay recallable on</text>
  <text x="640" y="332" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.6">demand rather than summarized away.</text>
</svg>

**Memory** is a pluggable backend. The default is built on the [ReMe](https://github.com/agentscope-ai/ReMe) memory library, which runs recall, write, and consolidation ("dream") as background work over the workspace; a simpler option reads and writes the same files directly. Either way the substrate is **human-readable Markdown** — `MEMORY.md` for durable notes and dated daily files — so memory is something you can open, audit, and edit. See [Memory](./memory) and [Memory-Evolving &amp; Proactive](./memory-evolving-and-proactive).

**Context** management is pluggable too. By default QwenPaw summarizes older turns once the window fills. The opt-in **Scroll** strategy instead keeps every turn in a durable store, maintains a compact index of what has scrolled out, and gives the agent a tool to replay any earlier span on demand, so long conversations stay fully recallable. See [Context](./context).

---

## Skills — the capability layer

Skills are how QwenPaw's abilities grow. A **skill is a folder**: instructions and metadata, plus an optional set of executable scripts. Built-in skills ship in language variants.

QwenPaw resolves which skills are active for a given workspace and channel, drawing from a per-workspace set and a shared pool. Each active skill becomes a tool the agent can invoke (or call as a `/skill-name` command). Skills install from external sources — GitHub, ModelScope, and others — through the [Skill Market](./skills).

Because skills can carry executable code, installation goes through the **skill scanner** (see the trust spine below) before a skill becomes usable. Read more in [Skills](./skills).

---

## Drivers and channels — reaching the outside world

QwenPaw distinguishes **channels** (how _people_ reach the agent) from **drivers** (how the agent reaches _external systems_).

**Channels** are the messaging surfaces. Each one converts its platform's native payloads to and from a common request/response shape, with access control, debouncing, and streaming. Built-in channels include DingTalk, Feishu, WeCom, WeChat, Discord, Slack, Telegram, QQ, and more, plus the web Console. See [Channels](./channels).

**Drivers** are a protocol-neutral **connector layer**. A connector declares its endpoint, its credential reference, and its policy; the system resolves credentials from an encrypted store and gates each call through policy and an approval step. The protocol implemented today is **MCP** (Model Context Protocol), which turns external tool servers into tools the agent can call. The abstraction is broader than MCP, so other connector protocols can slot in behind the same credential and policy model. See [MCP &amp; Built-in Tools](./mcp).

---

## Models — the cognitive engine

The model is the engine the agent thinks with, kept behind a stable interface so it can be swapped without disturbing the rest of the system.

- **Cloud providers** — OpenAI, Anthropic, Google Gemini, DashScope (Qwen), and OpenRouter, with sign-in flows where a provider needs them.
- **Local runtimes** — Ollama and LM Studio, plus fully on-device models via **llama.cpp** with no API key and no network.
- Each agent names the model it uses; capability probing records whether a model supports images or video, so unsupported inputs are rejected early.
- A **personalization** path can fine-tune a per-user model and serve the result like any other provider.

See [Models](./models) for configuration.

---

## The trust spine — security and governance

Every tool call and every external action passes through a layered trust spine before it can touch your machine or your data.

<svg viewBox="0 0 860 384" width="100%" role="img" aria-label="A tool call is wrapped by a policy check, evaluated by the governance policy to allow, deny, ask, or sandbox; allowed calls pass the tool guard and run inside a native OS sandbox." xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpSecArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- agent wants to call a tool -->
  <rect x="40" y="30" width="200" height="40" rx="8" fill="#ff9d4d" fill-opacity="0.16" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="140" y="55" text-anchor="middle" font-size="12.5" font-weight="600" fill="currentColor">Agent calls a tool</text>
  <line x1="240" y1="50" x2="296" y2="50" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <rect x="300" y="30" width="220" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="410" y="55" text-anchor="middle" font-size="12" fill="currentColor">Policy check (wraps every call)</text>
  <line x1="410" y1="70" x2="410" y2="92" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <!-- governance engine -->
  <rect x="270" y="96" width="280" height="58" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="410" y="120" text-anchor="middle" font-size="12.5" font-weight="600" fill="currentColor">Governance policy</text><text x="410" y="138" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.65">built-in rules + your rules → a decision</text>
  <!-- four outcomes -->
  <g font-size="11.5" fill="currentColor">
    <rect x="40" y="186" width="170" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="125" y="205" text-anchor="middle" font-weight="600">Deny</text><text x="125" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">blocked, reason returned</text>
    <rect x="226" y="186" width="170" height="40" rx="8" fill="#ff9d4d" fill-opacity="0.1" stroke="#ff9d4d" stroke-opacity="0.5"/><text x="311" y="205" text-anchor="middle" font-weight="600">Ask</text><text x="311" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">approval → you decide</text>
    <rect x="412" y="186" width="170" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="497" y="205" text-anchor="middle" font-weight="600">Sandbox</text><text x="497" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">force into isolation</text>
    <rect x="598" y="186" width="170" height="40" rx="8" fill="#ff9d4d" fill-opacity="0.16" stroke="#ff9d4d" stroke-opacity="0.6"/><text x="683" y="205" text-anchor="middle" font-weight="600">Allow</text><text x="683" y="219" text-anchor="middle" font-size="10" fill-opacity="0.65">proceed</text>
  </g>
  <g stroke="#ff9d4d" stroke-width="1.3">
    <line x1="330" y1="154" x2="160" y2="184" marker-end="url(#qpSecArrow)"/>
    <line x1="380" y1="154" x2="320" y2="184" marker-end="url(#qpSecArrow)"/>
    <line x1="440" y1="154" x2="500" y2="184" marker-end="url(#qpSecArrow)"/>
    <line x1="490" y1="154" x2="670" y2="184" marker-end="url(#qpSecArrow)"/>
  </g>
  <!-- approval note -->
  <text x="311" y="240" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.55">approve → proceeds as Allow</text>
  <!-- tool guard + sandbox -->
  <line x1="683" y1="226" x2="683" y2="252" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <rect x="560" y="256" width="246" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="683" y="275" text-anchor="middle" font-size="12" fill="currentColor">Tool guard — content screening</text><text x="683" y="289" text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.65">path · pattern · shell-evasion checks</text>
  <line x1="683" y1="296" x2="683" y2="320" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSecArrow)"/>
  <rect x="560" y="324" width="246" height="44" rx="8" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.55"/><text x="683" y="343" text-anchor="middle" font-size="12" font-weight="600" fill="currentColor">Execute in native OS sandbox</text><text x="683" y="358" text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.7">seatbelt · bubblewrap · landlock · appcontainer · none</text>
  <!-- side: skill scanner + secrets -->
  <rect x="40" y="256" width="280" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="180" y="275" text-anchor="middle" font-size="11.5" fill="currentColor">Skill scanner — gates skill installs</text><text x="180" y="289" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">static analysis before code can run</text>
  <rect x="40" y="324" width="280" height="40" rx="8" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3"/><text x="180" y="343" text-anchor="middle" font-size="11.5" fill="currentColor">Encrypted credential store</text><text x="180" y="357" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">provider keys &amp; connector secrets at rest</text>
</svg>

The layers:

- **Governance policy** — every tool call is checked against built-in rules plus your own rules and resolved to _allow_, _deny_, _ask_, or _sandbox_. The check is unavoidable because tools are wrapped before the agent can call them. An _ask_ raises an approval you answer from the Console or your IM channel.
- **Tool guard** — screens the _content_ of an allowed call for path traversal, sensitive files, risky patterns, and shell-evasion tricks.
- **Sandbox** — runs risky execution inside the host's native isolation: seatbelt on macOS, bubblewrap (preferred) or landlock on Linux, AppContainer on Windows, or none. A fresh sandbox is created per tool call with declared mounts and deny paths.
- **Skill scanner** — statically analyzes a skill's files before installation.
- **Encrypted secrets** — provider keys and connector credentials are encrypted at rest.

See [Security](./security) for the full policy model and configuration.

---

## Surfaces and operations

QwenPaw runs as a **long-lived service**, on your own machine or a server you control, with several front doors into the same runtime. Whichever surface you use, the agents, workspaces, memory, and policy underneath are the same.

<svg viewBox="0 0 860 290" width="100%" role="img" aria-label="One QwenPaw runtime reached through several surfaces (Console, desktop app, terminal UI, CLI, chat channels) and surrounded by operational capabilities (scheduling, inbox, backup)." xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif">
  <defs>
    <marker id="qpSurfArrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L6,3 L0,6 Z" fill="#ff9d4d"/>
    </marker>
  </defs>
  <!-- SURFACES column -->
  <text x="24" y="34" font-size="11" letter-spacing="1.5" font-weight="700" fill="#ff9d4d">SURFACES · how you reach it</text>
  <g font-size="12" fill="currentColor">
    <rect x="24" y="46" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="66" text-anchor="middle">Console — web hub</text>
    <rect x="24" y="86" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="106" text-anchor="middle">Desktop app (Beta)</text>
    <rect x="24" y="126" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="146" text-anchor="middle">Terminal UI</text>
    <rect x="24" y="166" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="186" text-anchor="middle">CLI + doctor</text>
    <rect x="24" y="206" width="252" height="32" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="150" y="226" text-anchor="middle">Chat channels</text>
  </g>
  <line x1="282" y1="150" x2="322" y2="150" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSurfArrow)"/>
  <text x="302" y="142" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">reach</text>
  <!-- center -->
  <rect x="326" y="100" width="208" height="100" rx="10" fill="#ff9d4d" fill-opacity="0.12" stroke="#ff9d4d" stroke-opacity="0.55"/>
  <text x="430" y="140" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">QwenPaw service</text>
  <text x="430" y="159" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.7">one runtime ·</text>
  <text x="430" y="173" text-anchor="middle" font-size="10.5" fill="currentColor" fill-opacity="0.7">per-agent workspaces</text>
  <line x1="538" y1="150" x2="578" y2="150" stroke="#ff9d4d" stroke-width="1.5" marker-end="url(#qpSurfArrow)"/>
  <text x="558" y="142" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.6">runs</text>
  <!-- OPERATIONS column -->
  <text x="584" y="34" font-size="11" letter-spacing="1.5" font-weight="700" fill="#ff9d4d">OPERATIONS · what keeps it running</text>
  <g font-size="11.5" fill="currentColor">
    <rect x="584" y="100" width="252" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="710" y="118" text-anchor="middle">Scheduling &amp; heartbeat</text>
    <rect x="584" y="136" width="252" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="710" y="154" text-anchor="middle">Proactive inbox</text>
    <rect x="584" y="172" width="252" height="28" rx="7" fill="currentColor" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.25"/><text x="710" y="190" text-anchor="middle">Backup &amp; restore</text>
  </g>
</svg>

### Surfaces

- **Console** — the primary web interface and management hub: real-time streaming chat plus configuration for agents, channels, models, skills and the skill market, connectors, security and approvals, backups, token usage, scheduled jobs, and a proactive-message inbox. See [Console](./console).
- **Desktop app** — the Console packaged as a cross-platform desktop application (Beta) with a bundled runtime and automatic updates, so it runs with no terminal and no manual setup. See [Desktop App](./desktop).
- **Terminal UI** — a full-screen terminal interface for chatting and managing agents from the shell, including project-scoped coding sessions; the bare `qwenpaw` command launches it. See [Terminal UI](./tui).
- **CLI** — scriptable `qwenpaw` commands for agents, providers, channels, skills, connectors, and scheduling, plus `qwenpaw doctor` for one-shot diagnostics and guided fixes. See [CLI](./cli).
- **Chat channels** — every messaging platform is itself a surface: people reach the agent from DingTalk, Feishu, Slack, Discord, and more. See [Channels](./channels).

### Operations

These capabilities make it practical to leave QwenPaw running unattended:

- **Scheduling and heartbeat** — run the agent on a timer and deliver the result to any channel (a morning digest, a periodic check-in). Scheduled runs use an isolated memory context, so automation never pollutes your interactive history. See [Cron Jobs](./cron) and [Heartbeat](./heartbeat).
- **Proactive inbox** — the agent can reach out on its own (reminders, digests, reflections), and those messages collect in a Console inbox you can review and route. See [Memory-Evolving &amp; Proactive](./memory-evolving-and-proactive).
- **Backup and restore** — a complete workspace (configuration, memory, skills, and optionally secrets) exports to a signed archive and restores wholesale or selectively. See [Backup &amp; Restore](./backup).

---

This page covers QwenPaw as it works today. For what's planned next, see the [Roadmap](./roadmap).
