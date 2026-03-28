# Multi-Agent

CoPaw supports **multi-agent**, allowing you to run multiple independent AI agents in a single CoPaw instance.

> This feature was introduced in **v0.1.0**.

**This document covers two parts:**

1. **Multi-Agent Workspace** - How to create and manage multiple agents, each with its own configuration, memory, skills, and conversation history
2. **Inter-Agent Collaboration** - How to enable the collaboration skill so agents can communicate with each other to accomplish complex tasks together

---

## Part 1: Multi-Agent Workspace

### What is Multi-Agent?

Simply put, **multi-agent** lets you run multiple "personas" in one CoPaw, where each persona:

- Has its own **personality and specialization** (configured via different persona files)
- Remembers **its own conversations** (no cross-talk)
- Uses **different skills** (one good at code, another at writing)
- Connects to **different channels** (one for DingTalk, one for Discord)

Think of it as having multiple assistants, each with their own specialty.

---

## Why Use Multi-Agent?

### Use Case 1: Functional Separation

You might need:

- A **daily assistant** - casual chat, lookup info, manage todos
- A **code assistant** - focused on code review and development
- A **writing assistant** - focused on document writing and editing

Each agent focuses on its domain without interference.

### Use Case 2: Platform Separation

You might use CoPaw across multiple platforms:

- **DingTalk** - work-related conversations
- **Discord** - community discussions
- **Console** - personal use

Different platforms' conversations and configs stay completely isolated.

### Use Case 3: Testing vs Production

You might need:

- **Production agent** - stable config for daily work
- **Test agent** - experiment with new features without affecting production

---

## How to Use? (Recommended Method)

### Managing Agents in Console

> This is the simplest way - **no command-line required**.

#### 1. View and Switch Agents

After starting CoPaw, you'll see the **Agent Selector** in the **top-right corner** of the console:

```
┌───────────────────────────────────┐
│  Current Agent  [Default ▼] (1)   │
└───────────────────────────────────┘
```

Click the dropdown to:

- View all agents' names and descriptions
- Switch to another agent
- See the current agent's ID

After switching, the page auto-refreshes to show the new agent's config and data.

#### 2. Create a New Agent

Go to **Settings → Agent Management** page:

1. Click "Create Agent" button
2. Fill in the information:
   - **Name**: Give the agent a name (e.g., "Code Assistant")
   - **Description**: Explain the agent's expertise and purpose (**Important**)
   - **ID**: Leave empty for auto-generation, or customize (e.g., "coder")
3. Click "OK"

After creation, the new agent appears in the list and you can immediately switch to it.

> **Important**: The **Description** field is critical! If you plan to use multi-agent collaboration, clearly describe the agent's areas of expertise and task types it excels at. For example: "Specializes in Python/JavaScript code review and refactoring optimization." Agents read this description when deciding which agent to collaborate with.

#### 3. Configure Agent-Specific Settings

After switching to an agent, you can configure it individually:

- **Channels** - Go to "Control → Channels" page to enable/configure channels
- **Skills** - Go to "Agent → Skills" page to enable/disable skills
- **Tools** - Go to "Agent → Tools" page to toggle built-in tools
- **Persona** - Go to "Agent → Workspace" page to edit AGENTS.md and SOUL.md

These settings **only affect the current agent** and won't impact other agents.

#### 4. Edit and Delete Agents

In **Settings → Agent Management** page:

- Click "Edit" button to modify agent's name and description (after modifying description, the system will automatically update PROFILE.md)
- Click "Delete" button to remove agent (default agent cannot be deleted)

---

## Example Scenarios

### Example 1: Work-Life Separation

**Scenario**: You want to separate work and personal conversations.

**Setup**:

1. Create two agents in console:

   - `work` - work assistant
   - `personal` - personal assistant

2. For `work` agent:

   - Enable DingTalk channel
   - Enable code and document-related skills
   - Configure formal persona (AGENTS.md)

