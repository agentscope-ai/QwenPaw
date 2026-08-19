---
title: "Agent Conversations Checkpoints: Introducing QwenPaw Checkpoint"
date: 2026-08-07
author: QwenPaw Team
tags: [Checkpoint, Conversation Recovery, State Management]
cover: https://img.alicdn.com/imgextra/i3/O1CN01LXaNPg4UfYB3rvs1_!!6000000007061-2-tps-1906-943.png
excerpt: "QwenPaw Checkpoint saves Agent conversation state and can optionally restore long-term memory and workspace files, so a conversation that drifts off course can return to the right timeline."
---

# Give Agent Conversations a Save Point: Introducing QwenPaw Checkpoint 🎮

Agent conversations sometimes drift because of a single misunderstanding. Correcting the Agent does not remove the bad context, so later turns may continue in the wrong direction. Starting a new conversation works, but then you have to explain the background and requirements all over again. QwenPaw Checkpoint is built for this situation: it saves conversation state and lets you return to an earlier point when needed.

> In short: **when a conversation goes off course, do not start over—return to the point before it drifted.**

## 1. How It Works

A checkpoint works much like a save point in a game. Create one after confirming requirements, completing a feature, or before attempting a risky operation, then restore it later if necessary. Every restore includes the current conversation. Long-term memory and workspace files are optional:

| Restore scope        | Default  | Content                                    |
| -------------------- | -------- | ------------------------------------------ |
| Current conversation | Included | Session files and Agent conversation state |
| Long-term memory     | Excluded | `MEMORY.md` and `memory/`                  |
| Workspace files      | Excluded | Files explicitly selected after preview    |

QwenPaw uses three checkpoint types:

- **Named snapshot:** Created manually for an important state and excluded from automatic GC.
- **Automatic checkpoint:** Created by the system when enabled and cleaned according to count and age policies.
- **Pre-restore safety point:** Created automatically before an applied restore, providing a way back if you change your mind.

Continuing a conversation after restoring an older node creates a new timeline branch. Later history is not simply erased. **HEAD** marks the checkpoint currently selected by the conversation.

Checkpoint data stays in the current Agent workspace and is separate from the project's own `.git/`. It does not create project commits, switch project branches, or rewrite Git history. Checkpoints are intended for everyday conversation rollback, not full-machine backups or cross-device migration.

![Checkpoint timeline](https://img.alicdn.com/imgextra/i3/O1CN01LXaNPg4UfYB3rvs1_!!6000000007061-2-tps-1906-943.png)

## 2. Command Overview

You can manage checkpoints from the Console or use magic commands directly in Chat.

![Viewing Checkpoint commands in Chat](https://img.alicdn.com/imgextra/i2/O1CN01ygWpyuERcQG2b85m_!!6000000000472-1-tps-1280-638.gif)

| Command                                       | Description                                           |
| --------------------------------------------- | ----------------------------------------------------- |
| `/checkpoint`                                 | Show command help                                     |
| `/checkpoint auto [on\|off]`                  | View, enable, or disable automatic checkpoints        |
| `/checkpoint snapshot [name]`                 | Create a named snapshot                               |
| `/checkpoint timeline [--limit=N] [--all]`    | View checkpoint history                               |
| `/checkpoint restore <target> [options]`      | Preview or apply a restore                            |
| `/checkpoint gc [--all-sessions] [--compact]` | Preview or clean up old checkpoints                   |
| `/checkpoint reset --confirm`                 | Clear checkpoint history and restore default settings |

A restore target can be a timeline number such as `#3`, a snapshot name, or a SHA prefix with at least seven characters. These are the options most people need day to day:

| Option               | Purpose                                                |
| -------------------- | ------------------------------------------------------ |
| `--dry-run`          | Preview changes without restoring or cleaning anything |
| `--confirm`          | Confirm and apply the operation                        |
| `--include-memory`   | Include long-term memory in a restore                  |
| `--include-files`    | Include workspace files in a restore                   |
| `--files <paths...>` | Select workspace files to restore or delete            |
| `--all-sessions`     | Run GC across all conversations in the workspace       |
| `--compact`          | Delete every non-HEAD automatic checkpoint             |

A common command flow looks like this:

```text
/checkpoint snapshot demo-start
/checkpoint auto on
/checkpoint timeline
/checkpoint restore demo-start --dry-run
/checkpoint restore demo-start --confirm
```

Run `--dry-run` first, inspect the target and changes, then use `--confirm`. The two options cannot be used together.

To restore workspace files, first inspect the candidate differences:

```text
/checkpoint restore demo-start --include-files --dry-run
```

Then explicitly select the paths to apply:

```text
/checkpoint restore demo-start --include-files --files checkpoint-demo/state.txt checkpoint-demo/temp.txt --confirm
```

If a selected file does not exist in the target checkpoint, the restore deletes the current file. The preview marks these operations clearly, so check the list before applying it.

## 3. Feature Walkthrough

The following small file-editing example shows how Checkpoint restores both a conversation and its workspace files.

### Create a Baseline

First, ask the Agent to create `checkpoint-demo/state.txt`:

```text
Checkpoint Demo
version=1
status=baseline
```

The conversation and file are now in the expected state. Open **Workspace → Checkpoints**, select **Create Snapshot**, and name it `demo-start`. To record later states automatically, enable **Automatic Checkpoints** in the upper-right corner.

![Creating the demo-start snapshot](https://img.alicdn.com/imgextra/i4/O1CN01SFtF4KZZWqF2b85m_!!6000000008121-1-tps-1280-638.gif)

### Change the Files

Next, ask the Agent to replace `state.txt` with:

```text
Checkpoint Demo
version=2
status=modified
```

Also create `checkpoint-demo/temp.txt`:

```text
temporary=true
```

Return to the Checkpoints page. A new automatic checkpoint now appears in the timeline, and HEAD has moved forward.

![Named and automatic checkpoints in the timeline](https://img.alicdn.com/imgextra/i3/O1CN01dETNOWraAFB5CGBb_!!6000000007332-2-tps-2560-1279.png)

### Preview and Restore

Select `demo-start`, choose **Restore**, enable **Workspace Files**, and preview the changes.

The preview contains two candidates:

- `checkpoint-demo/state.txt`: restore
- `checkpoint-demo/temp.txt`: delete

`temp.txt` was created after the target snapshot, so restoring the workspace to `demo-start` removes it. Review the file list, select the candidates, and apply the restore.

![Previewing and restoring workspace files](https://img.alicdn.com/imgextra/i1/O1CN01e0eWox9nnTI2b85m_!!6000000004176-1-tps-1280-638.gif)

Reading `state.txt` again now returns:

```text
Checkpoint Demo
version=1
status=baseline
```

The later `temp.txt` is gone. More importantly, the conversation itself has returned to the snapshot state, so the context that drifted off course no longer affects later turns.

The timeline preserves the previous history and creates a pre-restore safety point. When automatic checkpoints begin to accumulate, preview and run GC from the Console or Chat:

```text
/checkpoint gc --dry-run
/checkpoint gc --confirm
```

For a more aggressive cleanup, add `--compact`. Named snapshots and conversation HEADs remain available.

![Clearing the checkpoints](https://img.alicdn.com/imgextra/i1/O1CN01y0la0Zgm81F2b85m_!!6000000007125-1-tps-1280-638.gif)

Checkpoint is not meant to encourage constant undo. It provides a reliable return point when the Agent misunderstands a request or the conversation moves in the wrong direction. Choose the saved state, preview the changes, and restore—the conversation and important context remain, and the work can continue from the right place. 🙂
