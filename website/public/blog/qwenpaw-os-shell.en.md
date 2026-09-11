---
title: "QwenPaw OS Shell: A Desktop for Conversations, Agents, and Apps"
date: 2026-08-06
author: QwenPaw Team
tags: [QwenPaw OS Shell, Agent Space, App Market, Approvals, Multi-window]
cover: https://img.alicdn.com/imgextra/i1/O1CN01KdzUBgLJLmH3OTaP_!!6000000003854-2-tps-1672-941.png
excerpt: "QwenPaw OS Shell is a desktop-style frontend layer built on top of QwenPaw Console, bringing conversations, Agent Spaces, apps, system settings, and multi-window workflows together on one AI desktop."
---

# QwenPaw OS Shell: A Desktop for Conversations, Agents, and Apps

As Agents move beyond answering questions and begin completing ongoing work, users need more than a single chat box.

A complete task may involve conversations, files, approvals, apps, settings, and multiple Agents at the same time. Traditional management interfaces often split these capabilities across sidebars and separate pages. You have to remember where everything is—and keep switching context while you work.

**QwenPaw OS Shell** offers a different way to organize that work: it brings QwenPaw's existing frontend pages onto one desktop. Chat becomes a window, files and tools become apps, and each Agent gets its own Agent Space. You can open, arrange, minimize, and switch between them just as you would in a desktop operating system.

Here, “OS” describes a **desktop-style frontend interaction model**. QwenPaw OS Shell is not a standalone operating system, and it does not replace Windows, macOS, or Linux. It shares the same backend, Agents, configuration, and app routes as the classic QwenPaw Console; it simply provides a desktop interface designed for multi-task workflows.

## 01 How to Enter QwenPaw OS Shell

You do not need to run a command or edit the browser address to enter QwenPaw OS Shell. You can switch directly from the classic Console:

1. Click the **gear button** in the bottom-left corner of the classic Console to open quick settings;
2. Find **Enter Desktop Mode** in the Mode section;
3. Click it to switch the current page directly to QwenPaw OS Shell.

On your first visit, the Console may display a “Try Desktop Mode” guide in the bottom-left corner, pointing to the quick-settings entry. Follow the prompt to find **Enter Desktop Mode**.

