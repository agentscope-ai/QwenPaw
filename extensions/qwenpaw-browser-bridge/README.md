# QwenPaw Browser Bridge

Chrome Extension that lets QwenPaw control your existing Chrome browser tabs.

## Installation

1. Open Chrome, navigate to `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select this folder: `extensions/qwenpaw-browser-bridge/`
5. Extension icon appears in the toolbar

## Configuration

Click the extension icon (Popup):

- **Host**: QwenPaw server address (default `127.0.0.1`)
- **Port**: QwenPaw server port (default `8088`)
- **Workspace**: Workspace identifier (default `default`)
- Click **Connect**

Status dot turns green when connected.

## Usage

### From QwenPaw Agent

```python
# 1. Start takeover mode (waits for extension to connect)
browser_use(action="start", mode="takeover")

# 2. List user's open tabs
browser_use(action="discover_tabs", mode="takeover")

# 3. Claim a tab (attaches debugger + shows control banner)
browser_use(action="claim_tab", page_id="chrome_42", mode="takeover")

# 4. Get accessibility tree snapshot
browser_use(action="snapshot", mode="takeover")

# 5. Interact with elements
browser_use(action="click", ref="e1", mode="takeover")
browser_use(action="type", text="hello", mode="takeover")
browser_use(action="press_key", key="Enter", mode="takeover")

# 6. Navigate
browser_use(action="navigate", url="https://example.com", mode="takeover")

# 7. Take screenshot
browser_use(action="screenshot", mode="takeover")

# 8. Evaluate JavaScript
browser_use(action="evaluate", text="document.title", mode="takeover")

# 9. Release tab (removes banner + detaches debugger)
browser_use(action="release_tab", page_id="chrome_42", mode="takeover")

# 10. Stop bridge
browser_use(action="stop", mode="takeover")
```

### Set Default Mode

In `agent.json`, set takeover as default:

```json
{
  "builtin_tools": {
    "browser_use": {
      "config": {
        "default_mode": "takeover"
      }
    }
  }
}
```

## HITL Controls

When a tab is claimed, a top banner appears with:

- **Pause** — temporarily halt automation
- **Stop** — release all tabs and disconnect
- **Log** — toggle operation log panel

## Architecture

```
QwenPaw Backend                        Chrome Extension
browser_use(mode=takeover)             Service Worker
  └─ BrowserTakeoverBridge ◄──WS──►   ├─ chrome.debugger CDP
     /ws/browser (JSON-RPC 2.0)        ├─ chrome.tabs API
     /browser-bridge/info              └─ Content Script (Banner)
```
