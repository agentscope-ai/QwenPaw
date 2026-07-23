const I = {
  en: {
    routeLabel: "Computer Use",
    title: "Computer Use",
    ready: "Runtime ready",
    unavailable: "Runtime unavailable",
    refresh: "Refresh",
    stop: "Stop automation",
    application: "Application",
    applicationId: "Application ID",
    revoke: "Revoke access",
    revokeConfirm: "Revoke this application access?",
    empty: "No applications are always allowed.",
    approvalTitle: "Application access",
    unknownApplication: "Unknown application",
    risk: "Risk",
    deny: "Deny",
    allowSession: "Allow for this session",
    allowAlways: "Always allow",
    failed: "Action failed.",
    accessManagement: "Access management",
    version: "Version",
    decision: {
      deny: "Access denied.",
      session: "Access allowed for this session.",
      always: "Application always allowed."
    }
  },
  zh: {
    routeLabel: "电脑操作",
    title: "电脑操作",
    ready: "运行环境已就绪",
    unavailable: "运行环境不可用",
    refresh: "刷新",
    stop: "停止自动化",
    application: "应用",
    applicationId: "应用标识",
    revoke: "撤销授权",
    revokeConfirm: "撤销这个应用的授权？",
    empty: "暂未允许任何应用长期访问。",
    approvalTitle: "应用访问请求",
    unknownApplication: "未知应用",
    risk: "风险",
    deny: "拒绝",
    allowSession: "仅本次会话允许",
    allowAlways: "始终允许",
    failed: "操作失败。",
    accessManagement: "授权管理",
    version: "版本",
    decision: {
      deny: "已拒绝访问。",
      session: "已允许本次会话访问。",
      always: "已始终允许该应用。"
    }
  }
};
function _(t) {
  return t != null && t.toLowerCase().startsWith("zh") ? "zh" : "en";
}
function n(t, s) {
  if (s.startsWith("decision.")) {
    const a = s.slice(
      9
    );
    return I[t].decision[a];
  }
  return I[t][s];
}
const B = "2.0.0", D = {
  version: B
}, o = window.QwenPaw.host, e = o.React, {
  Badge: J,
  Button: f,
  Empty: R,
  Popconfirm: q,
  Space: S,
  Table: F,
  Tabs: Q,
  Tooltip: O,
  Typography: K,
  message: k
} = o.antd, {
  CheckOutlined: z,
  CloseOutlined: G,
  DeleteOutlined: H,
  FolderOpenOutlined: V,
  ReloadOutlined: X,
  SafetyCertificateOutlined: Y,
  StopOutlined: Z
} = o.antdIcons, { Text: c, Title: ee } = K;
function te() {
  try {
    return _(localStorage.getItem("language"));
  } catch {
    return _(void 0);
  }
}
async function g(t, s) {
  const a = o.fetch ? await o.fetch(t, s) : await fetch(o.getApiUrl(t), {
    ...s,
    headers: {
      ...(s == null ? void 0 : s.headers) || {},
      ...o.getApiToken() ? { Authorization: `Bearer ${o.getApiToken()}` } : {}
    }
  }), i = await a.text();
  let l = null;
  try {
    l = i ? JSON.parse(i) : null;
  } catch {
    l = null;
  }
  if (!a.ok) {
    const d = l && typeof l == "object" && "detail" in l ? l.detail : void 0;
    throw new Error(
      typeof d == "string" ? d : `HTTP ${a.status}`
    );
  }
  return l;
}
function ae(t, s) {
  const a = t.toolParams.display_name;
  if (typeof a == "string" && a.trim())
    return a;
  const i = t.toolParams.canonical_app_id;
  return typeof i == "string" && i.trim() ? i : n(s, "unknownApplication");
}
function ne(t) {
  const s = t.toolParams.canonical_app_id;
  if (typeof s != "string" || !s.trim())
    return "";
  const a = s.indexOf(":");
  return a !== -1 && s.slice(0, a) === "process" ? s.slice(a + 1) : s;
}
function se({ approval: t, onResolved: s }) {
  var E;
  const a = _((E = o.useLocale) == null ? void 0 : E.call(o)), [i, l] = e.useState(null), d = typeof t.toolParams.risk == "string" ? t.toolParams.risk : "", v = typeof t.toolParams.warning == "string" ? t.toolParams.warning : "", b = ae(t, a), p = ne(t), w = async (y) => {
    l(y);
    try {
      await g("/computer-use/session/pending/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: t.sessionId,
          request_id: t.requestId,
          decision: y
        })
      }), k.success(n(a, `decision.${y}`)), s();
    } catch (u) {
      k.error(
        u instanceof Error ? u.message : n(a, "failed")
      );
    } finally {
      l(null);
    }
  };
  return e.createElement(
    o.antd.Card,
    { size: "small", bordered: !0, style: { borderRadius: 8 } },
    e.createElement(
      "div",
      { style: { display: "grid", gap: 14 } },
      e.createElement(
        "div",
        { style: { display: "grid", gap: 4 } },
        e.createElement(
          S,
          { size: 8 },
          e.createElement(Y),
          e.createElement(
            c,
            { strong: !0 },
            n(a, "approvalTitle")
          )
        ),
        e.createElement(c, { strong: !0 }, b),
        p && p !== b ? e.createElement(
          "div",
          {
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              minWidth: 0,
              maxWidth: "100%",
              padding: "2px 8px",
              borderRadius: 6,
              background: "rgba(140, 140, 140, 0.1)"
            }
          },
          e.createElement(V, {
            style: { color: "#8c8c8c", flexShrink: 0, fontSize: 12 }
          }),
          e.createElement(
            c,
            {
              type: "secondary",
              copyable: { text: p },
              ellipsis: { tooltip: p },
              style: {
                fontSize: 12,
                minWidth: 0,
                fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"
              }
            },
            p
          )
        ) : null,
        d ? e.createElement(
          c,
          { type: "secondary" },
          `${n(a, "risk")}: ${d}`
        ) : null,
        v ? e.createElement(c, { type: "warning" }, v) : null
      ),
      e.createElement(
        S,
        { size: 8, wrap: !0 },
        e.createElement(
          f,
          {
            danger: !0,
            icon: e.createElement(G),
            loading: i === "deny",
            disabled: i !== null,
            onClick: () => void w("deny")
          },
          n(a, "deny")
        ),
        e.createElement(
          f,
          {
            icon: e.createElement(z),
            loading: i === "session",
            disabled: i !== null,
            onClick: () => void w("session")
          },
          n(a, "allowSession")
        ),
        e.createElement(
          f,
          {
            type: "primary",
            icon: e.createElement(z),
            loading: i === "always",
            disabled: i !== null,
            onClick: () => void w("always")
          },
          n(a, "allowAlways")
        )
      )
    )
  );
}
function oe() {
  var P, x, T;
  const t = _((P = o.useLocale) == null ? void 0 : P.call(o)), s = (x = o.useCurrentSession) == null ? void 0 : x.call(o), a = (s == null ? void 0 : s.id) ?? ((T = o.getCurrentSessionId) == null ? void 0 : T.call(o)) ?? null, [i, l] = e.useState(null), [d, v] = e.useState([]), [b, p] = e.useState(!1), [w, E] = e.useState(!0), [y, u] = e.useState(null), h = e.useCallback(async () => {
    E(!0);
    try {
      const r = [
        g("/computer-use/status"),
        g("/computer-use/access")
      ];
      a && r.push(
        g(
          `/computer-use/session?session_id=${encodeURIComponent(a)}`
        )
      );
      const [m, j, C] = await Promise.all(
        r
      );
      l(m), v(j.access || []), p(
        (C == null ? void 0 : C.automation_active) || !1
      );
    } catch (r) {
      k.error(
        r instanceof Error ? r.message : n(t, "failed")
      );
    } finally {
      E(!1);
    }
  }, [t, a]);
  e.useEffect(() => {
    h();
  }, [h]);
  const M = async (r) => {
    u(`revoke:${r.canonical_app_id}`);
    try {
      await g("/computer-use/access", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_app_id: r.canonical_app_id })
      }), await h();
    } catch (m) {
      k.error(
        m instanceof Error ? m.message : n(t, "failed")
      );
    } finally {
      u(null);
    }
  }, U = async () => {
    if (a) {
      u("stop");
      try {
        await g("/computer-use/session/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: a })
        }), await h();
      } catch (r) {
        k.error(
          r instanceof Error ? r.message : n(t, "failed")
        );
      } finally {
        u(null);
      }
    }
  }, W = [
    {
      title: n(t, "application"),
      dataIndex: "display_name",
      key: "display_name",
      render: (r) => e.createElement(c, { strong: !0 }, r)
    },
    {
      title: n(t, "applicationId"),
      dataIndex: "canonical_app_id",
      key: "canonical_app_id",
      render: (r) => e.createElement(c, { code: !0 }, r)
    },
    {
      key: "actions",
      width: 56,
      render: (r, m) => e.createElement(
        q,
        {
          title: n(t, "revokeConfirm"),
          onConfirm: () => void M(m)
        },
        e.createElement(
          O,
          { title: n(t, "revoke") },
          e.createElement(f, {
            type: "text",
            danger: !0,
            shape: "circle",
            icon: e.createElement(H),
            loading: y === `revoke:${m.canonical_app_id}`,
            "aria-label": n(t, "revoke")
          })
        )
      )
    }
  ], A = (i == null ? void 0 : i.runtime_available) === !0;
  return e.createElement(
    "main",
    {
      style: {
        maxWidth: 1080,
        margin: "24px auto",
        padding: "0 24px 40px",
        display: "grid",
        gap: 28
      }
    },
    e.createElement(
      "header",
      {
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          paddingBottom: 16,
          borderBottom: "1px solid rgba(0, 0, 0, 0.08)"
        }
      },
      e.createElement(
        "div",
        { style: { display: "grid", gap: 6 } },
        e.createElement(
          S,
          { align: "baseline", size: 8 },
          e.createElement(
            ee,
            { level: 3, style: { margin: 0 } },
            n(t, "title")
          ),
          e.createElement(
            c,
            { type: "secondary", style: { fontSize: 12 } },
            `${n(t, "version")} ${D.version}`
          )
        ),
        e.createElement(J, {
          status: A ? "success" : "error",
          text: n(t, A ? "ready" : "unavailable")
        })
      ),
      e.createElement(
        S,
        { size: 8 },
        e.createElement(
          O,
          { title: n(t, "refresh") },
          e.createElement(f, {
            type: "text",
            shape: "circle",
            icon: e.createElement(X),
            loading: w,
            onClick: () => void h(),
            "aria-label": n(t, "refresh")
          })
        ),
        e.createElement(
          f,
          {
            danger: !0,
            icon: e.createElement(Z),
            disabled: !a || !b,
            loading: y === "stop",
            onClick: () => void U()
          },
          n(t, "stop")
        )
      )
    ),
    e.createElement(Q, {
      defaultActiveKey: "access",
      items: [
        {
          key: "access",
          label: n(t, "accessManagement"),
          children: e.createElement(F, {
            rowKey: "canonical_app_id",
            columns: W,
            dataSource: d,
            pagination: !1,
            size: "middle",
            locale: {
              emptyText: e.createElement(R, {
                image: R.PRESENTED_IMAGE_SIMPLE,
                description: n(t, "empty")
              })
            }
          })
        }
      ]
    })
  );
}
var L;
(L = window.QwenPaw.chat) == null || L.approval.render(
  "computer-use-tool",
  "computer_use_app_access",
  se
);
var $, N;
(N = ($ = window.QwenPaw).registerRoutes) == null || N.call($, "computer-use-tool", [
  {
    path: "/plugin/computer-use-tool",
    component: oe,
    label: n(te(), "routeLabel"),
    icon: "🖥️",
    priority: 43
  }
]);
