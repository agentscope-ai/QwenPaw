# Multi-Agent Workspace

CoPaw supports **multi-agent workspace**, allowing you to run multiple independent AI agents in a single CoPaw instance, each with its own configuration, memory, skills, and conversation history.

> This feature was introduced in **v0.1.0**.

---

## What is Multi-Agent?

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
   - **Description**: Explain the agent's purpose (optional)
   - **ID**: Leave empty for auto-generation, or customize (e.g., "coder")
3. Click "OK"

After creation, the new agent appears in the list and you can immediately switch to it.

#### 3. Configure Agent-Specific Settings

After switching to an agent, you can configure it individually:

- **Channels** - Go to "Control → Channels" page to enable/configure channels
- **Skills** - Go to "Agent → Skills" page to enable/disable skills
- **Tools** - Go to "Agent → Tools" page to toggle built-in tools
- **Persona** - Go to "Agent → Workspace" page to edit AGENTS.md and SOUL.md

These settings **only affect the current agent** and won't impact other agents.

#### 4. Edit and Delete Agents

In **Settings → Agent Management** page:

- Click "Edit" button to modify agent's name and description
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

## Advanced: CLI and API

> If you're not familiar with command-line or APIs, you can skip this section. All features are available in the console.

### CLI Commands

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

## Related Pages

- [CLI Commands](./cli) - Detailed CLI reference
- [Configuration & Working Directory](./config) - Config file structure
- [Console](./console) - Web management interface
- [Skills](./skills) - Skill system
