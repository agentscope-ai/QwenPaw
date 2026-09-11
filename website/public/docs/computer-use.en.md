# Computer Use

Computer Use is an optional tool plugin that lets a QwenPaw Agent operate
**approved desktop applications** on your computer. It can launch apps, inspect
windows, click controls, enter text, scroll, and drag to complete routine
desktop tasks.

> **Beta feature:** Computer Use currently supports Windows and macOS, and is
> available only in the QwenPaw Desktop app. Install the plugin before use, and
> use it only when you can supervise the operation and are comfortable granting
> the target application access.

---

## Before you start

### Supported platforms

Computer Use relies on native capabilities supplied by QwenPaw Desktop.

| Platform | Requirement                                                    |
| -------- | -------------------------------------------------------------- |
| Windows  | Windows 10 or later, x64                                       |
| macOS    | macOS 14 (Sonoma) or later; Apple Silicon Macs are recommended |

Linux, the browser-based Console, Docker, and command-line-only environments
do not support Computer Use. The current plugin release targets QwenPaw 2.1.x;
always follow the compatibility notice shown in Plugin Manager when installing.

### Install the Computer Use plugin

Computer Use is not enabled as a default built-in tool. Install its plugin
first:

1. Start QwenPaw Desktop and open **Settings → Plugin Manager**.
2. Search for **Computer Use** under **Official Plugins** or **Plugin Market**,
   then select **Install**.
3. If you received a trusted plugin ZIP file or install URL from another
   source, select **Install Plugin** in the upper-right corner, then upload the
   ZIP file or enter the plugin URL.
4. In **Installed Plugins**, make sure **Computer Use** is shown as **Running**.
   Restart QwenPaw Desktop if the plugin has not loaded.

> Install plugins only from Official Plugins, Plugin Market, or another source
> you trust. Do not grant desktop-automation permissions to an unknown ZIP
> file.

### Use QwenPaw Desktop

Computer Use needs the native capabilities in
[QwenPaw Desktop](./desktop). Install and start the desktop app before
installing the plugin.

### macOS: grant the required permissions

On first use, macOS may request these permissions:

- **Accessibility**, so QwenPaw can operate controls in approved apps;
- **Screen Recording**, so QwenPaw can read the target window.

Allow the requests when macOS prompts you. If a prompt does not appear, or the
feature still cannot work after approval, open **System Settings → Privacy &
Security**. Confirm that QwenPaw Desktop is allowed under **Accessibility**
and **Screen Recording**, then restart QwenPaw Desktop.

Windows normally needs no additional setup. System-security prompts and
administrator-only interfaces are not valid targets for Computer Use.

---

## Feature controls

Computer Use has a global switch and an Agent-level switch. Both must be on
before an Agent can use the feature; operating an application still requires
separate approval for that application.

| Switch                 | Location                               | Scope                                                     |
| ---------------------- | -------------------------------------- | --------------------------------------------------------- |
| **Global switch**      | **Computer Use → Enable Computer Use** | Every Agent and chat in this QwenPaw Desktop installation |
| **Agent-level switch** | **Agent → Tools → Computer Use**       | The currently selected Agent                              |

### Global switch

Open **Computer Use** from the left sidebar in QwenPaw Desktop. Make sure the
runtime says it is ready, then check that **Enable Computer Use** is on. It is
on by default after installation until a choice has been saved, and your choice
persists after restarting the desktop app.

If Computer Use is missing from the sidebar, check that the plugin is
installed and restart the desktop app.

Turning off the global switch prevents every Agent and chat from using Computer
Use, stops active automation, and cancels pending application-access requests.
Use it to turn off the entire feature temporarily, not to stop one chat.

### Agent-level switch

Open **Agent → Tools** for the Agent that needs the feature and make sure
**Computer Use** is enabled. The plugin adds this tool to Agents and preserves
the switch setting you have already saved.

Turning off the Agent-level switch prevents only the current Agent from using
Computer Use. It does not affect other Agents or the global switch. It is not
a control for interrupting a task already in progress; to stop a task in one
chat, stop that chat directly.

---

## Get started in three steps

### 1. Start Computer Use in a conversation

In the chat where you want to operate a desktop application, enter
**`/computer_use`**. Follow the prompt to start Computer Use, then describe the
task you want to complete.

Before you start, make sure both the global switch and the current Agent's
tool switch above are enabled.

### 2. Give the Agent a task

State what you want to do and which application to use. For example:
**`/computer_use Create a meeting-notes document in Notepad and write these three action items.`**

When it first works with an app, the Agent checks the available windows and
reads the current state of the target window before clicking or typing. It also
checks again after the interface changes.

### 3. Approve application access

When the Agent needs to operate a new application, the chat shows an
**Application access** request. Verify the application name and displayed file
path, then choose one of the following options:

| Option                     | Meaning                                                                                    |
| -------------------------- | ------------------------------------------------------------------------------------------ |
| **Deny**                   | The Agent cannot operate the application and will not continue operating it for this task. |
| **Allow for this session** | Allow access only in the current chat session. You will be asked again in a later session. |
| **Always allow**           | Save access for this application so the same application does not ask again.               |

When in doubt, choose **Allow for this session**.

---

## Pause, resume, and stop a task

### Use your computer yourself

If you have recently used the mouse or keyboard, Computer Use temporarily
refuses the Agent's next desktop action. This prevents you and the Agent from
operating the same interface at once. Wait briefly, then ask the Agent to
inspect the window again before it continues.

This protection does not stop the entire task automatically, and it does not
save or undo changes in the target application.

### Stop immediately

To stop Computer Use in the current chat, stop the chat directly. This also
interrupts the Agent and its Computer Use actions in that chat.

### Manage saved access

Open **Computer Use → Access management** to see every application marked
**Always allow** and revoke any saved access. The next attempt to operate a
revoked application asks for your approval again.

---

## Safety boundaries

Computer Use binds input to the target window it just observed and refuses new
desktop input when the desktop is locked or it detects that you have recently
used the mouse or keyboard. The native runtime also rejects QwenPaw's own
windows and some credential windows that the operating system can identify.

These protections cannot identify every sensitive interface. System-permission
or security prompts, password and verification-code fields, CAPTCHAs, and
two-factor authentication flows primarily rely on the Agent's operating
guidance; do not treat them as absolute, feature-level blocks.

Handle these sensitive interfaces yourself, or review the action carefully
before continuing. Grant access only to applications you trust the Agent to
operate. Before choosing **Always allow**, check the application path carefully
to avoid authorizing an unknown program with a similar name.

---

## Troubleshooting

### The runtime is unavailable

Make sure you are using QwenPaw Desktop rather than the browser Console or a
command-line-only installation. If the runtime remains unavailable after
restarting the desktop app, update to a version that includes Computer Use and
include the desktop-app logs when reporting the problem.

### macOS cannot capture or click a window

Check QwenPaw Desktop's **Accessibility** and **Screen Recording** permissions
in **System Settings → Privacy & Security**. Fully quit and reopen QwenPaw
Desktop after changing either permission.

### The Agent cannot find the application

Open the target application yourself and keep its window visible, then submit
the task again. If several windows are open, tell the Agent the window title or
the content it should operate.

### The Agent did not continue after I moved the mouse

This is a safeguard against simultaneous human and Agent input. Wait briefly,
then ask the Agent to inspect the target window again; do not ask it to reuse
the previous click position.

---

## Related pages

- [Desktop App](./desktop) — installation, launch, and desktop troubleshooting
- [MCP & Built-in Tools](./mcp) — view and manage the tools available to an
  Agent
