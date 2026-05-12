# Design Philosophy & Architecture

## What We're Building

Large models today are remarkably capable. They can follow complex instructions, reason through multi-step problems, and produce high-quality content. But a model on its own only does one thing: take some input and generate some output. It has no memory. It doesn't know who it is. It can't touch anything in the real world. And the moment a conversation ends, everything is gone.

QwenPaw turns a large model from a "content generation engine" into an agent that **persists and grows over time**.

Our approach is to build an **Agent OS**: an operating system purpose-built for AI agents. Think about what an OS provides to a process. Isolated memory. A file system. I/O. Inter-process communication. A security model. An agent that truly runs on its own needs all of these things too. QwenPaw is that entire stack.

The industry calls this layer of infrastructure beyond the model an Agent Harness. The model handles reasoning and generation. The harness turns the model's output into real-world action. The model is the replaceable brain. QwenPaw is everything that lets that brain live in the real world.

---

## Five Conditions for an Agent to Exist

What does an AI agent actually need to truly "exist" in a user's world?

| Condition  | What It Means                                                           |
| ---------- | ----------------------------------------------------------------------- |
| Workspace  | A place of its own, where state persists                                |
| Persona    | A sense of identity: consistent behavior, consistent style              |
| Memory     | The ability to accumulate experience and understand context across time |
| Capability | The ability to perceive the environment and act on it                   |
| Connection | The ability to interact with people, other agents, and external systems |

Every core subsystem in QwenPaw maps to one of these conditions.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                         QwenPaw                             │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             Multi-Agent Orchestration                 │  │
│  │                                                      │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │  │
│  │  │ Workspace A │ │ Workspace B │ │ Workspace C │ .. │  │
│  │  │  Persona    │ │  Persona    │ │  Persona    │    │  │
│  │  │  Memory     │ │  Memory     │ │  Memory     │    │  │
│  │  │  Tools      │ │  Tools      │ │  Tools      │    │  │
│  │  │  Skills     │ │  Skills     │ │  Skills     │    │  │
│  │  │  MCP        │ │  MCP        │ │  MCP        │    │  │
│  │  │  Plugins    │ │  Plugins    │ │  Plugins    │    │  │
│  │  │  Model Core │ │  Model Core │ │  Model Core │    │  │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘    │  │
│  │         └─────── Collaboration ─────────┘            │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Security · Tool Guard · Skill Scanner · Approval     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Channels · ACP · Console · RESTful API               │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## Workspace: Where an Agent Lives

Every agent in QwenPaw gets its own workspace.

The workspace is the **container that holds an agent** within the Agent OS. Everything the agent has, persona, memory, skills, chat history, scheduled tasks, configuration, all lives inside it. A workspace is just a directory on disk, filled with human-readable files.

We call this approach **state externalization**: every piece of agent state is laid out as files, not hidden inside a database. The benefits are straightforward. Want to know why the agent behaved a certain way? Open the file and read it. Want to change its behavior? Edit a Markdown file. Need to back up or migrate? Copy the directory. The files keep evolving as the agent is used. Not a static template, but a living space that grows.

Workspaces also make agents something you can package and share. Configure an agent the way you like, bundle it, send it to someone, and they can import it right away. When multiple agents run inside the same QwenPaw instance, each one has its own workspace. Isolation by default. Sharing only when explicitly intended.

---

## Persona: Who the Agent Is

Persona determines how the agent understands a message and how it responds.

In QwenPaw, persona is a set of Markdown files stored in the workspace. When the agent starts up, it reads these files and weaves them into the system prompt. Different files handle different aspects. Some define core values and behavioral boundaries. Some define the agent's name, style, and expertise. Some define workflows and collaboration patterns. Everything is written in natural language, so the model reads it natively, no format conversion needed. Edit a file and the change takes effect immediately. No restart required.

Over time, as the agent interacts with users more and more, it can even enrich its own profile. Persona isn't a fixed label. It grows with experience.