3. For `personal` agent:
   - Enable Discord or console
   - Enable entertainment and news skills
   - Configure casual persona

**Usage**: Automatically use `work` agent on DingTalk, `personal` agent on Discord.

### Example 2: Specialized Assistant Team

**Scenario**: You want assistants for different professional domains.

**Setup**:

1. Create three agents:

   - `coder` - code assistant (enable code review, file operation skills)
   - `writer` - writing assistant (enable document processing, news digest skills)
   - `planner` - task assistant (enable cron, email skills)

2. Switch to the appropriate agent as needed.

**Benefits**: Each agent focuses on its domain with precise persona and uncluttered conversation history.

### Example 3: Multi-Language Support

**Scenario**: You need both Chinese and English assistants.

**Setup**:

1. Create two agents:

   - `zh-assistant` - Chinese assistant (language: "zh")
   - `en-assistant` - English assistant (language: "en")

2. Edit their AGENTS.md and SOUL.md in corresponding languages.

**Usage**: Switch to `zh-assistant` for Chinese conversations, `en-assistant` for English.

---

## FAQ

### Q: Do I need to create multiple agents?

Not necessarily. If your use case is simple, **using only the default agent is perfectly fine**.

Consider creating multiple agents when:

- You need clear functional separation (work/life, dev/writing, etc.)
- Connecting to multiple platforms and want isolated conversation histories
- Need to test new configs without affecting your daily-use agent

### Q: Will switching agents lose my conversations?

No. Each agent's conversation history is saved independently; switching only changes which agent you're currently viewing.

### Q: Do multiple agents increase costs?

No. Agents only call the LLM when in use; idle agents don't incur any fees.

### Q: Can I use multiple agents simultaneously?

Yes. If you configure different agents for DingTalk and Discord, they can respond to their respective channels simultaneously.

### Q: How to delete an agent?

Click the delete button in the "Settings → Agent Management" page in console.

**Note**: After deletion, the workspace directory is retained (to prevent accidental data loss). To completely remove it, manually delete the `~/.copaw/workspaces/{agent_id}` directory.

### Q: Can the default agent be deleted?

Not recommended. The `default` agent is the system's default fallback; deleting it may cause compatibility issues.

### Q: What can agents share?

**Globally Shared**:

- Model provider configuration (API keys, model selection)
- Environment variables (TAVILY_API_KEY, etc.)

**Independent Configuration**:

- Channel settings
- Skill enablement
- Conversation history
- Cron jobs
- Persona files

---

## Upgrading from Single-Agent

If you previously used CoPaw **v0.0.x**, upgrading to **v0.1.0** will **automatically migrate**:

1. **Automatic Migration on First Start**

   - Old configs and data are automatically moved to the `default` agent workspace
   - No manual file operations required

2. **Verify Migration**

   - After starting CoPaw, check the agent list in console
   - You should see an agent named "Default Agent"
   - Your old conversations and configs should still be there

3. **Backup Recommendation**
   Back up your working directory before upgrading:
   ```bash
   cp -r ~/.copaw ~/.copaw.backup
   ```

---

## Part 2: Inter-Agent Collaboration

Agents can communicate and collaborate with each other to handle complex tasks that a single agent cannot accomplish alone.

### What is Agent Collaboration?

**Multi-Agent Collaboration** is a built-in skill that, when enabled, allows your agents to:

- Request other agents' **specialized expertise** (e.g., ask code agent to review code, ask writing agent to polish documentation)
- Access other agents' **workspace data** (e.g., read another agent's config files)
- Seek **second opinions** or professional reviews
- Invoke specific agents when the user **explicitly requests** them

### How to Enable Collaboration?

#### Method 1: Enable in Console (Recommended)

1. Switch to the agent you want to enable collaboration for
2. Go to **Agent → Skills** page
3. Find the **Multi-Agent Collaboration** skill
4. Check to enable it
5. Click "Save"

