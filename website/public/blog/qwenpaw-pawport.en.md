---
title: "QwenPaw Import: Bring Recent Work from Other Agents and Keep Going"
date: 2026-09-14
author: QwenPaw Team
tags: [Import, Loop Engineering]
cover: https://img.alicdn.com/imgextra/i1/O1CN01dYqOyowBl3G3OTaP_!!6000000001080-2-tps-1672-941.png
excerpt: "Bring supported conversations, project memories, and familiar tools from Codex or Qoder into QwenPaw. Follow an ongoing project to see how to choose what to import, complete the move, and keep control over what runs."
---

You have worked through several rounds of requirements in Codex or Qoder, explored different approaches, and built up a list of things to do. But something still gets in the way: a capability you need is missing, costs are higher than you expected, or you feel constrained by how you can deploy and use the tools.

Now you want to try QwenPaw, but first you would have to explain the project all over again and set up your tools and Skills from scratch. Some tools even depend on the Codex or Qoder environment and cannot run in QwenPaw without adaptation. Then there is everything you have gradually put together: a writing or code review Skill, connections to external services, and a daily briefing. Rebuilding that setup takes time, and the move can feel daunting.

**QwenPaw is designed to make that switch easier. You can now import recent conversations, memories, Skills, plugins, MCP configurations, and scheduled tasks from Codex and Qoder, with compatibility adjustments to help you pick up your existing work and make the move as painless as possible.** Preview what is available and choose what to bring. You do not have to work through compatibility issues on your own: QwenPaw attempts to adapt tools from Codex and Qoder so they can run in QwenPaw.

