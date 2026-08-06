# Chrome extension

The Chrome extension connects QwenPaw to the Chrome you already use. Once
connected, an Agent can open tabs, click, and type inside your signed-in
browser — visible to you the whole time, and yours to take over at any moment.

> **Beta feature:** only local installation is supported for now (load the
> unpacked extension in Chrome). The Chrome Web Store listing is not available
> yet.

---

## Before you start

### Supported environment

| Item    | Requirement                                                                                         |
| ------- | --------------------------------------------------------------------------------------------------- |
| Browser | Desktop Google Chrome                                                                               |
| OS      | Windows, macOS, Linux                                                                               |
| QwenPaw | Runs on the same machine as Chrome and listens on a local address (`127.0.0.1`, `localhost`, `::1`) |

The extension relies on Chrome Native Messaging: it has to be able to start
QwenPaw's local connection helper. The following setups therefore do not work:

- QwenPaw runs in Docker, on a remote server, or in the cloud while Chrome runs
  on your own machine.
- You reach the Console through a non-local address. Setup then fails with an
  explicit message that QwenPaw must listen on a local address.

For those setups use the standalone browser instead (`avatar` / `guest`
identity) — see [Browser](./browser).

### Install the Chrome plugin

Chrome connectivity is provided by the official **Chrome** plugin, so install
the plugin first:

1. Open the Console and go to **Settings → Plugin Manager**.
2. Find **Chrome** under **Official Plugins** and select **Install**.
3. If you received a trusted plugin ZIP file or install URL from another
   source, select **Install Plugin** in the upper-right corner, then upload the
   ZIP file or enter the plugin URL.
4. Refresh the page after installing; a **Chrome** entry appears in the left
   sidebar.

> Only install plugins from the official list or other trusted sources. This
> plugin acts on pages in your browser on your behalf — do not grant that to a
> ZIP file of unknown origin.

---

## Install the extension

Open **Chrome** in the left sidebar. The top of the page shows the current
connection state, followed by **Install method**: **Local install** is marked
**Recommended** and is the only method available today, while **Chrome Web
Store** shows **Coming soon**.

Follow the **Local install steps** — you only need to do this once:

1. **Copy extensions page address** — select **Copy chrome://extensions**, then
   paste it into Chrome's address bar and press Enter.
2. **Enable Developer mode** — turn on **Developer mode** in the upper-right
   corner.
3. **Click load button** — select **Load unpacked** in Chrome.
4. **Paste path and open** — follow the **Quick paste path tips** on the right
   and select **Copy QwenPaw extension path** first, then follow your platform:

| Platform | In the folder picker                                                              |
| -------- | --------------------------------------------------------------------------------- |
| macOS    | Press `Cmd + Shift + G`, paste the path, press Enter, then select **Open**        |
| Windows  | Click the address bar, paste the path, press Enter, then select **Select Folder** |
| Linux    | Press `Ctrl + L`, paste the path, press Enter, then select **Open**               |

Return to the QwenPaw page and select **I've installed it, refresh status**.

> You can also use **Copy Path** or **Open Folder** to get at the extension
> folder directly.