#### Method 2: Enable via CLI

```bash
# Enable for default agent
copaw skills config

# Enable for specific agent
copaw skills config --agent-id abc123

# In the interactive interface:
# - Use ↑/↓ keys to find "multi_agent_collaboration"
# - Press Space to toggle
# - Press Enter to save
```

### How is Collaboration Triggered?

Once the collaboration skill is enabled, agents will automatically initiate collaboration in the following situations:

#### Trigger Method 1: User Explicitly Requests

User directly asks for another agent in the conversation:

**Example:**

```
User: Please ask the code assistant to review this code
```

The current agent will:

1. Identify that the user wants to involve "code assistant"
2. Query the available agent list
3. Send a review request to "code assistant"
4. Wait for "code assistant" to return results
5. Integrate the results and respond to the user

#### Trigger Method 2: Agent Proactively Decides

When processing a task, if the agent determines it needs another agent's expertise, it will initiate collaboration:

**Example:**

```
User: Generate a technical document and polish it with professional language

Current agent's workflow:
1. [Generate technical document draft]
2. [Determine: polishing needs writing expertise, call writing assistant]
3. [Send draft to writing assistant]
4. [Receive polished version from writing assistant]
5. [Return final document to user]
```

### Usage Scenarios

#### Scenario 1: Cross-Domain Collaboration

```
User: Analyze my project structure and generate an architecture document

Workflow:
1. Code agent analyzes project structure
2. Code agent calls writing agent
3. Writing agent generates professional documentation
4. Code agent returns final result
```

#### Scenario 2: Professional Review

```
User: What's wrong with this code? Let the senior assistant review it too

Workflow:
1. Current agent analyzes the code first
2. Identifies user requested "senior assistant" to participate
3. Calls "senior assistant" for review
4. Combines both opinions and responds to user
```

#### Scenario 3: Data Sharing

```
User: Send me the monthly report from the finance agent

Workflow:
1. Current agent identifies need for "finance agent" data
2. Requests monthly report from finance agent
3. Receives report data
4. Formats and sends to user
```

### Benefits of Collaboration

- **Specialized Division**: Each agent focuses on its domain, leveraging respective strengths in collaboration
- **Context Isolation**: Different agents' conversation histories don't interfere, avoiding confusion
- **Flexible Composition**: Dynamically combine different agents' capabilities based on task needs
- **Scalability**: Adding new agents extends the entire system's capabilities

### Importance of Agent Description

To make inter-agent collaboration more effective, you need to provide clear description information for each agent.

#### How Do Agents Identify Each Other?

When Agent A needs to collaborate with Agent B, it first queries the available agent list. The system reads and displays each agent's:

- **Name** - The agent's display name
- **ID** (agent_id) - Unique identifier
- **Description** - The expertise and purpose description filled in by the user when creating the agent (**Important**)
- **PROFILE.md** (auto-generated) - Detailed capability description automatically generated by the system based on the agent's configuration

#### How to Write Descriptions?

**When creating an agent**, the description field should clearly state:

✅ **Good description examples**:

```
Specializes in Python/JavaScript code review, refactoring, and performance optimization
```

```
Handles document writing, content polishing, and technical writing; proficient in Chinese and English
```

```
Manages financial data analysis, report generation, and budget management
```

❌ **Bad description examples**:

```
My assistant
```

```
For testing
```

```
(empty)
```

**Key elements of a good description**:

1. Clear **areas of expertise** (e.g., "code review", "document writing")
2. Specific **skill scope** (e.g., "Python/JavaScript", "bilingual")
3. **Task types** it excels at (e.g., "refactoring", "data analysis")

#### PROFILE.md Auto-Generation

The system **automatically generates** a `PROFILE.md` file based on the agent's configuration (including name, description, skills, persona files, etc.), stored in the workspace directory:

```
~/.copaw/workspaces/{agent_id}/PROFILE.md
```

You can view the auto-generated PROFILE.md in the **Agent → Workspace** page.

