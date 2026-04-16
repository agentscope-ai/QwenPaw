/**
 * hello-world-plugin — QwenPaw frontend plugin
 *
 * Demonstrates how to create a page-level plugin that appears in the
 * sidebar and renders a custom page.
 *
 * ## Plugin contract
 *
 * Access shared dependencies via `window.__QWENPAW__` (React, antd, …).
 * Register capabilities by implementing `setup()` in the plugin class:
 *   - `window.register_routes(id, routes[])`     — page-level routes
 *   - `window.register_tool_render(id, renderers)` — tool message renderers
 *
 * ## Build & Install
 *
 *   npm install && npm run build
 *   cp -r . ~/.qwenpaw/plugins/hello-world-plugin
 */

const { React, antd } = (window as any).__QWENPAW__;
const { Card, Typography, Space, Tag, Divider, Button } = antd;
const { Title, Paragraph, Text: AntText } = Typography;
const { useState, useEffect, useCallback } = React;

// ── Inline styles ───────────────────────────────────────────────────────────

const styles: Record<string, Record<string, unknown>> = {
  page: { padding: "24px 28px", maxWidth: 960, margin: "0 auto" },
  headerCard: { marginBottom: 24 },
  headerRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  cardRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
    gap: 16,
    marginBottom: 8,
  },
  infoCard: { textAlign: "center" as const },
  clockText: {
    fontSize: 32,
    fontWeight: 700,
    fontVariantNumeric: "tabular-nums",
  },
  counterText: { fontSize: 48, fontWeight: 700, color: "#4096ff" },
  codeBlock: {
    background: "#f5f5f5",
    borderRadius: 6,
    padding: "12px 16px",
    fontSize: 12,
    overflow: "auto",
    margin: 0,
  },
};

// ── Component ────────────────────────────────────────────────────────────────

/**
 * HelloDashboard — the main page rendered at
 * `/plugin/hello-world-plugin/dashboard`.
 */
function HelloDashboard() {
  const [clickCount, setClickCount] = useState(0);
  const [currentTime, setCurrentTime] = useState(
    new Date().toLocaleTimeString(),
  );

  useEffect(() => {
    const timer = setInterval(
      () => setCurrentTime(new Date().toLocaleTimeString()),
      1000,
    );
    return () => clearInterval(timer);
  }, []);

  const handleClick = useCallback(() => {
    setClickCount((previous: number) => previous + 1);
  }, []);

  return React.createElement(
    "div",
    { style: styles.page },

    // Header
    React.createElement(
      Card,
      { style: styles.headerCard },
      React.createElement(
        Space,
        { direction: "vertical", size: "small", style: { width: "100%" } },
        React.createElement(
          "div",
          { style: styles.headerRow },
          React.createElement(
            Title,
            { level: 3, style: { margin: 0 } },
            "👋 Hello World Plugin",
          ),
          React.createElement(Tag, { color: "green" }, "Active"),
        ),
        React.createElement(
          Paragraph,
          { type: "secondary", style: { margin: 0 } },
          "This is a minimal example of a page-level QwenPaw plugin. ",
          "It demonstrates how plugins can register custom pages that appear in the sidebar.",
        ),
      ),
    ),

    // Info cards row
    React.createElement(
      "div",
      { style: styles.cardRow },
      React.createElement(
        Card,
        { title: "🕐 Live Clock", style: styles.infoCard },
        React.createElement(AntText, { style: styles.clockText }, currentTime),
      ),
      React.createElement(
        Card,
        { title: "🔢 Click Counter", style: styles.infoCard },
        React.createElement(
          Space,
          { direction: "vertical", align: "center", style: { width: "100%" } },
          React.createElement(
            AntText,
            { style: styles.counterText },
            String(clickCount),
          ),
          React.createElement(
            Button,
            { type: "primary", onClick: handleClick },
            "Click me!",
          ),
        ),
      ),
      React.createElement(
        Card,
        { title: "📦 Plugin Info", style: styles.infoCard },
        React.createElement(
          Space,
          { direction: "vertical", size: "small" },
          React.createElement(
            AntText,
            null,
            React.createElement("strong", null, "ID: "),
            "hello-world-plugin",
          ),
          React.createElement(
            AntText,
            null,
            React.createElement("strong", null, "Version: "),
            "1.0.0",
          ),
          React.createElement(
            AntText,
            null,
            React.createElement("strong", null, "Author: "),
            "QwenPaw",
          ),
        ),
      ),
    ),

    // How it works section
    React.createElement(Divider, null),
    React.createElement(
      Card,
      { title: "🛠 How Page Plugins Work" },
      React.createElement(
        Space,
        { direction: "vertical", size: "middle", style: { width: "100%" } },
        React.createElement(
          "div",
          null,
          React.createElement(
            Title,
            { level: 5, style: { margin: "0 0 8px" } },
            "1. Declare entry points in plugin.json",
          ),
          React.createElement(
            "pre",
            { style: styles.codeBlock },
            JSON.stringify(
              { entry: { frontend: "dist/index.js", backend: null } },
              null,
              2,
            ),
          ),
        ),
        React.createElement(
          "div",
          null,
          React.createElement(
            Title,
            { level: 5, style: { margin: "0 0 8px" } },
            "2. Register with register_routes / register_tool_render",
          ),
          React.createElement(
            "pre",
            { style: styles.codeBlock },
            'const { React, antd } = window.__QWENPAW__;\n\nclass MyPlugin {\n  readonly id = "my-plugin";\n\n  setup() {\n    window.register_routes?.(this.id, [\n      { path: "/plugin/my-plugin/page", component: MyPage, label: "My Page", icon: "📊", priority: 10 },\n    ]);\n    window.register_tool_render?.(this.id, { my_tool: MyToolCard });\n  }\n}\n\nnew MyPlugin().setup();',
          ),
        ),
        React.createElement(
          "div",
          null,
          React.createElement(
            Title,
            { level: 5, style: { margin: "0 0 8px" } },
            "3. Build & install",
          ),
          React.createElement(
            "pre",
            { style: styles.codeBlock },
            "npm install && npm run build\ncp -r hello-world-plugin/ ~/.qwenpaw/plugins/",
          ),
        ),
      ),
    ),
  );
}

// ── Plugin class ─────────────────────────────────────────────────────────────

class HelloWorldPlugin {
  readonly id = "hello-world-plugin";

  setup(): void {
    this.registerRoutes();
  }

  private registerRoutes(): void {
    (window as any).register_routes?.(this.id, [
      {
        path: "/plugin/hello-world-plugin/dashboard",
        component: HelloDashboard,
        label: "Hello Dashboard",
        icon: "👋",
        priority: 100,
      },
    ]);
  }
}

new HelloWorldPlugin().setup();
