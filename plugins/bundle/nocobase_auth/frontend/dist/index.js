function O() {
  var e;
  return ((e = window.QwenPaw) == null ? void 0 : e.host) || {};
}
function U() {
  const { getApiToken: e } = O(), n = e == null ? void 0 : e(), t = {
    "Content-Type": "application/json"
  };
  return n && (t.Authorization = `Bearer ${n}`), t;
}
function z(e) {
  const { getApiUrl: n } = O();
  return (n == null ? void 0 : n(e)) || e;
}
async function T(e) {
  const n = await fetch(z(e), { headers: U() });
  if (!n.ok) {
    const t = await n.text().catch(() => "");
    throw new Error(t || `HTTP ${n.status}`);
  }
  return n.json();
}
async function j(e, n) {
  const t = await fetch(z(e), {
    method: "POST",
    headers: U(),
    body: void 0
  });
  if (!t.ok) {
    const m = await t.text().catch(() => "");
    throw new Error(m || `HTTP ${t.status}`);
  }
  return t.json();
}
async function F(e, n) {
  const t = await fetch(z(e), {
    method: "PUT",
    headers: U(),
    body: JSON.stringify(n)
  });
  if (!t.ok) {
    const m = await t.text().catch(() => "");
    throw new Error(m || `HTTP ${t.status}`);
  }
  return t.json();
}
const b = {
  getStatus: () => T("/nocobase-auth/status"),
  testConnection: () => j("/nocobase-auth/test-connection"),
  getUsers: () => T("/nocobase-auth/users"),
  getRoles: () => T("/nocobase-auth/roles"),
  getConfig: () => T("/nocobase-auth/config"),
  updateConfig: (e) => F("/nocobase-auth/config", e)
};
function H() {
  const { React: e, antd: n } = window.QwenPaw.host, { useState: t, useEffect: m } = e, { Card: k, Form: s, Input: f, Switch: S, Button: E, Space: p, message: c, Select: u, Spin: h } = n, [d] = s.useForm(), [_, y] = t(!0), [C, r] = t(!1), [I, w] = t(!1);
  m(() => {
    b.getConfig().then((a) => {
      d.setFieldsValue({
        enabled: a.enabled ?? !1,
        base_url: a.base_url ?? "",
        api_token: a.api_token ?? "",
        authenticator: a.authenticator ?? "basic",
        user_id_field: a.user_id_field ?? "email"
      });
    }).catch((a) => {
      c.error(a.message || "加载配置失败");
    }).finally(() => y(!1));
  }, [d, c]);
  const P = async () => {
    let a;
    try {
      a = await d.validateFields();
    } catch {
      return;
    }
    r(!0);
    try {
      await b.updateConfig({
        ...a,
        role_channel_map: []
      }), c.success("配置已保存");
    } catch (x) {
      c.error(x.message || "保存失败");
    } finally {
      r(!1);
    }
  }, v = async () => {
    w(!0);
    try {
      const a = await b.testConnection();
      a.ok ? c.success("NocoBase 连接成功") : c.error(a.error || "连接失败");
    } catch (a) {
      c.error(a.message || "连接测试失败");
    } finally {
      w(!1);
    }
  };
  return _ ? e.createElement(
    "div",
    { style: { textAlign: "center", padding: 60 } },
    e.createElement(h, { size: "large" })
  ) : e.createElement(
    k,
    { title: "NocoBase 连接配置", style: { maxWidth: 640 } },
    e.createElement(
      s,
      { form: d, layout: "vertical", onFinish: P },
      e.createElement(
        s.Item,
        {
          name: "enabled",
          valuePropName: "checked",
          label: "启用 NocoBase 权限"
        },
        e.createElement(S)
      ),
      e.createElement(
        s.Item,
        {
          name: "base_url",
          label: "NocoBase 地址",
          rules: [{ required: !0, message: "请输入 NocoBase 地址" }]
        },
        e.createElement(f, {
          placeholder: "https://nocobase.example.com"
        })
      ),
      e.createElement(
        s.Item,
        {
          name: "api_token",
          label: "API Token（用于同步用户/角色）"
        },
        e.createElement(f.Password, {
          placeholder: "NocoBase API Token"
        })
      ),
      e.createElement(
        s.Item,
        {
          name: "authenticator",
          label: "登录认证器",
          rules: [{ required: !0, message: "请输入登录认证器" }]
        },
        e.createElement(f, {
          placeholder: "basic"
        })
      ),
      e.createElement(
        s.Item,
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
        s.Item,
        {},
        e.createElement(
          p,
          {},
          e.createElement(
            E,
            { type: "primary", htmlType: "submit", loading: C },
            "保存"
          ),
          e.createElement(
            E,
            { onClick: v, loading: I },
            "测试连接"
          )
        )
      )
    )
  );
}
function D() {
  const { React: e, antd: n } = window.QwenPaw.host, { useState: t, useEffect: m } = e, { Card: k, Table: s, Tag: f, Button: S, Space: E, message: p, Spin: c } = n, [u, h] = t([]), [d, _] = t(!0), y = async () => {
    _(!0);
    try {
      const r = await b.getUsers();
      h(r || []);
    } catch (r) {
      p.error(r.message || "加载用户失败");
    } finally {
      _(!1);
    }
  };
  m(() => {
    y();
  }, []);
  const C = [
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
      render: (r, I) => (I.roles || []).map(
        (w, P) => e.createElement(f, { key: P, color: "blue" }, w)
      )
    }
  ];
  return e.createElement(
    k,
    {
      title: "NocoBase 用户",
      extra: e.createElement(
        E,
        {},
        e.createElement(S, { onClick: y, loading: d }, "刷新")
      )
    },
    d && u.length === 0 ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(c, { size: "large" })
    ) : e.createElement(s, {
      columns: C,
      dataSource: u.map((r) => ({ ...r, key: r.id || r.sender_id })),
      pagination: { pageSize: 20 }
    })
  );
}
function R(e) {
  return e.split(",").map((n) => n.trim()).filter(Boolean);
}
function A(e) {
  return (e || []).join(", ");
}
function J() {
  const { React: e, antd: n } = window.QwenPaw.host, { useState: t, useEffect: m } = e, { Card: k, Table: s, Input: f, Button: S, Space: E, message: p, Spin: c, Tag: u } = n, [h, d] = t(null), [_, y] = t(!0), [C, r] = t(!1), I = async () => {
    y(!0);
    try {
      const o = await b.getConfig();
      d(o);
    } catch (o) {
      p.error(o.message || "加载配置失败");
    } finally {
      y(!1);
    }
  };
  m(() => {
    I();
  }, []);
  const w = (o, g, i) => {
    d((l) => {
      if (!l) return l;
      const B = [...l.role_channel_map || []], N = B.findIndex((Q) => Q.role_name === o);
      return N >= 0 ? B[N] = { ...B[N], [g]: R(i) } : B.push({
        role_name: o,
        allowed_channels: g === "allowed_channels" ? R(i) : [],
        denied_channels: g === "denied_channels" ? R(i) : []
      }), { ...l, role_channel_map: B };
    });
  }, P = async () => {
    if (h) {
      r(!0);
      try {
        await b.updateConfig(h), p.success("角色映射已保存");
      } catch (o) {
        p.error(o.message || "保存失败");
      } finally {
        r(!1);
      }
    }
  }, v = (h == null ? void 0 : h.role_channel_map) || [], a = [
    {
      title: "角色",
      dataIndex: "role_name",
      key: "role_name",
      render: (o) => e.createElement("strong", null, o)
    },
    {
      title: "允许访问的频道",
      key: "allowed",
      render: (o, g) => {
        const i = v.find((l) => l.role_name === g.role_name);
        return e.createElement(f, {
          placeholder: "console, dingtalk, telegram",
          defaultValue: A(i == null ? void 0 : i.allowed_channels),
          onBlur: (l) => w(g.role_name, "allowed_channels", l.target.value)
        });
      }
    },
    {
      title: "拒绝访问的频道",
      key: "denied",
      render: (o, g) => {
        const i = v.find((l) => l.role_name === g.role_name);
        return e.createElement(f, {
          placeholder: "dingtalk",
          defaultValue: A(i == null ? void 0 : i.denied_channels),
          onBlur: (l) => w(g.role_name, "denied_channels", l.target.value)
        });
      }
    },
    {
      title: "说明",
      key: "hint",
      render: () => e.createElement(u, { color: "orange" }, "deny 优先于 allow")
    }
  ], x = v.map((o) => ({
    ...o,
    key: o.role_name
  }));
  return e.createElement(
    k,
    {
      title: "角色 → 频道映射",
      extra: e.createElement(
        S,
        { type: "primary", onClick: P, loading: C },
        "保存映射"
      )
    },
    _ ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(c, { size: "large" })
    ) : e.createElement(
      E,
      { direction: "vertical", style: { width: "100%" } },
      e.createElement(
        "div",
        { style: { color: "#8c8c8c", fontSize: 12 } },
        "先保存 NocoBase 连接配置，再在此页面为每个角色配置可访问的 QwenPaw 频道。多个频道用英文逗号分隔。"
      ),
      e.createElement(s, {
        columns: a,
        dataSource: x,
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
