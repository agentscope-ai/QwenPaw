# Import from Other Agents

QwenPaw lets you choose which supported conversations, memories, Skills, MCP configurations, plugins, and scheduled tasks to bring over from Codex or Qoder, helping you pick up as much of your existing work as possible. You decide what to import, and QwenPaw attempts to adapt the selected tools and settings to its ecosystem. This takes much of the manual compatibility work out of switching assistants, making migration as painless as possible.

For example, you can import project discussions and a code review plugin from Codex, or project memories and a daily briefing task from Qoder. You can then continue those conversations using QwenPaw's configured model and the tools you have imported.

## Before You Start

1. Select the QwenPaw agent that will receive the imported content. Make sure it uses the native backend and has a working [model](./models). Automatic compatibility repair uses that agent's model and counts toward model usage.
2. Make sure the system user running QwenPaw has permission to read the source data and any required project directories.
3. Prepare the local runtimes, environment variables, and service authorizations your tools need so you can verify them after import.

Source files are discovered and read locally. Compatibility repair passes relevant content to your configured model. If you use a remote model, that processing takes place through the remote model service.

### Supported Sources and Data Locations

| Source              | Default data directory | Environment variable   | How the data is read                                                                                                                                              |
| ------------------- | ---------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Codex               | `~/.codex`             | `CODEX_HOME`           | Uses the Codex app-server to read conversations and settings when available; tries local rollout JSONL files if conversation history is unavailable or incomplete |
| Qoder               | `~/.qoder`             | `QODER_HOME`           | Reads local IDE / Agent SDK conversations, memories, Skills, plugins, and MCP settings                                                                            |
| Qoder IDE user data | See below              | `QODER_USER_DATA_HOME` | Provides additional conversation indexes, Quest information, and scheduled task definitions                                                                       |

The default Qoder IDE user data locations are:

| System  | Directory                                                                                |
| ------- | ---------------------------------------------------------------------------------------- |
| macOS   | `~/Library/Application Support/Qoder/User`                                               |
| Windows | `%APPDATA%\Qoder\User`, or `~/AppData/Roaming/Qoder/User` if `APPDATA` is not set        |
| Linux   | `$XDG_CONFIG_HOME/Qoder/User`, or `~/.config/Qoder/User` if `XDG_CONFIG_HOME` is not set |

To use custom locations, set these variables to absolute paths **in the environment used to start QwenPaw**. `QODER_USER_DATA_HOME` must point to the `User` directory itself. The Import page does not provide a backup upload option or a picker for arbitrary directories.

If QwenPaw runs in a container, on a remote server, or under a different system user, it can only detect data accessible to that environment. It cannot automatically access data on the computer running your browser or fetch source content from another device.

## What Can Be Imported

| Content         | Result in QwenPaw                                                                                                  | What to check before use                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| Chat history    | Converted to sessions in the receiving agent, preserving readable messages, titles, timestamps, and archive status | Historical tool calls remain records; new messages use the current agent's model and capabilities          |
| Memory          | Markdown resources organized by source and scope                                                                   | Check the source and project before treating the content as instructions for your current work             |
| Skills          | Checked and adapted copies saved to the receiving workspace, disabled by default                                   | Read the content, check dependencies, and enable manually                                                  |
| MCP             | MCP DriverCards in the receiving workspace, disabled by default                                                    | Check launch settings, directories, credentials, and access policies before connecting and enabling        |
| Plugins         | Adapted and installed through QwenPaw's native plugin installation process                                         | Installation may execute plugin code; Skills supplied by generated adapter plugins are disabled by default |
| Scheduled tasks | Converted to QwenPaw agent tasks, disabled and awaiting review                                                     | Check the schedule, instructions, and directory; approve the review, then enable separately                |

QwenPaw currently converts only the content it can recognize. It does not transfer the source application's complete login state, model provider settings, built-in tools, sandbox and approval policies, or the state of running tasks. Standalone persona files such as `AGENTS.md` do not automatically replace the receiving agent's persona. For changes to the persona, see [Persona and Behavior](./persona).