#### View Agent Information

Use CLI to view all agents' information:

```bash
copaw agents list

# Example output:
# Agent ID: code_reviewer
# Name: Code Review Assistant
# Description: Specializes in Python/JavaScript code review, refactoring, and performance optimization
# Workspace: ~/.copaw/workspaces/code_reviewer
# Profile: [Auto-generated detailed capability description]
```

Agents reference both **Description** and **PROFILE.md** when making collaboration decisions.

### Important Notes

- **Skill must be enabled**: Collaboration requires explicitly enabling the "Multi-Agent Collaboration" skill
- **Write clear descriptions**: When creating agents, clearly describe their expertise and task types in the description field
- **Profile is auto-generated**: PROFILE.md is automatically generated by the system; no manual writing needed
- **Automated handling**: Once enabled, agents will automatically initiate collaboration as needed; users don't need manual operations
- **Performance consideration**: Collaboration involves multiple agents, which may require more time and API calls
- **Reasonable planning**: Recommend creating 3-5 agents based on actual needs; avoid over-complexity

---

## Advanced: CLI and API

> If you're not familiar with command-line or APIs, you can skip this section. All features are available in the console.

### Agent Collaboration CLI

When agents have the collaboration skill enabled, they automatically use these CLI commands in the background:

#### Query Available Agents

```bash
copaw agents list
```

This command lists all configured agents, including:

- **Agent ID**: The agent's unique identifier
- **Name**: Agent name
- **Description**: The expertise and purpose description filled in by the user when creating the agent
- **Workspace**: Workspace path
- **Profile**: Auto-generated `PROFILE.md` file content (if exists)

**Example output**:

```
Agent ID: code_reviewer
Name: Code Review Assistant
Description: Specializes in Python/JavaScript code review, refactoring, and performance optimization
Workspace: ~/.copaw/workspaces/code_reviewer
Profile: [Auto-generated detailed capability description based on config and persona files]

Agent ID: writer_bot
Name: Writing Assistant
Description: Handles document writing, content polishing, and technical writing; proficient in Chinese and English
Workspace: ~/.copaw/workspaces/writer_bot
Profile: [Auto-generated detailed capability description]
```

Agents reference both **Description** and **Profile** when deciding which agent to collaborate with.

#### Communicate with Other Agents

```bash
# Initiate new conversation (real-time mode, for quick queries)
copaw agents chat \
  --from-agent <current_agent> \
  --to-agent <target_agent> \
  --text "Request content"

# Multi-turn conversation (maintain context)
copaw agents chat \
  --from-agent <current_agent> \
  --to-agent <target_agent> \
  --session-id "<session_id>" \
  --text "Follow-up request"

# Complex task (background mode, for data analysis, report generation, etc.)
copaw agents chat --background \
  --from-agent <current_agent> \
  --to-agent <target_agent> \
  --text "Complex task request"
# Returns [TASK_ID: xxx] [SESSION: xxx]

# Check background task status (--to-agent is optional when querying)
copaw agents chat --background \
  --task-id <task_id>
# Status flow: submitted → pending → running → finished
# When finished, result shows: completed (✅) or failed (❌)
```

**Background Mode Explanation**:

When tasks are complex (e.g., data analysis, batch processing, report generation), use `--background` to avoid blocking the current agent, allowing it to continue processing other work. After submission, it returns a `task_id` that can be used later to query the task status and result.

**Task Status Flow**:

- `submitted`: Task accepted, waiting to start
- `pending`: Queued for execution
- `running`: Currently executing
- `finished`: Completed (check result for `completed` or `failed`)

**Scenarios for using background mode**:

- Data analysis and statistics
- Batch file processing
- Generating detailed reports
- Calling slow external APIs
- Complex tasks with uncertain execution time

> **Note**: These commands are executed automatically by agents; users typically don't need to call them manually. See [CLI - Agents](./cli#agents) for details.

