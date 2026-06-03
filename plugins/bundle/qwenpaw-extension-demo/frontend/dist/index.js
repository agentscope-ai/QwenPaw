const E = window.QwenPaw.host, e = E.React, { Card: y, Button: f, Space: i, Tag: x, message: a } = E.antd, t = "qwenpaw-extension-demo", P = "#fef9e7", r = "#a16207";
function v() {
  const [n, d] = e.useState(null);
  return /* @__PURE__ */ e.createElement("div", { style: { padding: 24 } }, /* @__PURE__ */ e.createElement(
    y,
    {
      title: /* @__PURE__ */ e.createElement("span", null, "🧪 QwenPaw Extension Demo ", /* @__PURE__ */ e.createElement(x, { color: "orange" }, "demo plugin"))
    },
    /* @__PURE__ */ e.createElement(i, { direction: "vertical", size: "middle", style: { width: "100%" } }, /* @__PURE__ */ e.createElement("p", null, "This page is rendered by ", /* @__PURE__ */ e.createElement("code", null, 'QwenPaw.route.add("', t, '", ...)'), '. The sidebar entry (under "Agent") was registered by', " ", /* @__PURE__ */ e.createElement("code", null, "QwenPaw.menu.add(...)"), " with", " ", /* @__PURE__ */ e.createElement("code", null, 'parentId: "core.agent-group"'), ", demonstrating that plugin items can land in any host group, not just plugins-group."), /* @__PURE__ */ e.createElement(i, null, /* @__PURE__ */ e.createElement(
      f,
      {
        type: "primary",
        onClick: () => {
          var l;
          const o = ((l = window.QwenPaw.audit) == null ? void 0 : l.overrides()) ?? [];
          d(o.length), a.info(
            `audit.overrides() returned ${o.length} record(s)`
          );
        }
      },
      "Dump audit overrides"
    ), n !== null && /* @__PURE__ */ e.createElement("span", { style: { color: "#888" } }, "last count: ", /* @__PURE__ */ e.createElement("b", null, n))), /* @__PURE__ */ e.createElement("p", { style: { color: "#888", fontSize: 12, marginTop: 16 } }, "Open the browser console — every registration above also emits an audit log line of the form ", /* @__PURE__ */ e.createElement("code", null, "[QwenPaw audit] menu.add ... by ", t), "."))
  ));
}
function Q() {
  return /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        background: P,
        color: r,
        padding: "4px 12px",
        fontSize: 12,
        textAlign: "center",
        borderBottom: `1px solid ${r}20`
      }
    },
    "🧪 /chat wrapped by qwenpaw-extension-demo via QwenPaw.route.wrap"
  );
}
function S() {
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
function B() {
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
var c;
(c = window.QwenPaw.menu) == null || c.add(t, {
  id: "demo.home",
  location: "primary.agentScoped",
  parentId: "core.agent-group",
  label: "Demo",
  icon: "🧪",
  route: "demo.home",
  order: 15
  // between core.workspace (10) and core.skills (20)
});
var s;
(s = window.QwenPaw.route) == null || s.add(t, {
  id: "demo.home",
  path: "/demo",
  component: v
});
var m;
(m = window.QwenPaw.route) == null || m.wrap(t, "core.chat", (n) => function(o) {
  return /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement(Q, null), /* @__PURE__ */ e.createElement(n, { ...o }));
});
var u;
(u = window.QwenPaw.slot) == null || u.fill(
  t,
  "sider.bottom",
  () => /* @__PURE__ */ e.createElement(S, null),
  { id: "demo.sider.badge", order: 100 }
);
var w;
(w = window.QwenPaw.chat) == null || w.welcome.set(t, {
  greeting: "👋 Hello from qwenpaw-extension-demo!",
  avatar: "/qwenpaw.png"
});
var p;
(p = window.QwenPaw.chat) == null || p.rightHeader.add(
  t,
  /* @__PURE__ */ e.createElement(
    f,
    {
      type: "text",
      size: "small",
      onClick: () => a.info("Demo header button clicked")
    },
    "🧪 Demo"
  ),
  { id: "demo.header.btn", order: 200 }
);
var g;
(g = window.QwenPaw.chat) == null || g.actions.add(t, {
  id: "demo.star",
  icon: /* @__PURE__ */ e.createElement("span", { title: "Star this message" }, "⭐"),
  onClick: () => a.success("Demo plugin starred the message")
});
var h;
(h = window.QwenPaw.chat) == null || h.response.append(
  t,
  (n) => n.isLast ? /* @__PURE__ */ e.createElement(B, null) : null,
  { id: "demo.response.footer" }
);
var b;
(b = window.QwenPaw.chat) == null || b.request.render(
  t,
  (n) => /* @__PURE__ */ e.createElement(
    "div",
    {
      style: {
        border: `2px dashed ${r}`,
        borderRadius: 6,
        padding: 4
      }
    },
    /* @__PURE__ */ e.createElement("div", { style: { fontSize: 10, color: r, marginBottom: 4 } }, "▼ user bubble wrapped by demo plugin (via chat.request.render + fallback)"),
    n.fallback()
  )
);
console.info(
  `[plugin:${t}] registered 9 extensions: menu / route / route.wrap / slot.fill / chat.welcome / chat.rightHeader / chat.actions / chat.response.append / chat.request.render`
);