Local project directory associations are preserved where possible, but the import **does not copy project code, create Git worktrees, or restore processes running in the original application**. To move an entire QwenPaw environment, use [Backup & Restore](./backup).

## Import Steps

### 1. Choose Applications

Open **Import** in the Console.

- Select Codex or Qoder marked **Detected**. You can select both.
- Sources marked **Not detected** cannot be selected. Check the data directories and startup environment, then reopen the page to detect them again.
- Click **Continue** and wait for QwenPaw to scan the available content.

At this stage, QwenPaw only reads the source and saves an import plan. It has not yet added conversations or tools to the receiving agent.

### 2. Choose Content

After scanning, each source has **Conversations** and **Tools & setup** sections:

- **Conversations** are selected together for each source. You cannot select individual conversations on this page. Each import can process up to **500 conversations per source**.
- **Tools & setup** includes Memory, Cron, Skills, MCP, and Plugins. Select individual items or entire groups.
- Selectable conversations and non-plugin items are checked by default. **Plugins are unchecked by default.**
- Items that cannot be safely read or fingerprinted cannot be selected; the page explains why.
- Some Codex heartbeat tasks depend on their original conversations. Import the conversations from that source at the same time, or complete the conversation import before retrying the scheduled task.

Check the displayed **Target agent**, then click **Start import**. Each agent can have only one active import job at a time. Switching agents does not change the destination of a job that has already been created.

If you select a plugin, the **Plugin execution warning** appears. Confirm that you trust the source, select the acknowledgment checkbox, and click **Confirm and import**. Plugins may install Python dependencies, run code inside the QwenPaw process, and register global tools, hooks, routes, or commands. Plugin installation affects the QwenPaw instance as a whole, so its effects can extend beyond the selected agent.

MCP configurations bound to a plugin's installation directory are imported with that plugin and do not appear as separate selectable items. Their configurations and credentials follow the MCP migration rules, and their DriverCards remain disabled.

### 3. Review Progress and Results

QwenPaw imports the selected conversations first, then starts [Mission mode](./loop-engineering) to inspect and repair Skills, MCP configurations, plugins, and scheduled tasks. Skills and plugins are modified in temporary copies; MCP configurations and scheduled tasks are adapted in their pending definitions. Original source files are not modified directly. Memories are copied as reference material, organized by scope.

| Status                   | Meaning                                                                                      |
| ------------------------ | -------------------------------------------------------------------------------------------- |
| Waiting                  | Processing has not started                                                                   |
| Repairing                | Adapting the tool to QwenPaw's formats and capabilities                                      |
| Repaired, pending import | Passed QwenPaw's compatibility checks and is waiting to be saved                             |
| Succeeded                | Saved successfully; availability still depends on activation, credentials, and review status |
| Already exists           | The existing QwenPaw item was preserved                                                      |
| Failed                   | The item could not be imported; check the details, resolve the issue, and retry              |

Hover over a status label for more information, or expand **Migration details** to see the process details. The imported conversation count reflects sessions newly written during this run. Existing, empty, or unreadable conversations may be skipped.

Compatibility checks cover formats, file safety, plugin interfaces, MCP executables, and schedule definitions. They do not run source scheduled tasks or verify that external service connections, authorization, or complete workflows succeed. Some items that still need manual attention may be saved in a disabled state. Complete the checks below before using them.

## Continue Working After Import

### Conversations and Projects

Find imported conversations in the receiving agent's chat history or on the **Sessions** page. Conversations archived in the source remain archived, so look in archived sessions when needed. You can continue with a message such as:

```text
Based on this conversation, summarize the project's current progress and unfinished work. First confirm the current project directory, then explain which files we need to look at next.
```

The current QwenPaw agent handles subsequent replies. Tools from the original application do not become available simply because they appear in the conversation history.

If the source conversation's absolute working directory still exists locally, QwenPaw uses it as the conversation's project directory. If the directory has moved or is inaccessible, select the project directory again. PawPort cannot reconstruct missing project files from chat history.

