# Agent Persona

CoPaw defines an agent's "persona" through a set of Markdown files that are loaded into the system prompt. These files determine the agent's behavioral style, working approach, and personality traits. By editing these files, you can shape the agent into your ideal assistant—whether that's a meticulous work aide, a warm life companion, or a technical expert.

---

## Persona Files

Agent persona files are Markdown documents stored in the agent's workspace directory. The workspace location is determined by the `COPAW_WORKING_DIR` environment variable (defaults to `~/.copaw`), with the full path being:

```
$COPAW_WORKING_DIR/workspaces/{agent_id}/
```

**Persona files are flexible and extensible.** The files shown below represent the default configuration, but you can freely add new Markdown files or remove existing ones. Any Markdown file enabled in the Console's **Agent → Workspace** page will be loaded into the system prompt.

### Default Persona Files

These files are included in the default configuration and loaded into the system prompt:

#### **AGENTS.md** - Workflows, Rules & Guidelines

Detailed operational specifications and workflows, including memory management strategies, safety guidelines, tool usage instructions, and more. This is the agent's "operating manual" that tells it how to complete various tasks.

**Main content:**

- How to use memory files (MEMORY.md, memory/YYYY-MM-DD.md)
- Safety and privacy guidelines
- Tool and Skills usage instructions
- Heartbeat-related rules (if enabled)

#### **SOUL.md** - Core Identity & Behavioral Principles

Defines the agent's values, style, and behavioral principles. This is the agent's "soul" that determines its personality and approach to interactions.

**Main content:**

- Core principles (how to interact with users)
- Boundaries and limits (what not to do)
- Style and tone (formal, casual, professional, etc.)
- Continuity guidance (how to maintain memory through files)

#### **PROFILE.md** - Identity & User Profile

Records the agent's identity settings and the user's personal information, helping the agent understand you better and provide personalized service.

**Main content:**

- **Identity** section: Agent's name, nature (AI assistant/bot/other), and style
- **User Profile** section: User's name, preferred address, preferences, and background

#### **MEMORY.md** - Long-Term Memory

While MEMORY.md is an important workspace file, it's **not loaded into the system prompt by default**. The agent can actively search memory content using the `memory_search` tool or read it with the `read_file` tool when needed.

> **Why not load by default?** To avoid excessive historical information consuming context space. The agent queries on demand, keeping the system prompt lean and efficient.

MEMORY.md stores distilled long-term memories (important decisions, lessons learned, user preferences, etc.).

**More details:** See the [Memory](./memory) documentation.

#### **BOOTSTRAP.md** - Initial Setup Guide

When running `copaw init` for the first time, BOOTSTRAP.md is automatically created to guide the initial "conversation" between user and agent, establishing identity, preferences, and style. Once complete, the agent writes the configuration to PROFILE.md and SOUL.md, then deletes BOOTSTRAP.md.

**Setup flow:**

1. Determine the agent's name, nature, and style
2. Learn basic user information
3. Discuss behavioral preferences and boundaries
4. Write content to respective files and delete BOOTSTRAP.md

After setup completes, BOOTSTRAP.md is deleted, so it only exists during initial setup.

---

## Configuration & Management

### Console Management

In the Console's **Agent → Workspace** page, you can:

<!-- TODO: Add screenshot - Show Workspace page with file list on the left and editor on the right -->

1. **View all persona files**: Left panel lists all Markdown files in the workspace (shows only `.md` files)
2. **Edit content online**: Click a file to edit it in the right-side editor, then click "Save" to apply changes
3. **Enable/disable files**: Each file has a switch on the right that controls whether it's loaded into the system prompt
   - **Enabled** (switch on, green dot shown): File content is loaded into the system prompt
   - **Disabled** (switch off): File is not loaded into the system prompt
