---
summary: Browser automation with 30+ operations (navigation, interaction, screenshots)
---

Browser automation with 30+ operations.

- **Basic Navigation**: start, stop, open, navigate, navigate_back, close
- **Page Interaction**: click, type, hover, drag, select_option
- **Page Analysis**: snapshot, screenshot, console_messages, network_requests
- **Form Operations**: fill_form, file_upload, press_key
- **JavaScript Execution**: eval, evaluate, run_code
- **Advanced Features**: cookies_get, cookies_set, cookies_clear, tabs, wait_for, pdf, resize, handle_dialog, install, connect_cdp, list_cdp_targets, clear_browser_cache
- Use `action` parameter to specify operation type
- Runs in headless mode by default; use `headed=True` to launch a visible browser window
- Supports multiple tabs (use different `page_id` values)
- `click` supports two targeting modes: element locators (`ref`/`selector`) and page coordinates (`page_x` / `page_y`, in page viewport pixels). When both are provided, the priority is `ref > selector > page_x/page_y`, and the coordinate parameters only take effect when neither `ref` nor `selector` is given
  - Coordinate clicks are backed by `page.mouse.click(...)`; they support `button` and `double_click`, but not `modifiers_json`
  - **When to use:** Designed for Canvas/WebGL UIs where no DOM sub-elements exist. Coordinates can be estimated from screenshots or computed via `action=evaluate` for pixel-precise targeting. Example evaluate-based workflow: (1) `action=evaluate` to get the canvas element's bounding rect, (2) compute click point with known offsets, (3) `action=click` with `page_x`/`page_y`

```json
{
  "action": "click",
  "page_x": 420,
  "page_y": 260
}
```

### CDP Mode (Advanced Feature)

The browser tool supports connecting to a running Chrome browser via Chrome DevTools Protocol (CDP):

- **Start with CDP port exposed**: Use `action="start"` with `cdp_port` (e.g., 9222) to launch Chrome with `--remote-debugging-port`
- **Connect to external browser**: Use `action="connect_cdp"` with `cdp_url` (e.g., `http://localhost:9222`) to connect to an already-running Chrome
- **Discover CDP endpoints**: Use `action="list_cdp_targets"` to scan local port range (default 9000-10000) and find available CDP connections

**CDP Mode Use Cases:**

- Connect to a user's manually opened Chrome (preserving login state, bookmarks, extensions, etc.)
- Integrate with external debugging tools
- Perform automation in an existing browser session
