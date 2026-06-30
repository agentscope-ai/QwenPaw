# Terminal UI (TUI)

The QwenPaw **TUI** is a full-screen chat interface that runs entirely in your terminal. It talks to the _same_ agent as the Console and the IM Channels — same memory, same skills, same MCP tools, same sessions — but without leaving the keyboard. If you live in a terminal, this is the fastest way to chat with your agent, drive a task, or pick up a session you started somewhere else.

It is also the most natural surface for **Coding Mode**: launch it from inside a repo and the agent treats that directory as its workshop.

![QwenPaw TUI](https://img.alicdn.com/imgextra/i2/O1CN01IULzib1TRAzigIcqG_!!6000000002378-2-tps-2350-1312.png)

---

## Launching

The TUI ships with the `qwenpaw` CLI. Running `qwenpaw` with no arguments opens it directly:

```bash
qwenpaw                       # open a chat with the active agent
qwenpaw tui                   # same thing, with explicit options
qwenpaw tui --agent NAME      # chat with a specific agent
qwenpaw tui --resume <id>     # resume a previous session and continue it
```

To start a **project-bound (Coding Mode)** session, point it at a directory:

```bash
qwenpaw .                     # use the current directory as the project
qwenpaw tui /path/to/repo     # use an explicit directory
```

This enables Coding-Mode prompt and tool behavior **for that TUI session only** — it does not change the project saved in `agent.json` or selected in the Console. See [Coding Mode](/docs/coding-mode) for what changes under the hood.

> No separate install or server to manage: the TUI launches its own `qwenpaw acp` backend using the interpreter it ships in, so it always drives the same install/venv as your `qwenpaw` command.

---

## The Layout

| Area                    | What it shows                                                                                                                                                                      |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Status bar** (top)    | The current agent, model, session id, running token usage (`tok ↑in ↓out`), and a busy/ready indicator.                                                                            |
| **Transcript** (middle) | The conversation — your messages, the agent's replies, collapsible _thinking_ and _tool call_ panels, plans, and file links.                                                       |
| **Prompt** (bottom)     | Where you type. The hint line reminds you of the core gestures: `/` for commands, `enter` to send, `shift+enter` for a newline, `esc` to interrupt, and paste for files/long text. |

---

## Basic Features

**Streaming chat.** Replies stream in token by token. The agent's reasoning and each tool call appear as collapsible panels so you can follow along or fold them away.

**Queue while busy.** You don't have to wait for a turn to finish. Type and press `enter` and your message is **queued**, then sent automatically when the current turn ends. Press `up` to recall and edit the last queued message.

**Interrupt.** Press `esc` to cancel the in-flight turn (or clear the input if you haven't sent anything yet).

**Sessions & resume.** Every chat is a session shared with the rest of QwenPaw. Use `/resume` to pick a recent session from the suggestions, or `/resume list` to browse all of them. You can also resume on launch with `qwenpaw tui --resume <id>`.

**Paste files & long text.** Paste an image or a file path and the TUI attaches it for the agent; paste a long block of text and it is stored as an attachment instead of flooding the prompt. Works with `data:` URLs too.

**Tool permissions.** When the agent wants to run a tool that needs your approval, an inline permission prompt appears — approve or deny without leaving the TUI.

**Inspection mode.** Toggle `/inspect` (or `ctrl+i`) to reveal deeper thought and tool-call detail when you want to see exactly what the agent is doing.

**Themes.** Run `/theme` to open the gallery, or `/theme <vibe>` to repaint the background to a named theme or a free-form prompt.

---

## Keyboard Shortcuts

| Key                 | Action                                              |
| ------------------- | --------------------------------------------------- |
| `enter`             | Send the message (or queue it if the agent is busy) |
| `shift+enter`       | Insert a newline                                    |
| `esc`               | Interrupt the current turn / clear the input        |
| `up`                | Recall and edit the last queued message             |
| `ctrl+i`            | Toggle inspection (deeper thought/tool detail)      |
| `ctrl+t`            | Hide / show tool-call panels                        |
| `ctrl+c` / `ctrl+q` | Quit                                                |

---

## Slash Commands

Type `/` in the prompt to get inline auto-suggestions. There are two kinds of commands.

### Handled by the TUI

These control the terminal interface itself:

| Command    | Purpose                                                 |
| ---------- | ------------------------------------------------------- |
| `/help`    | Show the TUI shortcuts and command hints                |
| `/resume`  | Resume a recent session (`/resume list` to browse all)  |
| `/theme`   | Open the theme gallery, or `/theme <vibe>` to apply one |
| `/inspect` | Toggle deeper thought / tool-call detail                |

### Handled by the agent

Everything else you type starting with `/` is forwarded to the QwenPaw agent — the **same magic commands** available in the Console and Channels, for example `/model`, `/clear`, `/compact`, `/skills`, and `/status`. The TUI advertises whatever commands the connected agent supports, so the suggestion list always matches your agent. See [Magic Commands](/docs/commands) for the full catalog.

---

## How It Works

You don't need to know the internals to use the TUI, but a one-paragraph mental model helps explain why sessions, memory, and tools "just work" the same as everywhere else.

The TUI is a thin **client**. It is a [Textual](https://textual.textualize.io/) terminal app that drives a local QwenPaw backend over **ACP** (the [Agent Client Protocol](/docs/acp-integration)). On launch it spawns `qwenpaw acp` as a subprocess and speaks ACP to it; all the real work — the model calls, memory, skills, MCP tools, session storage — happens in that backend, exactly the same backend the Console and Channels use.

<svg viewBox="0 0 760 220" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The QwenPaw TUI is a thin Textual client that drives a local qwenpaw acp backend over ACP via a stdio subprocess." style="width:100%;height:auto;max-width:700px;display:block;margin:1.5rem auto;font-family:ui-sans-serif,system-ui,sans-serif;">
<defs>
<marker id="tui-arrow" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto" markerUnits="userSpaceOnUse">
<path d="M0,0 L7,3 L0,6 Z" fill="var(--color-primary, #ff9d4d)"></path>
</marker>
</defs>
<rect x="24" y="62" width="244" height="96" rx="12" fill="var(--color-primary, #ff9d4d)" fill-opacity="0.08" stroke="var(--color-primary, #ff9d4d)" stroke-width="1.5"></rect>
<text x="146" y="98" text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">QwenPaw TUI</text>
<text x="146" y="122" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">Textual terminal app</text>
<text x="146" y="141" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">renders · forwards input</text>
<rect x="492" y="52" width="244" height="116" rx="12" fill="currentColor" fill-opacity="0.04" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"></rect>
<text x="614" y="86" text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">qwenpaw acp</text>
<text x="614" y="110" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">agent · LLM · tools</text>
<text x="614" y="129" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">memory · skills · MCP</text>
<text x="614" y="148" text-anchor="middle" font-size="13" fill="currentColor" opacity="0.7">session store</text>
<line x1="274" y1="100" x2="486" y2="100" stroke="var(--color-primary, #ff9d4d)" stroke-width="1.5" marker-end="url(#tui-arrow)"></line>
<line x1="486" y1="130" x2="274" y2="130" stroke="var(--color-primary, #ff9d4d)" stroke-width="1.5" marker-end="url(#tui-arrow)"></line>
<text x="380" y="90" text-anchor="middle" font-size="13" font-weight="600" fill="var(--color-primary, #ff9d4d)">ACP</text>
<text x="380" y="152" text-anchor="middle" font-size="12" fill="currentColor" opacity="0.6">stdio subprocess</text>
</svg>

Two practical consequences:

- **Sessions are shared.** A chat you start in the TUI shows up in `/resume` later, and you can resume a session that originated in the Console or a Channel — it's all one session store.
- **The TUI stays light.** Because it only renders and forwards input, it starts fast and the heavy agent runtime lives in the backend process.

---

## See Also

- [Coding Mode](/docs/coding-mode) — what changes when you launch the TUI inside a repo
- [Magic Commands](/docs/commands) — the full list of agent slash commands
- [ACP Integration](/docs/acp-integration) — the protocol the TUI speaks to the backend
- [CLI](/docs/cli) — other `qwenpaw` subcommands
