function Q() {
  var e;
  return ((e = window.QwenPaw) == null ? void 0 : e.host) || {};
}
function A() {
  const { getApiToken: e } = Q(), n = e == null ? void 0 : e(), t = {
    "Content-Type": "application/json"
  };
  return n && (t.Authorization = `Bearer ${n}`), t;
}
function U(e) {
  const { getApiUrl: n } = Q();
  return (n == null ? void 0 : n(e)) || e;
}
async function x(e) {
  const n = await fetch(U(e), { headers: A() });
  if (!n.ok) {
    const t = await n.text().catch(() => "");
    throw new Error(t || `HTTP ${n.status}`);
  }
  return n.json();
}
async function z(e, n) {
  const t = await fetch(U(e), {
    method: "POST",
    headers: A(),
    body: void 0
  });
  if (!t.ok) {
    const m = await t.text().catch(() => "");
    throw new Error(m || `HTTP ${t.status}`);
  }
  return t.json();
}
async function F(e, n) {
  const t = await fetch(U(e), {
    method: "PUT",
    headers: A(),
    body: JSON.stringify(n)
  });
  if (!t.ok) {
    const m = await t.text().catch(() => "");
    throw new Error(m || `HTTP ${t.status}`);
  }
  return t.json();
}
const _ = {
  getStatus: () => x("/nocobase-auth/status"),
  sync: () => z("/nocobase-auth/sync"),
  testConnection: () => z("/nocobase-auth/test-connection"),
  getUsers: () => x("/nocobase-auth/users"),
  getRoles: () => x("/nocobase-auth/roles"),
  getConfig: () => x("/nocobase-auth/config"),
  updateConfig: (e) => F("/nocobase-auth/config", e)
};
function H() {
  const { React: e, antd: n } = window.QwenPaw.host, { useState: t, useEffect: m } = e, { Card: I, Form: c, Input: y, Switch: b, Button: k, Space: h, message: l, Select: u, Spin: g } = n, [d] = c.useForm(), [S, C] = t(!0), [P, f] = t(!1), [T, w] = t(!1);
  m(() => {
    _.getConfig().then((a) => {
      d.setFieldsValue({
        enabled: a.enabled ?? !1,
        base_url: a.base_url ?? "",
        api_token: a.api_token ?? "",
        user_id_field: a.user_id_field ?? "email"
      });
    }).catch((a) => {
      l.error(a.message || "加载配置失败");
    }).finally(() => C(!1));
  }, [d, l]);
  const s = async () => {
    let a;
    try {
      a = await d.validateFields();
    } catch {
      return;
    }
    f(!0);
    try {
      await _.updateConfig({
        ...a,
        role_channel_map: []
      }), l.success("配置已保存");
    } catch (v) {
      l.error(v.message || "保存失败");
    } finally {
      f(!1);
    }
  }, E = async () => {
    w(!0);
    try {
      const a = await _.testConnection();
      a.ok ? l.success("NocoBase 连接成功") : l.error(a.error || "连接失败");
    } catch (a) {
      l.error(a.message || "连接测试失败");
    } finally {
      w(!1);
    }
  };
  return S ? e.createElement(
    "div",
    { style: { textAlign: "center", padding: 60 } },
    e.createElement(g, { size: "large" })
  ) : e.createElement(
    I,
    { title: "NocoBase 连接配置", style: { maxWidth: 640 } },
    e.createElement(
      c,
      { form: d, layout: "vertical", onFinish: s },
      e.createElement(
        c.Item,
        {
          name: "enabled",
          valuePropName: "checked",
          label: "启用 NocoBase 权限"
        },
        e.createElement(b)
      ),
      e.createElement(
        c.Item,
        {
          name: "base_url",
          label: "NocoBase 地址",
          rules: [{ required: !0, message: "请输入 NocoBase 地址" }]
        },
        e.createElement(y, {
          placeholder: "https://nocobase.example.com"
        })
      ),
      e.createElement(
        c.Item,
        {
          name: "api_token",
          label: "API Token",
          rules: [{ required: !0, message: "请输入 API Token" }]
        },
        e.createElement(y.Password, {
          placeholder: "NocoBase API Token"
        })
      ),
      e.createElement(
        c.Item,
        {
          name: "user_id_field",
          label: "用户 ID 字段",
          rules: [{ required: !0, message: "请选择用户 ID 字段" }]
        },
        e.createElement(
          u,
          {},
          e.createElement(u.Option, { value: "email" }, "Email"),
          e.createElement(u.Option, { value: "phone" }, "Phone"),
          e.createElement(u.Option, { value: "nickname" }, "Nickname"),
          e.createElement(u.Option, { value: "username" }, "Username")
        )
      ),
      e.createElement(
        c.Item,
        {},
        e.createElement(
          h,
          {},
          e.createElement(
            k,
            { type: "primary", htmlType: "submit", loading: P },
            "保存"
          ),
          e.createElement(
            k,
            { onClick: E, loading: T },
            "测试连接"
          )
        )
      )
    )
  );
}
function D() {
  const { React: e, antd: n } = window.QwenPaw.host, { useState: t, useEffect: m } = e, { Card: I, Table: c, Tag: y, Button: b, Space: k, message: h, Spin: l } = n, [u, g] = t([]), [d, S] = t(!0), [C, P] = t(!1), f = async () => {
    S(!0);
    try {
      const s = await _.getUsers();
      g(s || []);
    } catch (s) {
      h.error(s.message || "加载用户失败");
    } finally {
      S(!1);
    }
  }, T = async () => {
    P(!0);
    try {
      await _.sync(), h.success("同步完成"), await f();
    } catch (s) {
      h.error(s.message || "同步失败");
    } finally {
      P(!1);
    }
  };
  m(() => {
    f();
  }, []);
  const w = [
    {
      title: "NocoBase ID",
      dataIndex: "id",
      key: "id"
    },
    {
      title: "邮箱 / Sender ID",
      dataIndex: "sender_id",
      key: "sender_id"
    },
    {
      title: "昵称",
      dataIndex: "nickname",
      key: "nickname"
    },
    {
      title: "角色",
      key: "roles",
      render: (s, E) => (E.roles || []).map(
        (a, v) => e.createElement(y, { key: v, color: "blue" }, a)
      )
    }
  ];
  return e.createElement(
    I,
    {
      title: "NocoBase 用户",
      extra: e.createElement(
        k,
        {},
        e.createElement(b, { onClick: f, loading: d }, "刷新"),
        e.createElement(
          b,
          { type: "primary", onClick: T, loading: C },
          "立即同步"
        )
      )
    },
    d && u.length === 0 ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(l, { size: "large" })
    ) : e.createElement(c, {
      columns: w,
      dataSource: u.map((s) => ({ ...s, key: s.id || s.sender_id })),
      pagination: { pageSize: 20 }
    })
  );
}
function R(e) {
  return e.split(",").map((n) => n.trim()).filter(Boolean);
}
function O(e) {
  return (e || []).join(", ");
}
function J() {
  const { React: e, antd: n } = window.QwenPaw.host, { useState: t, useEffect: m } = e, { Card: I, Table: c, Input: y, Button: b, Space: k, message: h, Spin: l, Tag: u } = n, [g, d] = t(null), [S, C] = t(!0), [P, f] = t(!1), T = async () => {
    C(!0);
    try {
      const o = await _.getConfig();
      d(o);
    } catch (o) {
      h.error(o.message || "加载配置失败");
    } finally {
      C(!1);
    }
  };
  m(() => {
    T();
  }, []);
  const w = (o, p, i) => {
    d((r) => {
      if (!r) return r;
      const B = [...r.role_channel_map || []], N = B.findIndex((j) => j.role_name === o);
      return N >= 0 ? B[N] = { ...B[N], [p]: R(i) } : B.push({
        role_name: o,
        allowed_channels: p === "allowed_channels" ? R(i) : [],
        denied_channels: p === "denied_channels" ? R(i) : []
      }), { ...r, role_channel_map: B };
    });
  }, s = async () => {
    if (g) {
      f(!0);
      try {
        await _.updateConfig(g), h.success("角色映射已保存");
      } catch (o) {
        h.error(o.message || "保存失败");
      } finally {
        f(!1);
      }
    }
  }, E = (g == null ? void 0 : g.role_channel_map) || [], a = [
    {
      title: "角色",
      dataIndex: "role_name",
      key: "role_name",
      render: (o) => e.createElement("strong", null, o)
    },
    {
      title: "允许访问的频道",
      key: "allowed",
      render: (o, p) => {
        const i = E.find((r) => r.role_name === p.role_name);
        return e.createElement(y, {
          placeholder: "console, dingtalk, telegram",
          defaultValue: O(i == null ? void 0 : i.allowed_channels),
          onBlur: (r) => w(p.role_name, "allowed_channels", r.target.value)
        });
      }
    },
    {
      title: "拒绝访问的频道",
      key: "denied",
      render: (o, p) => {
        const i = E.find((r) => r.role_name === p.role_name);
        return e.createElement(y, {
          placeholder: "dingtalk",
          defaultValue: O(i == null ? void 0 : i.denied_channels),
          onBlur: (r) => w(p.role_name, "denied_channels", r.target.value)
        });
      }
    },
    {
      title: "说明",
      key: "hint",
      render: () => e.createElement(u, { color: "orange" }, "deny 优先于 allow")
    }
  ], v = E.map((o) => ({
    ...o,
    key: o.role_name
  }));
  return e.createElement(
    I,
    {
      title: "角色 → 频道映射",
      extra: e.createElement(
        b,
        { type: "primary", onClick: s, loading: P },
        "保存映射"
      )
    },
    S ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(l, { size: "large" })
    ) : e.createElement(
      k,
      { direction: "vertical", style: { width: "100%" } },
      e.createElement(
        "div",
        { style: { color: "#8c8c8c", fontSize: 12 } },
        "先保存 NocoBase 连接配置，再在此页面为每个角色配置可访问的 QwenPaw 频道。多个频道用英文逗号分隔。"
      ),
      e.createElement(c, {
        columns: a,
        dataSource: v,
        pagination: !1
      })
    )
  );
}
function $() {
  const e = window.QwenPaw;
  if (!(e != null && e.registerRoutes)) {
    console.warn("[nocobase-auth] QwenPaw.registerRoutes not available");
    return;
  }
  e.registerRoutes("nocobase-auth", [
    {
      path: "/nocobase-auth/config",
      component: H,
      label: "NocoBase Auth",
      icon: "🔐",
      priority: 10
    },
    {
      path: "/nocobase-auth/users",
      component: D,
      label: "NocoBase 用户",
      icon: "👤",
      priority: 11
    },
    {
      path: "/nocobase-auth/roles",
      component: J,
      label: "角色映射",
      icon: "🛡️",
      priority: 12
    }
  ]);
}
$();
