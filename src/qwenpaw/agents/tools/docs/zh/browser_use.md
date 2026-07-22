---
summary: 浏览器自动化，支持 30+ 种操作（导航、交互、截图等）
---

浏览器自动化，支持 30+ 种操作。

- **基础导航**：start, stop, open, navigate, navigate_back, close
- **页面交互**：click, type, hover, drag, select_option
- **页面分析**：snapshot, screenshot, console_messages, network_requests
- **表单操作**：fill_form, file_upload, press_key
- **JavaScript 执行**：eval, evaluate, run_code
- **高级功能**：cookies_get, cookies_set, cookies_clear, tabs, wait_for, pdf, resize, handle_dialog, install, connect_cdp, list_cdp_targets, clear_browser_cache
- 使用 `action` 参数指定操作类型
- 默认为无头模式（headless），使用 `headed=True` 启动可见浏览器窗口
- 支持多标签页（使用不同的 `page_id`）
- `click` 支持两种定位方式：元素定位（`ref`/`selector`）和页面坐标定位（`page_x`、`page_y`，单位为页面 viewport 像素）。当两者同时提供时，优先级为 `ref > selector > page_x/page_y`，坐标参数仅在未提供 `ref/selector` 时生效
  - 坐标点击底层使用 `page.mouse.click(...)`，支持 `button` 与 `double_click`，但不支持 `modifiers_json`
  - **适用场景：** 面向 Canvas/WebGL 等无 DOM 子元素的界面。坐标可通过截图估算获取，也可通过 `action=evaluate` 编程计算以获得像素级精度。evaluate 推荐流程：(1) `action=evaluate` 获取 canvas 元素的 bounding rect，(2) 加上已知偏移量计算点击位置，(3) `action=click` 传入 `page_x`/`page_y`

```json
{
  "action": "click",
  "page_x": 420,
  "page_y": 260
}
```

### CDP 模式（高级功能）

浏览器工具支持通过 Chrome DevTools Protocol (CDP) 连接到已运行的 Chrome 浏览器：

- **启动时暴露 CDP 端口**：使用 `action="start"` 并设置 `cdp_port`（如 9222），Chrome 会以 `--remote-debugging-port` 模式启动
- **连接到外部浏览器**：使用 `action="connect_cdp"` 和 `cdp_url`（如 `http://localhost:9222`）连接到已运行的 Chrome
- **发现 CDP 端点**：使用 `action="list_cdp_targets"` 扫描本地端口范围（默认 9000-10000），查找可用的 CDP 连接

**CDP 模式适用场景：**

- 连接到用户手动打开的 Chrome 浏览器（保持登录状态、书签、插件等）
- 与外部调试工具配合使用
- 在已有浏览器会话中执行自动化操作