Each source is limited to **500 conversations per import**, with additional limits on reading time, individual conversation size, and total history size. Codex internal subtask and automation-run conversations, as well as Qoder internal Agent / Experts execution traces, are filtered out. Calls and results already included in parent conversations remain available as history.

### Memory

By default, imported memories are saved in the receiving workspace at:

```text
memory/imports/<source>/<scope>/
  _scope.json
  ...Markdown resources
```

`<source>` is `codex` or `qoder`, and `<scope>` is a generated scope directory. If you have configured a different memory `daily_dir`, its `imports/` subdirectory is used instead. `_scope.json` records the source, project identifier, and original working directory.

- For Codex, QwenPaw reads curated `MEMORY.md` and `memory_summary.md` files, along with project resources from extensions. If curated memory is unavailable, it can read ad hoc notes. Raw internal memory and intermediate files from the memory consolidation process are not imported as long-term memory.
- For Qoder, QwenPaw supports global and project memories stored by account, as well as the older `projects/*/memory/` layout.

These files are not merged directly into QwenPaw's `MEMORY.md`. Before using retrieved content, the agent should check `_scope.json` and treat the content as reference material with a known source. See [Long-Term Memory](./memory) for more details.

### Skills and MCP

View imported Skills on the receiving workspace's **Skills** page. **Imported Skills are disabled by default.** Read `SKILL.md` and the accompanying scripts, check paths, commands, and dependencies, then enable them manually. Standalone Skills are imported into the current workspace; they are not automatically shared with other agents or added to the shared Skill Pool. To reuse them, follow the upload and broadcast workflows in [Skills](./skills).

View imported DriverCards on the **MCP** page. All imported MCP configurations are disabled by default. Check the following before enabling them:

- Migratable environment variable and request header bindings supplied by the Codex app-server are converted to QwenPaw credential references. Literal values are encrypted when stored. References to environment variables still require the corresponding values in the receiving environment.
- For Qoder MCP configurations and MCP definitions read from Codex or Qoder plugin manifests, `env` / `headers` values become placeholder references. Configure the required values again; do not assume the original values are available.
- OAuth login state is not imported, so you must authorize again. Configurations containing plaintext credentials in command lines or URLs are rejected if those credentials cannot be converted safely.
- MCP configurations that still reference the original application's or plugin's runtime directory may depend on those directories remaining in place. Check the executable, working directory, service address, and tool access policies, then verify the connection before enabling.

See [MCP & Built-in Tools](./mcp) for configuration details.

### Plugins

During import, QwenPaw inventories enabled plugins in the source and their Marketplace information. Directly supported adaptations include Codex content plugins containing Skills or MCP configurations and eligible Qoder plugins containing only Skills. Other local plugins must be adapted to QwenPaw's plugin manifest and entry point requirements and pass checks before installation.

Generated adapter plugins retain their Skills and required resources, with those Skills disabled by default. Source-specific hooks, commands, agents, and runtime interfaces are not guaranteed to migrate. A remote plugin URL alone, without local content that can be inspected, is not sufficient to pass compatibility checks.

Installation may already have registered capabilities across the QwenPaw instance. If a plugin's bound MCP configuration fails to import, the overall result may still show a failure. Check both the installed plugin and its MCP configuration. See [Plugin System](./plugins) for management details.

### Scheduled Tasks: Review First, Then Enable

On the **Cron Jobs** page, find tasks marked **Imported review required**:

1. Open **Edit** and check the prompt, execution time, time zone, delivery settings, and working directory.
2. To change the working directory, fill in **Local project directory mapping**. Tasks still marked as having a remote or unverifiable source directory must be mapped to an existing local directory before review can be approved.
3. Save, click **Approve review**, then click **Approve review** in the confirmation dialog.
4. The task remains disabled after approval. Click **Enable** when you are ready. You can also run it manually after review to verify the result.

Tasks cannot be enabled or run before review. Editing the task normally or resuming it through the CLI cannot bypass this requirement.