![Console Chrome page showing install methods and local install steps](https://img.alicdn.com/imgextra/i2/O1CN018PXoUzHJ5WH68fdG_!!6000000004186-0-tps-3024-1654.jpg)

![Chrome extensions page with Developer mode on and Load unpacked available](https://img.alicdn.com/imgextra/i1/O1CN015fXKuBrqFoI68fdG_!!6000000006443-0-tps-3024-1654.jpg)

---

## Connection status

The top of the page shows one of three states:

| State                                       | Meaning                                                  | What to do                                          |
| ------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------- |
| **Install Chrome Extension**                | Extension files are ready but Chrome has not loaded them | Load the extension with the steps above             |
| **Extension installed, waiting for Chrome** | The extension is loaded, the connection is not up yet    | Keep Chrome running, then select **Refresh Status** |
| **Chrome Connected**                        | Connected, showing extension version and connect time    | Ready for the Agent to use                          |

Once connected, the QwenPaw icon in the Chrome toolbar also reports status:
open it to see **Status** (connected or not), **QwenPaw tabs** (how many tabs
QwenPaw currently manages), and the extension **Version**.

### Connection checks

The **Connection checks** section lists health item by item, each marked
**Ready** or **Needs attention**:

| Check                     | Meaning                                                            | Advice when it needs attention                                   |
| ------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------- |
| **Extension bridge**      | The connection between the extension and QwenPaw                   | Reload the extension, or reopen the target browser tab           |
| **Native Messaging host** | Whether the local connection helper is installed and usable        | Reinstall the Native Messaging host (rerun setup from this page) |
| **Extension assets**      | Whether the version loaded in Chrome matches the one QwenPaw ships | Reload the unpacked extension in `chrome://extensions`           |
| **Bridge lifecycle**      | Whether the connection is stable                                   | Wait a moment or restart Chrome                                  |

It is worth revisiting this page after upgrading QwenPaw: if **Extension
assets** reports a version mismatch, rerun setup and reload the extension in
Chrome.

![Console Chrome page connected, with all four connection checks ready](https://img.alicdn.com/imgextra/i3/O1CN01wTb1PytQ6VK68fdG_!!6000000000485-0-tps-3024-1654.jpg)

---

## Let an Agent use your Chrome

No extra configuration is needed once connected: while `browser.identity` stays
at its default `auto`, the Agent uses your Chrome automatically (the `user`
identity). Set it explicitly to pin the behaviour — see [Browser](./browser).

The Agent works in new tabs of your Chrome. For sign-in, CAPTCHA, two-factor
authentication, or any step that must be done by a person, it stops and hands
that step back to you.

---

## File locations

**Advanced information** shows the real paths on your machine:

| Name                    | Location                                                                                                                                                                                                                                                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Extension folder        | `~/.qwenpaw/chrome-extension/qwenpaw-chrome`                                                                                                                                                                                                                                                                                          |
| Local connection helper | `~/.qwenpaw/bin/qwenpaw-nm-host` (`qwenpaw-nm-host.bat` on Windows)                                                                                                                                                                                                                                                                   |
| Local connection config | macOS: `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.qwenpaw.browser.json`<br>Linux: `~/.config/google-chrome/NativeMessagingHosts/com.qwenpaw.browser.json`<br>Windows: `~/.qwenpaw/com.qwenpaw.browser.json` (also registered under `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.qwenpaw.browser`) |
| Local settings file     | `~/.qwenpaw/nm-bridge.json`                                                                                                                                                                                                                                                                                                           |
| Connection endpoint     | Derived from the address the service actually listens on, for example `ws://127.0.0.1:8088/api/ws/chrome`                                                                                                                                                                                                                             |

---

## Security boundaries

- **The connection endpoint cannot be supplied manually.** It is derived from
  the address QwenPaw actually listens on, and must be a local address.
- **The local settings file holds a locally generated connection token**,
  readable only by your user (written with `600` permissions on macOS and
  Linux). The extension can only connect to QwenPaw on this machine.
- **The extension only accepts page messages from local addresses**
  (`localhost`, `127.0.0.1`, `[::1]`).

The extension needs Chrome's debugging, tabs, and all-sites permissions to act
on pages for you, which means it can act on the sessions you are already signed
in to in this Chrome. Keep it connected only for work you are willing to
delegate; disabling the extension in `chrome://extensions` disconnects it
immediately.

---

## Troubleshooting

### It stays on "Extension installed, waiting for Chrome"

Check in order: Chrome is running; the QwenPaw extension is enabled in
`chrome://extensions`; the QwenPaw service is running and listening on a local
address. Then select **Refresh Status**. If it still does not connect, reload
the extension in `chrome://extensions`.

### It stopped connecting after I changed the service port

The connection endpoint is derived from the address the service listens on.
After changing the `qwenpaw app` port, rerun setup from this page and reload the
extension in Chrome.

### It disconnects briefly after restarting Chrome or waking from sleep

The extension reconnects on its own (about 5 seconds at first, backing off to
at most 60 seconds). If the disconnect lasts longer than roughly a minute, the
extension stops acting on QwenPaw's behalf so it never keeps touching your
pages while out of contact; it resumes once reconnected.

### Can one computer connect to several QwenPaw instances?

No. The local connection config points at a single QwenPaw service, so one
Chrome connects to only one of them at a time.

### When will the Chrome Web Store version be available?

Not yet published. Use local install for now.

### I do not use Chrome

The extension currently supports desktop Google Chrome only. For other
browsers, use the standalone browser — see [Browser](./browser).

---

## Related pages

- [Browser](./browser) — browser identity, settings, and the standalone browser
- [Plugin system](./plugins) — installing and managing plugins
- [Desktop app](./desktop) — install, launch, and desktop troubleshooting
- [Security](./security) — access control and tokens
