async function Wt() {
  var at, it, ct, dt;
  const { React: e, antd: K, antdIcons: Q, getApiUrl: z, getApiToken: q } = window.QwenPaw.host, {
    Card: Ee,
    Table: ue,
    Tag: T,
    Typography: W,
    Space: D,
    Button: O,
    Input: J,
    Radio: fe,
    Collapse: Le,
    Descriptions: le,
    Tooltip: Ue,
    Spin: xe,
    message: Ke,
    theme: Ye
  } = K, { Text: X } = W, { TextArea: mt } = J, { useState: C, useMemo: we, useCallback: R, useRef: Ut } = e, {
    InfoCircleOutlined: Re,
    DownOutlined: qe,
    RightOutlined: pt,
    CheckCircleOutlined: ze,
    FieldTimeOutlined: Oe,
    FileTextOutlined: Xe
  } = Q || {};
  function Ge(t) {
    var i, d;
    const n = (d = (i = t == null ? void 0 : t.content) == null ? void 0 : i[0]) == null ? void 0 : d.data, o = n == null ? void 0 : n.arguments;
    if (typeof o == "string")
      try {
        return JSON.parse(o);
      } catch {
        return {};
      }
    return o ?? {};
  }
  function gt() {
    return window.currentSessionId ?? null;
  }
  function se(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function yt(t) {
    if (t == null) return !0;
    const n = se(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function ht(t, n) {
    try {
      const o = q(), i = {
        "Content-Type": "application/json"
      };
      return o && (i.Authorization = `Bearer ${o}`), (await fetch(z("/interaction"), {
        method: "POST",
        headers: i,
        body: JSON.stringify({ session_id: t, result: n })
      })).ok;
    } catch {
      return !1;
    }
  }
  function Qe(t) {
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
        if (typeof n == "object" && n !== null)
          return JSON.stringify(n);
      } catch {
        return t;
      }
    if (Array.isArray(t)) {
      const n = t.find((o) => (o == null ? void 0 : o.type) === "text" && (o == null ? void 0 : o.text));
      return (n == null ? void 0 : n.text) ?? null;
    }
    return typeof t == "object" ? JSON.stringify(t) : null;
  }
  function Et(t) {
    var l, c;
    if (!t || t.length < 2) return null;
    const n = (c = (l = t[1]) == null ? void 0 : l.data) == null ? void 0 : c.output, o = Qe(n);
    if (!o) return null;
    if (o.startsWith("Error:")) return o;
    const i = o.match(/^用户选择了「(.+?)」并确认部署$/);
    if (i) return `已确认部署「${i[1]}」`;
    const d = o.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/
    );
    if (d)
      return `已选择「${d[1]}」并调整：${d[2]}`;
    if (o === "用户确认部署") return "已确认部署";
    const g = o.match(/^用户要求调整资源[：:](.+)$/);
    return g ? `已反馈调整意见：${g[1]}` : "已确认";
  }
  const Ve = [
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
  ], xt = new Set(
    Ve.map((t) => t.toLowerCase())
  );
  function De(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = se(t[0]).trim().toLowerCase();
    return xt.has(n);
  }
  function Ze(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = se(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function wt(t) {
    const n = [];
    let o = [];
    for (const i of t)
      o.push(i), Ze(i) && (n.push(o), o = []);
    return o.length > 0 && (n.length > 0 ? n[n.length - 1].push(...o) : n.push(o)), n.length > 0 ? n : [t];
  }
  function St(t) {
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
  function At({ data: t }) {
    var ye, p, b;
    const [n, o] = C("confirm"), [i, d] = C(""), [g, l] = C(!1), [c, s] = C(null), [I, A] = C(
      {}
    ), _ = e.useRef(!1), F = e.useRef(null), [, te] = C(0), B = t == null ? void 0 : t.content, H = B && B.length >= 2 && ((p = (ye = B[1]) == null ? void 0 : ye.data) == null ? void 0 : p.output), j = we(
      () => Et(B),
      [B]
    ), P = _.current || H || j !== null, f = we(() => {
      const E = Ge(t), a = E == null ? void 0 : E.data;
      if (!a) return null;
      try {
        const y = typeof a == "string" ? JSON.parse(a) : a;
        let u;
        if (E.strategy_names)
          try {
            const N = typeof E.strategy_names == "string" ? JSON.parse(E.strategy_names) : E.strategy_names;
            u = Array.isArray(N) ? N : [];
          } catch {
            u = [];
          }
        else y != null && y.proposal_names ? u = y.proposal_names : u = [];
        const S = u.length >= 2 ? u.length : 0;
        let k;
        if (Array.isArray(y) && y.length > 0)
          if (Array.isArray(y[0]) && y[0].length === 10 && !Array.isArray(y[0][0])) {
            const L = y.filter(
              (oe) => !De(oe)
            );
            if (L.filter(
              (oe) => Ze(oe)
            ).length >= 2)
              k = wt(L);
            else if (S >= 2 && L.length >= S * 2) {
              const oe = Math.ceil(L.length / S);
              k = [];
              for (let he = 0; he < L.length; he += oe)
                k.push(L.slice(he, he + oe));
            } else
              k = [L];
          } else
            k = y.map(
              (L) => L.filter(
                (Z) => Array.isArray(Z) && Z.length === 10 && !De(Z)
              )
            );
        else if (y != null && y.proposals)
          k = y.proposals.map(
            (N) => N.filter((L) => !De(L))
          );
        else
          return null;
        if (k = k.filter((N) => N.length > 0), k.length === 0) return null;
        const ce = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (u.length < k.length)
          for (let N = u.length; N < k.length; N++)
            u.push(ce[N] || `方案${N + 1}`);
        return { proposals: k, names: u };
      } catch {
        return null;
      }
    }, [t]), x = gt(), m = (((b = f == null ? void 0 : f.proposals) == null ? void 0 : b.length) ?? 0) > 1, $ = R(async () => {
      if (!x || P || !f) return;
      const E = m ? c : 0, a = f.names[E ?? 0] || `方案${(E ?? 0) + 1}`;
      let y;
      n === "confirm" ? y = `用户选择了「${a}」并确认部署` : y = `用户选择「${a}」并要求调整：${i.trim() || "未填写具体要求"}`, l(!0);
      const u = await ht(x, y);
      l(!1), u ? (_.current = !0, n === "confirm" ? F.current = `已确认部署「${a}」` : F.current = `已选择「${a}」并调整：${i.trim()}`, te((S) => S + 1), Ke.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : Ke.error("操作失败，请重试");
    }, [
      x,
      P,
      f,
      n,
      i,
      c,
      m
    ]), ie = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created";
    if (!f)
      return ie ? e.createElement(
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
        e.createElement(xe, { size: "default" }),
        e.createElement(
          X,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        Ee,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(X, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: V, names: me } = f, U = Ve.map((E, a) => ({
      title: E,
      dataIndex: `col_${a}`,
      key: `col_${a}`,
      render: (y) => St(y),
      ellipsis: a < 3
    }));
    let pe = "待确认", G = "processing";
    P && (G = "success", pe = F.current || j || "已确认");
    const ne = e.createElement(
      T,
      {
        color: G,
        style: { marginLeft: 4 }
      },
      pe
    ), ke = e.createElement(
      D,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        X,
        { strong: !0, style: { fontSize: 14 } },
        P ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      ne
    ), ge = V.map((E, a) => {
      const y = m ? c === a : !0, u = I[a] || !1, S = (v) => {
        const ee = se(v[0] || "").trim();
        return /^合计|^总计|^total/i.test(ee);
      }, k = E.find(S), ce = E.filter((v) => !S(v)), N = ce.map((v) => ({
        type: se(v[0] || ""),
        purpose: se(v[1] || ""),
        spec: se(v[2] || ""),
        cost: v[9] ?? null
      })), L = k ? se(k[9] ?? "") : "", Z = E.map((v, ee) => {
        const Me = { key: ee };
        return v.forEach((Ie, We) => {
          Me[`col_${We}`] = Ie;
        }), Me;
      }), oe = y ? "2px solid #1677ff" : "1px solid #e8e8e8", he = y ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: a,
          style: {
            flex: 1,
            minWidth: 240,
            border: oe,
            borderRadius: 8,
            cursor: m ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: he,
            background: "#fff"
          },
          onClick: m ? () => s(a) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            X,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            me[a]
          ),
          ...N.map(
            (v, ee) => e.createElement(
              "div",
              {
                key: ee,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: ee < N.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  v.type
                ),
                v.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  v.spec
                )
              ),
              !yt(v.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                se(v.cost)
              )
            )
          ),
          // Total cost
          L && e.createElement(
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
              L
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
              onClick: (v) => {
                v.stopPropagation(), A((ee) => ({
                  ...ee,
                  [a]: !ee[a]
                }));
              }
            },
            e.createElement(
              u && qe ? qe : pt || "span",
              {
                style: { fontSize: 10 }
              }
            ),
            e.createElement(
              "span",
              null,
              `明细 · ${ce.length} 项`
            )
          ),
          u && e.createElement(
            "div",
            {
              onClick: (v) => v.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(ue, {
              columns: U,
              dataSource: Z,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), re = e.createElement(
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
    ), Se = !P && x && !(m && c === null) && e.createElement(
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
          e.createElement(fe, { checked: n === "confirm" }),
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
            e.createElement(fe, { checked: n === "adjust" }),
            e.createElement(
              "span",
              { style: { fontSize: 13 } },
              "调整资源"
            )
          ),
          n === "adjust" && e.createElement(mt, {
            value: i,
            onChange: (E) => d(E.target.value),
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
          X,
          { type: "secondary", style: { fontSize: 11 } },
          m ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          O,
          {
            type: "primary",
            size: "small",
            loading: g,
            onClick: $,
            disabled: n === "adjust" && !i.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), M = m && c === null && !P && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, ke),
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
        ...ge
      ),
      M,
      re,
      !P && Se
    );
  }
  function bt({ data: t }) {
    if (!t || !(t != null && t.content) || !Array.isArray(t == null ? void 0 : t.content))
      return null;
    const [n, o] = C(null), [i, d] = C(!1), g = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", l = we(() => {
      const f = Ge(t);
      return (f == null ? void 0 : f.loop_dir) || null;
    }, [t]), c = we(() => {
      var m, $, ie;
      const f = (ie = ($ = (m = t == null ? void 0 : t.content) == null ? void 0 : m[1]) == null ? void 0 : $.data) == null ? void 0 : ie.output;
      if (!f) return null;
      const x = Qe(f);
      if (!x) return null;
      try {
        return JSON.parse(x);
      } catch {
        return null;
      }
    }, [t]), s = (c == null ? void 0 : c.status) === "ok", I = (c == null ? void 0 : c.status) === "error", A = I ? (c == null ? void 0 : c.message) || "未知错误" : null, _ = R(async () => {
      if (l)
        try {
          const f = q(), x = {};
          f && (x.Authorization = `Bearer ${f}`);
          const m = await fetch(
            z(`/prd?loop_dir=${encodeURIComponent(l)}`),
            { headers: x }
          );
          if (!m.ok) {
            d(!0);
            return;
          }
          const $ = await m.json();
          $ && Array.isArray($.userStories) ? (o($), d(!1)) : d(!0);
        } catch {
          d(!0);
        }
    }, [l]);
    if (e.useEffect(() => {
      !g && s && l && _();
    }, [g, s, l, _]), g)
      return e.createElement(
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
        e.createElement(xe, { size: "default" }),
        e.createElement(
          X,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD..."
        )
      );
    if (I)
      return e.createElement(
        "div",
        {
          style: {
            width: "100%",
            borderRadius: 10,
            border: "1px solid #fff1f0",
            background: "#fff1f0",
            padding: "12px 16px",
            margin: "4px 0",
            display: "flex",
            alignItems: "center",
            gap: 8
          }
        },
        e.createElement(
          X,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${A}`
        )
      );
    if (!s || i || !n) return null;
    const F = n.userStories, te = [...F].sort(
      (f, x) => (f.priority || 99) - (x.priority || 99)
    ), B = F.filter((f) => f.passes).length, H = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (f, x) => {
          if (x.passes) {
            const $ = ze ? e.createElement(ze, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(Ue, { title: "已完成" }, $);
          }
          const m = Oe ? e.createElement(Oe, {
            style: { color: "#faad14", fontSize: 18 }
          }) : "🕐";
          return e.createElement(Ue, { title: "待处理" }, m);
        }
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (f) => e.createElement(T, { color: "blue" }, f)
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (f) => e.createElement(X, { strong: !0 }, f)
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (f, x) => {
          const m = x.priority;
          return e.createElement(
            T,
            { color: "default" },
            m != null ? String(m) : "-"
          );
        }
      },
      {
        title: "描述",
        dataIndex: "description",
        key: "description",
        ellipsis: !0
      },
      {
        title: "验收标准",
        key: "acceptance",
        width: 200,
        render: (f, x) => {
          const m = x.acceptanceCriteria;
          return typeof m == "string" ? e.createElement(
            "div",
            {
              style: { fontSize: 12, color: "#666", whiteSpace: "pre-wrap" }
            },
            m.length > 100 ? m.slice(0, 100) + "..." : m
          ) : Array.isArray(m) ? e.createElement(
            "div",
            { style: { fontSize: 12, color: "#666" } },
            m.length > 2 ? m.slice(0, 2).join(", ") + "..." : m.join(", ")
          ) : "-";
        }
      }
    ], j = e.createElement(
      D,
      { size: 8 },
      Xe ? e.createElement(Xe, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(X, { strong: !0 }, n.project || "PRD")
      )
    ), P = e.createElement(ue, {
      columns: H,
      dataSource: te.map((f) => ({ ...f, key: f.id })),
      size: "small",
      pagination: !1,
      scroll: { x: "max-content" },
      style: { marginBottom: 4 }
    });
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
      e.createElement("div", { style: { marginBottom: 8 } }, j),
      e.createElement(le, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: !1,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${B}/${F.length} 完成`
          }
        ]
      }),
      P,
      e.createElement(
        "div",
        {
          style: {
            fontSize: 11,
            color: "#8c8c8c",
            display: "flex",
            alignItems: "center",
            gap: 8
          }
        },
        ze ? e.createElement(ze, {
          style: { color: "#52c41a", fontSize: 14 }
        }) : "✅",
        e.createElement("span", null, "已完成"),
        e.createElement("span", { style: { margin: "0 4px" } }, "·"),
        Oe ? e.createElement(Oe, {
          style: { color: "#faad14", fontSize: 14 }
        }) : "🕐",
        e.createElement("span", null, "待处理")
      )
    );
  }
  const {
    Form: ae,
    Select: Pe,
    Drawer: kt,
    Modal: et,
    Empty: Ct,
    Badge: tt,
    Divider: Tt,
    message: Y
  } = K, {
    ApiOutlined: nt,
    PlusOutlined: rt,
    ReloadOutlined: $e,
    DeleteOutlined: ot,
    LinkOutlined: lt,
    DisconnectOutlined: Kt
  } = Q || {}, { useEffect: st } = e, Ae = "/a2a/agents";
  function Ne() {
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
  async function be(t, n) {
    const o = z(t), i = q == null ? void 0 : q(), d = Ne(), g = {
      "Content-Type": "application/json",
      ...i ? { Authorization: `Bearer ${i}` } : {},
      ...d ? { "X-Agent-Id": d } : {}
    }, l = await fetch(o, {
      ...n,
      headers: { ...g, ...(n == null ? void 0 : n.headers) || {} }
    });
    if (!l.ok) {
      const c = await l.text().catch(() => "");
      throw new Error(c || `HTTP ${l.status}`);
    }
    return l.status === 204 || l.headers.get("content-length") === "0" ? null : l.json();
  }
  function vt(t) {
    var c;
    const { agent: n, onClick: o } = t, i = n.status === "connected", d = i ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", g = i ? "已连接" : n.status === "error" ? "错误" : "未连接", l = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      Ee,
      {
        hoverable: !0,
        onClick: o,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          D,
          null,
          e.createElement(tt, { color: d }),
          e.createElement(
            "span",
            null,
            n.alias || n.name || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          T,
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
          lt ? e.createElement(lt, { style: { marginRight: 4 } }) : null,
          n.url
        ),
        n.description ? e.createElement(
          "div",
          { style: { marginBottom: 4, color: "#999" } },
          n.description
        ) : null,
        ((c = n.skills) == null ? void 0 : c.length) > 0 ? e.createElement(
          "div",
          null,
          n.skills.slice(0, 3).map(
            (s, I) => e.createElement(
              T,
              { key: I, style: { fontSize: 11 } },
              s.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            T,
            { style: { fontSize: 11 } },
            `+${n.skills.length - 3}`
          ) : null
        ) : null,
        e.createElement(
          "div",
          { style: { marginTop: 4, color: d, fontSize: 11 } },
          g,
          n.error ? ` - ${n.error}` : ""
        )
      )
    );
  }
  function It() {
    const t = e.useRef(Ne()), [n, o] = C(t.current);
    return st(() => {
      const i = () => {
        const g = Ne();
        g !== t.current && (t.current = g, o(g));
      }, d = setInterval(i, 200);
      return window.addEventListener("storage", i), () => {
        clearInterval(d), window.removeEventListener("storage", i);
      };
    }, []), n;
  }
  function _t() {
    var ut, ft;
    const { token: t } = Ye.useToken(), n = It(), [o, i] = C([]), [d, g] = C(!0), [l, c] = C(!1), [s, I] = C(null), [A, _] = C(!1), [F, te] = C(!1), [B, H] = C(!1), [j, P] = C(!1), [f, x] = C(""), [m] = ae.useForm(), [$, ie] = C(!1), [V, me] = C(!1), [U, pe] = C([]), [G, ne] = C(
      /* @__PURE__ */ new Set()
    ), [ke, ge] = C(
      []
    ), re = e.useRef(null), Se = (r) => !r || !r.trim() ? null : /\s/.test(r) ? "别名不能包含空格" : null, M = we(
      () => new Set(o.map((r) => r.url)),
      [o]
    ), ye = e.useRef(M);
    ye.current = M;
    const p = R(async () => {
      g(!0);
      try {
        const r = await be(Ae);
        i((r == null ? void 0 : r.agents) || []);
      } catch {
        i([]);
      } finally {
        g(!1);
      }
    }, []);
    st(() => {
      p();
    }, [n]);
    const b = R(() => {
      _(!0), I(null), c(!0), m.resetFields(), m.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [m]), E = R((r) => {
      _(!1), I(r), c(!0);
    }, []), a = R(() => {
      P(!1), x("");
    }, []), y = R(async () => {
      if (!s || !f.trim()) return;
      const r = Se(f);
      if (r) {
        Y.error(r);
        return;
      }
      const h = s.alias || s.url, w = f.trim();
      if (w === h) {
        a();
        return;
      }
      try {
        const de = await be(
          `${Ae}?alias=${encodeURIComponent(h)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_alias: w })
          }
        );
        Y.success("别名已修改"), P(!1), I(de), await p();
      } catch (de) {
        Y.error(de.message || "修改失败");
      }
    }, [s, f, p, a]), u = R(() => {
      a(), c(!1), I(null), _(!1), m.resetFields();
    }, [a, m]), S = R(async () => {
      let r;
      try {
        r = await m.validateFields();
      } catch {
        return;
      }
      const h = {
        url: String(r.url || "").trim(),
        alias: String(r.alias || "").trim() || void 0,
        auth_type: String(r.auth_type || ""),
        auth_token: String(r.auth_token || "")
      };
      if (h.url) {
        te(!0);
        try {
          await be(Ae, {
            method: "POST",
            body: JSON.stringify(h)
          }), Y.success("A2A Agent 注册成功"), await p(), u();
        } catch (w) {
          Y.error(w.message || "注册失败");
        } finally {
          te(!1);
        }
      }
    }, [m, p, u]), k = R(async () => {
      if (!s) return;
      const r = s.alias || s.url, h = s.name || r;
      et.confirm({
        title: "确认删除",
        content: `确定删除 A2A Agent「${h}」吗？此操作不可撤销。`,
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await be(`${Ae}?alias=${encodeURIComponent(r)}`, {
              method: "DELETE"
            }), Y.success(`已删除 A2A Agent「${h}」`), await p(), u();
          } catch (w) {
            Y.error(w.message || "删除失败");
          }
        }
      });
    }, [s, p, u]), ce = R(async () => {
      if (!s) return;
      const r = s.alias || s.url;
      H(!0);
      try {
        const h = await be(
          `${Ae}/refresh?alias=${encodeURIComponent(r)}`,
          {
            method: "POST"
          }
        );
        Y.success("Agent Card 已刷新"), await p(), h && I(h);
      } catch (h) {
        Y.error(h.message || "刷新失败");
      } finally {
        H(!1);
      }
    }, [s, p]), N = R(() => {
      s && (x(s.alias || ""), P(!0));
    }, [s]), L = R(() => {
      ie(!0), pe([]), ne(/* @__PURE__ */ new Set()), ge([]), re.current = null, oe();
    }, []), Z = R(() => {
      V && re.current && re.current.abort(), ie(!1), pe([]), ne(/* @__PURE__ */ new Set()), ge([]), re.current = null;
    }, [V]), oe = R(async () => {
      me(!0);
      const r = new AbortController();
      re.current = r;
      try {
        const h = q == null ? void 0 : q(), w = Ne(), de = {
          ...h ? { Authorization: `Bearer ${h}` } : {},
          ...w ? { "X-Agent-Id": w } : {}
        }, Te = await fetch(z("/a2a/import"), {
          method: "GET",
          headers: de,
          signal: r.signal
        });
        if (!Te.ok) {
          const _e = await Te.text().catch(() => "");
          throw new Error(_e || `HTTP ${Te.status}`);
        }
        const Je = await Te.json(), Fe = (Je == null ? void 0 : Je.agents) || [];
        if (Fe.length === 0) {
          Y.warning("未找到可用的 Agent");
          return;
        }
        pe(Fe);
        const jt = ye.current;
        ne(
          new Set(
            Fe.filter((_e) => !jt.has(_e.url)).map((_e) => _e.url)
          )
        );
      } catch (h) {
        if ((h == null ? void 0 : h.name) === "AbortError") return;
        Y.error(h.message || "获取 Agent 列表失败");
      } finally {
        me(!1), re.current = null;
      }
    }, []), he = R((r) => {
      ne((h) => {
        const w = new Set(h);
        return w.has(r) ? w.delete(r) : w.add(r), w;
      });
    }, []), v = R(() => {
      ne(
        new Set(
          U.filter((r) => !M.has(r.url)).map((r) => r.url)
        )
      );
    }, [U, M]), ee = R(() => {
      ne(/* @__PURE__ */ new Set());
    }, []), Me = R(async () => {
      const r = U.filter(
        (w) => G.has(w.url) && !M.has(w.url)
      );
      if (r.length === 0) {
        Y.warning("请至少选择一个 Agent");
        return;
      }
      me(!0), ge([]);
      const h = [];
      for (const w of r) {
        try {
          await be(Ae, {
            method: "POST",
            body: JSON.stringify({
              url: w.url,
              alias: w.name || void 0,
              auth_type: w.auth_type || "gateway",
              auth_token: ""
            })
          }), h.push({ name: w.name || w.url, success: !0 });
        } catch (de) {
          h.push({
            name: w.name || w.url,
            success: !1,
            error: de.message || "注册失败"
          });
        }
        ge([...h]);
      }
      await p(), Y.success(
        `导入完成：成功 ${h.filter((w) => w.success).length} 个，失败 ${h.filter((w) => !w.success).length} 个`
      ), me(!1), setTimeout(() => Z(), 800);
    }, [U, G, p, M]), Ie = ((ut = ae.useWatch) == null ? void 0 : ut.call(ae, "auth_type", m)) ?? "", We = e.createElement(
      ae,
      { form: m, layout: "vertical" },
      e.createElement(
        ae.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: !0, message: "请输入 Agent URL" }]
        },
        e.createElement(J, {
          placeholder: "https://agent.example.com"
        })
      ),
      e.createElement(
        ae.Item,
        {
          name: "alias",
          label: "别名",
          rules: [
            {
              validator: (r, h) => {
                const w = Se(h);
                return w ? Promise.reject(new Error(w)) : Promise.resolve();
              }
            }
          ]
        },
        e.createElement(J, {
          placeholder: "输入别名（可选，仅小写字母、数字和连字符）"
        })
      ),
      e.createElement(
        ae.Item,
        { name: "auth_type", label: "认证类型" },
        e.createElement(
          Pe,
          { allowClear: !0, placeholder: "无认证" },
          e.createElement(
            Pe.Option,
            { value: "bearer" },
            "Bearer Token"
          ),
          e.createElement(Pe.Option, { value: "api_key" }, "API Key"),
          e.createElement(
            Pe.Option,
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
        ae.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(J.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), Mt = s ? e.createElement(
      "div",
      null,
      e.createElement(
        le,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          le.Item,
          { label: "URL" },
          s.url
        ),
        e.createElement(
          le.Item,
          { label: "别名" },
          j ? e.createElement(
            "div",
            {
              style: { display: "flex", alignItems: "center", gap: 6 }
            },
            e.createElement(J, {
              value: f,
              onChange: (r) => x(r.target.value),
              onPressEnter: y,
              autoFocus: !0,
              placeholder: "输入新别名",
              size: "small",
              style: { flex: 1 }
            }),
            e.createElement(
              O,
              {
                type: "link",
                size: "small",
                onClick: y,
                disabled: !f.trim(),
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
                onClick: N
              },
              "修改"
            )
          )
        ),
        e.createElement(
          le.Item,
          { label: "Agent 名称" },
          s.name || "-"
        ),
        e.createElement(
          le.Item,
          { label: "状态" },
          e.createElement(tt, {
            color: s.status === "connected" ? "#52c41a" : s.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: s.status === "connected" ? "已连接" : s.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          le.Item,
          { label: "认证类型" },
          s.auth_type ? e.createElement(
            T,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[s.auth_type] || s.auth_type
          ) : "无认证"
        ),
        e.createElement(
          le.Item,
          { label: "描述" },
          s.description || "-"
        ),
        e.createElement(
          le.Item,
          { label: "版本" },
          s.version || "-"
        )
      ),
      ((ft = s.skills) == null ? void 0 : ft.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...s.skills.map(
          (r, h) => e.createElement(
            Ee,
            { key: h, size: "small", style: { marginBottom: 8 } },
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
          D,
          null,
          e.createElement(
            T,
            {
              color: s.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            T,
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
      e.createElement(Tt, null),
      e.createElement(
        D,
        null,
        e.createElement(
          O,
          {
            type: "primary",
            icon: $e ? e.createElement($e) : null,
            loading: B,
            onClick: ce
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          O,
          {
            danger: !0,
            icon: ot ? e.createElement(ot) : null,
            onClick: k
          },
          "删除"
        )
      )
    ) : null, Lt = e.createElement(
      kt,
      {
        title: A ? "注册远程 A2A Agent" : (s == null ? void 0 : s.name) || (s == null ? void 0 : s.alias) || "Agent 详情",
        open: l,
        onClose: u,
        width: 480,
        footer: A ? e.createElement(
          D,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(O, { onClick: u }, "取消"),
          e.createElement(
            O,
            { type: "primary", loading: F, onClick: S },
            "注册"
          )
        ) : null
      },
      A ? We : Mt
    ), Dt = e.createElement(
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
          D,
          null,
          e.createElement(
            O,
            {
              icon: $e ? e.createElement($e) : null,
              onClick: p,
              loading: d
            },
            "刷新列表"
          ),
          e.createElement(
            O,
            {
              icon: nt ? e.createElement(nt) : null,
              onClick: L
            },
            "从阿里云AgentHub导入"
          ),
          e.createElement(
            O,
            {
              type: "primary",
              icon: rt ? e.createElement(rt) : null,
              onClick: b
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
    ), Bt = d ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(xe, { size: "large" })
    ) : o.length === 0 ? e.createElement(Ct, {
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
        (r) => e.createElement(vt, {
          key: r.alias || r.url,
          agent: r,
          onClick: () => E(r)
        })
      )
    ), Ce = ke.length > 0, Ht = e.createElement(
      et,
      {
        title: Ce ? "导入结果" : "从阿里云AgentHub导入 Agent",
        open: $,
        onCancel: Z,
        closable: !V || Ce,
        maskClosable: !V || Ce,
        width: 800,
        footer: Ce ? e.createElement(
          D,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(
            O,
            { type: "primary", onClick: Z },
            "关闭"
          )
        ) : U.length > 0 ? e.createElement(
          D,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(
            O,
            { onClick: Z },
            "取消"
          ),
          e.createElement(
            O,
            {
              type: "primary",
              loading: V,
              disabled: G.size === 0,
              onClick: Me
            },
            `确认导入 (${G.size}/${U.length})`
          )
        ) : null
      },
      // Loading state
      V && U.length === 0 && e.createElement(
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
        e.createElement(xe, { size: "large" }),
        e.createElement(
          "span",
          { style: { fontSize: 13, color: t.colorTextTertiary } },
          "正在从 AgentHub 获取 Agent 列表..."
        )
      ),
      // Agent selection list (hide after import completed)
      !V && !Ce && U.length > 0 && e.createElement(
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
            `共 ${U.length} 个 Agent，已选 ${G.size} 个`
          ),
          e.createElement(
            D,
            { size: 4 },
            e.createElement(
              O,
              {
                size: "small",
                type: "link",
                style: { padding: 0, height: "auto" },
                onClick: v
              },
              "全选"
            ),
            e.createElement(
              O,
              {
                size: "small",
                type: "link",
                style: { padding: 0, height: "auto" },
                onClick: ee
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
          ...U.map((r) => {
            var w;
            const h = G.has(r.url);
            return e.createElement(
              "div",
              {
                key: r.url,
                style: {
                  display: "flex",
                  gap: 8,
                  padding: 10,
                  border: h ? `1px solid ${t.colorInfo}` : `1px solid ${t.colorBorderSecondary}`,
                  borderRadius: 6,
                  cursor: M.has(r.url) ? "default" : "pointer",
                  background: M.has(r.url) ? t.colorBgLayout : h ? t.colorInfoBg : t.colorBgContainer,
                  transition: "all 0.15s ease",
                  opacity: M.has(r.url) ? 0.7 : 1
                },
                onClick: () => {
                  M.has(r.url) || he(r.url);
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
                ((w = r.skills) == null ? void 0 : w.length) > 0 ? e.createElement(
                  "div",
                  { style: { marginTop: 4 } },
                  ...r.skills.slice(0, 3).map(
                    (de, Te) => e.createElement(
                      T,
                      {
                        key: Te,
                        color: t.colorInfoHover,
                        style: {
                          fontSize: 10,
                          marginRight: 4,
                          fontWeight: 500
                        }
                      },
                      de.name
                    )
                  ),
                  r.skills.length > 3 ? e.createElement(
                    T,
                    { style: { fontSize: 10 } },
                    `+${r.skills.length - 3}`
                  ) : null
                ) : null
              ),
              M.has(r.url) ? e.createElement(
                T,
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
      Ce && e.createElement(
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
        ...ke.map(
          (r, h) => e.createElement(
            "div",
            {
              key: h,
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
      Dt,
      Bt,
      Lt,
      Ht
    );
  }
  function Rt(t) {
    if (!t) return null;
    for (let n = t.lastIndexOf("{"); n >= 0; n = t.lastIndexOf("{", n - 1))
      try {
        return JSON.parse(t.substring(n));
      } catch {
        continue;
      }
    return null;
  }
  function zt({ data: t }) {
    var Se, M, ye;
    const { token: n } = Ye.useToken(), o = e.useRef(null), [i, d] = C({}), g = we(() => {
      var b, E, a;
      const p = (a = (E = (b = t == null ? void 0 : t.content) == null ? void 0 : b[0]) == null ? void 0 : E.data) == null ? void 0 : a.arguments;
      if (!p) return null;
      try {
        return JSON.parse(p);
      } catch {
        return null;
      }
    }, [(ye = (M = (Se = t == null ? void 0 : t.content) == null ? void 0 : Se[0]) == null ? void 0 : M.data) == null ? void 0 : ye.arguments]), { toolResult: l, rawErrorText: c } = we(() => {
      var b;
      const p = t == null ? void 0 : t.content;
      if (!Array.isArray(p))
        return { toolResult: null, rawErrorText: "" };
      for (const E of p) {
        const a = (b = E == null ? void 0 : E.data) == null ? void 0 : b.output;
        if (!a) continue;
        let y = "";
        if (Array.isArray(a)) {
          const u = a.find(
            (S) => (S == null ? void 0 : S.type) === "text" && (S == null ? void 0 : S.text)
          );
          y = (u == null ? void 0 : u.text) || "";
        } else if (typeof a == "string")
          try {
            const u = JSON.parse(a);
            if (typeof u == "object" && (u != null && u.steps || u != null && u.response_text))
              return { toolResult: u, rawErrorText: "" };
            if (Array.isArray(u)) {
              const S = u.find((k) => (k == null ? void 0 : k.type) === "text" && (k == null ? void 0 : k.text));
              S != null && S.text && (y = S.text);
            }
          } catch {
            y = a;
          }
        if (y)
          try {
            return { toolResult: JSON.parse(y), rawErrorText: "" };
          } catch {
            const u = Rt(y);
            return u ? { toolResult: u, rawErrorText: "" } : { toolResult: null, rawErrorText: y };
          }
      }
      return { toolResult: null, rawErrorText: "" };
    }, [t == null ? void 0 : t.content]), s = (l == null ? void 0 : l.steps) || [], I = (l == null ? void 0 : l.task_state) || "", A = (l == null ? void 0 : l.error) || "", _ = (l == null ? void 0 : l.response_text) || "", F = (l == null ? void 0 : l.context_id) || "";
    e.useEffect(() => {
      o.current && (o.current.scrollTop = o.current.scrollHeight);
    }, [s.length, _, c]), e.useEffect(() => {
      const p = { ...i };
      let b = !1;
      s.forEach((E, a) => {
        i[a] === void 0 && (E.type === "thinking" && E.done || E.type === "tool_call" && E.status !== "running") && (p[a] = !0, b = !0);
      }), b && d(p);
    }, [s]);
    const te = (g == null ? void 0 : g.agent_alias) || "", B = (g == null ? void 0 : g.agent_url) || "", H = te || B || "远程 Agent", j = {
      completed: { color: "#52c41a", text: "已完成" },
      TASK_STATE_COMPLETED: { color: "#52c41a", text: "已完成" },
      failed: { color: "#ff4d4f", text: "失败" },
      TASK_STATE_FAILED: { color: "#ff4d4f", text: "失败" },
      error: { color: "#ff4d4f", text: "出错" },
      canceled: { color: "#faad14", text: "已取消" },
      TASK_STATE_CANCELED: { color: "#faad14", text: "已取消" },
      AWAITING_USER_INPUT: { color: "#1677ff", text: "等待输入" },
      input_required: { color: "#1677ff", text: "等待输入" }
    }, x = (l !== null || !!c) && !(I === "working" || I === "TASK_STATE_WORKING");
    let m = "#1677ff", $ = "执行中...";
    x && (j[I] ? (m = j[I].color, $ = j[I].text) : c ? (m = "#ff4d4f", $ = "出错") : (m = "#52c41a", $ = "已完成"));
    const ie = e.createElement(
      D,
      { size: 6 },
      e.createElement("span", { style: { fontSize: 13 } }, "🔗"),
      e.createElement(
        X,
        { style: { fontSize: 12, color: "#595959" } },
        `A2A: ${H}`
      ),
      e.createElement(
        T,
        { color: m, style: { fontSize: 11, lineHeight: "18px" } },
        $
      )
    ), V = F ? e.createElement(
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
      `contextId: ${F}`
    ) : null, me = [ie, V], U = s.length === 0 && !c && !A, pe = !x && U ? e.createElement(
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
      e.createElement(xe, { size: "small" }),
      e.createElement(
        X,
        { style: { fontSize: 12, color: "#52c41a" } },
        `正在连接 ${H}...`
      )
    ) : null;
    function G(p) {
      d((b) => ({
        ...b,
        [p]: !b[p]
      }));
    }
    function ne(p, b) {
      const E = !!i[b];
      if (p.type === "thinking") {
        const a = !!p.done, y = a ? "💭" : "🧠", u = a ? "思考完成" : "思考中...", S = e.createElement(
          "div",
          {
            key: `step-${b}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: a ? "pointer" : "default",
              fontSize: 12,
              color: "#8c8c8c"
            },
            onClick: a ? () => G(b) : void 0
          },
          a && e.createElement(
            "span",
            { style: { fontSize: 10, color: "#bfbfbf" } },
            E ? "▶" : "▼"
          ),
          e.createElement("span", null, y),
          e.createElement("span", null, u),
          !a && e.createElement(xe, {
            size: "small",
            style: { marginLeft: 4 }
          })
        );
        return E ? S : e.createElement(
          "div",
          { key: `step-${b}` },
          S,
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
            p.text || ""
          )
        );
      }
      if (p.type === "tool_call") {
        const a = p.status === "running", y = p.status === "error", u = a ? "⚙️" : y ? "❌" : "✅", S = a ? `正在执行: ${p.name}` : y ? `执行失败: ${p.name}` : `执行完成: ${p.name}`, k = a ? "#1677ff" : y ? "#ff4d4f" : "#52c41a", ce = e.createElement(
          "div",
          {
            key: `step-${b}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: a ? "default" : "pointer",
              fontSize: 12,
              color: k
            },
            onClick: a ? void 0 : () => G(b)
          },
          !a && e.createElement(
            "span",
            { style: { fontSize: 10, color: "#bfbfbf" } },
            E ? "▶" : "▼"
          ),
          e.createElement("span", null, u),
          e.createElement("span", null, S),
          a && e.createElement(xe, {
            size: "small",
            style: { marginLeft: 4 }
          })
        );
        return E || !p.desc && !a ? ce : e.createElement(
          "div",
          { key: `step-${b}` },
          ce,
          p.desc && e.createElement(
            "div",
            {
              style: {
                marginLeft: 20,
                padding: "2px 8px",
                fontSize: 11,
                color: "#8c8c8c"
              }
            },
            p.desc
          )
        );
      }
      return p.type === "text" ? e.createElement(
        "div",
        {
          key: `step-${b}`,
          style: {
            padding: "4px 0",
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6",
            color: "#262626"
          }
        },
        p.text || ""
      ) : null;
    }
    const ke = s.length > 0 ? e.createElement(
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
      ...s.map(ne)
    ) : null, ge = c || A ? e.createElement(
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
      A ? `错误: ${A}` : c
    ) : null, re = !s.length && _ && !c ? e.createElement(
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
        X,
        {
          style: {
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6"
          }
        },
        _
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
        ...me
      ),
      pe,
      ke,
      re,
      ge
    );
  }
  const Ot = "__A2A_STREAM_START__", Pt = "A2A_STREAM_START", ve = /* @__PURE__ */ new Set();
  function Be(t) {
    return t ? t.includes(Ot) || t.includes(Pt) : !1;
  }
  function He(t) {
    var n, o;
    return t.getAttribute("data-msg-id") || t.getAttribute("data-message-id") || ((n = t.closest("[data-msg-id]")) == null ? void 0 : n.getAttribute("data-msg-id")) || ((o = t.closest("[data-message-id]")) == null ? void 0 : o.getAttribute("data-message-id")) || null;
  }
  function $t(t) {
    if (Be(t.innerHTML) || Be(t.textContent))
      return t;
    const n = document.createTreeWalker(
      t,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    for (; n.nextNode(); ) {
      const o = n.currentNode, i = o.nodeType === Node.TEXT_NODE ? o.textContent : o.innerHTML;
      if (Be(i)) {
        const d = o.nodeType === Node.TEXT_NODE ? o.parentElement : o;
        if (d) return d;
      }
    }
    return null;
  }
  async function je(t) {
    var s, I;
    const n = window.QwenPaw;
    if (!(n != null && n.host)) {
      console.warn("[a2a] QwenPaw.host not available");
      return;
    }
    const { getApiUrl: o, getApiToken: i } = n.host, d = o("/a2a/call/stream"), g = i();
    console.log("[a2a] Subscribing to SSE stream:", d);
    const l = document.createElement("div");
    l.style.cssText = "background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px;padding:12px 16px;margin:4px 0;font-size:13px;white-space:pre-wrap;word-break:break-word;color:#262626;min-height:24px;", l.textContent = "正在连接远程 Agent...", t.textContent = "", t.appendChild(l);
    const c = new AbortController();
    try {
      const A = {
        Accept: "text/event-stream"
      };
      g && (A.Authorization = `Bearer ${g}`);
      try {
        const H = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage"), j = (I = (s = JSON.parse(H || "{}")) == null ? void 0 : s.state) == null ? void 0 : I.selectedAgent;
        j && (A["X-Agent-Id"] = j);
      } catch {
      }
      console.log("[a2a] Fetching SSE with headers:", A);
      const _ = await fetch(d, { headers: A, signal: c.signal });
      if (console.log("[a2a] SSE response status:", _.status), !_.ok) {
        const H = await _.text().catch(() => "");
        l.textContent = `SSE 连接失败 (${_.status}): ${H.slice(
          0,
          100
        )}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0";
        return;
      }
      if (!_.body) {
        l.textContent = "SSE 连接失败：无响应体", l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0";
        return;
      }
      const F = _.body.getReader(), te = new TextDecoder();
      let B = "";
      for (; ; ) {
        const { done: H, value: j } = await F.read();
        if (H) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }
        B += te.decode(j, { stream: !0 });
        const P = B.split(`
`);
        B = P.pop() || "";
        for (const f of P)
          if (f.startsWith("data: "))
            try {
              const x = JSON.parse(f.slice(6));
              if (console.log("[a2a] SSE event:", x), x.done) {
                x.error && (l.textContent = `错误: ${x.error}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0"), console.log("[a2a] SSE done signal received");
                return;
              }
              typeof x.response_text == "string" && x.response_text && (l.textContent = x.response_text);
            } catch (x) {
              console.warn("[a2a] SSE parse error:", x, "line:", f);
            }
      }
    } catch (A) {
      (A == null ? void 0 : A.name) !== "AbortError" && (console.error("[a2a] SSE subscription error:", A), l.textContent = `连接出错: ${(A == null ? void 0 : A.message) || A}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0");
    }
  }
  function Nt() {
    console.log("[a2a] Initializing stream interceptor");
    function t(d) {
      if (d.nodeType !== Node.ELEMENT_NODE) return;
      const g = d, l = He(g);
      if (l && ve.has(l)) return;
      const c = $t(g);
      c && (console.log("[a2a] Marker detected in DOM, msgId:", l), l && ve.add(l), je(c));
    }
    new MutationObserver((d) => {
      for (const g of d) {
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
      const d = document.evaluate(
        "//text()[contains(., 'A2A_STREAM_START')]",
        document.body,
        null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
        null
      );
      for (let g = 0; g < d.snapshotLength; g++) {
        const c = d.snapshotItem(g).parentElement;
        if (c) {
          const s = He(c);
          if (s && ve.has(s)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", s), s && ve.add(s), je(c);
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
    for (let d = 0; d < i.snapshotLength; d++) {
      const l = i.snapshotItem(d).parentElement;
      if (l) {
        const c = He(l);
        c && ve.add(c), console.log("[a2a] Marker found in existing DOM, msgId:", c), je(l);
      }
    }
  }
  (it = (at = window.QwenPaw).registerToolRender) == null || it.call(at, "cloudpaw", {
    proposal_choice: At,
    manage_prd: bt,
    a2a_call: zt
  }), (dt = (ct = window.QwenPaw).registerRoutes) == null || dt.call(ct, "cloudpaw", [
    {
      path: "/a2a",
      component: _t,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), Jt(), await Ft(), Nt();
}
function Jt() {
  const e = "qwenpaw-last-used-agent", K = "qwenpaw-agent-storage", Q = "cloudpaw-first-install", z = "cloud-orchestrator";
  if (localStorage.getItem(Q)) return;
  const q = localStorage.getItem(e), Ee = localStorage.getItem(K);
  if (q || Ee) {
    localStorage.setItem(Q, "true"), console.info(
      "[cloudpaw] Existing agent selection found — skipping first-install override"
    );
    return;
  }
  localStorage.setItem(Q, "true");
  function ue() {
    localStorage.setItem(e, z);
    try {
      const T = localStorage.getItem(K);
      if (T) {
        const W = JSON.parse(T);
        W.state = W.state || {}, W.state.selectedAgent = z, localStorage.setItem(K, JSON.stringify(W));
      } else
        localStorage.setItem(
          K,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: z,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const T = sessionStorage.getItem(K);
      if (T) {
        const W = JSON.parse(T);
        W.state = W.state || {}, W.state.selectedAgent = z, sessionStorage.setItem(K, JSON.stringify(W));
      } else
        sessionStorage.setItem(
          K,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: z,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
  }
  ue(), window.addEventListener(
    "beforeunload",
    () => {
      ue();
    },
    { once: !0 }
  ), console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
  ), window.location.reload();
}
async function Ft() {
  var O;
  const e = window.QwenPaw;
  if (!e) return;
  const K = "Chat/OptionsPanel/defaultConfig", Q = e.loadModule ? await e.loadModule(K) : (O = e.modules) == null ? void 0 : O[K];
  if (!(Q != null && Q.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const z = Q.configProvider, q = z.getConfig.bind(z), Ee = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", ue = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, T = {
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
  }, W = {
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
  function D() {
    const J = localStorage.getItem("language") || "";
    return J ? J.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (z.getGreeting = () => ue[D()] || ue.en, z.getDescription = () => T[D()] || T.en, z.getPrompts = () => W[D()] || W.en, z.getConfig = function(J) {
    var Le;
    const fe = q(J);
    return {
      ...fe,
      theme: {
        ...fe.theme,
        leftHeader: {
          ...(Le = fe.theme) == null ? void 0 : Le.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...fe.welcome,
        avatar: Ee
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const J = document.createElement("style");
    J.id = "cloudpaw-welcome-style", J.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(J);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
const Yt = Wt();
export {
  Yt as default
};