### Agent Management CLI

All multi-agent-aware CLI commands accept the `--agent-id` parameter (defaults to `default`):

```bash
# View specific agent's configuration
copaw channels list --agent-id abc123
copaw cron list --agent-id abc123
copaw skills list --agent-id abc123

# Create cron job for specific agent
copaw cron create \
  --agent-id abc123 \
  --type agent \
  --name "Check Todos" \
  --cron "0 9 * * *" \
  --channel console \
  --target-user "user1" \
  --target-session "session1" \
  --text "What are my todos?"
```

**Commands Supporting `--agent-id`**:

- `copaw channels` - channel management
- `copaw cron` - cron jobs
- `copaw daemon` - runtime status
- `copaw chats` - chat management
- `copaw skills` - skill management

**Commands NOT Supporting `--agent-id`** (global operations):

- `copaw init` - initialization
- `copaw providers` - model providers
- `copaw models` - model configuration
- `copaw env` - environment variables

### REST API

#### Agent Management API

| Endpoint                        | Method | Description     |
| ------------------------------- | ------ | --------------- |
| `/api/agents`                   | GET    | List all agents |
| `/api/agents`                   | POST   | Create agent    |
| `/api/agents/{agent_id}`        | GET    | Get agent info  |
| `/api/agents/{agent_id}`        | PUT    | Update agent    |
| `/api/agents/{agent_id}`        | DELETE | Delete agent    |
| `/api/agents/{agent_id}/active` | POST   | Activate agent  |

#### Agent-Scoped API

All agent-specific APIs support the `X-Agent-Id` HTTP header:

```bash
# Get specific agent's chat list
curl -H "X-Agent-Id: abc123" http://localhost:7860/api/chats

# Create cron job for specific agent
curl -X POST http://localhost:7860/api/cron/jobs \
  -H "X-Agent-Id: abc123" \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

API endpoints supporting `X-Agent-Id`:

- `/api/chats/*` - chat management
- `/api/cron/*` - cron jobs
- `/api/config/*` - channel and heartbeat config
- `/api/skills/*` - skill management
- `/api/tools/*` - tool management
- `/api/mcp/*` - MCP client management
- `/api/agent/*` - workspace files and memory

### Configuration File Structure

If you need to directly edit configuration files:

#### Old Structure (v0.0.x)

```
~/.copaw/
├── config.json          # All config
├── chats.json
├── jobs.json
├── AGENTS.md
└── ...
```

#### New Structure (v0.1.0+)

```
~/.copaw/
├── config.json          # Global config (providers, agents.profiles)
└── workspaces/
    ├── default/         # Default agent workspace
    │   ├── agent.json   # Agent-specific config
    │   ├── chats.json
    │   ├── jobs.json
    │   ├── AGENTS.md
    │   └── ...
    └── abc123/          # Other agent
        └── ...
```

---

## Best Practices

### Plan Your Agent Count Wisely

✅ **Recommended**: 3-5 agents, organized by primary function or platform
❌ **Not Recommended**: Creating an agent for every small feature

Too many agents increase management complexity without proportional benefits.

### Use Clear Names

✅ **Good naming**:

- `default` - Default agent
- `work-assistant` - Work assistant
- `code-reviewer` - Code review assistant

❌ **Bad naming**:

- `abc123` - Meaningless random characters
- `test1`, `test2` - Unclear purpose

### Regular Backups

Back up important agent workspaces regularly:

```bash
# Backup specific agent
cp -r ~/.copaw/workspaces/abc123 ~/backups/agent-abc123-$(date +%Y%m%d)

# Backup all agents
cp -r ~/.copaw/workspaces ~/backups/workspaces-$(date +%Y%m%d)
```

---

## Related Pages

- [CLI Commands](./cli) - Detailed CLI reference
- [Configuration & Working Directory](./config) - Config file structure
- [Console](./console) - Web management interface
- [Skills](./skills) - Skill system
