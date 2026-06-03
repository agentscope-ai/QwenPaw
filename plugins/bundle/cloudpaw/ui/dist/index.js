function St() {
  var Ke, Ue, qe, Ye;
  const { React: e, antd: D, antdIcons: j, getApiUrl: J, getApiToken: U } = window.QwenPaw.host, {
    Card: W,
    Table: z,
    Tag: H,
    Typography: me,
    Space: K,
    Button: I,
    Input: q,
    Radio: pe,
    Collapse: kt,
    Descriptions: X,
    Tooltip: Pe,
    Spin: ae,
    message: Oe
  } = D, { Text: F } = me, { TextArea: Ge } = q, { useState: v, useMemo: se, useCallback: G, useRef: Tt } = e, {
    InfoCircleOutlined: xe,
    DownOutlined: Ne,
    RightOutlined: Qe,
    CheckCircleOutlined: we,
    FieldTimeOutlined: Se,
    FileTextOutlined: $e
  } = j || {};
  function De(t) {
    var i, l;
    const n = (l = (i = t == null ? void 0 : t.content) == null ? void 0 : i[0]) == null ? void 0 : l.data, o = n == null ? void 0 : n.arguments;
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
      const o = U(), i = {
        "Content-Type": "application/json"
      };
      return o && (i.Authorization = `Bearer ${o}`), (await fetch(J("/interaction"), {
        method: "POST",
        headers: i,
        body: JSON.stringify({ session_id: t, result: n })
      })).ok;
    } catch {
      return !1;
    }
  }
  function Le(t) {
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
  function tt(t) {
    var a, r;
    if (!t || t.length < 2) return null;
    const n = (r = (a = t[1]) == null ? void 0 : a.data) == null ? void 0 : r.output, o = Le(n);
    if (!o) return null;
    if (o.startsWith("Error:")) return o;
    const i = o.match(/^用户选择了「(.+?)」并确认部署$/);
    if (i) return `已确认部署「${i[1]}」`;
    const l = o.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/
    );
    if (l)
      return `已选择「${l[1]}」并调整：${l[2]}`;
    if (o === "用户确认部署") return "已确认部署";
    const c = o.match(/^用户要求调整资源[：:](.+)$/);
    return c ? `已反馈调整意见：${c[1]}` : "已确认";
  }
  const Me = [
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
    Me.map((t) => t.toLowerCase())
  );
  function ve(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = Q(t[0]).trim().toLowerCase();
    return nt.has(n);
  }
  function Be(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = Q(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function rt(t) {
    const n = [];
    let o = [];
    for (const i of t)
      o.push(i), Be(i) && (n.push(o), o = []);
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
  function at({ data: t }) {
    var g, P, w;
    const [n, o] = v("confirm"), [i, l] = v(""), [c, a] = v(!1), [r, h] = v(null), [T, x] = v(
      {}
    ), R = e.useRef(!1), L = e.useRef(null), [, Y] = v(0), C = t == null ? void 0 : t.content, S = C && C.length >= 2 && ((P = (g = C[1]) == null ? void 0 : g.data) == null ? void 0 : P.output), k = se(
      () => tt(C),
      [C]
    ), _ = R.current || S || k !== null, d = se(() => {
      const m = De(t), y = m == null ? void 0 : m.data;
      if (!y) return null;
      try {
        const E = typeof y == "string" ? JSON.parse(y) : y;
        let O;
        if (m.strategy_names)
          try {
            const $ = typeof m.strategy_names == "string" ? JSON.parse(m.strategy_names) : m.strategy_names;
            O = Array.isArray($) ? $ : [];
          } catch {
            O = [];
          }
        else E != null && E.proposal_names ? O = E.proposal_names : O = [];
        const te = O.length >= 2 ? O.length : 0;
        let N;
        if (Array.isArray(E) && E.length > 0)
          if (Array.isArray(E[0]) && E[0].length === 10 && !Array.isArray(E[0][0])) {
            const B = E.filter(
              (ne) => !ve(ne)
            );
            if (B.filter(
              (ne) => Be(ne)
            ).length >= 2)
              N = rt(B);
            else if (te >= 2 && B.length >= te * 2) {
              const ne = Math.ceil(B.length / te);
              N = [];
              for (let fe = 0; fe < B.length; fe += ne)
                N.push(B.slice(fe, fe + ne));
            } else
              N = [B];
          } else
            N = E.map(
              (B) => B.filter(
                (ue) => Array.isArray(ue) && ue.length === 10 && !ve(ue)
              )
            );
        else if (E != null && E.proposals)
          N = E.proposals.map(
            ($) => $.filter((B) => !ve(B))
          );
        else
          return null;
        if (N = N.filter(($) => $.length > 0), N.length === 0) return null;
        const Ce = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (O.length < N.length)
          for (let $ = O.length; $ < N.length; $++)
            O.push(Ce[$] || `方案${$ + 1}`);
        return { proposals: N, names: O };
      } catch {
        return null;
      }
    }, [t]), u = Ve(), p = (((w = d == null ? void 0 : d.proposals) == null ? void 0 : w.length) ?? 0) > 1, M = G(async () => {
      if (!u || _ || !d) return;
      const m = p ? r : 0, y = d.names[m ?? 0] || `方案${(m ?? 0) + 1}`;
      let E;
      n === "confirm" ? E = `用户选择了「${y}」并确认部署` : E = `用户选择「${y}」并要求调整：${i.trim() || "未填写具体要求"}`, a(!0);
      const O = await et(u, E);
      a(!1), O ? (R.current = !0, n === "confirm" ? L.current = `已确认部署「${y}」` : L.current = `已选择「${y}」并调整：${i.trim()}`, Y((te) => te + 1), Oe.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : Oe.error("操作失败，请重试");
    }, [
      u,
      _,
      d,
      n,
      i,
      r,
      p
    ]), ye = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created";
    if (!d)
      return ye ? e.createElement(
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
        e.createElement(ae, { size: "default" }),
        e.createElement(
          F,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        W,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(F, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: ee, names: he } = d, Ee = Me.map((m, y) => ({
      title: m,
      dataIndex: `col_${y}`,
      key: `col_${y}`,
      render: (E) => ot(E),
      ellipsis: y < 3
    }));
    let ie = "待确认", ce = "processing";
    _ && (ce = "success", ie = L.current || k || "已确认");
    const de = e.createElement(
      H,
      {
        color: ce,
        style: { marginLeft: 4 }
      },
      ie
    ), re = e.createElement(
      K,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        F,
        { strong: !0, style: { fontSize: 14 } },
        _ ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      de
    ), oe = ee.map((m, y) => {
      const E = p ? r === y : !0, O = T[y] || !1, te = (b) => {
        const Z = Q(b[0] || "").trim();
        return /^合计|^总计|^total/i.test(Z);
      }, N = m.find(te), Ce = m.filter((b) => !te(b)), $ = Ce.map((b) => ({
        type: Q(b[0] || ""),
        purpose: Q(b[1] || ""),
        spec: Q(b[2] || ""),
        cost: b[9] ?? null
      })), B = N ? Q(N[9] ?? "") : "", ue = m.map((b, Z) => {
        const Xe = { key: Z };
        return b.forEach((xt, wt) => {
          Xe[`col_${wt}`] = xt;
        }), Xe;
      }), ne = E ? "2px solid #1677ff" : "1px solid #e8e8e8", fe = E ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: y,
          style: {
            flex: 1,
            minWidth: 240,
            border: ne,
            borderRadius: 8,
            cursor: p ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: fe,
            background: "#fff"
          },
          onClick: p ? () => h(y) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            F,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            he[y]
          ),
          ...$.map(
            (b, Z) => e.createElement(
              "div",
              {
                key: Z,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: Z < $.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  b.type
                ),
                b.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  b.spec
                )
              ),
              !Ze(b.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                Q(b.cost)
              )
            )
          ),
          // Total cost
          B && e.createElement(
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
              B
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
              onClick: (b) => {
                b.stopPropagation(), x((Z) => ({
                  ...Z,
                  [y]: !Z[y]
                }));
              }
            },
            e.createElement(
              O && Ne ? Ne : Qe || "span",
              {
                style: { fontSize: 10 }
              }
            ),
            e.createElement(
              "span",
              null,
              `明细 · ${Ce.length} 项`
            )
          ),
          O && e.createElement(
            "div",
            {
              onClick: (b) => b.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(z, {
              columns: Ee,
              dataSource: ue,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), s = e.createElement(
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
      xe ? e.createElement(xe, {
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
    ), f = !_ && u && !(p && r === null) && e.createElement(
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
          e.createElement(pe, { checked: n === "confirm" }),
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
            e.createElement(pe, { checked: n === "adjust" }),
            e.createElement(
              "span",
              { style: { fontSize: 13 } },
              "调整资源"
            )
          ),
          n === "adjust" && e.createElement(Ge, {
            value: i,
            onChange: (m) => l(m.target.value),
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
          F,
          { type: "secondary", style: { fontSize: 11 } },
          p ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          I,
          {
            type: "primary",
            size: "small",
            loading: c,
            onClick: M,
            disabled: n === "adjust" && !i.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), A = p && r === null && !_ && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, re),
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
        ...oe
      ),
      A,
      s,
      !_ && f
    );
  }
  function st({ data: t }) {
    const [n, o] = v(null), [i, l] = v(!1), c = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", a = se(() => {
      const d = De(t);
      return (d == null ? void 0 : d.loop_dir) || null;
    }, [t]), r = se(() => {
      var u, p, M;
      const d = Le((M = (p = (u = t == null ? void 0 : t.content) == null ? void 0 : u[1]) == null ? void 0 : p.data) == null ? void 0 : M.output);
      if (!d) return null;
      try {
        return JSON.parse(d);
      } catch {
        return null;
      }
    }, [t]), h = (r == null ? void 0 : r.status) === "ok", T = (r == null ? void 0 : r.status) === "error", x = T ? (r == null ? void 0 : r.message) || "未知错误" : null, R = G(async () => {
      if (a)
        try {
          const d = U(), u = {};
          d && (u.Authorization = `Bearer ${d}`);
          const p = await fetch(
            J(`/prd?loop_dir=${encodeURIComponent(a)}`),
            { headers: u }
          );
          if (!p.ok) {
            l(!0);
            return;
          }
          const M = await p.json();
          M && Array.isArray(M.userStories) ? (o(M), l(!1)) : l(!0);
        } catch {
          l(!0);
        }
    }, [a]);
    if (e.useEffect(() => {
      !c && h && a && R();
    }, [c, h, a, R]), c)
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
        e.createElement(ae, { size: "default" }),
        e.createElement(
          F,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD..."
        )
      );
    if (T)
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
          F,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${x}`
        )
      );
    if (!h || i || !n) return null;
    const L = n.userStories, Y = [...L].sort(
      (d, u) => (d.priority || 99) - (u.priority || 99)
    ), C = L.filter((d) => d.passes).length, S = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (d, u) => {
          if (u.passes) {
            const M = we ? e.createElement(we, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(Pe, { title: "已完成" }, M);
          }
          const p = Se ? e.createElement(Se, {
            style: { color: "#faad14", fontSize: 18 }
          }) : "🕐";
          return e.createElement(Pe, { title: "待处理" }, p);
        }
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (d) => e.createElement(H, { color: "blue" }, d)
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (d) => e.createElement(F, { strong: !0 }, d)
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (d, u) => {
          const p = u.priority;
          return e.createElement(
            H,
            { color: "default" },
            p != null ? String(p) : "-"
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
        render: (d, u) => {
          const p = u.acceptanceCriteria;
          return typeof p == "string" ? e.createElement(
            "div",
            {
              style: { fontSize: 12, color: "#666", whiteSpace: "pre-wrap" }
            },
            p.length > 100 ? p.slice(0, 100) + "..." : p
          ) : Array.isArray(p) ? e.createElement(
            "div",
            { style: { fontSize: 12, color: "#666" } },
            p.length > 2 ? p.slice(0, 2).join(", ") + "..." : p.join(", ")
          ) : "-";
        }
      }
    ], k = e.createElement(
      K,
      { size: 8 },
      $e ? e.createElement($e, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(F, { strong: !0 }, n.project || "PRD")
      )
    ), _ = e.createElement(z, {
      columns: S,
      dataSource: Y.map((d) => ({ ...d, key: d.id })),
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
      e.createElement("div", { style: { marginBottom: 8 } }, k),
      e.createElement(X, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: !1,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${C}/${L.length} 完成`
          }
        ]
      }),
      _,
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
        we ? e.createElement(we, {
          style: { color: "#52c41a", fontSize: 14 }
        }) : "✅",
        e.createElement("span", null, "已完成"),
        e.createElement("span", { style: { margin: "0 4px" } }, "·"),
        Se ? e.createElement(Se, {
          style: { color: "#faad14", fontSize: 14 }
        }) : "🕐",
        e.createElement("span", null, "待处理")
      )
    );
  }
  const {
    Form: V,
    Select: Ae,
    Drawer: lt,
    Modal: it,
    Empty: ct,
    Badge: He,
    Divider: dt,
    message: le
  } = D, {
    ApiOutlined: Ct,
    PlusOutlined: je,
    ReloadOutlined: be,
    DeleteOutlined: We,
    LinkOutlined: Fe,
    DisconnectOutlined: vt
  } = j || {}, { useEffect: Je } = e, ke = "/a2a/agents";
  function _e() {
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
  async function Te(t, n) {
    const o = J(t), i = U == null ? void 0 : U(), l = _e(), c = {
      "Content-Type": "application/json",
      ...i ? { Authorization: `Bearer ${i}` } : {},
      ...l ? { "X-Agent-Id": l } : {}
    }, a = await fetch(o, {
      ...n,
      headers: { ...c, ...(n == null ? void 0 : n.headers) || {} }
    });
    if (!a.ok) {
      const r = await a.text().catch(() => "");
      throw new Error(r || `HTTP ${a.status}`);
    }
    return a.status === 204 || a.headers.get("content-length") === "0" ? null : a.json();
  }
  function ut(t) {
    var r;
    const { agent: n, onClick: o } = t, i = n.status === "connected", l = i ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", c = i ? "已连接" : n.status === "error" ? "错误" : "未连接", a = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      W,
      {
        hoverable: !0,
        onClick: o,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          K,
          null,
          e.createElement(He, { color: l }),
          e.createElement(
            "span",
            null,
            n.name || n.alias || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          H,
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
          Fe ? e.createElement(Fe, { style: { marginRight: 4 } }) : null,
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
            (h, T) => e.createElement(
              H,
              { key: T, style: { fontSize: 11 } },
              h.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            H,
            { style: { fontSize: 11 } },
            `+${n.skills.length - 3}`
          ) : null
        ) : null,
        e.createElement(
          "div",
          { style: { marginTop: 4, color: l, fontSize: 11 } },
          c,
          n.error ? ` - ${n.error}` : ""
        )
      )
    );
  }
  function ft() {
    const t = e.useRef(_e()), [n, o] = v(t.current);
    return Je(() => {
      const i = () => {
        const c = _e();
        c !== t.current && (t.current = c, o(c));
      }, l = setInterval(i, 200);
      return window.addEventListener("storage", i), () => {
        clearInterval(l), window.removeEventListener("storage", i);
      };
    }, []), n;
  }
  function mt() {
    var re, oe;
    const t = ft(), [n, o] = v([]), [i, l] = v(!0), [c, a] = v(!1), [r, h] = v(null), [T, x] = v(!1), [R, L] = v(!1), [Y, C] = v(!1), [S] = V.useForm(), k = G(async () => {
      l(!0);
      try {
        const s = await Te(ke);
        o((s == null ? void 0 : s.agents) || []);
      } catch {
        o([]);
      } finally {
        l(!1);
      }
    }, []);
    Je(() => {
      k();
    }, [t]);
    const _ = G(() => {
      x(!0), h(null), a(!0), S.resetFields(), S.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [S]), d = G((s) => {
      x(!1), h(s), a(!0);
    }, []), u = G(() => {
      a(!1), h(null), x(!1), S.resetFields();
    }, [S]), p = G(async () => {
      let s;
      try {
        s = await S.validateFields();
      } catch {
        return;
      }
      const f = {
        url: String(s.url || "").trim(),
        alias: String(s.alias || "").trim() || void 0,
        auth_type: String(s.auth_type || ""),
        auth_token: String(s.auth_token || "")
      };
      if (f.url) {
        L(!0);
        try {
          await Te(ke, {
            method: "POST",
            body: JSON.stringify(f)
          }), le.success("A2A Agent 注册成功"), await k(), u();
        } catch (A) {
          le.error(A.message || "注册失败");
        } finally {
          L(!1);
        }
      }
    }, [S, k, u]), M = G(async () => {
      if (!r) return;
      const s = r.alias || r.url;
      it.confirm({
        title: `删除 ${s}`,
        content: "确定删除该远程 A2A Agent 吗？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await Te(`${ke}/${encodeURIComponent(s)}`, {
              method: "DELETE"
            }), le.success("A2A Agent 已删除"), await k(), u();
          } catch (f) {
            le.error(f.message || "删除失败");
          }
        }
      });
    }, [r, k, u]), ye = G(async () => {
      if (!r) return;
      const s = r.alias || r.url;
      C(!0);
      try {
        const f = await Te(
          `${ke}/${encodeURIComponent(s)}/refresh`,
          {
            method: "POST"
          }
        );
        le.success("Agent Card 已刷新"), await k(), f && h(f);
      } catch (f) {
        le.error(f.message || "刷新失败");
      } finally {
        C(!1);
      }
    }, [r, k]), ee = ((re = V.useWatch) == null ? void 0 : re.call(V, "auth_type", S)) ?? "", he = e.createElement(
      V,
      { form: S, layout: "vertical" },
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
          Ae,
          { allowClear: !0, placeholder: "无认证" },
          e.createElement(
            Ae.Option,
            { value: "bearer" },
            "Bearer Token"
          ),
          e.createElement(Ae.Option, { value: "api_key" }, "API Key"),
          e.createElement(
            Ae.Option,
            { value: "gateway" },
            "阿里云Agent Hub"
          )
        )
      ),
      ee === "gateway" ? e.createElement(
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
      ee && ee !== "gateway" ? e.createElement(
        V.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(q.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), Ee = r ? e.createElement(
      "div",
      null,
      e.createElement(
        X,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          X.Item,
          { label: "URL" },
          r.url
        ),
        e.createElement(
          X.Item,
          { label: "别名" },
          r.alias || "-"
        ),
        e.createElement(
          X.Item,
          { label: "Agent 名称" },
          r.name || "-"
        ),
        e.createElement(
          X.Item,
          { label: "状态" },
          e.createElement(He, {
            color: r.status === "connected" ? "#52c41a" : r.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: r.status === "connected" ? "已连接" : r.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          X.Item,
          { label: "认证类型" },
          r.auth_type ? e.createElement(
            H,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[r.auth_type] || r.auth_type
          ) : "无认证"
        ),
        e.createElement(
          X.Item,
          { label: "描述" },
          r.description || "-"
        ),
        e.createElement(
          X.Item,
          { label: "版本" },
          r.version || "-"
        )
      ),
      ((oe = r.skills) == null ? void 0 : oe.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...r.skills.map(
          (s, f) => e.createElement(
            W,
            { key: f, size: "small", style: { marginBottom: 8 } },
            e.createElement("strong", null, s.name),
            s.description ? e.createElement(
              "div",
              { style: { color: "#666", fontSize: 12 } },
              s.description
            ) : null
          )
        )
      ) : null,
      r.capabilities ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "能力"),
        e.createElement(
          K,
          null,
          e.createElement(
            H,
            {
              color: r.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            H,
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
        K,
        null,
        e.createElement(
          I,
          {
            type: "primary",
            icon: be ? e.createElement(be) : null,
            loading: Y,
            onClick: ye
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          I,
          {
            danger: !0,
            icon: We ? e.createElement(We) : null,
            onClick: M
          },
          "删除"
        )
      )
    ) : null, ie = e.createElement(
      lt,
      {
        title: T ? "注册远程 A2A Agent" : (r == null ? void 0 : r.name) || (r == null ? void 0 : r.alias) || "Agent 详情",
        open: c,
        onClose: u,
        width: 480,
        footer: T ? e.createElement(
          K,
          { style: { float: "right" } },
          e.createElement(I, { onClick: u }, "取消"),
          e.createElement(
            I,
            { type: "primary", loading: R, onClick: p },
            "注册"
          )
        ) : null
      },
      T ? he : Ee
    ), ce = e.createElement(
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
          K,
          null,
          e.createElement(
            I,
            {
              icon: be ? e.createElement(be) : null,
              onClick: k,
              loading: i
            },
            "刷新列表"
          ),
          e.createElement(
            I,
            {
              type: "primary",
              icon: je ? e.createElement(je) : null,
              onClick: _
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
        xe ? e.createElement(xe, {
          style: { marginRight: 4, color: "#faad14" }
        }) : null,
        "当前 A2A 功能仅支持 CloudPaw 插件连接阿里云 Skills 门户 Agent，连接其他 Agent 可能存在不兼容问题。"
      )
    ), de = i ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(ae, { size: "large" })
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
        (s) => e.createElement(ut, {
          key: s.alias || s.url,
          agent: s,
          onClick: () => d(s)
        })
      )
    );
    return e.createElement(
      "div",
      { style: { padding: 24 } },
      ce,
      de,
      ie
    );
  }
  function pt({ data: t }) {
    var de, re, oe;
    const n = e.useRef(null), [o, i] = v({}), l = se(() => {
      var f, A, g;
      const s = (g = (A = (f = t == null ? void 0 : t.content) == null ? void 0 : f[0]) == null ? void 0 : A.data) == null ? void 0 : g.arguments;
      if (!s) return null;
      try {
        return JSON.parse(s);
      } catch {
        return null;
      }
    }, [(oe = (re = (de = t == null ? void 0 : t.content) == null ? void 0 : de[0]) == null ? void 0 : re.data) == null ? void 0 : oe.arguments]), { toolResult: c, rawErrorText: a } = se(() => {
      var f;
      const s = t == null ? void 0 : t.content;
      if (!Array.isArray(s))
        return { toolResult: null, rawErrorText: "" };
      for (const A of s) {
        const g = (f = A == null ? void 0 : A.data) == null ? void 0 : f.output;
        if (!g) continue;
        let P = "";
        if (Array.isArray(g)) {
          const w = g.find(
            (m) => (m == null ? void 0 : m.type) === "text" && (m == null ? void 0 : m.text)
          );
          P = (w == null ? void 0 : w.text) || "";
        } else if (typeof g == "string")
          try {
            const w = JSON.parse(g);
            if (typeof w == "object" && (w != null && w.steps || w != null && w.response_text))
              return { toolResult: w, rawErrorText: "" };
            if (Array.isArray(w)) {
              const m = w.find((y) => (y == null ? void 0 : y.type) === "text" && (y == null ? void 0 : y.text));
              m != null && m.text && (P = m.text);
            }
          } catch {
            P = g;
          }
        if (P)
          try {
            return { toolResult: JSON.parse(P), rawErrorText: "" };
          } catch {
            return { toolResult: null, rawErrorText: P };
          }
      }
      return { toolResult: null, rawErrorText: "" };
    }, [t == null ? void 0 : t.content]), r = (c == null ? void 0 : c.steps) || [], h = (c == null ? void 0 : c.task_state) || "", T = (c == null ? void 0 : c.error) || "", x = (c == null ? void 0 : c.response_text) || "";
    e.useEffect(() => {
      n.current && (n.current.scrollTop = n.current.scrollHeight);
    }, [r.length, x, a]), e.useEffect(() => {
      const s = { ...o };
      let f = !1;
      r.forEach((A, g) => {
        o[g] === void 0 && (A.type === "thinking" && A.done || A.type === "tool_call" && A.status !== "running") && (s[g] = !0, f = !0);
      }), f && i(s);
    }, [r]);
    const R = (l == null ? void 0 : l.agent_alias) || "", L = (l == null ? void 0 : l.agent_url) || "", Y = R || L || "远程 Agent", C = {
      completed: { color: "#52c41a", text: "已完成" },
      TASK_STATE_COMPLETED: { color: "#52c41a", text: "已完成" },
      failed: { color: "#ff4d4f", text: "失败" },
      TASK_STATE_FAILED: { color: "#ff4d4f", text: "失败" },
      error: { color: "#ff4d4f", text: "出错" },
      canceled: { color: "#faad14", text: "已取消" },
      TASK_STATE_CANCELED: { color: "#faad14", text: "已取消" },
      AWAITING_USER_INPUT: { color: "#1677ff", text: "等待输入" },
      input_required: { color: "#1677ff", text: "等待输入" }
    }, _ = (c !== null || !!a) && !(h === "working" || h === "TASK_STATE_WORKING");
    let d = "#1677ff", u = "执行中...";
    _ && (C[h] ? (d = C[h].color, u = C[h].text) : a ? (d = "#ff4d4f", u = "出错") : (d = "#52c41a", u = "已完成"));
    const p = e.createElement(
      K,
      { size: 6 },
      e.createElement("span", { style: { fontSize: 13 } }, "🔗"),
      e.createElement(
        F,
        { style: { fontSize: 12, color: "#595959" } },
        `A2A: ${Y}`
      ),
      e.createElement(
        H,
        { color: d, style: { fontSize: 11, lineHeight: "18px" } },
        u
      )
    ), M = r.length === 0 && !a && !T, ye = !_ && M ? e.createElement(
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
      e.createElement(ae, { size: "small" }),
      e.createElement(
        F,
        { style: { fontSize: 12, color: "#52c41a" } },
        `正在连接 ${Y}...`
      )
    ) : null;
    function ee(s) {
      i((f) => ({
        ...f,
        [s]: !f[s]
      }));
    }
    function he(s, f) {
      const A = !!o[f];
      if (s.type === "thinking") {
        const g = !!s.done, P = g ? "💭" : "🧠", w = g ? "思考完成" : "思考中...", m = e.createElement(
          "div",
          {
            key: `step-${f}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: g ? "pointer" : "default",
              fontSize: 12,
              color: "#8c8c8c"
            },
            onClick: g ? () => ee(f) : void 0
          },
          g && e.createElement(
            "span",
            { style: { fontSize: 10, color: "#bfbfbf" } },
            A ? "▶" : "▼"
          ),
          e.createElement("span", null, P),
          e.createElement("span", null, w),
          !g && e.createElement(ae, {
            size: "small",
            style: { marginLeft: 4 }
          })
        );
        return A ? m : e.createElement(
          "div",
          { key: `step-${f}` },
          m,
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
            s.text || ""
          )
        );
      }
      if (s.type === "tool_call") {
        const g = s.status === "running", P = s.status === "error", w = g ? "⚙️" : P ? "❌" : "✅", m = g ? `正在执行: ${s.name}` : P ? `执行失败: ${s.name}` : `执行完成: ${s.name}`, y = g ? "#1677ff" : P ? "#ff4d4f" : "#52c41a", E = e.createElement(
          "div",
          {
            key: `step-${f}`,
            style: {
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 0",
              cursor: g ? "default" : "pointer",
              fontSize: 12,
              color: y
            },
            onClick: g ? void 0 : () => ee(f)
          },
          !g && e.createElement(
            "span",
            { style: { fontSize: 10, color: "#bfbfbf" } },
            A ? "▶" : "▼"
          ),
          e.createElement("span", null, w),
          e.createElement("span", null, m),
          g && e.createElement(ae, {
            size: "small",
            style: { marginLeft: 4 }
          })
        );
        return A || !s.desc && !g ? E : e.createElement(
          "div",
          { key: `step-${f}` },
          E,
          s.desc && e.createElement(
            "div",
            {
              style: {
                marginLeft: 20,
                padding: "2px 8px",
                fontSize: 11,
                color: "#8c8c8c"
              }
            },
            s.desc
          )
        );
      }
      return s.type === "text" ? e.createElement(
        "div",
        {
          key: `step-${f}`,
          style: {
            padding: "4px 0",
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6",
            color: "#262626"
          }
        },
        s.text || ""
      ) : null;
    }
    const Ee = r.length > 0 ? e.createElement(
      "div",
      {
        ref: n,
        style: {
          background: "#fafafa",
          border: "1px solid #e8e8e8",
          borderRadius: 6,
          padding: "6px 10px",
          maxHeight: 200,
          overflowY: "auto"
        }
      },
      ...r.map(he)
    ) : null, ie = a || T ? e.createElement(
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
      T ? `错误: ${T}` : a
    ) : null, ce = !r.length && x && !a ? e.createElement(
      "div",
      {
        ref: n,
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
        F,
        {
          style: {
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6"
          }
        },
        x
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
      e.createElement("div", { style: { marginBottom: 6 } }, p),
      ye,
      Ee,
      ce,
      ie
    );
  }
  const gt = "__A2A_STREAM_START__", yt = "A2A_STREAM_START", ge = /* @__PURE__ */ new Set();
  function Ie(t) {
    return t ? t.includes(gt) || t.includes(yt) : !1;
  }
  function Re(t) {
    var n, o;
    return t.getAttribute("data-msg-id") || t.getAttribute("data-message-id") || ((n = t.closest("[data-msg-id]")) == null ? void 0 : n.getAttribute("data-msg-id")) || ((o = t.closest("[data-message-id]")) == null ? void 0 : o.getAttribute("data-message-id")) || null;
  }
  function ht(t) {
    if (Ie(t.innerHTML) || Ie(t.textContent))
      return t;
    const n = document.createTreeWalker(
      t,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    for (; n.nextNode(); ) {
      const o = n.currentNode, i = o.nodeType === Node.TEXT_NODE ? o.textContent : o.innerHTML;
      if (Ie(i)) {
        const l = o.nodeType === Node.TEXT_NODE ? o.parentElement : o;
        if (l) return l;
      }
    }
    return null;
  }
  async function ze(t) {
    var h, T;
    const n = window.QwenPaw;
    if (!(n != null && n.host)) {
      console.warn("[a2a] QwenPaw.host not available");
      return;
    }
    const { getApiUrl: o, getApiToken: i } = n.host, l = o("/a2a/call/stream"), c = i();
    console.log("[a2a] Subscribing to SSE stream:", l);
    const a = document.createElement("div");
    a.style.cssText = "background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px;padding:12px 16px;margin:4px 0;font-size:13px;white-space:pre-wrap;word-break:break-word;color:#262626;min-height:24px;", a.textContent = "正在连接远程 Agent...", t.textContent = "", t.appendChild(a);
    const r = new AbortController();
    try {
      const x = {
        Accept: "text/event-stream"
      };
      c && (x.Authorization = `Bearer ${c}`);
      try {
        const S = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage"), k = (T = (h = JSON.parse(S || "{}")) == null ? void 0 : h.state) == null ? void 0 : T.selectedAgent;
        k && (x["X-Agent-Id"] = k);
      } catch {
      }
      console.log("[a2a] Fetching SSE with headers:", x);
      const R = await fetch(l, { headers: x, signal: r.signal });
      if (console.log("[a2a] SSE response status:", R.status), !R.ok) {
        const S = await R.text().catch(() => "");
        a.textContent = `SSE 连接失败 (${R.status}): ${S.slice(
          0,
          100
        )}`, a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0";
        return;
      }
      if (!R.body) {
        a.textContent = "SSE 连接失败：无响应体", a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0";
        return;
      }
      const L = R.body.getReader(), Y = new TextDecoder();
      let C = "";
      for (; ; ) {
        const { done: S, value: k } = await L.read();
        if (S) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }
        C += Y.decode(k, { stream: !0 });
        const _ = C.split(`
`);
        C = _.pop() || "";
        for (const d of _)
          if (d.startsWith("data: "))
            try {
              const u = JSON.parse(d.slice(6));
              if (console.log("[a2a] SSE event:", u), u.done) {
                u.error && (a.textContent = `错误: ${u.error}`, a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0"), console.log("[a2a] SSE done signal received");
                return;
              }
              typeof u.response_text == "string" && u.response_text && (a.textContent = u.response_text);
            } catch (u) {
              console.warn("[a2a] SSE parse error:", u, "line:", d);
            }
      }
    } catch (x) {
      (x == null ? void 0 : x.name) !== "AbortError" && (console.error("[a2a] SSE subscription error:", x), a.textContent = `连接出错: ${(x == null ? void 0 : x.message) || x}`, a.style.borderColor = "#ff4d4f", a.style.background = "#fff1f0");
    }
  }
  function Et() {
    console.log("[a2a] Initializing stream interceptor");
    function t(l) {
      if (l.nodeType !== Node.ELEMENT_NODE) return;
      const c = l, a = Re(c);
      if (a && ge.has(a)) return;
      const r = ht(c);
      r && (console.log("[a2a] Marker detected in DOM, msgId:", a), a && ge.add(a), ze(r));
    }
    new MutationObserver((l) => {
      for (const c of l) {
        for (const a of c.addedNodes)
          t(a);
        c.target.nodeType === Node.ELEMENT_NODE && t(c.target);
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
      for (let c = 0; c < l.snapshotLength; c++) {
        const r = l.snapshotItem(c).parentElement;
        if (r) {
          const h = Re(r);
          if (h && ge.has(h)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", h), h && ge.add(h), ze(r);
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
    for (let l = 0; l < i.snapshotLength; l++) {
      const a = i.snapshotItem(l).parentElement;
      if (a) {
        const r = Re(a);
        r && ge.add(r), console.log("[a2a] Marker found in existing DOM, msgId:", r), ze(a);
      }
    }
  }
  (Ue = (Ke = window.QwenPaw).registerToolRender) == null || Ue.call(Ke, "cloudpaw", {
    proposal_choice: at,
    manage_prd: st,
    a2a_call: pt
  }), (Ye = (qe = window.QwenPaw).registerRoutes) == null || Ye.call(qe, "cloudpaw", [
    {
      path: "/a2a",
      component: mt,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), At(), bt(), Et();
}
function At() {
  const e = "qwenpaw-last-used-agent", D = "qwenpaw-agent-storage", j = "cloudpaw-first-install", J = "cloud-orchestrator";
  if (localStorage.getItem(j)) return;
  localStorage.setItem(j, "true");
  function U() {
    localStorage.setItem(e, J);
    try {
      const W = localStorage.getItem(D);
      if (W) {
        const z = JSON.parse(W);
        z.state = z.state || {}, z.state.selectedAgent = J, localStorage.setItem(D, JSON.stringify(z));
      } else
        localStorage.setItem(
          D,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: J,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const W = sessionStorage.getItem(D);
      if (W) {
        const z = JSON.parse(W);
        z.state = z.state || {}, z.state.selectedAgent = J, sessionStorage.setItem(D, JSON.stringify(z));
      } else
        sessionStorage.setItem(
          D,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: J,
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
function bt() {
  var K;
  const e = (K = window.QwenPaw) == null ? void 0 : K.modules;
  if (!e) return;
  const D = e["Chat/OptionsPanel/defaultConfig"];
  if (!(D != null && D.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const j = D.configProvider, J = j.getConfig.bind(j), U = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", W = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, z = {
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
  }, H = {
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
  function me() {
    const I = localStorage.getItem("language") || "";
    return I ? I.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (j.getGreeting = () => W[me()] || W.en, j.getDescription = () => z[me()] || z.en, j.getPrompts = () => H[me()] || H.en, j.getConfig = function(I) {
    var pe;
    const q = J(I);
    return {
      ...q,
      theme: {
        ...q.theme,
        leftHeader: {
          ...(pe = q.theme) == null ? void 0 : pe.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...q.welcome,
        avatar: U
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const I = document.createElement("style");
    I.id = "cloudpaw-welcome-style", I.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(I);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
St();