---

## Memory: From Amnesia to Growing Understanding

An AI assistant without memory starts every conversation as if meeting you for the first time. QwenPaw splits memory into two layers.

**Working memory** is the context of the current conversation, what the model can directly see. Context windows have a size limit, so QwenPaw uses smart compression when things get tight, keeping the most important information while making room for new input. Working memory is temporary. Once the conversation ends, it's gone.

**Long-term memory** is anything that gets persisted into files in the workspace. User preferences and key facts distilled from conversations. Skill knowledge the agent has learned. Scripts and documents it has produced along the way. But storing isn't enough. The agent also needs to **organize** and **recall**. As memories accumulate, they need periodic consolidation to stay useful. When a new conversation begins, the system automatically searches for relevant memories and injects them back into context.

The two layers are in constant **circulation**. Important information from conversations settles into long-term memory. Relevant long-term memories get pulled back in to inform current reasoning. This loop keeps turning, and the agent understands you better over time.

Looking further ahead, the ultimate form of memory isn't passive storage. It's an **active cognitive engine**. The agent discovers patterns in what it remembers, anticipates what you need, and reaches out before you ask.

---

## Capability: The Model Thinks, Tools Act

The model is the brain. It reasons and makes decisions. But the actual work of interacting with the environment, reading files, running commands, browsing the web, that falls to tools. QwenPaw offers four parallel ways to plug in capabilities:

- Built-in Tools: file operations, shell commands, web browsing, screen capture, and more. Ready to use out of the box.
- Skills: capability descriptions written in natural language, plus optional scripts. The agent reads a skill description and picks it up. Skills can be installed, removed, and routed by channel at runtime. Anyone can write and share them.
- MCP: external tool services connected via the [MCP protocol](https://modelcontextprotocol.io), with hot-swapping and automatic reconnection.
- Plugins: developers inject custom tool implementations without touching the core codebase.

These four are equals. The model **orchestrates them all** through a unified loop: observe, think, act, reflect, repeat until the job is done. Regardless of where a capability comes from, the model invokes it the same way. The Agent OS abstracts away the differences.

The boundaries between these capabilities aren't fixed, either. When the agent figures out a workflow that works, it can crystallize it into a new skill. It can **invent new capabilities through practice**, and the whole capability ecosystem keeps growing on its own.

---

## Connection: Reaching People, Agents, and the World

An agent shouldn't be locked inside a single interface. QwenPaw connects along multiple dimensions:

- Channels: simultaneously plugged into DingTalk, Feishu, WeChat, Discord, Telegram, and over a dozen other platforms. Wherever users are, the agent shows up.
- ACP: through the [Agent Communication Protocol](https://agentcommunicationprotocol.dev), agents can be discovered and called by external systems, and can proactively reach out to collaborate with other agents.
- Console & API: the Console provides visual management. The RESTful API enables programmatic integration into larger systems.
- Human-in-the-loop: approval gates, confirmation checks, feedback correction. People aren't just users; they're collaborators in the agent's runtime. When things are uncertain, the agent asks.

The guiding principle here is **openness**. Connect to any platform. Collaborate with any system that speaks standard protocols. And always keep humans in the loop.

---

## How It All Comes Together

Everything above isn't a collection of independent features. It's **one system**. Here's what a typical interaction looks like end to end.

The agent runs inside its own workspace. Persona files tell it what identity and style to use. Before the message reaches the model, the memory system searches long-term memory for anything relevant to the current topic and injects it into context. The model then reasons over the full picture and decides which tools or skills to call. Maybe it reads a file. Maybe it hits an MCP service. Maybe it runs through a workflow defined in a skill. After the task is done, valuable information from the conversation gets automatically distilled and deposited back into long-term memory. The agent's understanding of you just got a little deeper.

This cycle runs with every interaction. The agent isn't finishing a task and shutting down. It's continuously existing and growing.