Codex supports convertible daily, weekly, hourly, and minutely RRULEs, along with one-time tasks scheduled for the future. Rules with complex date restrictions, fixed start-time anchors, or no clearly equivalent schedule require manual adjustment. A Codex heartbeat tied to a conversation becomes a scheduled task that shares the imported conversation; it does not replace QwenPaw's global heartbeat configuration.

QwenPaw reads Qoder's `tasks.v2.json` first and uses v1 only if v2 does not exist. It supports one-time, hourly, daily, weekly, and interval schedules whose original timing can be preserved. Deleted or finished tasks are filtered out; execution queues and run history are not restored. A corrupted v2 file does not trigger a fallback to v1 that would restore older tasks.

Imported tasks default to Console delivery, save their results to the Inbox, and have tool safety enabled. Regular tasks use a dedicated task session. Information about the source model, notification method, and execution environment does not mean that the same behavior will be enabled in QwenPaw. See [Scheduled Tasks](./cron) for details.

## Retries, Interruptions, and Repeated Imports

- **Retry failed items:** Select failed tools or settings on the results page, click **Retry selected**, and confirm. QwenPaw reads the source again, creates a new plan, and imports the selected items. Retrying plugins still requires confirmation of code execution. Conversations are not included in this retry; to retry them, start a new import with conversations selected.
- **Repeated imports:** Previously imported source conversations, memory scopes, and scheduled tasks are preserved, as are existing Skills and MCP configurations with the same name and plugins with the same ID. Retrying does not force an overwrite. Use the relevant management page to edit existing content.
- **Page refresh or temporary disconnection:** Reopen Import and select the original receiving agent to restore the job view and reconnect to progress updates. Keep the QwenPaw service running during import.
- **Cancellation or service restart:** Cancellation waits for the current operation to stop safely. A service restart marks unfinished scans or imports as interrupted; they do not resume automatically. Content already saved is preserved. Review the results, then retry failed items or scan again.
- **Partial failure:** Items are saved independently. A failed item does not undo successful imports, and cancellation does not roll back the entire import.

## Frequently Asked Questions

### Why Is the Import Taking So Long?

Start by checking **Migration details** for errors. If none are reported, a longer import can be normal. QwenPaw automatically starts Mission mode to iteratively revise incompatible tools, with the aim of making each one usable in QwenPaw. Larger amounts of content take more time.

Imported conversations and tools are saved persistently, so you do not need to repeat the import each time you use them. The repair process also has limits on attempts and runtime, so an import cannot continue indefinitely.

### No Application Is Detected, or Access Is Restricted to Local Connections

Check that the source directories exist, that the path environment variables are available to the QwenPaw process, and that the system user running it has read permission. Accessing the Console remotely does not grant permission to import. If the Codex CLI is unavailable, QwenPaw can still attempt to read local conversations and other content, but it may discover less than when the app-server is available.

### Source Data Changed After Preview

The tool files or configuration changed after scanning, so the current plan can no longer be used. End this job, scan again, review the content, and restart the import. Avoid modifying selected source content between scanning and starting the import.

### Where Can I Find More Diagnostic Information?

The receiving workspace's `.qwenpaw/imports/` directory stores job snapshots, plans, and compatibility repair summaries. The summary at `migration-*/adaptation/summary.md` can help identify items that still need repair. Temporary `staging/` files and the compatibility `manifest.json` are removed when the import ends, so do not treat them as a backup of the source. QwenPaw service logs can provide further error details.

## Related Pages

- [Console](./console) — Select the receiving agent, view conversations, and manage imported content
- [Skills](./skills) — Review, enable, and share Skills
- [MCP & Built-in Tools](./mcp) — Configure services, credentials, and tool access policies
- [Long-Term Memory](./memory) — Retrieve historical information with its source recorded
- [Plugin System](./plugins) — Manage plugins that affect the entire instance
- [Scheduled Tasks](./cron) — Review, enable, and inspect task results
- [Backup & Restore](./backup) — Move or restore a QwenPaw environment
