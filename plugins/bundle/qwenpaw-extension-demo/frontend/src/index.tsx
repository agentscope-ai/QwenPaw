/**
 * qwenpaw-extension-demo — frontend smoke test for the new QwenPaw plugin APIs.
 *
 * Self-registers via window.QwenPaw at module load:
 *
 *   Console-wide:
 *     menu.add        → sidebar item under core.agent-group
 *     route.add       → /demo page rendered by DemoPage component
 *     route.wrap      → wrap /chat with a thin yellow banner
 *     slot.fill       → small badge at sider.bottom
 *
 *   Chat surface:
 *     welcome.set         → custom greeting + avatar on empty chat
 *     rightHeader.add     → "🧪 Demo" button in chat header
 *     actions.add         → ⭐ button under every AI message
 *     response.append     → info banner BELOW the last AI bubble
 *     request.render      → wrap the user bubble with "(demo-wrapped)" prefix
 *
 *   Audit:
 *     Click the audit button on /demo to dump the audit ring buffer.
 */
const host = window.QwenPaw.host;
const React = host.React;
const { Card, Button, Space, Tag, message } = host.antd as {
  Card: any;
  Button: any;
  Space: any;
  Tag: any;
  message: { info: (m: string) => void; success: (m: string) => void };
};

const PLUGIN_ID = "qwenpaw-extension-demo";
const BANNER_BG = "#fef9e7";
const BANNER_TEXT = "#a16207";

// ─────────────────────────────────────────────────────────────────────────────
// Components
// ─────────────────────────────────────────────────────────────────────────────

function DemoPage() {
  const [auditCount, setAuditCount] = React.useState<number | null>(null);
  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <span>
            🧪 QwenPaw Extension Demo <Tag color="orange">demo plugin</Tag>
          </span>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <p>
            This page is rendered by <code>QwenPaw.route.add("{PLUGIN_ID}", ...)</code>.
            The sidebar entry (under "Agent") was registered by{" "}
            <code>QwenPaw.menu.add(...)</code> with{" "}
            <code>parentId: "core.agent-group"</code>, demonstrating that
            plugin items can land in any host group, not just plugins-group.
          </p>
          <Space>
            <Button
              type="primary"
              onClick={() => {
                const records = window.QwenPaw.audit?.overrides() ?? [];
                setAuditCount(records.length);
                message.info(
                  `audit.overrides() returned ${records.length} record(s)`,
                );
              }}
            >
              Dump audit overrides
            </Button>
            {auditCount !== null && (
              <span style={{ color: "#888" }}>
                last count: <b>{auditCount}</b>
              </span>
            )}
          </Space>
          <p style={{ color: "#888", fontSize: 12, marginTop: 16 }}>
            Open the browser console — every registration above also emits an
            audit log line of the form <code>[QwenPaw audit] menu.add ... by {PLUGIN_ID}</code>.
          </p>
        </Space>
      </Card>
    </div>
  );
}

function ChatBanner() {
  return (
    <div
      style={{
        background: BANNER_BG,
        color: BANNER_TEXT,
        padding: "4px 12px",
        fontSize: 12,
        textAlign: "center",
        borderBottom: `1px solid ${BANNER_TEXT}20`,
      }}
    >
      🧪 /chat wrapped by qwenpaw-extension-demo via QwenPaw.route.wrap
    </div>
  );
}

function SiderBadge() {
  return (
    <div
      style={{
        padding: "6px 8px",
        fontSize: 11,
        color: "#888",
        textAlign: "center",
        borderTop: "1px dashed #ddd",
      }}
    >
      🧪 demo plugin active
    </div>
  );
}

function ResponseFooter() {
  return (
    <div
      style={{
        marginTop: 8,
        padding: "6px 10px",
        background: "#f0f8ff",
        fontSize: 11,
        color: "#0369a1",
        borderRadius: 4,
        borderLeft: "3px solid #0ea5e9",
      }}
    >
      🧪 demo plugin: chat.response.append rendered this footer below the AI bubble
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Registrations — run at module load (synchronous, before any host render)
// ─────────────────────────────────────────────────────────────────────────────

// 1. Sidebar menu entry under Agent group
window.QwenPaw.menu?.add(PLUGIN_ID, {
  id: "demo.home",
  location: "primary.agentScoped",
  parentId: "core.agent-group",
  label: "Demo",
  icon: "🧪",
  route: "demo.home",
  order: 15, // between core.workspace (10) and core.skills (20)
});

// 2. /demo route
window.QwenPaw.route?.add(PLUGIN_ID, {
  id: "demo.home",
  path: "/demo",
  component: DemoPage,
});

// 3. Wrap /chat (core.chat) with a thin banner — exercises route.wrap onion
window.QwenPaw.route?.wrap(PLUGIN_ID, "core.chat", (Inner: any) => {
  return function ChatWithDemoBanner(props: any) {
    return (
      <>
        <ChatBanner />
        <Inner {...props} />
      </>
    );
  };
});

// 4. Fill sider.bottom slot with a small badge
window.QwenPaw.slot?.fill(
  PLUGIN_ID,
  "sider.bottom",
  () => <SiderBadge />,
  { id: "demo.sider.badge", order: 100 },
);

// 5. Chat welcome: override greeting + avatar on empty chat
window.QwenPaw.chat?.welcome.set(PLUGIN_ID, {
  greeting: "👋 Hello from qwenpaw-extension-demo!",
  avatar: "/qwenpaw.png",
});

// 6. Chat header: add a button in the right header (host defaults preserved)
window.QwenPaw.chat?.rightHeader.add(
  PLUGIN_ID,
  <Button
    type="text"
    size="small"
    onClick={() => message.info("Demo header button clicked")}
  >
    🧪 Demo
  </Button>,
  { id: "demo.header.btn", order: 200 },
);

// 7. Chat actions: ⭐ button under every AI message
window.QwenPaw.chat?.actions.add(PLUGIN_ID, {
  id: "demo.star",
  icon: <span title="Star this message">⭐</span>,
  onClick: () => message.success("Demo plugin starred the message"),
});

// 8. chat.response.append: info banner BELOW only the newest AI bubble
window.QwenPaw.chat?.response.append(
  PLUGIN_ID,
  (ctx: { data: unknown; isLast?: boolean }) => {
    if (!ctx.isLast) return null;
    return <ResponseFooter />;
  },
  { id: "demo.response.footer" },
);

// 9. chat.request.render: wrap user bubble — exercises render+fallback
window.QwenPaw.chat?.request.render(
  PLUGIN_ID,
  (ctx: { data: unknown; fallback: () => any }) => (
    <div
      style={{
        border: `2px dashed ${BANNER_TEXT}`,
        borderRadius: 6,
        padding: 4,
      }}
    >
      <div style={{ fontSize: 10, color: BANNER_TEXT, marginBottom: 4 }}>
        ▼ user bubble wrapped by demo plugin (via chat.request.render + fallback)
      </div>
      {ctx.fallback()}
    </div>
  ),
);

console.info(
  `[plugin:${PLUGIN_ID}] registered 9 extensions: menu / route / route.wrap / slot.fill / chat.welcome / chat.rightHeader / chat.actions / chat.response.append / chat.request.render`,
);