4. **Adjust load order**: Enabled files can be drag-and-drop reordered, **affecting their concatenation order in the system prompt** (top to bottom, files higher up are loaded first)
5. **Upload/download workspace**:
   - Upload ZIP files (max 100MB) to batch import persona files into workspace (overwrites same-named files; non-`.md` files won't display in UI but are preserved)
   - Download entire workspace as ZIP for backup
6. **View workspace path**: Page header shows the current workspace's full path

**Hot reload:** Changes to persona files take effect automatically—no server restart needed.

**Multi-agent support:** Each agent has independent persona configuration without interference. After switching agents in the Console header, you'll see that agent's dedicated workspace files. This means:

- Different agents can have completely different AGENTS.md, SOUL.md, and PROFILE.md
- Modifying one agent's persona files doesn't affect other agents
- Each agent's persona evolves independently without conflicts

See [Multi-Agent](./multi-agent) for details.

### Configuration File Management

You can also directly edit the `system_prompt_files` field in the agent configuration file (`~/.copaw/workspaces/{agent_id}/agent.json`) to manage persona file loading:

```json
{
  "system_prompt_files": ["AGENTS.md", "SOUL.md", "PROFILE.md"]
}
```

- Array entries correspond to Markdown files in the workspace directory
- Array order determines load order
- Empty or missing array causes the agent to fall back to the default "You are a helpful assistant" prompt

### Initial Setup

Running `copaw init` automatically creates template files based on your chosen language (`zh` / `en` / `ru`):

- AGENTS.md
- SOUL.md
- PROFILE.md
- BOOTSTRAP.md (initial setup guide)

If using `copaw init --defaults`, the default language is `zh` (Chinese).

### Switching Agent Language

You can switch the agent's language in the Console's **Agent → Runtime Config** page. After switching:

<!-- TODO: Add screenshot - Show language dropdown in Agent → Runtime Config page -->

1. The system will **overwrite** existing persona files (AGENTS.md, SOUL.md, PROFILE.md) with new language templates
2. This is the **agent's own language** setting that determines the system prompt language
3. It's **independent of the Console UI language** (Console language is switched in the top-right corner)

**Warning:** Switching agent language overwrites your custom modifications to persona files. Back up important content first (use the Console's "Download" feature to backup the entire workspace).

---

## Complete System Prompt Content

Beyond persona files, the system prompt includes the following auto-generated content to ensure proper agent operation:

### Overall Structure

```
[Agent Identity]
  ↓
[Persona File Content - concatenated in enabled order]
  AGENTS.md
  SOUL.md
  PROFILE.md
  ↓
[Runtime Context Information - dynamically injected]
  - Current time & timezone
  - Working directory path
  - Available tools list
  - Skills list & descriptions
```

### Agent Identity

```
# Agent Identity

Your agent id is `{agent_id}`. This is your unique identifier in the multi-agent system.
```

In a multi-agent environment, agents need to know their own ID to call other agents or identify their workspace.

### Context Information (Runtime Injection)

The system dynamically injects the following information during each conversation:

- **Current time & timezone**: Lets the agent know what time it is for proper time-related task handling
- **Working directory path**: The agent's current workspace location
- **Available tools list**: Currently enabled built-in tools and MCP tools
- **Skills list**: Currently enabled Skills and their descriptions

This information isn't saved to files but is generated dynamically based on current state during each conversation, ensuring the agent always has up-to-date environment information.

### Tools & Skills Details

The system prompt also includes tool and Skill descriptions:

- **Built-in and MCP tools**: See [MCP & Built-in Tools](./mcp)
- **Skills**: Each enabled Skill loads portions of its `SKILL.md` (name and description fields), informing the agent of the Skill's purpose. See [Skills](./skills)

> The persona management mechanism design was inspired by [OpenClaw](https://github.com/openclaw/openclaw). Special thanks.

---

## Built-in QA Agent

CoPaw automatically creates a built-in agent named **"QA Agent"** (ID: `CoPaw_QA_Agent_0.1beta1`) when you first run `copaw init`.

### QA Agent Features

This is an agent **specifically designed to answer CoPaw-related questions**:

- **Dedicated persona**: Uses persona files optimized for Q&A (different from regular agents)
- **Pre-installed skills**: Auto-enables `guidance` and `copaw_source_index` skills for querying CoPaw documentation and source code
- **Tool configuration**: Only core tools enabled by default (execute_shell_command, read_file, write_file, edit_file, view_image); other built-in tools are disabled
- **Auto-maintained**: Running `copaw init` ensures this agent exists

### How to Use?

You can select "QA Agent" in the agent switcher at the top-right of the Console, then ask it any questions about CoPaw.

**Good questions:**

- "How do I configure the DingTalk channel?"
- "How does the memory system work?"
- "What MCP tools are supported?"

**Not suited for:**

- Complex programming tasks

### Can I modify or delete it?

- **Can modify**: You can manage it like any other agent—edit persona files in "Agent → Workspace" or adjust skills and tools in "Agent → Skills"
- **Can delete**: Delete it in "Settings → Agent Management" (doesn't affect other agents; will be recreated on next `copaw init`)
- **Workspace location**: `$COPAW_WORKING_DIR/workspaces/CoPaw_QA_Agent_0.1beta1/` (defaults to `~/.copaw/workspaces/CoPaw_QA_Agent_0.1beta1/`)
