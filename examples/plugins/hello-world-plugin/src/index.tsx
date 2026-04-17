/**
 * hello-world-plugin — QwenPaw frontend plugin
 *
 * Demonstrates how to create a page-level plugin that appears in the
 * sidebar and renders a custom page.
 *
 * Build:   npm install && npm run build
 * Install: cp -r . ~/.qwenpaw/plugins/hello-world-plugin
 */

// React and antd come from the host — never bundled into the plugin.
// The classic JSX transform (vite.config.ts) compiles <Card> →
// React.createElement(Card, ...), so this import must stay at the top level.
const { React, antd } = (window as any).QwenPaw.host;
const { Card, Typography, Space, Tag, Divider, Button } = antd;
const { Title, Paragraph, Text: AntText } = Typography;
const { useState, useEffect, useCallback } = React;

// ── Inline styles ────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
    page: { padding: "24px 28px", maxWidth: 960, margin: "0 auto" },
    headerCard: { marginBottom: 24 },
    headerRow: { display: "flex", alignItems: "center", justifyContent: "space-between" },
    cardRow: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16, marginBottom: 8 },
    infoCard: { textAlign: "center" },
    clockText: { fontSize: 32, fontWeight: 700, fontVariantNumeric: "tabular-nums" },
    counterText: { fontSize: 48, fontWeight: 700, color: "#4096ff" },
    codeBlock: { background: "#f5f5f5", borderRadius: 6, padding: "12px 16px", fontSize: 12, overflow: "auto", margin: 0 },
};

// ── Component ────────────────────────────────────────────────────────────────

function HelloDashboard() {
    const [clickCount, setClickCount] = useState(0);
    const [currentTime, setCurrentTime] = useState(new Date().toLocaleTimeString());

    useEffect(() => {
        const timer = setInterval(() => setCurrentTime(new Date().toLocaleTimeString()), 1000);
        return () => clearInterval(timer);
    }, []);

    const handleClick = useCallback(() => {
        setClickCount((prev: number) => prev + 1);
    }, []);

    const codeExample = `const { React, antd } = window.QwenPaw.host;

class MyPlugin {
  readonly id = "my-plugin";

  setup() {
    window.QwenPaw.registerRoutes?.(this.id, [
      { path: "/plugin/my-plugin/page", component: MyPage, label: "My Page", icon: "📊", priority: 10 },
    ]);
    window.QwenPaw.registerToolRender?.(this.id, { my_tool: MyToolCard });
  }
}

new MyPlugin().setup();`;

    return (
        <div style={styles.page}>
            {/* Header */}
            <Card style={styles.headerCard}>
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    <div style={styles.headerRow}>
                        <Title level={3} style={{ margin: 0 }}>👋 Hello World Plugin</Title>
                        <Tag color="green">Active</Tag>
                    </div>
                    <Paragraph type="secondary" style={{ margin: 0 }}>
                        This is a minimal example of a page-level QwenPaw plugin.{" "}
                        It demonstrates how plugins can register custom pages that appear in the sidebar.
                    </Paragraph>
                </Space>
            </Card>

            {/* Info cards row */}
            <div style={styles.cardRow}>
                <Card title="🕐 Live Clock" style={styles.infoCard}>
                    <AntText style={styles.clockText}>{currentTime}</AntText>
                </Card>

                <Card title="🔢 Click Counter" style={styles.infoCard}>
                    <Space direction="vertical" align="center" style={{ width: "100%" }}>
                        <AntText style={styles.counterText}>{clickCount}</AntText>
                        <Button type="primary" onClick={handleClick}>Click me!</Button>
                    </Space>
                </Card>

                <Card title="📦 Plugin Info" style={styles.infoCard}>
                    <Space direction="vertical" size="small">
                        <AntText><strong>ID: </strong>hello-world-plugin</AntText>
                        <AntText><strong>Version: </strong>1.0.0</AntText>
                        <AntText><strong>Author: </strong>QwenPaw</AntText>
                    </Space>
                </Card>
            </div>

            {/* How it works */}
            <Divider />
            <Card title="🛠 How Page Plugins Work">
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <div>
                        <Title level={5} style={{ margin: "0 0 8px" }}>1. Declare entry points in plugin.json</Title>
                        <pre style={styles.codeBlock}>
                            {JSON.stringify({ entry: { frontend: "dist/index.js", backend: null } }, null, 2)}
                        </pre>
                    </div>
                    <div>
                        <Title level={5} style={{ margin: "0 0 8px" }}>2. Register routes and tool renderers</Title>
                        <pre style={styles.codeBlock}>{codeExample}</pre>
                    </div>
                    <div>
                        <Title level={5} style={{ margin: "0 0 8px" }}>3. Build &amp; install</Title>
                        <pre style={styles.codeBlock}>{"npm install && npm run build\ncp -r hello-world-plugin/ ~/.qwenpaw/plugins/"}</pre>
                    </div>
                </Space>
            </Card>
        </div>
    );
}

// ── Plugin class ──────────────────────────────────────────────────────────────

class HelloWorldPlugin {
    readonly id = "hello-world-plugin";

    setup(): void {
        (window as any).QwenPaw.registerRoutes?.(this.id, [
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
