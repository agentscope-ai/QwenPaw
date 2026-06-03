const D = window.QwenPaw.host, e = D.React, { Card: S, Button: C, Space: i, Tag: A, message: l } = D.antd, t = "qwenpaw-extension-demo", z = "#fef9e7", d = "#a16207";
function B() {
  const [n, o] = e.useState(null);
  return /* @__PURE__ */ e.createElement("div", { style: { padding: 24 } }, /* @__PURE__ */ e.createElement(
    S,
    {
      title: /* @__PURE__ */ e.createElement("span", null, "🧪 QwenPaw Extension Demo ", /* @__PURE__ */ e.createElement(A, { color: "orange" }, "demo plugin"))
    },
    /* @__PURE__ */ e.createElement(i, { direction: "vertical", size: "middle", style: { width: "100%" } }, /* @__PURE__ */ e.createElement("p", null, "This page is rendered by ", /* @__PURE__ */ e.createElement("code", null, 'QwenPaw.route.add("', t, '", ...)'), '. The sidebar entry (under "Agent") was registered by', " ", /* @__PURE__ */ e.createElement("code", null, "QwenPaw.menu.add(...)"), " with", " ", /* @__PURE__ */ e.createElement("code", null, 'parentId: "core.agent-group"'), ", demonstrating that plugin items can land in any host group, not just plugins-group."), /* @__PURE__ */ e.createElement(i, null, /* @__PURE__ */ e.createElement(
      C,
      {
        type: "primary",
        onClick: () => {
          var a;
          const r = ((a = window.QwenPaw.audit) == null ? void 0 : a.overrides()) ?? [];
          o(r.length), l.info(
            `audit.overrides() returned ${r.length} record(s)`
          );
        }
      },
      "Dump audit overrides"
    ), n !== null && /* @__PURE__ */ e.createElement("span", { style: { color: "#888" } }, "last count: ", /* @__PURE__ */ e.createElement("b", null, n))), /* @__PURE__ */ e.createElement("p", { style: { color: "#888", fontSize: 12, marginTop: 16 } }, "Open the browser console — every registration above also emits an audit log line of the form ", /* @__PURE__ */ e.createElement("code", null, "[QwenPaw audit] menu.add ... by ", t), "."))
  ));
}
function R() {
  return /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        background: z,
        color: d,
        padding: "4px 12px",
        fontSize: 12,
        textAlign: "center",
        borderBottom: `1px solid ${d}20`
      }
    },
    "🧪 /chat wrapped by qwenpaw-extension-demo via QwenPaw.route.wrap"
  );
}
function q() {
  return /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        padding: "6px 8px",
        fontSize: 11,
        color: "#888",
        textAlign: "center",
        borderTop: "1px dashed #ddd"
      }
    },
    "🧪 demo plugin active"
  );
}
function I() {
  return /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        marginTop: 8,
        padding: "6px 10px",
        background: "#f0f8ff",
        fontSize: 11,
        color: "#0369a1",
        borderRadius: 4,
        borderLeft: "3px solid #0ea5e9"
      }
    },
    "🧪 demo plugin: chat.response.append rendered this footer below the AI bubble"
  );
}
const _ = /* @__PURE__ */ new Set([
  "id",
  "role",
  "type",
  "status",
  "session_id",
  "created_at",
  "updated_at",
  "timestamp"
]);
function N(n) {
  let o = 0;
  const r = (a) => {
    if (typeof a == "string") {
      for (const c of a) o += 1;
      return;
    }
    if (Array.isArray(a)) {
      a.forEach(r);
      return;
    }
    if (a && typeof a == "object")
      for (const [c, k] of Object.entries(a))
        _.has(c) || r(k);
  };
  return r(n), o;
}
function j({ data: n }) {
  const o = e.useMemo(() => N(n), [n]);
  return /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        marginTop: 4,
        padding: "2px 8px",
        background: "#f0fdf4",
        color: "#15803d",
        fontSize: 11,
        border: "1px solid #bbf7d0",
        borderRadius: 999
      }
    },
    /* @__PURE__ */ e.createElement("span", null, "📝"),
    /* @__PURE__ */ e.createElement("span", null, "本回复约 ", /* @__PURE__ */ e.createElement("b", null, o), " 字")
  );
}
function T({
  title: n,
  description: o
}) {
  return /* @__PURE__ */ e.createElement("div", { style: { padding: 24 } }, /* @__PURE__ */ e.createElement(
    S,
    {
      title: /* @__PURE__ */ e.createElement("span", null, n, " ", /* @__PURE__ */ e.createElement(A, { color: "blue" }, "Datapaw demo"))
    },
    /* @__PURE__ */ e.createElement(i, { direction: "vertical", size: "middle", style: { width: "100%" } }, /* @__PURE__ */ e.createElement("p", null, o), /* @__PURE__ */ e.createElement("p", { style: { color: "#888", fontSize: 12 } }, "This page is a placeholder rendered by", /* @__PURE__ */ e.createElement("code", null, ' QwenPaw.route.add("', t, '", ...)'), "."))
  ));
}
function W() {
  return /* @__PURE__ */ e.createElement(
    T,
    {
      title: "🔌 Data Connection",
      description: "Configure external data sources, credentials, and freshness policies for the Datapaw runtime."
    }
  );
}
function $() {
  return /* @__PURE__ */ e.createElement(
    T,
    {
      title: "🧬 Semantic Weaving",
      description: "Design semantic links between datasets — joins, denormalizations, and embedding stitches that Datapaw uses to answer analytic questions."
    }
  );
}
var s;
(s = window.QwenPaw.menu) == null || s.add(t, {
  id: "demo.home",
  location: "primary.agentScoped",
  parentId: "core.agent-group",
  label: "Demo",
  icon: "🧪",
  route: "demo.home",
  order: 15
  // between core.workspace (10) and core.skills (20)
});
var m;
(m = window.QwenPaw.menu) == null || m.add(t, {
  id: "demo.datapaw-group",
  location: "primary.agentScoped",
  label: "Datapaw",
  icon: "📊",
  isGroup: !0,
  order: 15
  // inbox=10, datapaw=15, control-group=20, agent-group=30
});
var p;
(p = window.QwenPaw.menu) == null || p.add(t, {
  id: "demo.datapaw.data-connection",
  location: "primary.agentScoped",
  parentId: "demo.datapaw-group",
  label: "Data Connection",
  icon: "🔌",
  route: "demo.datapaw.data-connection",
  order: 10
});
var u;
(u = window.QwenPaw.menu) == null || u.add(t, {
  id: "demo.datapaw.semantic-weaving",
  location: "primary.agentScoped",
  parentId: "demo.datapaw-group",
  label: "Semantic Weaving",
  icon: "🧬",
  route: "demo.datapaw.semantic-weaving",
  order: 20
});
var w;
(w = window.QwenPaw.route) == null || w.add(t, {
  id: "demo.home",
  path: "/demo",
  component: B
});
var g;
(g = window.QwenPaw.route) == null || g.add(t, {
  id: "demo.datapaw.data-connection",
  path: "/demo/datapaw/data-connection",
  component: W
});
var h;
(h = window.QwenPaw.route) == null || h.add(t, {
  id: "demo.datapaw.semantic-weaving",
  path: "/demo/datapaw/semantic-weaving",
  component: $
});
var f;
(f = window.QwenPaw.route) == null || f.wrap(t, "core.chat", (n) => function(r) {
  return /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement(R, null), /* @__PURE__ */ e.createElement(n, { ...r }));
});
var b;
(b = window.QwenPaw.slot) == null || b.fill(
  t,
  "sider.bottom",
  () => /* @__PURE__ */ e.createElement(q, null),
  { id: "demo.sider.badge", order: 100 }
);
var E;
(E = window.QwenPaw.chat) == null || E.welcome.set(t, {
  greeting: "👋 Hello from qwenpaw-extension-demo!",
  avatar: "/qwenpaw.png"
});
var y;
(y = window.QwenPaw.chat) == null || y.rightHeader.add(
  t,
  /* @__PURE__ */ e.createElement(
    C,
    {
      type: "text",
      size: "small",
      onClick: () => l.info("Demo header button clicked")
    },
    "🧪 Demo"
  ),
  { id: "demo.header.btn", order: 200 }
);
var P;
(P = window.QwenPaw.chat) == null || P.actions.add(t, {
  id: "demo.star",
  icon: /* @__PURE__ */ e.createElement("span", { title: "Star this message" }, "⭐"),
  onClick: () => l.success("Demo plugin starred the message")
});
var x;
(x = window.QwenPaw.chat) == null || x.response.append(
  t,
  (n) => n.isLast ? /* @__PURE__ */ e.createElement(I, null) : null,
  { id: "demo.response.footer" }
);
var Q;
(Q = window.QwenPaw.chat) == null || Q.response.append(
  t,
  (n) => /* @__PURE__ */ e.createElement(j, { data: n.data }),
  { id: "demo.response.charcount", order: 10 }
);
var v;
(v = window.QwenPaw.chat) == null || v.request.render(
  t,
  (n) => /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        border: `2px dashed ${d}`,
        borderRadius: 6,
        padding: 4
      }
    },
    /* @__PURE__ */ e.createElement("div", { style: { fontSize: 10, color: d, marginBottom: 4 } }, "▼ user bubble wrapped by demo plugin (via chat.request.render + fallback)"),
    n.fallback()
  )
);
console.info(
  `[plugin:${t}] registered 14 extensions: menu×4 (demo.home + Datapaw group + 2 children) / route×3 (/demo + 2 Datapaw subpages) / route.wrap / slot.fill / chat.welcome / chat.rightHeader / chat.actions / chat.response.append×2 (banner + char-count) / chat.request.render`
);