![Enter Desktop Mode from quick settings in the classic Console](https://img.alicdn.com/imgextra/i4/O1CN016yb4RooFSZJ5Bsl3_!!6000000006635-0-tps-2557-1224.jpg)

The page then changes to a full-screen desktop layout. The menu bar sits at the top, app windows and desktop icons occupy the center, and the Dock appears at the bottom. A short startup screen may appear the first time you enter.

To return to the classic Console, click the **QwenPaw logo** in the upper-left corner and select **Return to console**. OS Shell is simply another frontend entry point; switching interfaces does not create a second copy of your QwenPaw data.

![The Chat window on the QwenPaw OS Shell desktop](https://img.alicdn.com/imgextra/i1/O1CN01JLELdKorvLB5CGAm_!!6000000004339-0-tps-2560-1228.jpg)

## 02 Get to Know the Desktop: Icons, Launchpad, Dock, and Windows

Once you are in OS Shell, there are three ways to open an app:

1. **Desktop icons:** Double-click an icon to open the corresponding app;
2. **Launchpad:** Click the grid button on the far left of the Dock to view and open every app currently available;
3. **Dock:** Click a pinned or running app icon to open it or bring its existing window to the front.

Each app runs in its own window. The title bar displays the app name and provides controls to close, minimize, and maximize the window:

- **Close:** Remove the current window. You can reopen it later from the desktop, Launchpad, or Dock;
- **Minimize:** Temporarily put the window away while keeping the app in the current Agent Space;
- **Maximize:** Expand the window to fill the main work area, then click again to restore its previous size;
- **Switch focus:** Click any window directly, or click a running app in the Dock;
- **Move and resize:** Drag the title bar to move a window, or drag an edge or corner to resize it.

You can also double-click a window's title bar to switch between maximized and original size. Desktop app icons can be dragged into a cleaner arrangement, while Dock apps can be pinned and reordered to match the way you work.

These desktop interactions do not change what the apps themselves can do. Chat, Files, Skills, configuration pages, and PawApps still use QwenPaw's existing pages; OS Shell simply places them inside one consistent window system.

## 03 Start a Conversation and Approve Critical Actions

Chat is the most direct way to start work in QwenPaw OS Shell. Open Chat, describe your goal as usual, and let the current Agent analyze the task, use tools, and report progress.

A conversation does not mean handing every permission to the Agent at once. When a tool call triggers a security policy, QwenPaw pauses that action and waits for a human decision.

You can handle an approval in three ways:

1. Select **Approve** or **Deny** directly from the approval notification in the upper-right corner of the desktop;
2. Open Inbox from the notification to review the tool, parameters, and risk information before deciding;
3. Enter **`/approve`** or **`/deny`** in Chat to process the current request. If several requests are pending, you can include the request ID.

Approval controls the pending critical action; it does not close the conversation. After approval, the task continues. After denial, the Agent receives the result and can revise its plan or explain the next step.

**Recommendation:** Do not approve a request simply because the Agent wants to continue. Check the tool, target path, parameters, and expected impact. If the information is incomplete, denying the request and asking the Agent to explain is usually safer than allowing it immediately.

## 04 Switch Agents—and the Entire Workspace With Them

In QwenPaw OS Shell, every Agent has its own **Agent Space**. Each space preserves that Agent's open windows and desktop layout, so switching Agents means switching an entire working scene—not just changing a name.

Move the pointer to the top edge of the desktop to reveal the Agent Space strip, then click a space name directly. Each space shows its current window count, making it easy to choose the workspace you want to resume.

For example, you can use the Default Agent for everyday conversations and a QA Agent for product questions or document verification. The QA Agent has its own window arrangement, so its workspace does not disrupt the Default Agent's desktop.

![A separate desktop space for the QA Agent](https://img.alicdn.com/imgextra/i4/O1CN015P4tmnPeQSG5CGAn_!!6000000002843-0-tps-2560-1229.jpg)

This separation works well in two common situations. You can divide spaces by role—such as research, development, and quality assurance—or divide them by project so that each Agent's conversations, files, and app windows stay within a clear boundary.

Agent Spaces isolate the window layout inside OS Shell. When you switch spaces, the current arrangement is preserved. Switch back later, and you can continue from the same set of windows.

## 05 Install an App from App Market and Open It Immediately

QwenPaw OS Shell provides a unified **App Market** for managing desktop apps and PawApps. Its content falls into three main groups:

- Desktop apps built into QwenPaw;
- PawApps already installed in the current instance;
- Apps available to install from the plugin market.

![App Market in QwenPaw OS Shell](https://img.alicdn.com/imgextra/i4/O1CN01HGGw9SrWaUK5CGAi_!!6000000006930-0-tps-2560-1224.jpg)

The installation flow is similar to using a regular desktop app store:

1. Double-click **App Market** on the desktop;
2. Search or browse for the app you need;
3. Review its description, version, and compatibility notice;
4. Click Install and wait for the process to finish;
5. Open the new app from its desktop icon or from Launchpad.

During this walkthrough, we installed **Agent Kanban**. As soon as the installation finished, it appeared on the QwenPaw OS Shell desktop and could be opened in its own window without leaving the current Agent Space.

![Agent Kanban opened after installation](https://img.alicdn.com/imgextra/i4/O1CN01ry1ahIYcqPE5CGAk_!!6000000007395-0-tps-2560-1226.jpg)

Apps still run through QwenPaw's plugin and routing system underneath OS Shell. Before installing one, confirm its source, version compatibility, and required permissions. If you no longer need an app, return to App Market to uninstall it.

## 06 Manage Configuration in System Settings

As QwenPaw gains more capabilities, its configuration entry points need to stay organized. System Settings brings common management tools into a single window, including:

- Agents and Models;
- Skill Pool and Environments;
- Security and Token Usage;
- Backups and Voice Transcription;
- Debug and Plugin Manager.

![System Settings in QwenPaw OS Shell](https://img.alicdn.com/imgextra/i1/O1CN0197z888mPcoD5CGAl_!!6000000001126-0-tps-2560-1227.jpg)

To add an Agent, change a model, manage Skills, or review security settings, double-click **System Settings** on the desktop and choose the relevant category from the left sidebar. When you finish, close the window to return to the same desktop; the positions of your other apps remain undisturbed.

For an instance that will run over the long term, check three areas first: whether the default model is available, whether each Agent's tool access matches its responsibilities, and whether the approval and sandbox policies under Security match the risk level of the current workspace.

## 07 Multi-window Workflows: Keep Task Context on the Desktop

Complex tasks rarely fit comfortably on a single page. QwenPaw OS Shell lets multiple app windows remain open at the same time, keeping conversations, files, settings, and specialized apps together on one desktop.

A typical workspace might include:

- Chat, where you assign the task and follow the Agent's progress;
- Files, where you inspect documents the Agent reads or creates;
- A PawApp such as Agent Kanban, where you manage structured tasks;
- System Settings, kept nearby so you can adjust Agents, models, or security controls when needed.

![Chat, Files, and Agent Kanban open together in multiple windows](https://img.alicdn.com/imgextra/i3/O1CN01sEc6VFNbC5J5CGAe_!!6000000000192-0-tps-2560-1220.jpg)

### Arrange and Switch Between Windows

Drag a title bar to reposition a window. Drag an edge or corner to change its width and height. You can also drag a window toward the edge of the desktop to use a snap layout and place two working windows side by side.

Clicking a window brings it to the front. When several windows overlap, click the relevant app icon in the Dock to focus it quickly. Running apps retain a status indicator in the Dock.

### Put Windows Away Temporarily

Click Minimize when you need more room on the desktop. The window is put away but remains part of the current Agent Space. Click its app in the Dock to restore it with the original task context intact.

Closing and minimizing are different. Closing removes the window from the current desktop, but it does not uninstall the app. You can still reopen it from a desktop icon, Launchpad, or App Market.

### Manage Multiple Windows with Mission Control

When the desktop becomes busy, move the pointer to the top edge of the desktop to reveal the Agent Space strip, then click the current space name. Mission Control lists every window in the current Agent Space; click any window card to focus that app directly.

The top of Mission Control also shows how many windows are preserved in each Agent Space. This makes it both a window switcher and the main entry point for moving between different Agents' working scenes.

In the screenshot above, Chat, Files, and Agent Kanban are all open in the QA Agent's space. You can arrange them side by side or layer them according to how frequently you use each one. Clicking any window brings it to the front. You do not have to leave Chat to inspect a file, or hunt through separate pages to find an app. In Agent workflows that require continuous observation and frequent verification, keeping the context visible can matter more than simply adding more features.

## 08 Usage and Security Tips

QwenPaw OS Shell makes Agent work easier to see, but placing an app in a window does not change the permissions already available to that app or its tools. Keep these practices in mind:

1. **Check the target before approving access.** Review the tool, parameters, paths, and real-world impact instead of approving mechanically when notifications become frequent.
2. **Divide Agent Spaces by responsibility.** Use different Agents for different projects or trust boundaries so sensitive work does not become mixed with everyday tasks.
3. **Install only trusted apps.** Prefer official listings, the plugin market, or verified sources, and pay attention to version compatibility.
4. **Match models, tools, and permissions.** More capable Agents should have clearer workspace boundaries, sandbox policies, and approval rules.
5. **Review windows and apps regularly.** Close windows you no longer need and uninstall unused apps to keep every Agent Space easy to understand.

Moving from a chat page to an AI desktop is about more than adding a few windows. QwenPaw OS Shell brings Agents, apps, and human decisions into the same visible workspace: Agents can keep moving forward, while people can still understand, switch, and take control at critical moments.

When conversations, approvals, settings, and multiple apps each have a clear place on the desktop, QwenPaw becomes much closer to a personal Agent workspace designed for long-term use.

## Further Reading

- [QwenPaw Quick Start](/docs/quickstart)
- [QwenPaw Commands](/docs/commands)
- [QwenPaw Security](/docs/security)
