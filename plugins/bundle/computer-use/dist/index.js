const I = {
  en: {
    routeLabel: "Computer Use",
    title: "Computer Use",
    ready: "Runtime ready",
    unavailable: "Runtime unavailable",
    refresh: "Refresh",
    stop: "Stop automation",
    feature: "Enable Computer Use",
    enabledMsg: "Computer Use enabled",
    disabledMsg: "Computer Use disabled; running automation stopped",
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
    feature: "启用电脑操作",
    enabledMsg: "已启用电脑操作",
    disabledMsg: "已关闭电脑操作，正在进行的自动化已停止",
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
function a(t, n) {
  if (n.startsWith("decision.")) {
    const s = n.slice(
      9
    );
    return I[t].decision[s];
  }
  return I[t][n];
}
const B = "1.0.1", D = {
  version: B
}, o = window.QwenPaw.host, e = o.React, {
  Badge: J,
  Button: h,
  Empty: R,
  Popconfirm: F,
  Space: k,
  Switch: q,
  Table: Q,
  Tabs: K,
  Tooltip: z,
  Typography: G,
  message: m
} = o.antd, {
  CheckOutlined: M,
  CloseOutlined: H,
  DeleteOutlined: V,
  FolderOpenOutlined: X,
  ReloadOutlined: Y,
  SafetyCertificateOutlined: Z
} = o.antdIcons, { Text: d, Title: ee } = G;
function te() {
  try {
    return _(localStorage.getItem("language"));
  } catch {
    return _(void 0);
  }
}
async function b(t, n) {
  const s = o.fetch ? await o.fetch(t, n) : await fetch(o.getApiUrl(t), {
    ...n,
    headers: {
      ...(n == null ? void 0 : n.headers) || {},
      ...o.getApiToken() ? { Authorization: `Bearer ${o.getApiToken()}` } : {}
    }
  }), l = await s.text();
  let r = null;
  try {
    r = l ? JSON.parse(l) : null;
  } catch {
    r = null;
  }
  if (!s.ok) {
    const u = r && typeof r == "object" && "detail" in r ? r.detail : void 0;
    throw new Error(
      typeof u == "string" ? u : `HTTP ${s.status}`
    );
  }
  return r;
}
function ae(t, n) {
  const s = t.toolParams.display_name;
  if (typeof s == "string" && s.trim())
    return s;
  const l = t.toolParams.canonical_app_id;
  return typeof l == "string" && l.trim() ? l : a(n, "unknownApplication");
}
function ne(t) {
  const n = t.toolParams.canonical_app_id;
  if (typeof n != "string" || !n.trim())
    return "";
  const s = n.indexOf(":");
  return s !== -1 && n.slice(0, s) === "process" ? n.slice(s + 1) : n;
}
function se({ approval: t, onResolved: n }) {
  var g;
  const s = _((g = o.useLocale) == null ? void 0 : g.call(o)), [l, r] = e.useState(null), u = typeof t.toolParams.risk == "string" ? t.toolParams.risk : "", v = typeof t.toolParams.warning == "string" ? t.toolParams.warning : "", S = ae(t, s), p = ne(t), y = async (f) => {
    r(f);
    try {
      await b("/computer-use/session/pending/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: t.sessionId,
          request_id: t.requestId,
          decision: f
        })
      }), m.success(a(s, `decision.${f}`)), n();
    } catch (E) {
      m.error(
        E instanceof Error ? E.message : a(s, "failed")
      );
    } finally {
      r(null);
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
          k,
          { size: 8 },
          e.createElement(Z),
          e.createElement(
            d,
            { strong: !0 },
            a(s, "approvalTitle")
          )
        ),
        e.createElement(d, { strong: !0 }, S),
        p && p !== S ? e.createElement(
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
          e.createElement(X, {
            style: { color: "#8c8c8c", flexShrink: 0, fontSize: 12 }
          }),
          e.createElement(
            d,
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
        u ? e.createElement(
          d,
          { type: "secondary" },
          `${a(s, "risk")}: ${u}`
        ) : null,
        v ? e.createElement(d, { type: "warning" }, v) : null
      ),
      e.createElement(
        k,
        { size: 8, wrap: !0 },
        e.createElement(
          h,
          {
            danger: !0,
            icon: e.createElement(H),
            loading: l === "deny",
            disabled: l !== null,
            onClick: () => void y("deny")
          },
          a(s, "deny")
        ),
        e.createElement(
          h,
          {
            icon: e.createElement(M),
            loading: l === "session",
            disabled: l !== null,
            onClick: () => void y("session")
          },
          a(s, "allowSession")
        ),
        e.createElement(
          h,
          {
            type: "primary",
            icon: e.createElement(M),
            loading: l === "always",
            disabled: l !== null,
            onClick: () => void y("always")
          },
          a(s, "allowAlways")
        )
      )
    )
  );
}
function oe() {
  var P, T, x;
  const t = _((P = o.useLocale) == null ? void 0 : P.call(o)), n = (T = o.useCurrentSession) == null ? void 0 : T.call(o), s = (n == null ? void 0 : n.id) ?? ((x = o.getCurrentSessionId) == null ? void 0 : x.call(o)) ?? null, [l, r] = e.useState(null), [u, v] = e.useState([]), [S, p] = e.useState(!0), [y, g] = e.useState(!1), [f, E] = e.useState(!0), [U, A] = e.useState(null), w = e.useCallback(async () => {
    E(!0);
    try {
      const [i, c] = await Promise.all([
        b("/computer-use/status"),
        b("/computer-use/access")
      ]);
      r(i), v(c.access || []), p(i.enabled !== !1);
    } catch (i) {
      m.error(
        i instanceof Error ? i.message : a(t, "failed")
      );
    } finally {
      E(!1);
    }
  }, [t]);
  e.useEffect(() => {
    w();
  }, [w]);
  const $ = async (i) => {
    A(`revoke:${i.canonical_app_id}`);
    try {
      await b("/computer-use/access", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canonical_app_id: i.canonical_app_id })
      }), await w();
    } catch (c) {
      m.error(
        c instanceof Error ? c.message : a(t, "failed")
      );
    } finally {
      A(null);
    }
  }, W = async (i) => {
    g(!0);
    try {
      await b("/computer-use/feature", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: i, session_id: s })
      }), p(i), m.success(a(t, i ? "enabledMsg" : "disabledMsg")), await w();
    } catch (c) {
      m.error(
        c instanceof Error ? c.message : a(t, "failed")
      );
    } finally {
      g(!1);
    }
  }, j = [
    {
      title: a(t, "application"),
      dataIndex: "display_name",
      key: "display_name",
      render: (i) => e.createElement(d, { strong: !0 }, i)
    },
    {
      title: a(t, "applicationId"),
      dataIndex: "canonical_app_id",
      key: "canonical_app_id",
      render: (i) => e.createElement(d, { code: !0 }, i)
    },
    {
      key: "actions",
      width: 56,
      render: (i, c) => e.createElement(
        F,
        {
          title: a(t, "revokeConfirm"),
          onConfirm: () => void $(c)
        },
        e.createElement(
          z,
          { title: a(t, "revoke") },
          e.createElement(h, {
            type: "text",
            danger: !0,
            shape: "circle",
            icon: e.createElement(V),
            loading: U === `revoke:${c.canonical_app_id}`,
            "aria-label": a(t, "revoke")
          })
        )
      )
    }
  ], C = (l == null ? void 0 : l.runtime_available) === !0;
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
          k,
          { align: "baseline", size: 8 },
          e.createElement(
            ee,
            { level: 3, style: { margin: 0 } },
            a(t, "title")
          ),
          e.createElement(
            d,
            { type: "secondary", style: { fontSize: 12 } },
            `${a(t, "version")} ${D.version}`
          )
        ),
        e.createElement(J, {
          status: C ? "success" : "error",
          text: a(t, C ? "ready" : "unavailable")
        })
      ),
      e.createElement(
        k,
        { size: 8 },
        e.createElement(
          z,
          { title: a(t, "refresh") },
          e.createElement(h, {
            type: "text",
            shape: "circle",
            icon: e.createElement(Y),
            loading: f,
            onClick: () => void w(),
            "aria-label": a(t, "refresh")
          })
        ),
        e.createElement(
          k,
          { size: 8, align: "center" },
          e.createElement(
            d,
            { type: "secondary", style: { fontSize: 13 } },
            a(t, "feature")
          ),
          e.createElement(q, {
            checked: S,
            loading: y,
            disabled: !C,
            onChange: (i) => void W(i),
            "aria-label": a(t, "feature")
          })
        )
      )
    ),
    e.createElement(K, {
      defaultActiveKey: "access",
      items: [
        {
          key: "access",
          label: a(t, "accessManagement"),
          children: e.createElement(Q, {
            rowKey: "canonical_app_id",
            columns: j,
            dataSource: u,
            pagination: !1,
            size: "middle",
            locale: {
              emptyText: e.createElement(R, {
                image: R.PRESENTED_IMAGE_SIMPLE,
                description: a(t, "empty")
              })
            }
          })
        }
      ]
    })
  );
}
var O;
(O = window.QwenPaw.chat) == null || O.approval.render(
  "computer-use",
  "computer_use_app_access",
  se
);
var L, N;
(N = (L = window.QwenPaw).registerRoutes) == null || N.call(L, "computer-use", [
  {
    path: "/plugin/computer-use",
    component: oe,
    label: a(te(), "routeLabel"),
    icon: "🖥️",
    priority: 43
  }
]);
