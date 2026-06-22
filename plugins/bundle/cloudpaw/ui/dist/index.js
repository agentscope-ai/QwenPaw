function Nt() {
  var et, tt, nt, rt;
  const { React: e, antd: N, antdIcons: U, getApiUrl: q, getApiToken: F } = window.QwenPaw.host, {
    Card: K,
    Table: L,
    Tag: M,
    Typography: ke,
    Space: B,
    Button: A,
    Input: X,
    Radio: Te,
    Descriptions: ae,
    Spin: he,
    message: We,
    theme: Je
  } = N, { Text: ie } = ke, { TextArea: st } = X, { useState: k, useMemo: Ce, useCallback: I } = e, { InfoCircleOutlined: Re, DownOutlined: Ue, RightOutlined: at } = U || {};
  function it(t) {
    var i, u;
    const n = (u = (i = t == null ? void 0 : t.content) == null ? void 0 : i[0]) == null ? void 0 : u.data, o = n == null ? void 0 : n.arguments;
    if (typeof o == "string")
      try {
        return JSON.parse(o);
      } catch {
        return {};
      }
    return o ?? {};
  }
  function ct() {
    return window.currentSessionId ?? null;
  }
  function re(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function dt(t) {
    if (t == null) return !0;
    const n = re(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function ut(t, n) {
    try {
      const o = F(), i = {
        "Content-Type": "application/json"
      };
      return o && (i.Authorization = `Bearer ${o}`), (await fetch(q("/interaction"), {
        method: "POST",
        headers: i,
        body: JSON.stringify({ session_id: t, result: n })
      })).ok;
    } catch {
      return !1;
    }
  }
  function ft(t) {
    if (!t) return null;
    if (typeof t == "string")
      try {
        const n = JSON.parse(t);
        if (Array.isArray(n)) {
          const o = n.find(
            (i) => (i == null ? void 0 : i.type) === "text" && (i == null ? void 0 : i.text)
          );
          return (o == null ? void 0 : o.text) ?? null;
        }
        if (typeof n == "string") return n;
      } catch {
        return t;
      }
    if (Array.isArray(t)) {
      const n = t.find((o) => (o == null ? void 0 : o.type) === "text" && (o == null ? void 0 : o.text));
      return (n == null ? void 0 : n.text) ?? null;
    }
    return null;
  }
  function mt(t) {
    var l, m;
    if (!t || t.length < 2) return null;
    const n = (m = (l = t[1]) == null ? void 0 : l.data) == null ? void 0 : m.output, o = ft(n);
    if (!o) return null;
    if (o.startsWith("Error:")) return o;
    const i = o.match(/^用户选择了「(.+?)」并确认部署$/);
    if (i) return `已确认部署「${i[1]}」`;
    const u = o.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/
    );
    if (u)
      return `已选择「${u[1]}」并调整：${u[2]}`;
    if (o === "用户确认部署") return "已确认部署";
    const g = o.match(/^用户要求调整资源[：:](.+)$/);
    return g ? `已反馈调整意见：${g[1]}` : "已确认";
  }
  const Fe = [
    "资源类型",
    "资源用途",
    "规格",
    "地域",
    "数量",
    "计费方式",
    "时长",
    "原价",
    "优惠",
    "预估算费用"
  ], pt = new Set(
    Fe.map((t) => t.toLowerCase())
  );
  function Ne(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = re(t[0]).trim().toLowerCase();
    return pt.has(n);
  }
  function Ke(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = re(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function gt(t) {
    const n = [];
    let o = [];
    for (const i of t)
      o.push(i), Ke(i) && (n.push(o), o = []);
    return o.length > 0 && (n.length > 0 ? n[n.length - 1].push(...o) : n.push(o)), n.length > 0 ? n : [t];
  }
  function yt(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && t.text ? t.url ? e.createElement(
      "a",
      {
        href: t.url,
        target: "_blank",
        rel: "noopener noreferrer"
      },
      t.text
    ) : t.text : String(t ?? "");
  }
  function ht({ data: t }) {
    var pe, c, x;
    const [n, o] = k("confirm"), [i, u] = k(""), [g, l] = k(!1), [m, s] = k(null), [_, S] = k(
      {}
    ), R = e.useRef(!1), Z = e.useRef(null), [, ce] = k(0), j = t == null ? void 0 : t.content, W = j && j.length >= 2 && ((c = (pe = j[1]) == null ? void 0 : pe.data) == null ? void 0 : c.output), J = Ce(
      () => mt(j),
      [j]
    ), $ = R.current || W || J !== null, v = Ce(() => {
      const y = it(t), a = y == null ? void 0 : y.data;
      if (!a) return null;
      try {
        const f = typeof a == "string" ? JSON.parse(a) : a;
        let d;
        if (y.strategy_names)
          try {
            const z = typeof y.strategy_names == "string" ? JSON.parse(y.strategy_names) : y.strategy_names;
            d = Array.isArray(z) ? z : [];
          } catch {
            d = [];
          }
        else f != null && f.proposal_names ? d = f.proposal_names : d = [];
        const E = d.length >= 2 ? d.length : 0;
        let w;
        if (Array.isArray(f) && f.length > 0)
          if (Array.isArray(f[0]) && f[0].length === 10 && !Array.isArray(f[0][0])) {
            const P = f.filter(
              (ne) => !Ne(ne)
            );
            if (P.filter(
              (ne) => Ke(ne)
            ).length >= 2)
              w = gt(P);
            else if (E >= 2 && P.length >= E * 2) {
              const ne = Math.ceil(P.length / E);
              w = [];
              for (let ge = 0; ge < P.length; ge += ne)
                w.push(P.slice(ge, ge + ne));
            } else
              w = [P];
          } else
            w = f.map(
              (P) => P.filter(
                (Q) => Array.isArray(Q) && Q.length === 10 && !Ne(Q)
              )
            );
        else if (f != null && f.proposals)
          w = f.proposals.map(
            (z) => z.filter((P) => !Ne(P))
          );
        else
          return null;
        if (w = w.filter((z) => z.length > 0), w.length === 0) return null;
        const le = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (d.length < w.length)
          for (let z = d.length; z < w.length; z++)
            d.push(le[z] || `方案${z + 1}`);
        return { proposals: w, names: d };
      } catch {
        return null;
      }
    }, [t]), C = ct(), b = (((x = v == null ? void 0 : v.proposals) == null ? void 0 : x.length) ?? 0) > 1, de = I(async () => {
      if (!C || $ || !v) return;
      const y = b ? m : 0, a = v.names[y ?? 0] || `方案${(y ?? 0) + 1}`;
      let f;
      n === "confirm" ? f = `用户选择了「${a}」并确认部署` : f = `用户选择「${a}」并要求调整：${i.trim() || "未填写具体要求"}`, l(!0);
      const d = await ut(C, f);
      l(!1), d ? (R.current = !0, n === "confirm" ? Z.current = `已确认部署「${a}」` : Z.current = `已选择「${a}」并调整：${i.trim()}`, ce((E) => E + 1), We.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : We.error("操作失败，请重试");
    }, [
      C,
      $,
      v,
      n,
      i,
      m,
      b
    ]), we = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created";
    if (!v)
      return we ? e.createElement(
        "div",
        {
          style: {
            width: "100%",
            borderRadius: 10,
            border: "1px solid #f0f0f0",
            background: "#fff",
            padding: "24px 16px",
            margin: "4px 0",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12
          }
        },
        e.createElement(he, { size: "default" }),
        e.createElement(
          ie,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        K,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(ie, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: G, names: ue } = v, D = Fe.map((y, a) => ({
      title: y,
      dataIndex: `col_${a}`,
      key: `col_${a}`,
      render: (f) => yt(f),
      ellipsis: a < 3
    }));
    let fe = "待确认", Y = "processing";
    $ && (Y = "success", fe = Z.current || J || "已确认");
    const ee = e.createElement(
      M,
      {
        color: Y,
        style: { marginLeft: 4 }
      },
      fe
    ), Se = e.createElement(
      B,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        ie,
        { strong: !0, style: { fontSize: 14 } },
        $ ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      ee
    ), me = G.map((y, a) => {
      const f = b ? m === a : !0, d = _[a] || !1, E = (T) => {
        const V = re(T[0] || "").trim();
        return /^合计|^总计|^total/i.test(V);
      }, w = y.find(E), le = y.filter((T) => !E(T)), z = le.map((T) => ({
        type: re(T[0] || ""),
        purpose: re(T[1] || ""),
        spec: re(T[2] || ""),
        cost: T[9] ?? null
      })), P = w ? re(w[9] ?? "") : "", Q = y.map((T, V) => {
        const $e = { key: V };
        return T.forEach((Ie, Be) => {
          $e[`col_${Be}`] = Ie;
        }), $e;
      }), ne = f ? "2px solid #1677ff" : "1px solid #e8e8e8", ge = f ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: a,
          style: {
            flex: 1,
            minWidth: 240,
            border: ne,
            borderRadius: 8,
            cursor: b ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: ge,
            background: "#fff"
          },
          onClick: b ? () => s(a) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            ie,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            ue[a]
          ),
          ...z.map(
            (T, V) => e.createElement(
              "div",
              {
                key: V,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: V < z.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  T.type
                ),
                T.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  T.spec
                )
              ),
              !dt(T.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                re(T.cost)
              )
            )
          ),
          // Total cost
          P && e.createElement(
            "div",
            {
              style: {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginTop: 6,
                paddingTop: 6,
                borderTop: "1px dashed #e8e8e8"
              }
            },
            e.createElement(
              "span",
              { style: { fontSize: 12, fontWeight: 500 } },
              "合计"
            ),
            e.createElement(
              "span",
              {
                style: { fontSize: 14, fontWeight: 700, color: "#fa541c" }
              },
              P
            )
          ),
          // Details toggle
          e.createElement(
            "div",
            {
              style: {
                display: "flex",
                alignItems: "center",
                gap: 4,
                color: "#8c8c8c",
                fontSize: 12,
                cursor: "pointer",
                marginTop: 6
              },
              onClick: (T) => {
                T.stopPropagation(), S((V) => ({
                  ...V,
                  [a]: !V[a]
                }));
              }
            },
            e.createElement(
              d && Ue ? Ue : at || "span",
              {
                style: { fontSize: 10 }
              }
            ),
            e.createElement(
              "span",
              null,
              `明细 · ${le.length} 项`
            )
          ),
          d && e.createElement(
            "div",
            {
              onClick: (T) => T.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(L, {
              columns: D,
              dataSource: Q,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), te = e.createElement(
      "div",
      {
        style: {
          background: "#fffbe6",
          border: "1px solid #ffe58f",
          borderRadius: 6,
          padding: "8px 12px",
          marginBottom: 10,
          display: "flex",
          alignItems: "flex-start",
          gap: 8
        }
      },
      Re ? e.createElement(Re, {
        style: {
          color: "#faad14",
          fontSize: 14,
          flexShrink: 0,
          marginTop: 1
        }
      }) : e.createElement("span", null, "⚠️"),
      e.createElement(
        "span",
        {
          style: { fontSize: 12, color: "#8c6e00", lineHeight: 1.5 }
        },
        "在服务部署与配置过程中，可能因实际资源需求变化导致资源变配及费用调整，请及时关注实际资源使用情况与账单详情。"
      )
    ), ye = !$ && C && !(b && m === null) && e.createElement(
      "div",
      null,
      e.createElement(
        "div",
        {
          style: {
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            marginBottom: 8
          }
        },
        // Confirm option
        e.createElement(
          "div",
          {
            style: {
              flex: 1,
              minWidth: 140,
              border: `1px solid ${n === "confirm" ? "#1677ff" : "#e8e8e8"}`,
              borderRadius: 6,
              padding: "8px 12px",
              cursor: "pointer",
              transition: "all 0.15s ease",
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: n === "confirm" ? "#e6f4ff" : "transparent"
            },
            onClick: () => o("confirm")
          },
          e.createElement(Te, { checked: n === "confirm" }),
          e.createElement(
            "span",
            { style: { fontSize: 13 } },
            "确认部署"
          )
        ),
        // Adjust option
        e.createElement(
          "div",
          {
            style: {
              flex: 1,
              minWidth: 140,
              border: `1px solid ${n === "adjust" ? "#1677ff" : "#e8e8e8"}`,
              borderRadius: 6,
              padding: "8px 12px",
              transition: "all 0.15s ease",
              background: n === "adjust" ? "#e6f4ff" : "transparent"
            }
          },
          e.createElement(
            "div",
            {
              style: {
                display: "flex",
                alignItems: "center",
                gap: 8,
                cursor: "pointer"
              },
              onClick: () => o("adjust")
            },
            e.createElement(Te, { checked: n === "adjust" }),
            e.createElement(
              "span",
              { style: { fontSize: 13 } },
              "调整资源"
            )
          ),
          n === "adjust" && e.createElement(st, {
            value: i,
            onChange: (y) => u(y.target.value),
            placeholder: "请输入调整要求",
            autoSize: { minRows: 1, maxRows: 3 },
            style: { fontSize: 12, marginTop: 6 }
          })
        )
      ),
      // Footer
      e.createElement(
        "div",
        {
          style: {
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingTop: 8
          }
        },
        e.createElement(
          ie,
          { type: "secondary", style: { fontSize: 11 } },
          b ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          A,
          {
            type: "primary",
            size: "small",
            loading: g,
            onClick: de,
            disabled: n === "adjust" && !i.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), O = b && m === null && !$ && e.createElement(
      "div",
      {
        style: {
          textAlign: "center",
          padding: "8px 0 4px",
          color: "rgba(0,0,0,0.45)",
          fontSize: 12
        }
      },
      "请点击选择一个方案后继续操作"
    );
    return e.createElement(
      "div",
      {
        style: {
          width: "100%",
          borderRadius: 10,
          border: "1px solid #f0f0f0",
          overflow: "hidden",
          background: "#fff",
          padding: "12px 16px",
          margin: "4px 0"
        }
      },
      // Header
      e.createElement("div", { style: { marginBottom: 10 } }, Se),
      // Proposals grid
      e.createElement(
        "div",
        {
          style: {
            display: "flex",
            gap: 10,
            marginBottom: 12,
            flexWrap: "wrap"
          }
        },
        ...me
      ),
      O,
      te,
      !$ && ye
    );
  }
  const {
    Form: oe,
    Select: ze,
    Drawer: Et,
    Modal: Ye,
    Empty: xt,
    Badge: qe,
    Divider: wt,
    message: H
  } = N, {
    ApiOutlined: Xe,
    PlusOutlined: Ge,
    ReloadOutlined: Oe,
    DeleteOutlined: Qe,
    LinkOutlined: Ve,
    DisconnectOutlined: Dt
  } = U || {}, { useEffect: Ze } = e, Ee = "/a2a/agents";
  function Pe() {
    var t;
    try {
      const n = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage");
      if (n) {
        const o = JSON.parse(n);
        return ((t = o == null ? void 0 : o.state) == null ? void 0 : t.selectedAgent) || null;
      }
    } catch {
    }
    return null;
  }
  async function xe(t, n) {
    const o = q(t), i = F == null ? void 0 : F(), u = Pe(), g = {
      "Content-Type": "application/json",
      ...i ? { Authorization: `Bearer ${i}` } : {},
      ...u ? { "X-Agent-Id": u } : {}
    }, l = await fetch(o, {
      ...n,
      headers: { ...g, ...(n == null ? void 0 : n.headers) || {} }
    });
    if (!l.ok) {
      const m = await l.text().catch(() => "");
      throw new Error(m || `HTTP ${l.status}`);
    }
    return l.status === 204 || l.headers.get("content-length") === "0" ? null : l.json();
  }
  function St(t) {
    var m;
    const { agent: n, onClick: o } = t, i = n.status === "connected", u = i ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", g = i ? "已连接" : n.status === "error" ? "错误" : "未连接", l = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      K,
      {
        hoverable: !0,
        onClick: o,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          B,
          null,
          e.createElement(qe, { color: u }),
          e.createElement(
            "span",
            null,
            n.alias || n.name || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          M,
          { color: "blue" },
          l[n.auth_type] || n.auth_type
        ) : null
      },
      e.createElement(
        "div",
        { style: { fontSize: 12, color: "#666" } },
        e.createElement(
          "div",
          { style: { marginBottom: 4 } },
          Ve ? e.createElement(Ve, { style: { marginRight: 4 } }) : null,
          n.url
        ),
        n.description ? e.createElement(
          "div",
          { style: { marginBottom: 4, color: "#999" } },
          n.description
        ) : null,
        ((m = n.skills) == null ? void 0 : m.length) > 0 ? e.createElement(
          "div",
          null,
          n.skills.slice(0, 3).map(
            (s, _) => e.createElement(
              M,
              { key: _, style: { fontSize: 11 } },
              s.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            M,
            { style: { fontSize: 11 } },
            `+${n.skills.length - 3}`
          ) : null
        ) : null,
        e.createElement(
          "div",
          { style: { marginTop: 4, color: u, fontSize: 11 } },
          g,
          n.error ? ` - ${n.error}` : ""
        )
      )
    );
  }
  function At() {
    const t = e.useRef(Pe()), [n, o] = k(t.current);
    return Ze(() => {
      const i = () => {
        const g = Pe();
        g !== t.current && (t.current = g, o(g));
      }, u = setInterval(i, 200);
      return window.addEventListener("storage", i), () => {
        clearInterval(u), window.removeEventListener("storage", i);
      };
    }, []), n;
  }
  function bt() {
    var ot, lt;
    const { token: t } = Je.useToken(), n = At(), [o, i] = k([]), [u, g] = k(!0), [l, m] = k(!1), [s, _] = k(null), [S, R] = k(!1), [Z, ce] = k(!1), [j, W] = k(!1), [J, $] = k(!1), [v, C] = k(""), [b] = oe.useForm(), [de, we] = k(!1), [G, ue] = k(!1), [D, fe] = k([]), [Y, ee] = k(
      /* @__PURE__ */ new Set()
    ), [Se, me] = k(
      []
    ), te = e.useRef(null), ye = (r) => !r || !r.trim() ? null : /\s/.test(r) ? "别名不能包含空格" : null, O = Ce(
      () => new Set(o.map((r) => r.url)),
      [o]
    ), pe = e.useRef(O);
    pe.current = O;
    const c = I(async () => {
      g(!0);
      try {
        const r = await xe(Ee);
        i((r == null ? void 0 : r.agents) || []);
      } catch {
        i([]);
      } finally {
        g(!1);
      }
    }, []);
    Ze(() => {
      c();
    }, [n]);
    const x = I(() => {
      R(!0), _(null), m(!0), b.resetFields(), b.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [b]), y = I((r) => {
      R(!1), _(r), m(!0);
    }, []), a = I(() => {
      $(!1), C("");
    }, []), f = I(async () => {
      if (!s || !v.trim()) return;
      const r = ye(v);
      if (r) {
        H.error(r);
        return;
      }
      const p = s.alias || s.url, h = v.trim();
      if (h === p) {
        a();
        return;
      }
      try {
        const se = await xe(
          `${Ee}?alias=${encodeURIComponent(p)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_alias: h })
          }
        );
        H.success("别名已修改"), $(!1), _(se), await c();
      } catch (se) {
        H.error(se.message || "修改失败");
      }
    }, [s, v, c, a]), d = I(() => {
      a(), m(!1), _(null), R(!1), b.resetFields();
    }, [a, b]), E = I(async () => {
      let r;
      try {
        r = await b.validateFields();
      } catch {
        return;
      }
      const p = {
        url: String(r.url || "").trim(),
        alias: String(r.alias || "").trim() || void 0,
        auth_type: String(r.auth_type || ""),
        auth_token: String(r.auth_token || "")
      };
      if (p.url) {
        ce(!0);
        try {
          await xe(Ee, {
            method: "POST",
            body: JSON.stringify(p)
          }), H.success("A2A Agent 注册成功"), await c(), d();
        } catch (h) {
          H.error(h.message || "注册失败");
        } finally {
          ce(!1);
        }
      }
    }, [b, c, d]), w = I(async () => {
      if (!s) return;
      const r = s.alias || s.url, p = s.name || r;
      Ye.confirm({
        title: "确认删除",
        content: `确定删除 A2A Agent「${p}」吗？此操作不可撤销。`,
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await xe(`${Ee}?alias=${encodeURIComponent(r)}`, {
              method: "DELETE"
            }), H.success(`已删除 A2A Agent「${p}」`), await c(), d();
          } catch (h) {
            H.error(h.message || "删除失败");
          }
        }
      });
    }, [s, c, d]), le = I(async () => {
      if (!s) return;
      const r = s.alias || s.url;
      W(!0);
      try {
        const p = await xe(
          `${Ee}/refresh?alias=${encodeURIComponent(r)}`,
          {
            method: "POST"
          }
        );
        H.success("Agent Card 已刷新"), await c(), p && _(p);
      } catch (p) {
        H.error(p.message || "刷新失败");
      } finally {
        W(!1);
      }
    }, [s, c]), z = I(() => {
      s && (C(s.alias || ""), $(!0));
    }, [s]), P = I(() => {
      we(!0), fe([]), ee(/* @__PURE__ */ new Set()), me([]), te.current = null, ne();
    }, []), Q = I(() => {
      G && te.current && te.current.abort(), we(!1), fe([]), ee(/* @__PURE__ */ new Set()), me([]), te.current = null;
    }, [G]), ne = I(async () => {
      ue(!0);
      const r = new AbortController();
      te.current = r;
      try {
        const p = F == null ? void 0 : F(), h = Pe(), se = {
          ...p ? { Authorization: `Bearer ${p}` } : {},
          ...h ? { "X-Agent-Id": h } : {}
        }, be = await fetch(q("/a2a/import"), {
          method: "GET",
          headers: se,
          signal: r.signal
        });
        if (!be.ok) {
          const _e = await be.text().catch(() => "");
          throw new Error(_e || `HTTP ${be.status}`);
        }
        const He = await be.json(), je = (He == null ? void 0 : He.agents) || [];
        if (je.length === 0) {
          H.warning("未找到可用的 Agent");
          return;
        }
        fe(je);
        const $t = pe.current;
        ee(
          new Set(
            je.filter((_e) => !$t.has(_e.url)).map((_e) => _e.url)
          )
        );
      } catch (p) {
        if ((p == null ? void 0 : p.name) === "AbortError") return;
        H.error(p.message || "获取 Agent 列表失败");
      } finally {
        ue(!1), te.current = null;
      }
    }, []), ge = I((r) => {
      ee((p) => {
        const h = new Set(p);
        return h.has(r) ? h.delete(r) : h.add(r), h;
      });
    }, []), T = I(() => {
      ee(
        new Set(
          D.filter((r) => !O.has(r.url)).map((r) => r.url)
        )
      );
    }, [D, O]), V = I(() => {
      ee(/* @__PURE__ */ new Set());
    }, []), $e = I(async () => {
      const r = D.filter(
        (h) => Y.has(h.url) && !O.has(h.url)
      );
      if (r.length === 0) {
        H.warning("请至少选择一个 Agent");
        return;
      }
      ue(!0), me([]);
      const p = [];
      for (const h of r) {
        try {
          await xe(Ee, {
            method: "POST",
            body: JSON.stringify({
              url: h.url,
              alias: h.name || void 0,
              auth_type: h.auth_type || "gateway",
              auth_token: ""
            })
          }), p.push({ name: h.name || h.url, success: !0 });
        } catch (se) {
          p.push({
            name: h.name || h.url,
            success: !1,
            error: se.message || "注册失败"
          });
        }
        me([...p]);
      }
      await c(), H.success(
        `导入完成：成功 ${p.filter((h) => h.success).length} 个，失败 ${p.filter((h) => !h.success).length} 个`
      ), ue(!1), setTimeout(() => Q(), 800);
    }, [D, Y, c, O]), Ie = ((ot = oe.useWatch) == null ? void 0 : ot.call(oe, "auth_type", b)) ?? "", Be = e.createElement(
      oe,
      { form: b, layout: "vertical" },
      e.createElement(
        oe.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: !0, message: "请输入 Agent URL" }]
        },
        e.createElement(X, {
          placeholder: "https://agent.example.com"
        })
      ),
      e.createElement(
        oe.Item,
        {
          name: "alias",
          label: "别名",
          rules: [
            {
              validator: (r, p) => {
                const h = ye(p);
                return h ? Promise.reject(new Error(h)) : Promise.resolve();
              }
            }
          ]
        },
        e.createElement(X, {
          placeholder: "输入别名（可选，仅小写字母、数字和连字符）"
        })
      ),
      e.createElement(
        oe.Item,
        { name: "auth_type", label: "认证类型" },
        e.createElement(
          ze,
          { allowClear: !0, placeholder: "无认证" },
          e.createElement(
            ze.Option,
            { value: "bearer" },
            "Bearer Token"
          ),
          e.createElement(ze.Option, { value: "api_key" }, "API Key"),
          e.createElement(
            ze.Option,
            { value: "gateway" },
            "阿里云Agent Hub"
          )
        )
      ),
      Ie === "gateway" ? e.createElement(
        "div",
        {
          style: {
            marginBottom: 16,
            padding: "8px 12px",
            background: "#f6ffed",
            border: "1px solid #b7eb8f",
            borderRadius: 6,
            fontSize: 12,
            color: "#52c41a"
          }
        },
        "阿里云Agent Hub 模式将自动使用环境变量中的 AK-SK 换取 Bearer Token"
      ) : null,
      Ie && Ie !== "gateway" ? e.createElement(
        oe.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(X.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), _t = s ? e.createElement(
      "div",
      null,
      e.createElement(
        ae,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          ae.Item,
          { label: "URL" },
          s.url
        ),
        e.createElement(
          ae.Item,
          { label: "别名" },
          J ? e.createElement(
            "div",
            {
              style: { display: "flex", alignItems: "center", gap: 6 }
            },
            e.createElement(X, {
              value: v,
              onChange: (r) => C(r.target.value),
              onPressEnter: f,
              autoFocus: !0,
              placeholder: "输入新别名",
              size: "small",
              style: { flex: 1 }
            }),
            e.createElement(
              A,
              {
                type: "link",
                size: "small",
                onClick: f,
                disabled: !v.trim(),
                style: { padding: 0 }
              },
              "保存"
            )
          ) : e.createElement(
            "div",
            {
              style: { display: "flex", alignItems: "center", gap: 8 }
            },
            e.createElement("span", null, s.alias || "-"),
            e.createElement(
              "a",
              {
                style: { fontSize: 12 },
                onClick: z
              },
              "修改"
            )
          )
        ),
        e.createElement(
          ae.Item,
          { label: "Agent 名称" },
          s.name || "-"
        ),
        e.createElement(
          ae.Item,
          { label: "状态" },
          e.createElement(qe, {
            color: s.status === "connected" ? "#52c41a" : s.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: s.status === "connected" ? "已连接" : s.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          ae.Item,
          { label: "认证类型" },
          s.auth_type ? e.createElement(
            M,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[s.auth_type] || s.auth_type
          ) : "无认证"
        ),
        e.createElement(
          ae.Item,
          { label: "描述" },
          s.description || "-"
        ),
        e.createElement(
          ae.Item,
          { label: "版本" },
          s.version || "-"
        )
      ),
      ((lt = s.skills) == null ? void 0 : lt.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...s.skills.map(
          (r, p) => e.createElement(
            K,
            { key: p, size: "small", style: { marginBottom: 8 } },
            e.createElement("strong", null, r.name),
            r.description ? e.createElement(
              "div",
              { style: { color: "#666", fontSize: 12 } },
              r.description
            ) : null
          )
        )
      ) : null,
      s.capabilities ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "能力"),
        e.createElement(
          B,
          null,
          e.createElement(
            M,
            {
              color: s.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            M,
            {
              color: s.capabilities.push_notifications ? "green" : "default"
            },
            "Push Notifications"
          )
        )
      ) : null,
      s.error ? e.createElement(
        "div",
        {
          style: {
            marginTop: 16,
            padding: "8px 12px",
            background: "#fff2f0",
            border: "1px solid #ffccc7",
            borderRadius: 6,
            fontSize: 12,
            color: "#ff4d4f"
          }
        },
        s.error
      ) : null,
      e.createElement(wt, null),
      e.createElement(
        B,
        null,
        e.createElement(
          A,
          {
            type: "primary",
            icon: Oe ? e.createElement(Oe) : null,
            loading: j,
            onClick: le
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          A,
          {
            danger: !0,
            icon: Qe ? e.createElement(Qe) : null,
            onClick: w
          },
          "删除"
        )
      )
    ) : null, Rt = e.createElement(
      Et,
      {
        title: S ? "注册远程 A2A Agent" : (s == null ? void 0 : s.name) || (s == null ? void 0 : s.alias) || "Agent 详情",
        open: l,
        onClose: d,
        width: 480,
        footer: S ? e.createElement(
          B,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(A, { onClick: d }, "取消"),
          e.createElement(
            A,
            { type: "primary", loading: Z, onClick: E },
            "注册"
          )
        ) : null
      },
      S ? Be : _t
    ), zt = e.createElement(
      "div",
      { style: { marginBottom: 16 } },
      e.createElement(
        "div",
        {
          style: {
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center"
          }
        },
        e.createElement("h2", { style: { margin: 0 } }, "A2A 远程 Agent"),
        e.createElement(
          B,
          null,
          e.createElement(
            A,
            {
              icon: Oe ? e.createElement(Oe) : null,
              onClick: c,
              loading: u
            },
            "刷新列表"
          ),
          e.createElement(
            A,
            {
              icon: Xe ? e.createElement(Xe) : null,
              onClick: P
            },
            "从阿里云AgentHub导入"
          ),
          e.createElement(
            A,
            {
              type: "primary",
              icon: Ge ? e.createElement(Ge) : null,
              onClick: x
            },
            "注册 Agent"
          )
        )
      ),
      e.createElement(
        "div",
        {
          style: {
            marginTop: 8,
            fontSize: 12,
            color: "#8c8c8c",
            lineHeight: 1.6
          }
        },
        Re ? e.createElement(Re, {
          style: { marginRight: 4, color: "#faad14" }
        }) : null,
        "当前 A2A 功能仅支持 CloudPaw 插件连接阿里云 Skills 门户 Agent，连接其他 Agent 可能存在不兼容问题。"
      )
    ), Ot = u ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(he, { size: "large" })
    ) : o.length === 0 ? e.createElement(xt, {
      description: "暂无注册的远程 A2A Agent"
    }) : e.createElement(
      "div",
      {
        style: {
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 12
        }
      },
      ...o.map(
        (r) => e.createElement(St, {
          key: r.alias || r.url,
          agent: r,
          onClick: () => y(r)
        })
      )
    ), Ae = Se.length > 0, Pt = e.createElement(
      Ye,
      {
        title: Ae ? "导入结果" : "从阿里云AgentHub导入 Agent",
        open: de,
        onCancel: Q,
        closable: !G || Ae,
        maskClosable: !G || Ae,
        width: 800,
        footer: Ae ? e.createElement(
          B,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(
            A,
            { type: "primary", onClick: Q },
            "关闭"
          )
        ) : D.length > 0 ? e.createElement(
          B,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(
            A,
            { onClick: Q },
            "取消"
          ),
          e.createElement(
            A,
            {
              type: "primary",
              loading: G,
              disabled: Y.size === 0,
              onClick: $e
            },
            `确认导入 (${Y.size}/${D.length})`
          )
        ) : null
      },
      // Loading state
      G && D.length === 0 && e.createElement(
        "div",
        {
          style: {
            textAlign: "center",
            padding: 40,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12
          }
        },
        e.createElement(he, { size: "large" }),
        e.createElement(
          "span",
          { style: { fontSize: 13, color: t.colorTextTertiary } },
          "正在从 AgentHub 获取 Agent 列表..."
        )
      ),
      // Agent selection list (hide after import completed)
      !G && !Ae && D.length > 0 && e.createElement(
        "div",
        null,
        // Header bar
        e.createElement(
          "div",
          {
            style: {
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 8,
              fontSize: 12,
              color: t.colorTextTertiary
            }
          },
          e.createElement(
            "span",
            null,
            `共 ${D.length} 个 Agent，已选 ${Y.size} 个`
          ),
          e.createElement(
            B,
            { size: 4 },
            e.createElement(
              A,
              {
                size: "small",
                type: "link",
                style: { padding: 0, height: "auto" },
                onClick: T
              },
              "全选"
            ),
            e.createElement(
              A,
              {
                size: "small",
                type: "link",
                style: { padding: 0, height: "auto" },
                onClick: V
              },
              "取消全选"
            )
          )
        ),
        // Agent list
        e.createElement(
          "div",
          {
            style: {
              display: "flex",
              flexDirection: "column",
              gap: 8,
              maxHeight: 420,
              overflowY: "auto"
            }
          },
          ...D.map((r) => {
            var h;
            const p = Y.has(r.url);
            return e.createElement(
              "div",
              {
                key: r.url,
                style: {
                  display: "flex",
                  gap: 8,
                  padding: 10,
                  border: p ? `1px solid ${t.colorInfo}` : `1px solid ${t.colorBorderSecondary}`,
                  borderRadius: 6,
                  cursor: O.has(r.url) ? "default" : "pointer",
                  background: O.has(r.url) ? t.colorBgLayout : p ? t.colorInfoBg : t.colorBgContainer,
                  transition: "all 0.15s ease",
                  opacity: O.has(r.url) ? 0.7 : 1
                },
                onClick: () => {
                  O.has(r.url) || ge(r.url);
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "div",
                  {
                    style: {
                      fontWeight: 500,
                      fontSize: 13,
                      marginBottom: 2
                    }
                  },
                  r.name || r.url
                ),
                r.description ? e.createElement(
                  "div",
                  {
                    style: {
                      fontSize: 11,
                      color: t.colorTextTertiary,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap"
                    }
                  },
                  r.description
                ) : null,
                ((h = r.skills) == null ? void 0 : h.length) > 0 ? e.createElement(
                  "div",
                  { style: { marginTop: 4 } },
                  ...r.skills.slice(0, 3).map(
                    (se, be) => e.createElement(
                      M,
                      {
                        key: be,
                        color: t.colorInfoHover,
                        style: {
                          fontSize: 10,
                          marginRight: 4,
                          fontWeight: 500
                        }
                      },
                      se.name
                    )
                  ),
                  r.skills.length > 3 ? e.createElement(
                    M,
                    { style: { fontSize: 10 } },
                    `+${r.skills.length - 3}`
                  ) : null
                ) : null
              ),
              O.has(r.url) ? e.createElement(
                M,
                {
                  color: t.colorSuccess,
                  style: {
                    fontWeight: 600,
                    fontSize: 11,
                    flexShrink: 0,
                    padding: "2px 8px",
                    lineHeight: "18px",
                    height: 22,
                    borderRadius: 4
                  }
                },
                "✓ 已导入"
              ) : null
            );
          })
        )
      ),
      // Import results
      Ae && e.createElement(
        "div",
        {
          style: {
            maxHeight: 350,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 6
          }
        },
        ...Se.map(
          (r, p) => e.createElement(
            "div",
            {
              key: p,
              style: {
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 10px",
                borderRadius: 4,
                background: r.success ? t.colorInfoBg : t.colorErrorBg,
                border: r.success ? `1px solid ${t.colorInfo}` : `1px solid ${t.colorErrorBorder}`,
                fontSize: 12
              }
            },
            e.createElement(
              "span",
              {
                style: {
                  color: r.success ? t.colorSuccess : t.colorError,
                  fontSize: 14
                }
              },
              r.success ? "✓" : "✗"
            ),
            e.createElement(
              "span",
              {
                style: {
                  flex: 1,
                  color: r.success ? t.colorText : t.colorError
                }
              },
              r.name,
              r.error ? ` - ${r.error}` : ""
            )
          )
        )
      )
    );
    return e.createElement(
      "div",
      { style: { padding: 24 } },
      zt,
      Ot,
      Rt,
      Pt
    );
  }
  function kt({ data: t }) {
    var ye, O, pe;
    const { token: n } = Je.useToken(), o = e.useRef(null), [i, u] = k({}), g = Ce(() => {
      var x, y, a;
      const c = (a = (y = (x = t == null ? void 0 : t.content) == null ? void 0 : x[0]) == null ? void 0 : y.data) == null ? void 0 : a.arguments;
      if (!c) return null;
      try {
        return JSON.parse(c);
      } catch {
        return null;
      }
    }, [(pe = (O = (ye = t == null ? void 0 : t.content) == null ? void 0 : ye[0]) == null ? void 0 : O.data) == null ? void 0 : pe.arguments]), { toolResult: l, rawErrorText: m } = Ce(() => {
      var x;
      const c = t == null ? void 0 : t.content;
      if (!Array.isArray(c))
        return { toolResult: null, rawErrorText: "" };
      for (const y of c) {
        const a = (x = y == null ? void 0 : y.data) == null ? void 0 : x.output;
        if (!a) continue;
        let f = "";
        if (Array.isArray(a)) {
          const d = a.find(
            (E) => (E == null ? void 0 : E.type) === "text" && (E == null ? void 0 : E.text)
          );
          f = (d == null ? void 0 : d.text) || "";
        } else if (typeof a == "string")
          try {
            const d = JSON.parse(a);
            if (typeof d == "object" && (d != null && d.steps || d != null && d.response_text))
              return { toolResult: d, rawErrorText: "" };
            if (Array.isArray(d)) {
              const E = d.find((w) => (w == null ? void 0 : w.type) === "text" && (w == null ? void 0 : w.text));
              E != null && E.text && (f = E.text);
            }
          } catch {
            f = a;
          }
        if (f)
          try {
            return { toolResult: JSON.parse(f), rawErrorText: "" };
          } catch {
            return { toolResult: null, rawErrorText: f };
          }
      }
      return { toolResult: null, rawErrorText: "" };
    }, [t == null ? void 0 : t.content]), s = (l == null ? void 0 : l.steps) || [], _ = (l == null ? void 0 : l.task_state) || "", S = (l == null ? void 0 : l.error) || "", R = (l == null ? void 0 : l.response_text) || "", Z = (l == null ? void 0 : l.context_id) || "";
    e.useEffect(() => {
      o.current && (o.current.scrollTop = o.current.scrollHeight);
    }, [s.length, R, m]), e.useEffect(() => {
      const c = { ...i };
      let x = !1;
      s.forEach((y, a) => {
        i[a] === void 0 && (y.type === "thinking" && y.done || y.type === "tool_call" && y.status !== "running") && (c[a] = !0, x = !0);
      }), x && u(c);
    }, [s]);
    const ce = (g == null ? void 0 : g.agent_alias) || "", j = (g == null ? void 0 : g.agent_url) || "", W = ce || j || "远程 Agent", J = {
      completed: { color: "#52c41a", text: "已完成" },
      TASK_STATE_COMPLETED: { color: "#52c41a", text: "已完成" },
      failed: { color: "#ff4d4f", text: "失败" },
      TASK_STATE_FAILED: { color: "#ff4d4f", text: "失败" },
      error: { color: "#ff4d4f", text: "出错" },
      canceled: { color: "#faad14", text: "已取消" },
      TASK_STATE_CANCELED: { color: "#faad14", text: "已取消" },
      AWAITING_USER_INPUT: { color: "#1677ff", text: "等待输入" },
      input_required: { color: "#1677ff", text: "等待输入" }
    }, C = (l !== null || !!m) && !(_ === "working" || _ === "TASK_STATE_WORKING");
    let b = "#1677ff", de = "执行中...";
    C && (J[_] ? (b = J[_].color, de = J[_].text) : m ? (b = "#ff4d4f", de = "出错") : (b = "#52c41a", de = "已完成"));
    const we = e.createElement(
      B,
      { size: 6 },
      e.createElement("span", { style: { fontSize: 13 } }, "🔗"),
      e.createElement(
        ie,
        { style: { fontSize: 12, color: "#595959" } },
        `A2A: ${W}`
      ),
      e.createElement(
        M,
        { color: b, style: { fontSize: 11, lineHeight: "18px" } },
        de
      )
    ), G = Z ? e.createElement(
      "div",
      {
        style: {
          fontSize: 10,
          fontFamily: "monospace",
          maxWidth: "100%",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          lineHeight: "16px",
          padding: "2px 8px",
          borderRadius: 4,
          marginBottom: 6,
          background: n.colorBgLayout,
          color: n.colorTextSecondary
        }
      },
      `contextId: ${Z}`
    ) : null, ue = [we, G], D = s.length === 0 && !m && !S, fe = !C && D ? e.createElement(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px",
          marginBottom: 8,
          background: "#f6ffed",
          border: "1px solid #b7eb8f",
          borderRadius: 6
        }
      },
      e.createElement(he, { size: "small" }),
      e.createElement(
        ie,
        { style: { fontSize: 12, color: "#52c41a" } },
        `正在连接 ${W}...`
      )
    ) : null;
    function Y(c) {
      u((x) => ({
        ...x,
        [c]: !x[c]
      }));
    }
    function ee(c, x) {
      const y = !!i[x];
      if (c.type === "thinking") {
        const a = !!c.done, f = a ? "💭" : "🧠", d = a ? "思考完成" : "思考中...", E = e.createElement(
          "div",
          {
            key: `step-${x}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: a ? "pointer" : "default",
              fontSize: 12,
              color: "#8c8c8c"
            },
            onClick: a ? () => Y(x) : void 0
          },
          a && e.createElement(
            "span",
            { style: { fontSize: 10, color: "#bfbfbf" } },
            y ? "▶" : "▼"
          ),
          e.createElement("span", null, f),
          e.createElement("span", null, d),
          !a && e.createElement(he, {
            size: "small",
            style: { marginLeft: 4 }
          })
        );
        return y ? E : e.createElement(
          "div",
          { key: `step-${x}` },
          E,
          e.createElement(
            "div",
            {
              style: {
                marginLeft: 20,
                padding: "4px 8px",
                background: "#fafafa",
                borderRadius: 4,
                fontSize: 12,
                color: "#595959",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: 120,
                overflowY: "auto",
                lineHeight: "1.5"
              }
            },
            c.text || ""
          )
        );
      }
      if (c.type === "tool_call") {
        const a = c.status === "running", f = c.status === "error", d = a ? "⚙️" : f ? "❌" : "✅", E = a ? `正在执行: ${c.name}` : f ? `执行失败: ${c.name}` : `执行完成: ${c.name}`, w = a ? "#1677ff" : f ? "#ff4d4f" : "#52c41a", le = e.createElement(
          "div",
          {
            key: `step-${x}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: a ? "default" : "pointer",
              fontSize: 12,
              color: w
            },
            onClick: a ? void 0 : () => Y(x)
          },
          !a && e.createElement(
            "span",
            { style: { fontSize: 10, color: "#bfbfbf" } },
            y ? "▶" : "▼"
          ),
          e.createElement("span", null, d),
          e.createElement("span", null, E),
          a && e.createElement(he, {
            size: "small",
            style: { marginLeft: 4 }
          })
        );
        return y || !c.desc && !a ? le : e.createElement(
          "div",
          { key: `step-${x}` },
          le,
          c.desc && e.createElement(
            "div",
            {
              style: {
                marginLeft: 20,
                padding: "2px 8px",
                fontSize: 11,
                color: "#8c8c8c"
              }
            },
            c.desc
          )
        );
      }
      return c.type === "text" ? e.createElement(
        "div",
        {
          key: `step-${x}`,
          style: {
            padding: "4px 0",
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6",
            color: "#262626"
          }
        },
        c.text || ""
      ) : null;
    }
    const Se = s.length > 0 ? e.createElement(
      "div",
      {
        ref: o,
        style: {
          background: "#fafafa",
          border: "1px solid #e8e8e8",
          borderRadius: 6,
          padding: "6px 10px",
          maxHeight: 200,
          overflowY: "auto"
        }
      },
      ...s.map(ee)
    ) : null, me = m || S ? e.createElement(
      "div",
      {
        style: {
          background: "#fff2f0",
          border: "1px solid #ffccc7",
          borderRadius: 6,
          padding: "8px 12px",
          fontSize: 12,
          color: "#ff4d4f",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word"
        }
      },
      S ? `错误: ${S}` : m
    ) : null, te = !s.length && R && !m ? e.createElement(
      "div",
      {
        ref: o,
        style: {
          background: "#fafafa",
          border: "1px solid #e8e8e8",
          borderRadius: 6,
          padding: "10px 12px",
          maxHeight: 200,
          overflowY: "auto"
        }
      },
      e.createElement(
        ie,
        {
          style: {
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6"
          }
        },
        R
      )
    ) : null;
    return e.createElement(
      "div",
      {
        style: {
          width: "100%",
          borderRadius: 8,
          border: "1px solid #f0f0f0",
          overflow: "hidden",
          background: "#fff",
          padding: "8px 12px",
          margin: "4px 0"
        }
      },
      e.createElement(
        "div",
        { style: { marginBottom: 6 } },
        ...ue
      ),
      fe,
      Se,
      te,
      me
    );
  }
  const Tt = "__A2A_STREAM_START__", Ct = "A2A_STREAM_START", ve = /* @__PURE__ */ new Set();
  function Le(t) {
    return t ? t.includes(Tt) || t.includes(Ct) : !1;
  }
  function Me(t) {
    var n, o;
    return t.getAttribute("data-msg-id") || t.getAttribute("data-message-id") || ((n = t.closest("[data-msg-id]")) == null ? void 0 : n.getAttribute("data-msg-id")) || ((o = t.closest("[data-message-id]")) == null ? void 0 : o.getAttribute("data-message-id")) || null;
  }
  function vt(t) {
    if (Le(t.innerHTML) || Le(t.textContent))
      return t;
    const n = document.createTreeWalker(
      t,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    for (; n.nextNode(); ) {
      const o = n.currentNode, i = o.nodeType === Node.TEXT_NODE ? o.textContent : o.innerHTML;
      if (Le(i)) {
        const u = o.nodeType === Node.TEXT_NODE ? o.parentElement : o;
        if (u) return u;
      }
    }
    return null;
  }
  async function De(t) {
    var s, _;
    const n = window.QwenPaw;
    if (!(n != null && n.host)) {
      console.warn("[a2a] QwenPaw.host not available");
      return;
    }
    const { getApiUrl: o, getApiToken: i } = n.host, u = o("/a2a/call/stream"), g = i();
    console.log("[a2a] Subscribing to SSE stream:", u);
    const l = document.createElement("div");
    l.style.cssText = "background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px;padding:12px 16px;margin:4px 0;font-size:13px;white-space:pre-wrap;word-break:break-word;color:#262626;min-height:24px;", l.textContent = "正在连接远程 Agent...", t.textContent = "", t.appendChild(l);
    const m = new AbortController();
    try {
      const S = {
        Accept: "text/event-stream"
      };
      g && (S.Authorization = `Bearer ${g}`);
      try {
        const W = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage"), J = (_ = (s = JSON.parse(W || "{}")) == null ? void 0 : s.state) == null ? void 0 : _.selectedAgent;
        J && (S["X-Agent-Id"] = J);
      } catch {
      }
      console.log("[a2a] Fetching SSE with headers:", S);
      const R = await fetch(u, { headers: S, signal: m.signal });
      if (console.log("[a2a] SSE response status:", R.status), !R.ok) {
        const W = await R.text().catch(() => "");
        l.textContent = `SSE 连接失败 (${R.status}): ${W.slice(
          0,
          100
        )}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0";
        return;
      }
      if (!R.body) {
        l.textContent = "SSE 连接失败：无响应体", l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0";
        return;
      }
      const Z = R.body.getReader(), ce = new TextDecoder();
      let j = "";
      for (; ; ) {
        const { done: W, value: J } = await Z.read();
        if (W) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }
        j += ce.decode(J, { stream: !0 });
        const $ = j.split(`
`);
        j = $.pop() || "";
        for (const v of $)
          if (v.startsWith("data: "))
            try {
              const C = JSON.parse(v.slice(6));
              if (console.log("[a2a] SSE event:", C), C.done) {
                C.error && (l.textContent = `错误: ${C.error}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0"), console.log("[a2a] SSE done signal received");
                return;
              }
              typeof C.response_text == "string" && C.response_text && (l.textContent = C.response_text);
            } catch (C) {
              console.warn("[a2a] SSE parse error:", C, "line:", v);
            }
      }
    } catch (S) {
      (S == null ? void 0 : S.name) !== "AbortError" && (console.error("[a2a] SSE subscription error:", S), l.textContent = `连接出错: ${(S == null ? void 0 : S.message) || S}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0");
    }
  }
  function It() {
    console.log("[a2a] Initializing stream interceptor");
    function t(u) {
      if (u.nodeType !== Node.ELEMENT_NODE) return;
      const g = u, l = Me(g);
      if (l && ve.has(l)) return;
      const m = vt(g);
      m && (console.log("[a2a] Marker detected in DOM, msgId:", l), l && ve.add(l), De(m));
    }
    new MutationObserver((u) => {
      for (const g of u) {
        for (const l of g.addedNodes)
          t(l);
        g.target.nodeType === Node.ELEMENT_NODE && t(g.target);
      }
    }).observe(document.body, {
      childList: !0,
      subtree: !0,
      characterData: !0,
      characterDataOldValue: !0
    });
    const o = setInterval(() => {
      const u = document.evaluate(
        "//text()[contains(., 'A2A_STREAM_START')]",
        document.body,
        null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
        null
      );
      for (let g = 0; g < u.snapshotLength; g++) {
        const m = u.snapshotItem(g).parentElement;
        if (m) {
          const s = Me(m);
          if (s && ve.has(s)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", s), s && ve.add(s), De(m);
        }
      }
    }, 500);
    window.addEventListener("beforeunload", () => clearInterval(o));
    const i = document.evaluate(
      "//text()[contains(., 'A2A_STREAM_START')]",
      document.body,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null
    );
    for (let u = 0; u < i.snapshotLength; u++) {
      const l = i.snapshotItem(u).parentElement;
      if (l) {
        const m = Me(l);
        m && ve.add(m), console.log("[a2a] Marker found in existing DOM, msgId:", m), De(l);
      }
    }
  }
  (tt = (et = window.QwenPaw).registerToolRender) == null || tt.call(et, "cloudpaw", {
    proposal_choice: ht,
    a2a_call: kt
  }), (rt = (nt = window.QwenPaw).registerRoutes) == null || rt.call(nt, "cloudpaw", [
    {
      path: "/a2a",
      component: bt,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), Lt(), Mt(), It();
}
function Lt() {
  const e = "qwenpaw-last-used-agent", N = "qwenpaw-agent-storage", U = "cloudpaw-first-install", q = "cloud-orchestrator";
  if (localStorage.getItem(U)) return;
  localStorage.setItem(U, "true");
  function F() {
    localStorage.setItem(e, q);
    try {
      const K = localStorage.getItem(N);
      if (K) {
        const L = JSON.parse(K);
        L.state = L.state || {}, L.state.selectedAgent = q, localStorage.setItem(N, JSON.stringify(L));
      } else
        localStorage.setItem(
          N,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: q,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const K = sessionStorage.getItem(N);
      if (K) {
        const L = JSON.parse(K);
        L.state = L.state || {}, L.state.selectedAgent = q, sessionStorage.setItem(N, JSON.stringify(L));
      } else
        sessionStorage.setItem(
          N,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: q,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
  }
  F(), window.addEventListener(
    "beforeunload",
    () => {
      F();
    },
    { once: !0 }
  ), console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
  ), window.location.reload();
}
function Mt() {
  var B;
  const e = (B = window.QwenPaw) == null ? void 0 : B.modules;
  if (!e) return;
  const N = e["Chat/OptionsPanel/defaultConfig"];
  if (!(N != null && N.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const U = N.configProvider, q = U.getConfig.bind(U), F = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", K = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, L = {
    zh: `告诉 CloudPaw 你想做什么，它会自动帮你完成云资源管理、基础设施编排与应用创建上云等任务。
⚠️ 使用前请在左上角下拉框切换到「CloudPaw-Master」，否则功能无法正常使用！
对于复杂的长程任务，建议使用 /mission 命令启动 Mission Mode 来自动拆解和执行。`,
    en: `Tell CloudPaw what you want to do — it will automatically handle cloud resource management, infrastructure orchestration, and application deployment.
⚠️ Please switch to 'CloudPaw-Master' from the dropdown in the top-left corner before use — features won't work otherwise!
For complex, multi-step tasks, use /mission to start Mission Mode for automated decomposition and execution.`,
    ja: `CloudPaw にやりたいことを伝えるだけで、クラウドリソース管理、インフラ構成、アプリケーションのデプロイなどを自動で行います。
⚠️ 使用前に左上のドロップダウンから「CloudPaw-Master」に切り替えてください。切り替えないと機能が正常に動作しません！
複雑なタスクには /mission コマンドで Mission Mode を起動し、自動分解・実行できます。`,
    ru: `Расскажите CloudPaw, что вы хотите сделать — он автоматически выполнит управление облачными ресурсами, оркестрацию инфраструктуры и развёртывание приложений.
⚠️ Перед началом переключитесь на 'CloudPaw-Master' в выпадающем списке в левом верхнем углу — иначе функции не будут работать!
Для сложных задач используйте /mission для автоматической декомпозиции и выполнения.`
  }, M = {
    zh: [
      {
        label: "创建个人主页并部署到云端",
        value: "/mission 帮我创建一个个人主页并上线到云端。页面包含：个人介绍、技能展示、项目经历、联系方式，所有个人信息请先用占位符代替。风格简洁清爽，适配手机和电脑。请使用阿里云 ECS 部署。"
      },
      {
        label: "快速发布 API 服务到云端",
        value: "/mission 帮我把一个 API 服务快速发布到云端。我希望默认提供 /health 和 /hello 两个接口，并给我可直接调用的地址和示例请求，配置尽量简单清晰。"
      }
    ],
    en: [
      {
        label: "Create a personal homepage and deploy to the cloud",
        value: "/mission Help me create a personal homepage and deploy it to the cloud. The page should include: personal introduction, skills, project experience, and contact info — please use placeholders for all personal information. The style should be clean and minimal, responsive for mobile and desktop. Please deploy using Alibaba Cloud ECS."
      },
      {
        label: "Deploy an API service to the cloud",
        value: "/mission Help me quickly deploy an API service to the cloud. I want it to provide /health and /hello endpoints by default, and give me a callable URL with example requests. Keep the configuration as simple and clean as possible."
      }
    ]
  };
  function ke() {
    const A = localStorage.getItem("language") || "";
    return A ? A.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (U.getGreeting = () => K[ke()] || K.en, U.getDescription = () => L[ke()] || L.en, U.getPrompts = () => M[ke()] || M.en, U.getConfig = function(A) {
    var Te;
    const X = q(A);
    return {
      ...X,
      theme: {
        ...X.theme,
        leftHeader: {
          ...(Te = X.theme) == null ? void 0 : Te.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...X.welcome,
        avatar: F
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const A = document.createElement("style");
    A.id = "cloudpaw-welcome-style", A.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(A);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
Nt();
