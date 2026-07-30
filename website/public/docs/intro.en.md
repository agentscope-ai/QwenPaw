# Introduction

This page explains what NousAIPaw is, what it can do, and how to get started
step by step with the documentation.

---

## What is NousAIPaw?

NousAIPaw is a **personal assistant** that runs in your own environment.

![console fig](https://img.alicdn.com/imgextra/i2/O1CN01EP1ra01iOAcBvF0TC_!!6000000004402-2-tps-3822-2070.png)

- **Multi-channel chat** — Talk through DingTalk, Feishu, Discord, Telegram,
  and more.
- **Multi-agent collaboration** — Create multiple independent agents, each with
  its own configuration, memory, and skills. They can communicate and work
  together through collaboration skills to complete complex tasks.
- **Scheduled execution** — Run tasks automatically on your configured schedule.
- **Powered by Skills — unlimited possibilities** — Built-in skills include
  scheduled tasks, PDF and forms, Word/Excel/PPT document processing, news
  summaries, file reading, and more. Extend capabilities through [Skills](./skills).
- **Local model support** — Run large language models locally without API keys,
  completely offline.
- **All data stays local** — No third-party hosting.
- **Multi-layer security** — Built-in tool protection, file access control,
  skill security scanning, and more to ensure safe operation.

NousAIPaw is built by the [AgentScope team](https://github.com/agentscope-ai) on
[AgentScope](https://github.com/agentscope-ai/agentscope),
[AgentScope Runtime](https://github.com/agentscope-ai/agentscope-runtime), and
[ReMe](https://github.com/agentscope-ai/ReMe).

For a high-level tour of how NousAIPaw is put together — the Agent OS design and its
AgentScope foundation — see [Architecture](./architecture).

---

## How do you use NousAIPaw?

There are two main ways to use NousAIPaw:

1. **Chat in messaging apps**
   Send messages in DingTalk, Feishu, WeChat, Discord, Telegram, or other apps,
   and NousAIPaw replies in the same app. Whether looking things up, managing todos,
   or answering questions — it all depends on your enabled Skills. A single
   NousAIPaw instance can connect to multiple apps, responding in whichever channel
   you're using.

2. **Scheduled execution**
   No need to send messages manually each time. NousAIPaw can run automatically at
   set times:
   - Send a fixed message to a channel (e.g., "Good morning" to DingTalk at 9am);
   - Ask NousAIPaw a question and send the answer to a channel (e.g., every 2 hours
     ask "What are my todos?" and post to DingTalk);
   - Run a scheduled check-in or digest: use your prepared questions to query
     NousAIPaw and send the answers to your last active channel.

After installation, connecting at least one channel, and starting the service,
you can chat with NousAIPaw in DingTalk, Feishu, QQ, and other apps, and enjoy
scheduled messages and check-ins. What it can do depends on which Skills
you've enabled.

---

## Key concepts in the documentation

- **Console** — NousAIPaw's built-in web management interface. Chat, configure
  channels, manage skills, set up models, and more. See [Console](./console).
- **Channel** — Where you talk to NousAIPaw (DingTalk, Feishu, QQ, Discord,
  iMessage, etc.). Configure step by step in [Channels](./channels).
- **Heartbeat** — Ask NousAIPaw your prepared questions at fixed intervals, and
  optionally send the answers to your last active channel. See
  [Heartbeat](./heartbeat).
- **Scheduled tasks** — Multiple tasks, each with independent time configuration
  (send X daily at 9am, ask NousAIPaw Y every 2 hours, etc.), managed through the
  Console or [CLI](./cli).
- **Skill pool and workspace skills** — The skill pool is a shared skill
  repository. Workspace skills are local copies that an agent actually uses
  when running. See [Skills](./skills).
- **MCP and tools** — MCP (Model Context Protocol) is a standard protocol for
  connecting external tool servers to extend capabilities. Tools are NousAIPaw's
  built-in core abilities (reading/writing files, executing commands, browser,
  etc.). See [MCP and Tools](./mcp).
- **Agent/Workspace** — Starting from v0.1.0, NousAIPaw supports multi-agent,
  allowing multiple independent AI agents to run. Each agent has its own
  workspace, configuration, memory, skills, and conversation history. Agents
  can communicate and collaborate through collaboration skills to complete
  complex tasks. See [Multi-Agent](./multi-agent).
- **Security mechanisms** — NousAIPaw provides multi-layer security, including
  tool protection (intercept dangerous command parameters), file protection
  (restrict sensitive path access), and skill scanner (check skill package
  security). See [Security](./security).

Each concept is explained in detail in its corresponding chapter.

---

## Suggested reading and setup order

1. **[Quick start](./quickstart)** — Get the service running in three commands.
2. **[Console](./console)** — After the service starts, open the Console in
   your browser (`http://127.0.0.1:8088/`). **This is the central hub for
   configuring and using NousAIPaw.** Start by chatting and configuring models in
   the Console to understand how NousAIPaw works.
3. **[Models](./models)** — Configure API keys for cloud LLM providers or
   download local models. This is a **required prerequisite** for using NousAIPaw.
4. **Configure and use as needed**:
   - [Channels](./channels) — Connect DingTalk / Feishu / WeChat / Discord / Telegram to chat with NousAIPaw in those apps;
   - [Skills](./skills) — Understand and extend NousAIPaw's capabilities;
   - [MCP and Tools](./mcp) — Connect external MCP tool servers;
   - [Magic Commands](./commands) — Use special commands to quickly control conversation state (like `/new` for new conversation, `/clear` to clear history, `/stop` to stop tasks, `/restart` to restart service, etc.) without waiting for AI to understand;
   - [Security](./security) — Configure tool protection, file protection, skill security scanning, and other security mechanisms;
   - [Heartbeat](./heartbeat) — Set up scheduled check-ins or digests (optional);
   - [Scheduled tasks](./console#scheduled-tasks) or [CLI](./cli) — Scheduled tasks, `qwenpaw doctor` diagnostics, `qwenpaw doctor fix`, and more;
   - [Multi-Agent](./multi-agent) — Multi-agent configuration, management, and collaboration (v0.1.0+ feature);
   - [Config & working directory](./config) — Working directory and config file details.
