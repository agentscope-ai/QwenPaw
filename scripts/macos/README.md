# macOS DMG packaging

Build from repo root:

```bash
bash scripts/macos/build_dmg.sh [VERSION]
bash scripts/macos/build_dmg.sh [VERSION] --dev   # also build Dev variant
```

Output: `dist/CoPaw.app`, `dist/CoPaw-<version>.dmg`.
With `--dev`: also `dist/CoPaw-Dev.app`, `dist/CoPaw-Dev-<version>.dmg`.

---

## Release vs Dev

| | Release (CoPaw.app) | Dev (CoPaw-Dev.app) |
|---|---------------------|----------------------|
| **UI** | Double-click opens one window: the **Console** (chat and config). | Same: the same Console window. |
| **Terminal / logs** | No terminal, no live logs. | Run from Terminal to see live backend logs, or check the log file after a crash. |
| **Log file** | Only a small amount in `gui_launcher.log`. | **All** stdout/stderr and uncaught exceptions go to `copaw_dev.log`. |
| **On crash** | Almost no visible error. | Uncaught exceptions are written to `copaw_dev.log`; open it for the full traceback. |
| **Use case** | Daily use, sharing with others. | Debugging, inspecting logs, tracking down crashes. |

Behaviour is the same; the Dev build adds live logs in the terminal and persistent logs (including exceptions) to a file for easier debugging.

---

**Release (CoPaw):** Double-click opens one window — the **Console** (CoPaw’s web UI for chat and config).

**Dev (CoPaw-Dev):** Same **Console** window (the CoPaw web UI) plus backend logs.

- **Console:** The window that shows the CoPaw interface (chat, settings). Same as the release app; it’s the main window that opens when you launch CoPaw-Dev.
- **Terminal (where to see logs):** If you double-click CoPaw-Dev in Finder, some macOS versions will also open **Terminal.app** and show logs there. If you don’t see a terminal, run the app **from Terminal** so logs appear in that window:
  ```bash
  # Built from source (app in dist/):
  /Users/xxxx/CoPaw/dist/CoPaw-Dev.app/Contents/MacOS/CoPaw-Dev
  # Installed from DMG (e.g. in Applications):
  /Applications/CoPaw-Dev.app/Contents/MacOS/CoPaw-Dev
  ```
  Replace the path if CoPaw-Dev.app is elsewhere. You must run the binary inside the .app (`…/Contents/MacOS/CoPaw-Dev`), not the .app folder.
- **Log file (even when no terminal):** All stdout/stderr and uncaught exceptions are written to
  `~/Library/Application Support/CoPaw/logs/copaw_dev.log`
  Open that file after a crash to see the traceback.

First launch runs `copaw init --defaults --accept-security` in
`~/Library/Application Support/CoPaw`. Closing the Console window quits the app and server.

## If macOS says the app is "damaged" (or "from an unidentified developer")

**Apps downloaded from the internet** (e.g. from GitHub Releases) are **quarantined** by macOS. Opening them before removing the quarantine often shows **"damaged"** or **"cannot be opened"**. This is normal for unsigned apps; the app is not actually damaged.

**Fix: remove the quarantine attribute, then open the app:**

```bash
# Typical: app is in Downloads after opening the DMG
xattr -cr ~/Downloads/CoPaw.app
xattr -cr ~/Downloads/CoPaw-Dev.app   # for Dev build

# If you moved the app elsewhere:
xattr -cr "/path/to/CoPaw.app"
```

Then open the app again. Alternatively, in **System Settings → Privacy & Security** you can click **"Open Anyway"** for the blocked app (after the first failed open).
