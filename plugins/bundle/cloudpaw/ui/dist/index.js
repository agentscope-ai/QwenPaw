function jt() {
  var st, at, it, ct;
  const { React: e, antd: D, antdIcons: U, getApiUrl: Y, getApiToken: q } = window.QwenPaw.host, {
    Card: ue,
    Table: fe,
    Tag: v,
    Typography: M,
    Space: W,
    Button: T,
    Input: Q,
    Radio: Te,
    Collapse: Ft,
    Descriptions: le,
    Tooltip: Fe,
    Spin: Ee,
    message: Ue,
    theme: Ke
  } = D, { Text: X } = M, { TextArea: ft } = Q, { useState: C, useMemo: xe, useCallback: z, useRef: Ut } = e, {
    InfoCircleOutlined: Re,
    DownOutlined: Ye,
    RightOutlined: mt,
    CheckCircleOutlined: ze,
    FieldTimeOutlined: Oe,
    FileTextOutlined: qe
  } = U || {};
  function Xe(t) {
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
  function pt() {
    return window.currentSessionId ?? null;
  }
  function se(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function gt(t) {
    if (t == null) return !0;
    const n = se(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function yt(t, n) {
    try {
      const o = q(), i = {
        "Content-Type": "application/json"
      };
      return o && (i.Authorization = `Bearer ${o}`), (await fetch(Y("/interaction"), {
        method: "POST",
        headers: i,
        body: JSON.stringify({ session_id: t, result: n })
      })).ok;
    } catch {
      return !1;
    }
  }
  function Ge(t) {
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
  function ht(t) {
    var l, c;
    if (!t || t.length < 2) return null;
    const n = (c = (l = t[1]) == null ? void 0 : l.data) == null ? void 0 : c.output, o = Ge(n);
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
  const Qe = [
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
  ], Et = new Set(
    Qe.map((t) => t.toLowerCase())
  );
  function De(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = se(t[0]).trim().toLowerCase();
    return Et.has(n);
  }
  function Ve(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = se(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function xt(t) {
    const n = [];
    let o = [];
    for (const i of t)
      o.push(i), Ve(i) && (n.push(o), o = []);
    return o.length > 0 && (n.length > 0 ? n[n.length - 1].push(...o) : n.push(o)), n.length > 0 ? n : [t];
  }
  function wt(t) {
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
  function St({ data: t }) {
    var ye, p, b;
    const [n, o] = C("confirm"), [i, d] = C(""), [g, l] = C(!1), [c, s] = C(null), [_, A] = C(
      {}
    ), R = e.useRef(!1), J = e.useRef(null), [, te] = C(0), B = t == null ? void 0 : t.content, H = B && B.length >= 2 && ((p = (ye = B[1]) == null ? void 0 : ye.data) == null ? void 0 : p.output), j = xe(
      () => ht(B),
      [B]
    ), O = R.current || H || j !== null, f = xe(() => {
      const E = Xe(t), a = E == null ? void 0 : E.data;
      if (!a) return null;
      try {
        const y = typeof a == "string" ? JSON.parse(a) : a;
        let u;
        if (E.strategy_names)
          try {
            const $ = typeof E.strategy_names == "string" ? JSON.parse(E.strategy_names) : E.strategy_names;
            u = Array.isArray($) ? $ : [];
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
              (oe) => Ve(oe)
            ).length >= 2)
              k = xt(L);
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
            ($) => $.filter((L) => !De(L))
          );
        else
          return null;
        if (k = k.filter(($) => $.length > 0), k.length === 0) return null;
        const ce = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (u.length < k.length)
          for (let $ = u.length; $ < k.length; $++)
            u.push(ce[$] || `方案${$ + 1}`);
        return { proposals: k, names: u };
      } catch {
        return null;
      }
    }, [t]), x = pt(), m = (((b = f == null ? void 0 : f.proposals) == null ? void 0 : b.length) ?? 0) > 1, P = z(async () => {
      if (!x || O || !f) return;
      const E = m ? c : 0, a = f.names[E ?? 0] || `方案${(E ?? 0) + 1}`;
      let y;
      n === "confirm" ? y = `用户选择了「${a}」并确认部署` : y = `用户选择「${a}」并要求调整：${i.trim() || "未填写具体要求"}`, l(!0);
      const u = await yt(x, y);
      l(!1), u ? (R.current = !0, n === "confirm" ? J.current = `已确认部署「${a}」` : J.current = `已选择「${a}」并调整：${i.trim()}`, te((S) => S + 1), Ue.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : Ue.error("操作失败，请重试");
    }, [
      x,
      O,
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
        e.createElement(Ee, { size: "default" }),
        e.createElement(
          X,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        ue,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(X, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: V, names: me } = f, F = Qe.map((E, a) => ({
      title: E,
      dataIndex: `col_${a}`,
      key: `col_${a}`,
      render: (y) => wt(y),
      ellipsis: a < 3
    }));
    let pe = "待确认", G = "processing";
    O && (G = "success", pe = J.current || j || "已确认");
    const ne = e.createElement(
      v,
      {
        color: G,
        style: { marginLeft: 4 }
      },
      pe
    ), be = e.createElement(
      W,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        X,
        { strong: !0, style: { fontSize: 14 } },
        O ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      ne
    ), ge = V.map((E, a) => {
      const y = m ? c === a : !0, u = _[a] || !1, S = (I) => {
        const ee = se(I[0] || "").trim();
        return /^合计|^总计|^total/i.test(ee);
      }, k = E.find(S), ce = E.filter((I) => !S(I)), $ = ce.map((I) => ({
        type: se(I[0] || ""),
        purpose: se(I[1] || ""),
        spec: se(I[2] || ""),
        cost: I[9] ?? null
      })), L = k ? se(k[9] ?? "") : "", Z = E.map((I, ee) => {
        const Le = { key: ee };
        return I.forEach((Ie, je) => {
          Le[`col_${je}`] = Ie;
        }), Le;
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
          ...$.map(
            (I, ee) => e.createElement(
              "div",
              {
                key: ee,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: ee < $.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  I.type
                ),
                I.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  I.spec
                )
              ),
              !gt(I.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                se(I.cost)
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
              onClick: (I) => {
                I.stopPropagation(), A((ee) => ({
                  ...ee,
                  [a]: !ee[a]
                }));
              }
            },
            e.createElement(
              u && Ye ? Ye : mt || "span",
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
              onClick: (I) => I.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(fe, {
              columns: F,
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
    ), we = !O && x && !(m && c === null) && e.createElement(
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
          n === "adjust" && e.createElement(ft, {
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
          T,
          {
            type: "primary",
            size: "small",
            loading: g,
            onClick: P,
            disabled: n === "adjust" && !i.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), N = m && c === null && !O && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, be),
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
      N,
      re,
      !O && we
    );
  }
  function At({ data: t }) {
    if (!t || !(t != null && t.content) || !Array.isArray(t == null ? void 0 : t.content))
      return null;
    const [n, o] = C(null), [i, d] = C(!1), g = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", l = xe(() => {
      const f = Xe(t);
      return (f == null ? void 0 : f.loop_dir) || null;
    }, [t]), c = xe(() => {
      var m, P, ie;
      const f = (ie = (P = (m = t == null ? void 0 : t.content) == null ? void 0 : m[1]) == null ? void 0 : P.data) == null ? void 0 : ie.output;
      if (!f) return null;
      const x = Ge(f);
      if (!x) return null;
      try {
        return JSON.parse(x);
      } catch {
        return null;
      }
    }, [t]), s = (c == null ? void 0 : c.status) === "ok", _ = (c == null ? void 0 : c.status) === "error", A = _ ? (c == null ? void 0 : c.message) || "未知错误" : null, R = z(async () => {
      if (l)
        try {
          const f = q(), x = {};
          f && (x.Authorization = `Bearer ${f}`);
          const m = await fetch(
            Y(`/prd?loop_dir=${encodeURIComponent(l)}`),
            { headers: x }
          );
          if (!m.ok) {
            d(!0);
            return;
          }
          const P = await m.json();
          P && Array.isArray(P.userStories) ? (o(P), d(!1)) : d(!0);
        } catch {
          d(!0);
        }
    }, [l]);
    if (e.useEffect(() => {
      !g && s && l && R();
    }, [g, s, l, R]), g)
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
        e.createElement(Ee, { size: "default" }),
        e.createElement(
          X,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD..."
        )
      );
    if (_)
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
    const J = n.userStories, te = [...J].sort(
      (f, x) => (f.priority || 99) - (x.priority || 99)
    ), B = J.filter((f) => f.passes).length, H = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (f, x) => {
          if (x.passes) {
            const P = ze ? e.createElement(ze, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(Fe, { title: "已完成" }, P);
          }
          const m = Oe ? e.createElement(Oe, {
            style: { color: "#faad14", fontSize: 18 }
          }) : "🕐";
          return e.createElement(Fe, { title: "待处理" }, m);
        }
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (f) => e.createElement(v, { color: "blue" }, f)
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
            v,
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
      W,
      { size: 8 },
      qe ? e.createElement(qe, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(X, { strong: !0 }, n.project || "PRD")
      )
    ), O = e.createElement(fe, {
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
            children: `${B}/${J.length} 完成`
          }
        ]
      }),
      O,
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
    Drawer: bt,
    Modal: Ze,
    Empty: kt,
    Badge: et,
    Divider: Ct,
    message: K
  } = D, {
    ApiOutlined: tt,
    PlusOutlined: nt,
    ReloadOutlined: $e,
    DeleteOutlined: rt,
    LinkOutlined: ot,
    DisconnectOutlined: Kt
  } = U || {}, { useEffect: lt } = e, Se = "/a2a/agents";
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
  async function Ae(t, n) {
    const o = Y(t), i = q == null ? void 0 : q(), d = Ne(), g = {
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
  function Tt(t) {
    var c;
    const { agent: n, onClick: o } = t, i = n.status === "connected", d = i ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", g = i ? "已连接" : n.status === "error" ? "错误" : "未连接", l = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      ue,
      {
        hoverable: !0,
        onClick: o,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          W,
          null,
          e.createElement(et, { color: d }),
          e.createElement(
            "span",
            null,
            n.alias || n.name || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          v,
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
          ot ? e.createElement(ot, { style: { marginRight: 4 } }) : null,
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
            (s, _) => e.createElement(
              v,
              { key: _, style: { fontSize: 11 } },
              s.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            v,
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
  function vt() {
    const t = e.useRef(Ne()), [n, o] = C(t.current);
    return lt(() => {
      const i = () => {
        const g = Ne();
        g !== t.current && (t.current = g, o(g));
      }, d = setInterval(i, 200);
      return window.addEventListener("storage", i), () => {
        clearInterval(d), window.removeEventListener("storage", i);
      };
    }, []), n;
  }
  function It() {
    var dt, ut;
    const { token: t } = Ke.useToken(), n = vt(), [o, i] = C([]), [d, g] = C(!0), [l, c] = C(!1), [s, _] = C(null), [A, R] = C(!1), [J, te] = C(!1), [B, H] = C(!1), [j, O] = C(!1), [f, x] = C(""), [m] = ae.useForm(), [P, ie] = C(!1), [V, me] = C(!1), [F, pe] = C([]), [G, ne] = C(
      /* @__PURE__ */ new Set()
    ), [be, ge] = C(
      []
    ), re = e.useRef(null), we = (r) => !r || !r.trim() ? null : /\s/.test(r) ? "别名不能包含空格" : null, N = xe(
      () => new Set(o.map((r) => r.url)),
      [o]
    ), ye = e.useRef(N);
    ye.current = N;
    const p = z(async () => {
      g(!0);
      try {
        const r = await Ae(Se);
        i((r == null ? void 0 : r.agents) || []);
      } catch {
        i([]);
      } finally {
        g(!1);
      }
    }, []);
    lt(() => {
      p();
    }, [n]);
    const b = z(() => {
      R(!0), _(null), c(!0), m.resetFields(), m.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [m]), E = z((r) => {
      R(!1), _(r), c(!0);
    }, []), a = z(() => {
      O(!1), x("");
    }, []), y = z(async () => {
      if (!s || !f.trim()) return;
      const r = we(f);
      if (r) {
        K.error(r);
        return;
      }
      const h = s.alias || s.url, w = f.trim();
      if (w === h) {
        a();
        return;
      }
      try {
        const de = await Ae(
          `${Se}?alias=${encodeURIComponent(h)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_alias: w })
          }
        );
        K.success("别名已修改"), O(!1), _(de), await p();
      } catch (de) {
        K.error(de.message || "修改失败");
      }
    }, [s, f, p, a]), u = z(() => {
      a(), c(!1), _(null), R(!1), m.resetFields();
    }, [a, m]), S = z(async () => {
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
          await Ae(Se, {
            method: "POST",
            body: JSON.stringify(h)
          }), K.success("A2A Agent 注册成功"), await p(), u();
        } catch (w) {
          K.error(w.message || "注册失败");
        } finally {
          te(!1);
        }
      }
    }, [m, p, u]), k = z(async () => {
      if (!s) return;
      const r = s.alias || s.url, h = s.name || r;
      Ze.confirm({
        title: "确认删除",
        content: `确定删除 A2A Agent「${h}」吗？此操作不可撤销。`,
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await Ae(`${Se}?alias=${encodeURIComponent(r)}`, {
              method: "DELETE"
            }), K.success(`已删除 A2A Agent「${h}」`), await p(), u();
          } catch (w) {
            K.error(w.message || "删除失败");
          }
        }
      });
    }, [s, p, u]), ce = z(async () => {
      if (!s) return;
      const r = s.alias || s.url;
      H(!0);
      try {
        const h = await Ae(
          `${Se}/refresh?alias=${encodeURIComponent(r)}`,
          {
            method: "POST"
          }
        );
        K.success("Agent Card 已刷新"), await p(), h && _(h);
      } catch (h) {
        K.error(h.message || "刷新失败");
      } finally {
        H(!1);
      }
    }, [s, p]), $ = z(() => {
      s && (x(s.alias || ""), O(!0));
    }, [s]), L = z(() => {
      ie(!0), pe([]), ne(/* @__PURE__ */ new Set()), ge([]), re.current = null, oe();
    }, []), Z = z(() => {
      V && re.current && re.current.abort(), ie(!1), pe([]), ne(/* @__PURE__ */ new Set()), ge([]), re.current = null;
    }, [V]), oe = z(async () => {
      me(!0);
      const r = new AbortController();
      re.current = r;
      try {
        const h = q == null ? void 0 : q(), w = Ne(), de = {
          ...h ? { Authorization: `Bearer ${h}` } : {},
          ...w ? { "X-Agent-Id": w } : {}
        }, Ce = await fetch(Y("/a2a/import"), {
          method: "GET",
          headers: de,
          signal: r.signal
        });
        if (!Ce.ok) {
          const _e = await Ce.text().catch(() => "");
          throw new Error(_e || `HTTP ${Ce.status}`);
        }
        const We = await Ce.json(), Je = (We == null ? void 0 : We.agents) || [];
        if (Je.length === 0) {
          K.warning("未找到可用的 Agent");
          return;
        }
        pe(Je);
        const Ht = ye.current;
        ne(
          new Set(
            Je.filter((_e) => !Ht.has(_e.url)).map((_e) => _e.url)
          )
        );
      } catch (h) {
        if ((h == null ? void 0 : h.name) === "AbortError") return;
        K.error(h.message || "获取 Agent 列表失败");
      } finally {
        me(!1), re.current = null;
      }
    }, []), he = z((r) => {
      ne((h) => {
        const w = new Set(h);
        return w.has(r) ? w.delete(r) : w.add(r), w;
      });
    }, []), I = z(() => {
      ne(
        new Set(
          F.filter((r) => !N.has(r.url)).map((r) => r.url)
        )
      );
    }, [F, N]), ee = z(() => {
      ne(/* @__PURE__ */ new Set());
    }, []), Le = z(async () => {
      const r = F.filter(
        (w) => G.has(w.url) && !N.has(w.url)
      );
      if (r.length === 0) {
        K.warning("请至少选择一个 Agent");
        return;
      }
      me(!0), ge([]);
      const h = [];
      for (const w of r) {
        try {
          await Ae(Se, {
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
      await p(), K.success(
        `导入完成：成功 ${h.filter((w) => w.success).length} 个，失败 ${h.filter((w) => !w.success).length} 个`
      ), me(!1), setTimeout(() => Z(), 800);
    }, [F, G, p, N]), Ie = ((dt = ae.useWatch) == null ? void 0 : dt.call(ae, "auth_type", m)) ?? "", je = e.createElement(
      ae,
      { form: m, layout: "vertical" },
      e.createElement(
        ae.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: !0, message: "请输入 Agent URL" }]
        },
        e.createElement(Q, {
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
                const w = we(h);
                return w ? Promise.reject(new Error(w)) : Promise.resolve();
              }
            }
          ]
        },
        e.createElement(Q, {
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
        e.createElement(Q.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), Nt = s ? e.createElement(
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
            e.createElement(Q, {
              value: f,
              onChange: (r) => x(r.target.value),
              onPressEnter: y,
              autoFocus: !0,
              placeholder: "输入新别名",
              size: "small",
              style: { flex: 1 }
            }),
            e.createElement(
              T,
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
                onClick: $
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
          e.createElement(et, {
            color: s.status === "connected" ? "#52c41a" : s.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: s.status === "connected" ? "已连接" : s.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          le.Item,
          { label: "认证类型" },
          s.auth_type ? e.createElement(
            v,
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
      ((ut = s.skills) == null ? void 0 : ut.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...s.skills.map(
          (r, h) => e.createElement(
            ue,
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
          W,
          null,
          e.createElement(
            v,
            {
              color: s.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            v,
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
      e.createElement(Ct, null),
      e.createElement(
        W,
        null,
        e.createElement(
          T,
          {
            type: "primary",
            icon: $e ? e.createElement($e) : null,
            loading: B,
            onClick: ce
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          T,
          {
            danger: !0,
            icon: rt ? e.createElement(rt) : null,
            onClick: k
          },
          "删除"
        )
      )
    ) : null, Lt = e.createElement(
      bt,
      {
        title: A ? "注册远程 A2A Agent" : (s == null ? void 0 : s.name) || (s == null ? void 0 : s.alias) || "Agent 详情",
        open: l,
        onClose: u,
        width: 480,
        footer: A ? e.createElement(
          W,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(T, { onClick: u }, "取消"),
          e.createElement(
            T,
            { type: "primary", loading: J, onClick: S },
            "注册"
          )
        ) : null
      },
      A ? je : Nt
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
          W,
          null,
          e.createElement(
            T,
            {
              icon: $e ? e.createElement($e) : null,
              onClick: p,
              loading: d
            },
            "刷新列表"
          ),
          e.createElement(
            T,
            {
              icon: tt ? e.createElement(tt) : null,
              onClick: L
            },
            "从阿里云AgentHub导入"
          ),
          e.createElement(
            T,
            {
              type: "primary",
              icon: nt ? e.createElement(nt) : null,
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
    ), Mt = d ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(Ee, { size: "large" })
    ) : o.length === 0 ? e.createElement(kt, {
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
        (r) => e.createElement(Tt, {
          key: r.alias || r.url,
          agent: r,
          onClick: () => E(r)
        })
      )
    ), ke = be.length > 0, Bt = e.createElement(
      Ze,
      {
        title: ke ? "导入结果" : "从阿里云AgentHub导入 Agent",
        open: P,
        onCancel: Z,
        closable: !V || ke,
        maskClosable: !V || ke,
        width: 800,
        footer: ke ? e.createElement(
          W,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(
            T,
            { type: "primary", onClick: Z },
            "关闭"
          )
        ) : F.length > 0 ? e.createElement(
          W,
          { style: { display: "flex", justifyContent: "flex-end" } },
          e.createElement(
            T,
            { onClick: Z },
            "取消"
          ),
          e.createElement(
            T,
            {
              type: "primary",
              loading: V,
              disabled: G.size === 0,
              onClick: Le
            },
            `确认导入 (${G.size}/${F.length})`
          )
        ) : null
      },
      // Loading state
      V && F.length === 0 && e.createElement(
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
        e.createElement(Ee, { size: "large" }),
        e.createElement(
          "span",
          { style: { fontSize: 13, color: t.colorTextTertiary } },
          "正在从 AgentHub 获取 Agent 列表..."
        )
      ),
      // Agent selection list (hide after import completed)
      !V && !ke && F.length > 0 && e.createElement(
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
            `共 ${F.length} 个 Agent，已选 ${G.size} 个`
          ),
          e.createElement(
            W,
            { size: 4 },
            e.createElement(
              T,
              {
                size: "small",
                type: "link",
                style: { padding: 0, height: "auto" },
                onClick: I
              },
              "全选"
            ),
            e.createElement(
              T,
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
          ...F.map((r) => {
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
                  cursor: N.has(r.url) ? "default" : "pointer",
                  background: N.has(r.url) ? t.colorBgLayout : h ? t.colorInfoBg : t.colorBgContainer,
                  transition: "all 0.15s ease",
                  opacity: N.has(r.url) ? 0.7 : 1
                },
                onClick: () => {
                  N.has(r.url) || he(r.url);
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
                    (de, Ce) => e.createElement(
                      v,
                      {
                        key: Ce,
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
                    v,
                    { style: { fontSize: 10 } },
                    `+${r.skills.length - 3}`
                  ) : null
                ) : null
              ),
              N.has(r.url) ? e.createElement(
                v,
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
      ke && e.createElement(
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
        ...be.map(
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
      Mt,
      Lt,
      Bt
    );
  }
  function _t(t) {
    if (!t) return null;
    for (let n = t.lastIndexOf("{"); n >= 0; n = t.lastIndexOf("{", n - 1))
      try {
        return JSON.parse(t.substring(n));
      } catch {
        continue;
      }
    return null;
  }
  function Rt({ data: t }) {
    var we, N, ye;
    const { token: n } = Ke.useToken(), o = e.useRef(null), [i, d] = C({}), g = xe(() => {
      var b, E, a;
      const p = (a = (E = (b = t == null ? void 0 : t.content) == null ? void 0 : b[0]) == null ? void 0 : E.data) == null ? void 0 : a.arguments;
      if (!p) return null;
      try {
        return JSON.parse(p);
      } catch {
        return null;
      }
    }, [(ye = (N = (we = t == null ? void 0 : t.content) == null ? void 0 : we[0]) == null ? void 0 : N.data) == null ? void 0 : ye.arguments]), { toolResult: l, rawErrorText: c } = xe(() => {
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
            const u = _t(y);
            return u ? { toolResult: u, rawErrorText: "" } : { toolResult: null, rawErrorText: y };
          }
      }
      return { toolResult: null, rawErrorText: "" };
    }, [t == null ? void 0 : t.content]), s = (l == null ? void 0 : l.steps) || [], _ = (l == null ? void 0 : l.task_state) || "", A = (l == null ? void 0 : l.error) || "", R = (l == null ? void 0 : l.response_text) || "", J = (l == null ? void 0 : l.context_id) || "";
    e.useEffect(() => {
      o.current && (o.current.scrollTop = o.current.scrollHeight);
    }, [s.length, R, c]), e.useEffect(() => {
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
    }, x = (l !== null || !!c) && !(_ === "working" || _ === "TASK_STATE_WORKING");
    let m = "#1677ff", P = "执行中...";
    x && (j[_] ? (m = j[_].color, P = j[_].text) : c ? (m = "#ff4d4f", P = "出错") : (m = "#52c41a", P = "已完成"));
    const ie = e.createElement(
      W,
      { size: 6 },
      e.createElement("span", { style: { fontSize: 13 } }, "🔗"),
      e.createElement(
        X,
        { style: { fontSize: 12, color: "#595959" } },
        `A2A: ${H}`
      ),
      e.createElement(
        v,
        { color: m, style: { fontSize: 11, lineHeight: "18px" } },
        P
      )
    ), V = J ? e.createElement(
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
      `contextId: ${J}`
    ) : null, me = [ie, V], F = s.length === 0 && !c && !A, pe = !x && F ? e.createElement(
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
      e.createElement(Ee, { size: "small" }),
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
          !a && e.createElement(Ee, {
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
          a && e.createElement(Ee, {
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
    const be = s.length > 0 ? e.createElement(
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
    ) : null, re = !s.length && R && !c ? e.createElement(
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
        ...me
      ),
      pe,
      be,
      re,
      ge
    );
  }
  const zt = "__A2A_STREAM_START__", Ot = "A2A_STREAM_START", ve = /* @__PURE__ */ new Set();
  function Me(t) {
    return t ? t.includes(zt) || t.includes(Ot) : !1;
  }
  function Be(t) {
    var n, o;
    return t.getAttribute("data-msg-id") || t.getAttribute("data-message-id") || ((n = t.closest("[data-msg-id]")) == null ? void 0 : n.getAttribute("data-msg-id")) || ((o = t.closest("[data-message-id]")) == null ? void 0 : o.getAttribute("data-message-id")) || null;
  }
  function Pt(t) {
    if (Me(t.innerHTML) || Me(t.textContent))
      return t;
    const n = document.createTreeWalker(
      t,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    for (; n.nextNode(); ) {
      const o = n.currentNode, i = o.nodeType === Node.TEXT_NODE ? o.textContent : o.innerHTML;
      if (Me(i)) {
        const d = o.nodeType === Node.TEXT_NODE ? o.parentElement : o;
        if (d) return d;
      }
    }
    return null;
  }
  async function He(t) {
    var s, _;
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
        const H = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage"), j = (_ = (s = JSON.parse(H || "{}")) == null ? void 0 : s.state) == null ? void 0 : _.selectedAgent;
        j && (A["X-Agent-Id"] = j);
      } catch {
      }
      console.log("[a2a] Fetching SSE with headers:", A);
      const R = await fetch(d, { headers: A, signal: c.signal });
      if (console.log("[a2a] SSE response status:", R.status), !R.ok) {
        const H = await R.text().catch(() => "");
        l.textContent = `SSE 连接失败 (${R.status}): ${H.slice(
          0,
          100
        )}`, l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0";
        return;
      }
      if (!R.body) {
        l.textContent = "SSE 连接失败：无响应体", l.style.borderColor = "#ff4d4f", l.style.background = "#fff1f0";
        return;
      }
      const J = R.body.getReader(), te = new TextDecoder();
      let B = "";
      for (; ; ) {
        const { done: H, value: j } = await J.read();
        if (H) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }
        B += te.decode(j, { stream: !0 });
        const O = B.split(`
`);
        B = O.pop() || "";
        for (const f of O)
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
  function $t() {
    console.log("[a2a] Initializing stream interceptor");
    function t(d) {
      if (d.nodeType !== Node.ELEMENT_NODE) return;
      const g = d, l = Be(g);
      if (l && ve.has(l)) return;
      const c = Pt(g);
      c && (console.log("[a2a] Marker detected in DOM, msgId:", l), l && ve.add(l), He(c));
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
          const s = Be(c);
          if (s && ve.has(s)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", s), s && ve.add(s), He(c);
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
        const c = Be(l);
        c && ve.add(c), console.log("[a2a] Marker found in existing DOM, msgId:", c), He(l);
      }
    }
  }
  (at = (st = window.QwenPaw).registerToolRender) == null || at.call(st, "cloudpaw", {
    proposal_choice: St,
    manage_prd: At,
    a2a_call: Rt
  }), (ct = (it = window.QwenPaw).registerRoutes) == null || ct.call(it, "cloudpaw", [
    {
      path: "/a2a",
      component: It,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), Wt(), Jt(), $t();
}
function Wt() {
  const e = "qwenpaw-last-used-agent", D = "qwenpaw-agent-storage", U = "cloudpaw-first-install", Y = "cloud-orchestrator";
  if (localStorage.getItem(U)) return;
  const q = localStorage.getItem(e), ue = localStorage.getItem(D);
  if (q || ue) {
    localStorage.setItem(U, "true"), console.info(
      "[cloudpaw] Existing agent selection found — skipping first-install override"
    );
    return;
  }
  localStorage.setItem(U, "true");
  function fe() {
    localStorage.setItem(e, Y);
    try {
      const v = localStorage.getItem(D);
      if (v) {
        const M = JSON.parse(v);
        M.state = M.state || {}, M.state.selectedAgent = Y, localStorage.setItem(D, JSON.stringify(M));
      } else
        localStorage.setItem(
          D,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: Y,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const v = sessionStorage.getItem(D);
      if (v) {
        const M = JSON.parse(v);
        M.state = M.state || {}, M.state.selectedAgent = Y, sessionStorage.setItem(D, JSON.stringify(M));
      } else
        sessionStorage.setItem(
          D,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: Y,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
  }
  fe(), window.addEventListener(
    "beforeunload",
    () => {
      fe();
    },
    { once: !0 }
  ), console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
  ), window.location.reload();
}
function Jt() {
  var W;
  const e = (W = window.QwenPaw) == null ? void 0 : W.modules;
  if (!e) return;
  const D = e["Chat/OptionsPanel/defaultConfig"];
  if (!(D != null && D.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const U = D.configProvider, Y = U.getConfig.bind(U), q = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", ue = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, fe = {
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
  }, v = {
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
  function M() {
    const T = localStorage.getItem("language") || "";
    return T ? T.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (U.getGreeting = () => ue[M()] || ue.en, U.getDescription = () => fe[M()] || fe.en, U.getPrompts = () => v[M()] || v.en, U.getConfig = function(T) {
    var Te;
    const Q = Y(T);
    return {
      ...Q,
      theme: {
        ...Q.theme,
        leftHeader: {
          ...(Te = Q.theme) == null ? void 0 : Te.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...Q.welcome,
        avatar: q
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const T = document.createElement("style");
    T.id = "cloudpaw-welcome-style", T.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(T);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
jt();
