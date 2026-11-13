---
title: "PawGit: Recoverable Agent Session State for QwenPaw"
date: 2026-07-07
author: QwenPaw Team
tags: [Plugin, SessionVersionControl, StateSnapshots, SessionRewind]
cover: https://img.alicdn.com/imgextra/i2/O1CN01cdSRbU26gXIFiTRjL_!!6000000007691-2-tps-1254-1254.png
excerpt: "In long sessions, Agents get dragged down by dirty context. PawGit adds checkpoints, timelines, and rewind for QwenPaw Agent session state—so you can return to a clean point without opening a new window and re-feeding your entire prompt."
related:
  heading: "Related Plugin: PawGit"
  description: "Version control for QwenPaw sessions and memory, with state snapshots, DAG timelines, session rewind, and state reset."
  linkText: "View and install PawGit →"
  linkUrl: "https://platform.agentscope.io/plugins/pawgit"
---

# PawGit: Recoverable Agent Session State for QwenPaw

If you often use QwenPaw for complex tasks, you probably know this moment well:

At first, it feels brilliant. You open a fresh session and feed it the project background, directory structure, design goals, constraints, and lessons already learned. It reads carefully and answers on point. You might even feel: this time it's solid—it really gets it.

Then the task grows longer. You ask it to analyze first, change a bit of code, then revisit the plan. You correct a wrong assumption. Later you find an API doesn't match expectations, so you adjust again. Then you pivot temporarily and tell it to skip phase 2 and just close out phase 1.

After dozens of turns, something odd starts happening. It still responds, but something feels off. It brings back a plan you already rejected. It holds onto a wrong premise you already corrected. New reasoning mixes in stale context. It suddenly becomes overly cautious—or the opposite, confidently filling gaps that don't exist.

