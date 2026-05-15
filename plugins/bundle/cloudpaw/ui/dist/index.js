function wt() {
  var We, Fe, Je, Ke;
  const { React: e, antd: D, antdIcons: j, getApiUrl: F, getApiToken: U } = window.QwenPaw.host, {
    Card: H,
    Table: I,
    Tag: L,
    Typography: ue,
    Space: J,
    Button: k,
    Input: q,
    Radio: fe,
    Collapse: bt,
    Descriptions: G,
    Tooltip: Ie,
    Spin: pe,
    message: Re
  } = D, { Text: W } = ue, { TextArea: Ye } = q, { useState: v, useMemo: ae, useCallback: Y, useRef: Ct } = e, {
    InfoCircleOutlined: ge,
    DownOutlined: Pe,
    RightOutlined: Qe,
    CheckCircleOutlined: ye,
    FieldTimeOutlined: he,
    FileTextOutlined: Oe
  } = j || {};
  function ze(t) {
    var s, l;
    const n = (l = (s = t == null ? void 0 : t.content) == null ? void 0 : s[0]) == null ? void 0 : l.data, o = n == null ? void 0 : n.arguments;
    if (typeof o == "string")
      try {
        return JSON.parse(o);
      } catch {
        return {};
      }
    return o ?? {};
  }
  function Ve() {
    return window.currentSessionId ?? null;
  }
  function Q(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function Ze(t) {
    if (t == null) return !0;
    const n = Q(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function et(t, n) {
    try {
      const o = U(), s = {
        "Content-Type": "application/json"
      };
      return o && (s.Authorization = `Bearer ${o}`), (await fetch(F("/interaction"), {
        method: "POST",
        headers: s,
        body: JSON.stringify({ session_id: t, result: n })
      })).ok;
    } catch {
      return !1;
    }
  }
  function Ne(t) {
    if (!t) return null;
    if (typeof t == "string")
      try {
        const n = JSON.parse(t);
        if (Array.isArray(n)) {
          const o = n.find(
            (s) => (s == null ? void 0 : s.type) === "text" && (s == null ? void 0 : s.text)
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
  function tt(t) {
    var a, r;
    if (!t || t.length < 2) return null;
    const n = (r = (a = t[1]) == null ? void 0 : a.data) == null ? void 0 : r.output, o = Ne(n);
    if (!o) return null;
    if (o.startsWith("Error:")) return o;
    const s = o.match(/^用户选择了「(.+?)」并确认部署$/);
    if (s) return `已确认部署「${s[1]}」`;
    const l = o.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/
    );
    if (l)
      return `已选择「${l[1]}」并调整：${l[2]}`;
    if (o === "用户确认部署") return "已确认部署";
    const d = o.match(/^用户要求调整资源[：:](.+)$/);
    return d ? `已反馈调整意见：${d[1]}` : "已确认";
  }
  const De = [
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
  ], nt = new Set(
    De.map((t) => t.toLowerCase())
  );
  function Te(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = Q(t[0]).trim().toLowerCase();
    return nt.has(n);
  }
  function $e(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = Q(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function rt(t) {
    const n = [];
    let o = [];
    for (const s of t)
      o.push(s), $e(s) && (n.push(o), o = []);
    return o.length > 0 && (n.length > 0 ? n[n.length - 1].push(...o) : n.push(o)), n.length > 0 ? n : [t];
  }
  function ot(t) {
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
  function st({ data: t }) {
    var Ue, qe, Xe;
    const [n, o] = v("confirm"), [s, l] = v(""), [d, a] = v(!1), [r, m] = v(null), [S, p] = v(
      {}
    ), T = e.useRef(!1), w = e.useRef(null), [, ne] = v(0), R = t == null ? void 0 : t.content, h = R && R.length >= 2 && ((qe = (Ue = R[1]) == null ? void 0 : Ue.data) == null ? void 0 : qe.output), y = ae(
      () => tt(R),
      [R]
    ), A = T.current || h || y !== null, i = ae(() => {
      const b = ze(t), E = b == null ? void 0 : b.data;
      if (!E) return null;
      try {
        const g = typeof E == "string" ? JSON.parse(E) : E;
        let O;
        if (b.strategy_names)
          try {
            const N = typeof b.strategy_names == "string" ? JSON.parse(b.strategy_names) : b.strategy_names;
            O = Array.isArray(N) ? N : [];
          } catch {
            O = [];
          }
        else g != null && g.proposal_names ? O = g.proposal_names : O = [];
        const oe = O.length >= 2 ? O.length : 0;
        let z;
        if (Array.isArray(g) && g.length > 0)
          if (Array.isArray(g[0]) && g[0].length === 10 && !Array.isArray(g[0][0])) {
            const M = g.filter(
              (se) => !Te(se)
            );
            if (M.filter(
              (se) => $e(se)
            ).length >= 2)
              z = rt(M);
            else if (oe >= 2 && M.length >= oe * 2) {
              const se = Math.ceil(M.length / oe);
              z = [];
              for (let de = 0; de < M.length; de += se)
                z.push(M.slice(de, de + se));
            } else
              z = [M];
          } else
            z = g.map(
              (M) => M.filter(
                (ce) => Array.isArray(ce) && ce.length === 10 && !Te(ce)
              )
            );
        else if (g != null && g.proposals)
          z = g.proposals.map(
            (N) => N.filter((M) => !Te(M))
          );
        else
          return null;
        if (z = z.filter((N) => N.length > 0), z.length === 0) return null;
        const Ae = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (O.length < z.length)
          for (let N = O.length; N < z.length; N++)
            O.push(Ae[N] || `方案${N + 1}`);
        return { proposals: z, names: O };
      } catch {
        return null;
      }
    }, [t]), c = Ve(), f = (((Xe = i == null ? void 0 : i.proposals) == null ? void 0 : Xe.length) ?? 0) > 1, P = Y(async () => {
      if (!c || A || !i) return;
      const b = f ? r : 0, E = i.names[b ?? 0] || `方案${(b ?? 0) + 1}`;
      let g;
      n === "confirm" ? g = `用户选择了「${E}」并确认部署` : g = `用户选择「${E}」并要求调整：${s.trim() || "未填写具体要求"}`, a(!0);
      const O = await et(c, g);
      a(!1), O ? (T.current = !0, n === "confirm" ? w.current = `已确认部署「${E}」` : w.current = `已选择「${E}」并调整：${s.trim()}`, ne((oe) => oe + 1), Re.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : Re.error("操作失败，请重试");
    }, [
      c,
      A,
      i,
      n,
      s,
      r,
      f
    ]), ie = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created";
    if (!i)
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
        e.createElement(pe, { size: "default" }),
        e.createElement(
          W,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        H,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(W, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: re, names: Z } = i, ee = De.map((b, E) => ({
      title: b,
      dataIndex: `col_${E}`,
      key: `col_${E}`,
      render: (g) => ot(g),
      ellipsis: E < 3
    }));
    let K = "待确认", $ = "processing";
    A && ($ = "success", K = w.current || y || "已确认");
    const X = e.createElement(
      L,
      {
        color: $,
        style: { marginLeft: 4 }
      },
      K
    ), C = e.createElement(
      J,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        W,
        { strong: !0, style: { fontSize: 14 } },
        A ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      X
    ), _ = re.map((b, E) => {
      const g = f ? r === E : !0, O = S[E] || !1, oe = (x) => {
        const te = Q(x[0] || "").trim();
        return /^合计|^总计|^total/i.test(te);
      }, z = b.find(oe), Ae = b.filter((x) => !oe(x)), N = Ae.map((x) => ({
        type: Q(x[0] || ""),
        purpose: Q(x[1] || ""),
        spec: Q(x[2] || ""),
        cost: x[9] ?? null
      })), M = z ? Q(z[9] ?? "") : "", ce = b.map((x, te) => {
        const Ge = { key: te };
        return x.forEach((xt, St) => {
          Ge[`col_${St}`] = xt;
        }), Ge;
      }), se = g ? "2px solid #1677ff" : "1px solid #e8e8e8", de = g ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: E,
          style: {
            flex: 1,
            minWidth: 240,
            border: se,
            borderRadius: 8,
            cursor: f ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: de,
            background: "#fff"
          },
          onClick: f ? () => m(E) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            W,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            Z[E]
          ),
          ...N.map(
            (x, te) => e.createElement(
              "div",
              {
                key: te,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: te < N.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  x.type
                ),
                x.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  x.spec
                )
              ),
              !Ze(x.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                Q(x.cost)
              )
            )
          ),
          // Total cost
          M && e.createElement(
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
              M
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
              onClick: (x) => {
                x.stopPropagation(), p((te) => ({
                  ...te,
                  [E]: !te[E]
                }));
              }
            },
            e.createElement(
              O && Pe ? Pe : Qe || "span",
              {
                style: { fontSize: 10 }
              }
            ),
            e.createElement(
              "span",
              null,
              `明细 · ${Ae.length} 项`
            )
          ),
          O && e.createElement(
            "div",
            {
              onClick: (x) => x.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(I, {
              columns: ee,
              dataSource: ce,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), u = e.createElement(
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
      ge ? e.createElement(ge, {
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
    ), B = !A && c && !(f && r === null) && e.createElement(
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
          n === "adjust" && e.createElement(Ye, {
            value: s,
            onChange: (b) => l(b.target.value),
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
          W,
          { type: "secondary", style: { fontSize: 11 } },
          f ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          k,
          {
            type: "primary",
            size: "small",
            loading: d,
            onClick: P,
            disabled: n === "adjust" && !s.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), _e = f && r === null && !A && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, C),
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
        ..._
      ),
      _e,
      u,
      !A && B
    );
  }
  function at({ data: t }) {
    const [n, o] = v(null), [s, l] = v(!1), d = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", a = ae(() => {
      const i = ze(t);
      return (i == null ? void 0 : i.loop_dir) || null;
    }, [t]), r = ae(() => {
      var c, f, P;
      const i = Ne((P = (f = (c = t == null ? void 0 : t.content) == null ? void 0 : c[1]) == null ? void 0 : f.data) == null ? void 0 : P.output);
      if (!i) return null;
      try {
        return JSON.parse(i);
      } catch {
        return null;
      }
    }, [t]), m = (r == null ? void 0 : r.status) === "ok", S = (r == null ? void 0 : r.status) === "error", p = S ? (r == null ? void 0 : r.message) || "未知错误" : null, T = Y(async () => {
      if (a)
        try {
          const i = U(), c = {};
          i && (c.Authorization = `Bearer ${i}`);
          const f = await fetch(
            F(`/prd?loop_dir=${encodeURIComponent(a)}`),
            { headers: c }
          );
          if (!f.ok) {
            l(!0);
            return;
          }
          const P = await f.json();
          P && Array.isArray(P.userStories) ? (o(P), l(!1)) : l(!0);
        } catch {
          l(!0);
        }
    }, [a]);
    if (e.useEffect(() => {
      !d && m && a && T();
    }, [d, m, a, T]), d)
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
        e.createElement(pe, { size: "default" }),
        e.createElement(
          W,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD..."
        )
      );
    if (S)
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
          W,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${p}`
        )
      );
    if (!m || s || !n) return null;
    const w = n.userStories, ne = [...w].sort(
      (i, c) => (i.priority || 99) - (c.priority || 99)
    ), R = w.filter((i) => i.passes).length, h = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (i, c) => {
          if (c.passes) {
            const P = ye ? e.createElement(ye, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(Ie, { title: "已完成" }, P);
          }
          const f = he ? e.createElement(he, {
            style: { color: "#faad14", fontSize: 18 }
          }) : "🕐";
          return e.createElement(Ie, { title: "待处理" }, f);
        }
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (i) => e.createElement(L, { color: "blue" }, i)
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (i) => e.createElement(W, { strong: !0 }, i)
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (i, c) => {
          const f = c.priority;
          return e.createElement(
            L,
            { color: "default" },
            f != null ? String(f) : "-"
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
        render: (i, c) => {
          const f = c.acceptanceCriteria;
          return typeof f == "string" ? e.createElement(
            "div",
            {
              style: { fontSize: 12, color: "#666", whiteSpace: "pre-wrap" }
            },
            f.length > 100 ? f.slice(0, 100) + "..." : f
          ) : Array.isArray(f) ? e.createElement(
            "div",
            { style: { fontSize: 12, color: "#666" } },
            f.length > 2 ? f.slice(0, 2).join(", ") + "..." : f.join(", ")
          ) : "-";
        }
      }
    ], y = e.createElement(
      J,
      { size: 8 },
      Oe ? e.createElement(Oe, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(W, { strong: !0 }, n.project || "PRD")
      )
    ), A = e.createElement(I, {
      columns: h,
      dataSource: ne.map((i) => ({ ...i, key: i.id })),
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
      e.createElement("div", { style: { marginBottom: 8 } }, y),
      e.createElement(G, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: !1,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${R}/${w.length} 完成`
          }
        ]
      }),
      A,
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
        ye ? e.createElement(ye, {
          style: { color: "#52c41a", fontSize: 14 }
        }) : "✅",
        e.createElement("span", null, "已完成"),
        e.createElement("span", { style: { margin: "0 4px" } }, "·"),
        he ? e.createElement(he, {
          style: { color: "#faad14", fontSize: 14 }
        }) : "🕐",
        e.createElement("span", null, "待处理")
      )
    );
  }
  const {
    Form: V,
    Select: Ee,
    Drawer: lt,
    Modal: it,
    Empty: ct,
    Badge: Me,
    Divider: dt,
    message: le
  } = D, {
    ApiOutlined: kt,
    PlusOutlined: Le,
    ReloadOutlined: xe,
    DeleteOutlined: Be,
    LinkOutlined: je,
    DisconnectOutlined: vt
  } = j || {}, { useEffect: He } = e, Se = "/a2a/agents";
  function be() {
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
  async function we(t, n) {
    const o = F(t), s = U == null ? void 0 : U(), l = be(), d = {
      "Content-Type": "application/json",
      ...s ? { Authorization: `Bearer ${s}` } : {},
      ...l ? { "X-Agent-Id": l } : {}
    }, a = await fetch(o, {
      ...n,
      headers: { ...d, ...(n == null ? void 0 : n.headers) || {} }
    });
    if (!a.ok) {
      const r = await a.text().catch(() => "");
      throw new Error(r || `HTTP ${a.status}`);
    }
    return a.status === 204 || a.headers.get("content-length") === "0" ? null : a.json();
  }
  function ut(t) {
    var r;
    const { agent: n, onClick: o } = t, s = n.status === "connected", l = s ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", d = s ? "已连接" : n.status === "error" ? "错误" : "未连接", a = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      H,
      {
        hoverable: !0,
        onClick: o,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          J,
          null,
          e.createElement(Me, { color: l }),
          e.createElement(
            "span",
            null,
            n.name || n.alias || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          L,
          { color: "blue" },
          a[n.auth_type] || n.auth_type
        ) : null
      },
      e.createElement(
        "div",
        { style: { fontSize: 12, color: "#666" } },
        e.createElement(
          "div",
          { style: { marginBottom: 4 } },
          je ? e.createElement(je, { style: { marginRight: 4 } }) : null,
          n.url
        ),
        n.description ? e.createElement(
          "div",
          { style: { marginBottom: 4, color: "#999" } },
          n.description
        ) : null,
        ((r = n.skills) == null ? void 0 : r.length) > 0 ? e.createElement(
          "div",
          null,
          n.skills.slice(0, 3).map(
            (m, S) => e.createElement(
              L,
              { key: S, style: { fontSize: 11 } },
              m.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            L,
            { style: { fontSize: 11 } },
            `+${n.skills.length - 3}`
          ) : null
        ) : null,
        e.createElement(
          "div",
          { style: { marginTop: 4, color: l, fontSize: 11 } },
          d,
          n.error ? ` - ${n.error}` : ""
        )
      )
    );
  }
  function ft() {
    const t = e.useRef(be()), [n, o] = v(t.current);
    return He(() => {
      const s = () => {
        const d = be();
        d !== t.current && (t.current = d, o(d));
      }, l = setInterval(s, 200);
      return window.addEventListener("storage", s), () => {
        clearInterval(l), window.removeEventListener("storage", s);
      };
    }, []), n;
  }
  function mt() {
    var C, _;
    const t = ft(), [n, o] = v([]), [s, l] = v(!0), [d, a] = v(!1), [r, m] = v(null), [S, p] = v(!1), [T, w] = v(!1), [ne, R] = v(!1), [h] = V.useForm(), y = Y(async () => {
      l(!0);
      try {
        const u = await we(Se);
        o((u == null ? void 0 : u.agents) || []);
      } catch {
        o([]);
      } finally {
        l(!1);
      }
    }, []);
    He(() => {
      y();
    }, [t]);
    const A = Y(() => {
      p(!0), m(null), a(!0), h.resetFields(), h.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [h]), i = Y((u) => {
      p(!1), m(u), a(!0);
    }, []), c = Y(() => {
      a(!1), m(null), p(!1), h.resetFields();
    }, [h]), f = Y(async () => {
      let u;
      try {
        u = await h.validateFields();
      } catch {
        return;
      }
      const B = {
        url: String(u.url || "").trim(),
        alias: String(u.alias || "").trim() || void 0,
        auth_type: String(u.auth_type || ""),
        auth_token: String(u.auth_token || "")
      };
      if (B.url) {
        w(!0);
        try {
          await we(Se, {
            method: "POST",
            body: JSON.stringify(B)
          }), le.success("A2A Agent 注册成功"), await y(), c();
        } catch (_e) {
          le.error(_e.message || "注册失败");
        } finally {
          w(!1);
        }
      }
    }, [h, y, c]), P = Y(async () => {
      if (!r) return;
      const u = r.alias || r.url;
      it.confirm({
        title: `删除 ${u}`,
        content: "确定删除该远程 A2A Agent 吗？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await we(`${Se}/${encodeURIComponent(u)}`, {
              method: "DELETE"
            }), le.success("A2A Agent 已删除"), await y(), c();
          } catch (B) {
            le.error(B.message || "删除失败");
          }
        }
      });
    }, [r, y, c]), ie = Y(async () => {
      if (!r) return;
      const u = r.alias || r.url;
      R(!0);
      try {
        const B = await we(
          `${Se}/${encodeURIComponent(u)}/refresh`,
          {
            method: "POST"
          }
        );
        le.success("Agent Card 已刷新"), await y(), B && m(B);
      } catch (B) {
        le.error(B.message || "刷新失败");
      } finally {
        R(!1);
      }
    }, [r, y]), re = ((C = V.useWatch) == null ? void 0 : C.call(V, "auth_type", h)) ?? "", Z = e.createElement(
      V,
      { form: h, layout: "vertical" },
      e.createElement(
        V.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: !0, message: "请输入 Agent URL" }]
        },
        e.createElement(q, {
          placeholder: "https://agent.example.com"
        })
      ),
      e.createElement(
        V.Item,
        { name: "alias", label: "别名" },
        e.createElement(q, { placeholder: "输入别名（可选）" })
      ),
      e.createElement(
        V.Item,
        { name: "auth_type", label: "认证类型" },
        e.createElement(
          Ee,
          { allowClear: !0, placeholder: "无认证" },
          e.createElement(
            Ee.Option,
            { value: "bearer" },
            "Bearer Token"
          ),
          e.createElement(Ee.Option, { value: "api_key" }, "API Key"),
          e.createElement(
            Ee.Option,
            { value: "gateway" },
            "阿里云Agent Hub"
          )
        )
      ),
      re === "gateway" ? e.createElement(
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
      re && re !== "gateway" ? e.createElement(
        V.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(q.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), ee = r ? e.createElement(
      "div",
      null,
      e.createElement(
        G,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          G.Item,
          { label: "URL" },
          r.url
        ),
        e.createElement(
          G.Item,
          { label: "别名" },
          r.alias || "-"
        ),
        e.createElement(
          G.Item,
          { label: "Agent 名称" },
          r.name || "-"
        ),
        e.createElement(
          G.Item,
          { label: "状态" },
          e.createElement(Me, {
            color: r.status === "connected" ? "#52c41a" : r.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: r.status === "connected" ? "已连接" : r.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          G.Item,
          { label: "认证类型" },
          r.auth_type ? e.createElement(
            L,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[r.auth_type] || r.auth_type
          ) : "无认证"
        ),
        e.createElement(
          G.Item,
          { label: "描述" },
          r.description || "-"
        ),
        e.createElement(
          G.Item,
          { label: "版本" },
          r.version || "-"
        )
      ),
      ((_ = r.skills) == null ? void 0 : _.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...r.skills.map(
          (u, B) => e.createElement(
            H,
            { key: B, size: "small", style: { marginBottom: 8 } },
            e.createElement("strong", null, u.name),
            u.description ? e.createElement(
              "div",
              { style: { color: "#666", fontSize: 12 } },
              u.description
            ) : null
          )
        )
      ) : null,
      r.capabilities ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "能力"),
        e.createElement(
          J,
          null,
          e.createElement(
            L,
            {
              color: r.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            L,
            {
              color: r.capabilities.push_notifications ? "green" : "default"
            },
            "Push Notifications"
          )
        )
      ) : null,
      r.error ? e.createElement(
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
        r.error
      ) : null,
      e.createElement(dt, null),
      e.createElement(
        J,
        null,
        e.createElement(
          k,
          {
            type: "primary",
            icon: xe ? e.createElement(xe) : null,
            loading: ne,
            onClick: ie
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          k,
          {
            danger: !0,
            icon: Be ? e.createElement(Be) : null,
            onClick: P
          },
          "删除"
        )
      )
    ) : null, K = e.createElement(
      lt,
      {
        title: S ? "注册远程 A2A Agent" : (r == null ? void 0 : r.name) || (r == null ? void 0 : r.alias) || "Agent 详情",
        open: d,
        onClose: c,
        width: 480,
        footer: S ? e.createElement(
          J,
          { style: { float: "right" } },
          e.createElement(k, { onClick: c }, "取消"),
          e.createElement(
            k,
            { type: "primary", loading: T, onClick: f },
            "注册"
          )
        ) : null
      },
      S ? Z : ee
    ), $ = e.createElement(
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
          J,
          null,
          e.createElement(
            k,
            {
              icon: xe ? e.createElement(xe) : null,
              onClick: y,
              loading: s
            },
            "刷新列表"
          ),
          e.createElement(
            k,
            {
              type: "primary",
              icon: Le ? e.createElement(Le) : null,
              onClick: A
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
        ge ? e.createElement(ge, {
          style: { marginRight: 4, color: "#faad14" }
        }) : null,
        "当前 A2A 功能仅支持 CloudPaw 插件连接阿里云 Skills 门户 Agent，连接其他 Agent 可能存在不兼容问题。"
      )
    ), X = s ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(pe, { size: "large" })
    ) : n.length === 0 ? e.createElement(ct, { description: "暂无注册的远程 A2A Agent" }) : e.createElement(
      "div",
      {
        style: {
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 12
        }
      },
      ...n.map(
        (u) => e.createElement(ut, {
          key: u.alias || u.url,
          agent: u,
          onClick: () => i(u)
        })
      )
    );
    return e.createElement(
      "div",
      { style: { padding: 24 } },
      $,
      X,
      K
    );
  }
  function pt({ data: t }) {
    var P, ie, re;
    const n = e.useRef(null), o = ae(() => {
      var ee, K, $;
      const Z = ($ = (K = (ee = t == null ? void 0 : t.content) == null ? void 0 : ee[0]) == null ? void 0 : K.data) == null ? void 0 : $.arguments;
      if (!Z) return null;
      try {
        return JSON.parse(Z);
      } catch {
        return null;
      }
    }, [(re = (ie = (P = t == null ? void 0 : t.content) == null ? void 0 : P[0]) == null ? void 0 : ie.data) == null ? void 0 : re.arguments]), { toolResult: s, rawErrorText: l } = ae(() => {
      var ee;
      const Z = t == null ? void 0 : t.content;
      if (!Array.isArray(Z)) return { toolResult: null, rawErrorText: "" };
      for (const K of Z) {
        const $ = (ee = K == null ? void 0 : K.data) == null ? void 0 : ee.output;
        if (!$) continue;
        let X = "";
        if (Array.isArray($)) {
          const C = $.find(
            (_) => (_ == null ? void 0 : _.type) === "text" && (_ == null ? void 0 : _.text)
          );
          X = (C == null ? void 0 : C.text) || "";
        } else if (typeof $ == "string")
          try {
            const C = JSON.parse($);
            if (typeof C == "object" && (C != null && C.response_text))
              return { toolResult: C, rawErrorText: "" };
            if (Array.isArray(C)) {
              const _ = C.find(
                (u) => (u == null ? void 0 : u.type) === "text" && (u == null ? void 0 : u.text)
              );
              _ != null && _.text && (X = _.text);
            }
          } catch {
            X = $;
          }
        if (X)
          try {
            return { toolResult: JSON.parse(X), rawErrorText: "" };
          } catch {
            return { toolResult: null, rawErrorText: X };
          }
      }
      return { toolResult: null, rawErrorText: "" };
    }, [t == null ? void 0 : t.content]);
    e.useEffect(() => {
      n.current && (n.current.scrollTop = n.current.scrollHeight);
    }, [s == null ? void 0 : s.response_text, l]);
    const d = (o == null ? void 0 : o.agent_alias) || "", a = (o == null ? void 0 : o.agent_url) || "", r = d || a || "远程 Agent", m = (s == null ? void 0 : s.response_text) || "", S = (s == null ? void 0 : s.task_state) || "", p = (s == null ? void 0 : s.error) || "", T = {
      completed: { color: "#52c41a", text: "已完成" },
      TASK_STATE_COMPLETED: { color: "#52c41a", text: "已完成" },
      failed: { color: "#ff4d4f", text: "失败" },
      TASK_STATE_FAILED: { color: "#ff4d4f", text: "失败" },
      error: { color: "#ff4d4f", text: "出错" },
      canceled: { color: "#faad14", text: "已取消" },
      TASK_STATE_CANCELED: { color: "#faad14", text: "已取消" },
      AWAITING_USER_INPUT: { color: "#1677ff", text: "等待输入" },
      input_required: { color: "#1677ff", text: "等待输入" }
    };
    let w = "";
    p ? w = `错误: ${p}` : m ? w = m : l && (w = l);
    const h = (s !== null || !!l) && !(S === "working" || S === "TASK_STATE_WORKING");
    let y = "#1677ff", A = "执行中...";
    h && (T[S] ? (y = T[S].color, A = T[S].text) : l ? (y = "#ff4d4f", A = "出错") : (y = "#52c41a", A = "已完成"));
    const i = e.createElement(
      J,
      { size: 6 },
      e.createElement("span", { style: { fontSize: 13 } }, "🔗"),
      e.createElement(
        W,
        { style: { fontSize: 12, color: "#595959" } },
        `A2A: ${r}`
      ),
      e.createElement(
        L,
        { color: y, style: { fontSize: 11, lineHeight: "18px" } },
        A
      )
    ), c = !h && !w ? e.createElement(
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
      e.createElement(pe, { size: "small" }),
      e.createElement(
        W,
        { style: { fontSize: 12, color: "#52c41a" } },
        `正在连接 ${r}...`
      )
    ) : null, f = w ? e.createElement(
      "div",
      {
        ref: n,
        style: {
          background: "#fafafa",
          border: "1px solid #e8e8e8",
          borderRadius: 6,
          padding: "10px 12px",
          maxHeight: 250,
          overflowY: "auto"
        }
      },
      e.createElement(
        W,
        {
          style: {
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6"
          }
        },
        w
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
          padding: "10px 14px",
          margin: "4px 0"
        }
      },
      e.createElement("div", { style: { marginBottom: 8 } }, i),
      c,
      f
    );
  }
  const gt = "__A2A_STREAM_START__", yt = "A2A_STREAM_START", me = /* @__PURE__ */ new Set();
  function Ce(t) {
    return t ? t.includes(gt) || t.includes(yt) : !1;
  }
  function ke(t) {
    var n, o;
    return t.getAttribute("data-msg-id") || t.getAttribute("data-message-id") || ((n = t.closest("[data-msg-id]")) == null ? void 0 : n.getAttribute("data-msg-id")) || ((o = t.closest("[data-message-id]")) == null ? void 0 : o.getAttribute("data-message-id")) || null;
  }
  function ht(t) {
    if (Ce(t.innerHTML) || Ce(t.textContent))
      return t;
    const n = document.createTreeWalker(
      t,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    for (; n.nextNode(); ) {
      const o = n.currentNode, s = o.nodeType === Node.TEXT_NODE ? o.textContent : o.innerHTML;
      if (Ce(s)) {
        const l = o.nodeType === Node.TEXT_NODE ? o.parentElement : o;
        if (l) return l;
      }
    }
    return null;
  }
  async function ve(t) {
    var m, S;
    const n = window.QwenPaw;
    if (!(n != null && n.host)) {
      console.warn("[a2a] QwenPaw.host not available");
      return;
    }
    const { getApiUrl: o, getApiToken: s } = n.host, l = o("/a2a/call/stream"), d = s();
    console.log("[a2a] Subscribing to SSE stream:", l);
    const a = document.createElement("div");
    a.style.cssText = "background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px;padding:12px 16px;margin:4px 0;font-size:13px;white-space:pre-wrap;word-break:break-word;color:#262626;min-height:24px;", a.textContent = "正在连接远程 Agent...", t.textContent = "", t.appendChild(a);
    const r = new AbortController();
    try {
      const p = {
        Accept: "text/event-stream"
      };
      d && (p.Authorization = `Bearer ${d}`);
      try {
        const h = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage"), y = (S = (m = JSON.parse(h || "{}")) == null ? void 0 : m.state) == null ? void 0 : S.selectedAgent;
        y && (p["X-Agent-Id"] = y);
      } catch {
      }
      console.log("[a2a] Fetching SSE with headers:", p);
      const T = await fetch(l, { headers: p, signal: r.signal });
      if (console.log("[a2a] SSE response status:", T.status), !T.ok) {
        const h = await T.text().catch(() => "");
        a.textContent = `SSE 连接失败 (${T.status}): ${h.slice(0, 100)}`, a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0";
        return;
      }
      if (!T.body) {
        a.textContent = "SSE 连接失败：无响应体", a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0";
        return;
      }
      const w = T.body.getReader(), ne = new TextDecoder();
      let R = "";
      for (; ; ) {
        const { done: h, value: y } = await w.read();
        if (h) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }
        R += ne.decode(y, { stream: !0 });
        const A = R.split(`
`);
        R = A.pop() || "";
        for (const i of A)
          if (i.startsWith("data: "))
            try {
              const c = JSON.parse(i.slice(6));
              if (console.log("[a2a] SSE event:", c), c.done) {
                c.error && (a.textContent = `错误: ${c.error}`, a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0"), console.log("[a2a] SSE done signal received");
                return;
              }
              typeof c.response_text == "string" && c.response_text && (a.textContent = c.response_text);
            } catch (c) {
              console.warn("[a2a] SSE parse error:", c, "line:", i);
            }
      }
    } catch (p) {
      (p == null ? void 0 : p.name) !== "AbortError" && (console.error("[a2a] SSE subscription error:", p), a.textContent = `连接出错: ${(p == null ? void 0 : p.message) || p}`, a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0");
    }
  }
  function Et() {
    console.log("[a2a] Initializing stream interceptor");
    function t(l) {
      if (l.nodeType !== Node.ELEMENT_NODE) return;
      const d = l, a = ke(d);
      if (a && me.has(a)) return;
      const r = ht(d);
      r && (console.log("[a2a] Marker detected in DOM, msgId:", a), a && me.add(a), ve(r));
    }
    new MutationObserver((l) => {
      for (const d of l) {
        for (const a of d.addedNodes)
          t(a);
        d.target.nodeType === Node.ELEMENT_NODE && t(d.target);
      }
    }).observe(document.body, {
      childList: !0,
      subtree: !0,
      characterData: !0,
      characterDataOldValue: !0
    });
    const o = setInterval(() => {
      const l = document.evaluate(
        "//text()[contains(., 'A2A_STREAM_START')]",
        document.body,
        null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
        null
      );
      for (let d = 0; d < l.snapshotLength; d++) {
        const r = l.snapshotItem(d).parentElement;
        if (r) {
          const m = ke(r);
          if (m && me.has(m)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", m), m && me.add(m), ve(r);
        }
      }
    }, 500);
    window.addEventListener("beforeunload", () => clearInterval(o));
    const s = document.evaluate(
      "//text()[contains(., 'A2A_STREAM_START')]",
      document.body,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null
    );
    for (let l = 0; l < s.snapshotLength; l++) {
      const a = s.snapshotItem(l).parentElement;
      if (a) {
        const r = ke(a);
        r && me.add(r), console.log("[a2a] Marker found in existing DOM, msgId:", r), ve(a);
      }
    }
  }
  (Fe = (We = window.QwenPaw).registerToolRender) == null || Fe.call(We, "cloudpaw", {
    proposal_choice: st,
    manage_prd: at,
    a2a_call: pt
  }), (Ke = (Je = window.QwenPaw).registerRoutes) == null || Ke.call(Je, "cloudpaw", [
    {
      path: "/a2a",
      component: mt,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), At(), Tt(), Et();
}
function At() {
  const e = "qwenpaw-last-used-agent", D = "qwenpaw-agent-storage", j = "cloudpaw-first-install", F = "cloud-orchestrator";
  if (localStorage.getItem(j)) return;
  localStorage.setItem(j, "true");
  function U() {
    localStorage.setItem(e, F);
    try {
      const H = localStorage.getItem(D);
      if (H) {
        const I = JSON.parse(H);
        I.state = I.state || {}, I.state.selectedAgent = F, localStorage.setItem(D, JSON.stringify(I));
      } else
        localStorage.setItem(
          D,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: F,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const H = sessionStorage.getItem(D);
      if (H) {
        const I = JSON.parse(H);
        I.state = I.state || {}, I.state.selectedAgent = F, sessionStorage.setItem(D, JSON.stringify(I));
      } else
        sessionStorage.setItem(
          D,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: F,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
  }
  U(), window.addEventListener(
    "beforeunload",
    () => {
      U();
    },
    { once: !0 }
  ), console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
  ), window.location.reload();
}
function Tt() {
  var J;
  const e = (J = window.QwenPaw) == null ? void 0 : J.modules;
  if (!e) return;
  const D = e["Chat/OptionsPanel/defaultConfig"];
  if (!(D != null && D.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const j = D.configProvider, F = j.getConfig.bind(j), U = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", H = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, I = {
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
  }, L = {
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
  function ue() {
    const k = localStorage.getItem("language") || "";
    return k ? k.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (j.getGreeting = () => H[ue()] || H.en, j.getDescription = () => I[ue()] || I.en, j.getPrompts = () => L[ue()] || L.en, j.getConfig = function(k) {
    var fe;
    const q = F(k);
    return {
      ...q,
      theme: {
        ...q.theme,
        leftHeader: {
          ...(fe = q.theme) == null ? void 0 : fe.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...q.welcome,
        avatar: U
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const k = document.createElement("style");
    k.id = "cloudpaw-welcome-style", k.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(k);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
wt();
