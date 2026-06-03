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

// Best-effort: walk the response payload and sum the length of every
// string value found. Vendor's ChatResponseData has no fixed shape, so
// counting all strings is the simplest demo. Skips obvious metadata keys
// (id/role/type/created_at/status/timestamps) to avoid inflating the
// number with non-content fields. Treats codepoints as characters so
// emoji and CJK count as 1 each rather than UTF-16 surrogate pairs.
const METADATA_KEYS = new Set([
  "id",
  "role",
  "type",
  "status",
  "session_id",
  "created_at",
  "updated_at",
  "timestamp",
]);
function countResponseChars(data: unknown): number {
  let total = 0;
  const visit = (v: unknown) => {
    if (typeof v === "string") {
      // Iterating a string with for...of yields codepoints, not UTF-16
      // code units, so 🎉 counts as 1 and 中 counts as 1.
      for (const _ of v) total += 1;
      return;
    }
    if (Array.isArray(v)) {
      v.forEach(visit);
      return;
    }
    if (v && typeof v === "object") {
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
        if (METADATA_KEYS.has(k)) continue;
        visit(val);
      }
    }
  };
  visit(data);
  return total;
}

function CharCountBadge({ data }: { data: unknown }) {
  const count = React.useMemo(() => countResponseChars(data), [data]);
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        marginTop: 4,
        padding: "2px 8px",
        background: "#f0fdf4",
        color: "#15803d",
        fontSize: 11,
        border: "1px solid #bbf7d0",
        borderRadius: 999,
      }}
    >
      <span>📝</span>
      <span>
        本回复约 <b>{count}</b> 字
      </span>
    </div>
  );
}

function DatapawSubPage({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <span>
            {title} <Tag color="blue">Datapaw demo</Tag>
          </span>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <p>{description}</p>
          <p style={{ color: "#888", fontSize: 12 }}>
            This page is a placeholder rendered by
            <code> QwenPaw.route.add("{PLUGIN_ID}", ...)</code>.
          </p>
        </Space>
      </Card>
    </div>
  );
}

function DataConnectionPage() {
  return (
    <DatapawSubPage
      title="🔌 Data Connection"
      description="Configure external data sources, credentials, and freshness policies for the Datapaw runtime."
    />
  );
}

function SemanticWeavingPage() {
  return (
    <DatapawSubPage
      title="🧬 Semantic Weaving"
      description="Design semantic links between datasets — joins, denormalizations, and embedding stitches that Datapaw uses to answer analytic questions."
    />
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

// 1b. "Datapaw" parent group sitting ABOVE Control (control-group order=20).
//     Two children: Data Connection + Semantic Weaving.
window.QwenPaw.menu?.add(PLUGIN_ID, {
  id: "demo.datapaw-group",
  location: "primary.agentScoped",
  label: "Datapaw",
  icon: "📊",
  isGroup: true,
  order: 15, // inbox=10, datapaw=15, control-group=20, agent-group=30
});
window.QwenPaw.menu?.add(PLUGIN_ID, {
  id: "demo.datapaw.data-connection",
  location: "primary.agentScoped",
  parentId: "demo.datapaw-group",
  label: "Data Connection",
  icon: "🔌",
  route: "demo.datapaw.data-connection",
  order: 10,
});
window.QwenPaw.menu?.add(PLUGIN_ID, {
  id: "demo.datapaw.semantic-weaving",
  location: "primary.agentScoped",
  parentId: "demo.datapaw-group",
  label: "Semantic Weaving",
  icon: "🧬",
  route: "demo.datapaw.semantic-weaving",
  order: 20,
});

// 2. /demo route
window.QwenPaw.route?.add(PLUGIN_ID, {
  id: "demo.home",
  path: "/demo",
  component: DemoPage,
});

// 2b. Datapaw sub-pages
window.QwenPaw.route?.add(PLUGIN_ID, {
  id: "demo.datapaw.data-connection",
  path: "/demo/datapaw/data-connection",
  component: DataConnectionPage,
});
window.QwenPaw.route?.add(PLUGIN_ID, {
  id: "demo.datapaw.semantic-weaving",
  path: "/demo/datapaw/semantic-weaving",
  component: SemanticWeavingPage,
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

// 8b. chat.response.append: char-count badge BELOW every AI bubble.
//     Order > demo.response.footer so the badge sits beneath the banner.
window.QwenPaw.chat?.response.append(
  PLUGIN_ID,
  (ctx: { data: unknown; isLast?: boolean }) => <CharCountBadge data={ctx.data} />,
  { id: "demo.response.charcount", order: 10 },
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
  `[plugin:${PLUGIN_ID}] registered 14 extensions: menu×4 (demo.home + Datapaw group + 2 children) / route×3 (/demo + 2 Datapaw subpages) / route.wrap / slot.fill / chat.welcome / chat.rightHeader / chat.actions / chat.response.append×2 (banner + char-count) / chat.request.render`,
);