![Deep into a long session, the Agent starts getting dragged down by stale context](https://img.alicdn.com/imgextra/i2/O1CN01cdSRbU26gXIFiTRjL_!!6000000007691-2-tps-1254-1254.png)

What's more frustrating is that you know the model itself isn't the problem—it's the context. It's weighed down by the baggage of a long session. More and more people call this **Context Rot**: not that context is too short, but that it has started to get dirty.

Your natural instinct is: open a new window. But you hesitate immediately. A new window means re-feeding prompts, re-explaining project background, re-pasting design docs, re-stating which plans were rejected, and re-telling it where the code currently stands. More importantly, you lose a lot of valuable discussion from before.

So you're stuck in an uncomfortable place:

> The current session is no longer clean.
> But starting a new one is too "expensive."
> What you really want isn't a full restart—it's to go back to a point that was still clean.

That's the problem PawGit is built to solve.

![You don't want a new window and a full re-brief—you want to return to a clean session state](https://img.alicdn.com/imgextra/i1/O1CN013ToS4J1giCj57TDSI_!!6000000004175-2-tps-1254-1254.png)

## Overview

1. What PawGit is: recoverability for Agent session state
2. How to use PawGit: Rewind, Timeline, GC, and Reset
3. Recommended workflow: using PawGit in real Agent work
4. Summary: a third option beyond dirty sessions and expensive restarts

(About 8 minutes to read)

## I. What PawGit Is: Recoverability for Agent Session State

### 1. Why Agent sessions need version control

We're used to version control for code. Break something? Revert to the last commit. Before a refactor? Tag it. Want to try an uncertain direction? Open a branch. Even if it fails, it's not the end of the world—Git gives us a simple safety net: I can explore, and I can come back.

But when we work with Agents, what changes isn't just code. It's also:

- The current session state.
- The Agent's understanding of the project.
- Judgments, biases, corrections, and half-baked conclusions accumulated over dozens of turns.

None of this has Git. So we often hit an absurd situation: project files can be restored to 10 minutes ago, but the Agent's "mind" can't go back. It keeps moving forward with that messy context. For ordinary chat, that might be fine. But an Agent is different—it reads files, writes files, calls tools, updates memory, and keeps reasoning on top of existing context. Once a bad state enters later reasoning, it's not just one wrong answer—it becomes context debt.

That's where PawGit comes in. It's not a replacement for project Git. It does something else: **add save points for QwenPaw Agent session state**.

### 2. How PawGit saves Agent session state

PawGit is a QwenPaw plugin, available on the official platform: [https://platform.agentscope.io/plugins/pawgit](https://platform.agentscope.io/plugins/pawgit).

![PawGit plugin page](https://img.alicdn.com/imgextra/i1/O1CN01d0hBui28YrtUkYTK4_!!6000000007945-2-tps-1366-680.png)

It maintains a private directory in the workspace:

```text
<workspace>/.pawgit/
```

Think of it as the Agent's save slots. Inside is a shadow Git repository that stores PawGit checkpoints. This repo doesn't take over your project and doesn't require your business code to use Git. It borrows Git's object storage and ref management to snapshot state during Agent work. The layout looks like this:

```text
<workspace>/.pawgit/
|-- shadow.git/    # PawGit's private Git repo
|-- index          # Git index used by PawGit
|-- config.toml    # PawGit configuration
|-- heads.json     # Logical HEAD per session
```

Each checkpoint captures workspace content under PawGit management and writes it as an independent Git tree. One detail worth noting: **PawGit checkpoint commits are parentless commits**. Each checkpoint is a standalone snapshot; history isn't expressed through Git's parent chain. The real session timeline DAG is maintained by PawGit through metadata and `heads.json`.

Why design it this way?

Because PawGit cares about Agent state history, not source history. It needs **fast creation**, **fast lookup**, **fast cleanup**, and **rollback-friendly state points**—not a traditional code commit chain. Parentless commits make GC much faster when cleaning up checkpoints that are no longer needed.

## II. Using PawGit: Rewind, Timeline, GC, and Reset

This section covers PawGit's core capabilities. In practice you don't need to remember internals—just a few actions: create recovery points with snapshot, inspect the path with timeline, dry-run before rewind, then rewind for real; use GC when auto snapshots pile up; use reset when you need to clear PawGit's own archive system.

### 1. Snapshot: create stable recovery points

With PawGit, before a slightly risky Agent task I create a named snapshot:

```bash
/pawgit snapshot before-runtime-refactor
```

Although an auto snapshot runs after every reply, manual snapshots get human-readable names and aren't removed by GC. It's a small action, but the mental load drops immediately.

![Create a named snapshot before a critical task](https://img.alicdn.com/imgextra/i3/O1CN01Z9WH0k1PROiyJIykS_!!6000000001837-2-tps-853-232.png)

Then I can let QwenPaw read code, compare options, and try implementations without worrying that once the conversation drifts, I'm stuck pushing through dirty context. Named snapshots go into PawGit's permanent snapshot area—they won't be cleared by ordinary GC:

```text
refs/snap/
```

I prefer naming at key milestones. Days later, `before-runtime-refactor` is still easier to understand than "auto checkpoint #17."

### 2. Timeline: inspect checkpoints and state history

The best moment for PawGit is when you suddenly realize: this session has gone wrong. Common signals:

- It brings up a plan you already rejected again.
- It keeps explaining an unimportant compatibility branch.
- You say "don't touch core code"; it agrees, but later analysis still assumes core changes are fine.
- It has zigzagged between directions, leaving residue from old plans in every answer.

Then check the timeline:

```bash
/pawgit timeline
```

You'll see checkpoints in the current session—auto checkpoints, manual snapshots, and safety backups created before real rewinds.

![View session checkpoints via timeline](https://img.alicdn.com/imgextra/i1/O1CN01xOJkHY1FEtl1isRJT_!!6000000000456-2-tps-1047-976.png)

Conceptually it looks like this:

```text
# PawGit Timeline

## Checkpoint Graph

`*` HEAD, `o` active path, `x` branch

ROOT
\-- o #1 auto 40d652e48fa5
    \-- * #2 snap before-runtime-refactor 92d92e8808fd
```

The symbols are straightforward:

```text
*  current session HEAD
o  active path
x  branch left after rewind
```

PawGit 0.2 also adds a UI page for a clearer checkpoint view—stage relationships and details at a glance.

![Checkpoint view in the PawGit UI](https://img.alicdn.com/imgextra/i1/O1CN01VGvGmE1VRIKVP23j3_!!6000000002649-2-tps-1771-794.png)

From `/pawgit timeline` output you can rewind by index:

```bash
/pawgit rewind 1
```

Or by snapshot name:

```bash
/pawgit rewind before-runtime-refactor
```

Or by commit SHA prefix:

```bash
/pawgit rewind 92d92e8808fd
```

But I recommend not rewinding immediately—dry-run first.

```bash
/pawgit rewind before-runtime-refactor --dry-run
```

Dry-run doesn't write files, move HEAD, or change the current session. It only shows what a real rewind would restore.

![Dry-run before rewind to preview impact](https://img.alicdn.com/imgextra/i2/O1CN01TFA2pa20fitbYvAMF_!!6000000006877-2-tps-953-362.png)

This step matters. Between "I want to go back" and "I'm actually back at that state," a preview is worth having.

### 3. Slash commands, skills, and tools: multiple entry points

You might think: typing commands manually is tedious. PawGit also provides skills and tools. Besides slash commands, you can find them on the Skills and Tools pages. A QwenPaw 2.0 version is in development; on 1.0 the skill is named `pawgit`.

![PawGit skill page](https://img.alicdn.com/imgextra/i2/O1CN016Dta6X1e9jgg24tzt_!!6000000003829-2-tps-1282-812.png)

![PawGit tool page](https://img.alicdn.com/imgextra/i2/O1CN01HFd2Fk1gHBMH1Ao5Z_!!6000000004116-2-tps-2154-842.png)

So besides actually running `/pawgit rewind`, you can ask the Agent to run other commands for you.

For example, ask the Agent to show the timeline:

![Ask the Agent to show the PawGit timeline](https://img.alicdn.com/imgextra/i3/O1CN01EFxrMO1xajjikUykz_!!6000000006460-2-tps-940-811.png)

Or ask it to explain how to use PawGit:

![Ask the Agent to explain PawGit usage](https://img.alicdn.com/imgextra/i3/O1CN01l53HPa1n6NK66TWQz_!!6000000005040-2-tps-956-1156.png)

There's a safety boundary: because rewind modifies files and directly affects Agent runtime state, the Agent will never execute a real rewind on its own. At most it may run rewind with `--dry-run`. Real rewind stays with the human.

### 4. Rewind: restore current session state

After dry-run looks good:

```bash
/pawgit rewind before-runtime-refactor
```

![Execute a normal rewind](https://img.alicdn.com/imgextra/i3/O1CN01f20Kf51EOED6NGg00_!!6000000000341-2-tps-927-362.png)

Normal rewind is deliberately narrow. It only restores the current session's session JSON. It does not roll back project code, arbitrarily change workspace files, or touch `MEMORY.md`.

It solves a very specific problem:

> I don't want a new window.
> I don't want to keep carrying dirty context.
> I just want this session back at a clean point from before.

That's one of the biggest differences from ordinary Git. Git manages project file history. PawGit manages Agent session state history. They complement each other—they're not the same thing.

### 5. Memory Rewind: handle long-term memory pollution

Sometimes the problem isn't only the current session. Say you asked the Agent to summarize project conventions and it wrote to:

```text
MEMORY.md
memory/
```

Later you find the summary wrong or outdated. That's awkward—these files are often shared at workspace level. New sessions may keep reading them. The error isn't just "wrong in this chat"—it becomes long-term memory pollution.

Use memory rewind:

```bash
/pawgit rewind before-memory-change --include-memory --dry-run
```

Then after confirming:

```bash
/pawgit rewind before-memory-change --include-memory --confirm
```

![Memory rewind with --include-memory](https://img.alicdn.com/imgextra/i2/O1CN01DHssFo28UHvwZsORq_!!6000000007935-2-tps-912-403.png)

This command requires `--confirm` by design. `--include-memory` restores:

```text
current session JSON
MEMORY.md
memory/
```

`MEMORY.md` and `memory/` can affect multiple sessions. Rolling them back in one session may discard memories another session wrote after the target checkpoint. PawGit won't let you do memory rewind casually—it expects dry-run first, then confirm.

### 6. Safety boundary: real rewind must be user-triggered

PawGit has two entry points.

User slash commands:

```bash
/pawgit timeline
/pawgit snapshot before-refactor
/pawgit rewind 1
```

And Agent tool calls:

```python
pawgit(action="timeline", limit=10)
pawgit(action="snapshot", message="before-risky-change")
pawgit(action="rewind", target="1", dry_run=true)
pawgit(action="gc", dry_run=true)
```

But there's a hard line:

> Agent tools can dry-run rewind, not execute real rewind.
> If the Agent tries a real rollback, PawGit requires a slash command.

That matters because real rewind changes the session state the Agent depends on. If tools could rewrite that context mid-reasoning, you get a recursive risk: it thinks while swapping out the basis for why it's thinking that way.

So real rewind must be explicitly triggered by the user. The Agent can show timeline, explain risk, and dry-run. The final click is yours.

### 7. GC: manage auto checkpoint lifecycle

Besides manual snapshots, PawGit creates an auto checkpoint after every Agent reply, stored under:

```text
refs/auto/
```

To avoid excessive auto snapshots, debounce is configurable:

```toml
[auto]
debounce_seconds = 1.5
```

Auto checkpoints suit "the last few turns went wrong—I want to go back a bit." Snapshots can't grow forever, so PawGit has GC:

```bash
/pawgit gc --dry-run
/pawgit gc
```

Default settings are roughly:

```toml
[gc]
gc_keep_count = 20
gc_keep_days = 7
pre_rewind_retention_days = 7
```

Each session keeps a recent batch of auto checkpoints; auto and pre-rewind within a retention window; manual snapshots are always kept.

For more aggressive cleanup, add `--compact`:

```bash
/pawgit gc --compact
```

To clean all sessions, add `--all-sessions`:

```bash
/pawgit gc --all-sessions
```

I still recommend dry-run first. Most risky PawGit actions should be previewed.

### 8. Reset: clear PawGit state, not project rollback

To fully clear PawGit's own state:

```bash
/pawgit reset --confirm
```

This deletes and rebuilds:

```text
.pawgit/
```

—checkpoints, refs, timeline metadata, and config. It does **not** modify:

```text
project files
current session JSON
MEMORY.md
memory/
```

So reset means "clear PawGit's archive system," not "restore the workspace."

## III. Recommended Workflow in Real Agent Work

For day-to-day use, a few flows are enough.

### 1. Snapshot before long tasks

```bash
/pawgit snapshot before-long-session
```

### 2. When context feels wrong: preview, then rewind

```bash
/pawgit timeline
/pawgit rewind 2 --dry-run
/pawgit rewind 2
```

### 3. When long-term memory is wrong: Memory Rewind

```bash
/pawgit timeline
/pawgit rewind before-good-memory --include-memory --dry-run
/pawgit rewind before-good-memory --include-memory --confirm
```

### 4. Periodically clean old auto snapshots

```bash
/pawgit gc --dry-run
/pawgit gc
```

### 5. Clear PawGit archive state

```bash
/pawgit reset --confirm
```

That's it. You don't need to watch PawGit every day. It's more like a seatbelt—you barely notice it until a long session starts to rot, and then you're glad you snapped in earlier.

## IV. Summary: A Third Option for Long Sessions

I don't think the biggest problem with AI Agents is that they make mistakes. People do, programs do, systems go down wrong paths. What's painful is when bad state gets inherited. A wrong belief in one reply is easy to fix. Once it enters context, memory, and dozens of later reasoning steps, it becomes cognitive debt—you spend more time correcting than progressing.

That's why I increasingly feel Agent systems need more than longer context, stronger models, and richer tools. They need **recoverability**.

Checkpoints.

Dry-run.

Rewind.

A third path between "open a new window and re-feed the prompt" and "keep chatting through dirty context."

That's what PawGit is for. It doesn't promise Agents never err. It admits they do, that long sessions rot, that context sometimes gets dirty—and gives you a dignified way to go back.

Finally, although certain products use tricks to block similar capabilities, we're still grateful to Claude Code's rewind design, which informed PawGit's implementation.