![pawport](https://img.alicdn.com/imgextra/i1/O1CN01dYqOyowBl3G3OTaP_!!6000000001080-2-tps-1672-941.png)

## When Would You Use It?

- **You want to continue a project with a different assistant.** Bring over the requirements you discussed and the decisions you made, then plan the next steps in QwenPaw with less copying, pasting, and repeating yourself.
- **You already have a setup that works for you.** Import supported Skills for weekly reports, code reviews, or organizing research, along with MCP connections to external services. Review and enable them when you are ready.
- **You want QwenPaw to take over your regular tasks.** Bring supported daily briefings or weekly reviews across, check their schedules and instructions, then let them run in QwenPaw.

## What Can You Bring?

The currently supported sources are **Codex and Qoder**. After scanning, the page lists the content it found:

| Content         | How you can use it in QwenPaw                                                              |
| --------------- | ------------------------------------------------------------------------------------------ |
| Conversations   | Read existing conversations and keep chatting                                              |
| Memory          | Keep curated notes and project knowledge as reference material with the source recorded    |
| Skills          | Bring instructions and supporting resources for specific jobs; review them before enabling |
| MCP             | Import supported MCP configurations and complete authorization before use                  |
| Plugins         | Bring compatible extensions with your explicit selection and installation approval         |
| Scheduled tasks | Keep schedules that can be converted; review and enable them before they run               |

What can be imported depends on the source data and compatibility checks. Conversations can retain their connection to a project directory that still exists locally. **Project code and files are not copied with the chat.** Sign-ins, model settings, and the runtime environment also need to be configured separately in QwenPaw.

## How to Use Import

Suppose you have been planning a product website in Codex or Qoder. You have discussed the page structure, writing style, and remaining work. Now you want to bring those discussions into QwenPaw and finish the copy for the opening section.

### Before You Start

Run QwenPaw on the computer that holds your source data and open the Console locally. Select the agent that will receive the content, make sure it uses the **native QwenPaw backend**, and configure a working model. See the [Quick Start](/docs/quickstart?lang=en) if you need help with the initial setup.

Open **Import** in the Console. PawPort reads data from the environment where QwenPaw runs. If QwenPaw is in a container or on a remote server, it cannot automatically access conversations on the computer running your browser. For a first try, using the local environment where your source data already lives is more straightforward.

### 1. Choose Your Source Applications

Select Codex or Qoder marked **Detected**, or select both, then click **Continue**.

PawPort first scans the available content. No conversations or tools have been added to the receiving agent yet, so you can review the list before deciding.

![Choose source applications](https://img.alicdn.com/imgextra/i3/O1CN014Y8t4aBsYvC4G6Li_!!6000000000928-0-tps-2098-904.jpg)

### 2. Choose What to Import

On **Choose content**, each source has **Conversations** and **Tools & setup** sections.

To try continuing a discussion first, keep conversations selected and deselect any tools or settings you do not need yet. You can select tools individually. Conversations are selected together for each source; you cannot select individual chats on this page.

Selectable conversations and non-plugin items are checked by default. **Plugins are unchecked.** Review the list and the displayed **Target agent**, then click **Start import**.

![Choose the content to import](https://img.alicdn.com/imgextra/i3/O1CN01erQWM5PAcyE5sJ2Y_!!6000000000010-0-tps-2894-1692.jpg)

### 3. Check What Is Ready

Each item has its own progress status. If you selected tools or scheduled tasks, you may see **Repairing** while QwenPaw attempts to adapt them for use.

When the import finishes, review each result. **Succeeded** means the content was saved; **Already exists** means existing content was preserved. For failed items, open **Migration details**, address the issue, and retry.

Successfully imported tools may still need authorization, dependencies, or manual enabling. Keep QwenPaw running throughout the import.

![Review import progress and results](https://img.alicdn.com/imgextra/i4/O1CN01yQvh9inNJ3H3k83Q_!!6000000004356-0-tps-1844-1216.jpg)

### 4. Reopen the Discussion and Take the Next Step

Go to the receiving agent's chat history or **Sessions** page and find the website discussion. If the original conversation was archived, look in archived sessions.

Start by making the next task clear:

```text
Review this conversation and summarize the page structure, writing style, and remaining work we agreed on.
Give me a brief progress recap, then list the questions we still need to answer before finishing the copy for the opening section.
```

Once you have confirmed that it understands the context, continue:

```text
Using the style we agreed on, draft a headline, subheading, and button copy for the opening section. Give me two versions to compare.
```

If your next step involves editing project files, first check that the conversation points to the correct project directory and that the files are still accessible. Further work uses QwenPaw's currently configured model and tools. Historical tool calls remain records.

## Reconnect Your Tools and Routines

After resuming the conversation, you can gradually enable the capabilities you imported:

- **Skills:** Read their contents on the **Skills** page, check any required programs or resources, then enable them manually.
- **MCP:** Review the connection settings on the **MCP** page, supply credentials or authorize again, verify the connection, then enable it.
- **Memory:** Imported notes are saved as reference material with their source recorded. Check which project they belong to so that another project's conventions do not get mixed into your current work.

For a task such as “summarize project progress every morning,” follow these steps after import:

1. On **Cron Jobs**, find the task marked **Imported review required** and open **Edit**.
2. Check its instructions, time, time zone, result destination, and working directory. If the page requires a directory mapping, enter an existing local project directory.
3. Save, click **Approve review**, then click **Approve review** in the confirmation dialog. The task is still disabled at this point.
4. You can run it manually to check the result, then click **Enable** to let it run on schedule.

Imported tasks save results to the QwenPaw Inbox by default, so you can return to them later. Importing does not automatically stop the task in its original application. Before enabling it, decide which application should keep running it to avoid duplicate reminders.

![Review imported scheduled tasks](https://img.alicdn.com/imgextra/i2/O1CN01oEmw5W0PP4D6e8UK_!!6000000004540-0-tps-3274-494.jpg)

## Stay in Control of Your Data and What Runs

### Will the Original Content Change?

QwenPaw reads source data and makes compatibility adjustments to copies or configurations awaiting import. It does not directly rewrite the original Codex or Qoder files. Repeated imports preserve previously imported conversations and existing items such as tools with the same name, without forcing an overwrite.

### Where Is the Data Processed?

Source discovery and reading happen locally, and the import endpoints only allow local access. **Compatibility repair uses the model configured for the receiving agent and passes relevant content to that model for processing.** If you use a remote model, that content is sent to the corresponding model service and counts toward model usage. Before selecting tools and settings, check which model you are using and what content it will process.

Tool credentials are not all copied as-is. Secret values that support secure migration are encrypted when stored; other settings may need to be entered again. OAuth connections require fresh authorization.

### Does Everything Start Running Immediately?

Imported **Skills and MCP configurations are disabled by default**. **Scheduled tasks must be reviewed first and enabled separately**; they cannot run before review. You can inspect the content, permissions, and schedule before deciding when to use them.

**Pay particular attention to plugin installation.** Plugins are unchecked by default. If you select them, the page asks you to confirm code execution. Installation may download dependencies, run code inside QwenPaw, and add capabilities across the whole instance. Confirm that you trust the source before installing.

## Start With an Unfinished Conversation

Open **Import**, choose Codex or Qoder, and bring your conversations across. Find a discussion you want to continue, ask QwenPaw to recap the decisions, and work through the next step together.

For detailed instructions on supported content, custom data directories, and retrying failed imports, see the [Import guide](/docs/import?lang=en).
