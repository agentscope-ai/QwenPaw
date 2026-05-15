function St() {
  var We, Fe, Je, Ue;
  const { React: e, antd: v, antdIcons: N, getApiUrl: B, getApiToken: j } = window.QwenPaw.host, {
    Card: M,
    Table: b,
    Tag: D,
    Typography: te,
    Space: H,
    Button: x,
    Input: W,
    Radio: ne,
    Collapse: bt,
    Descriptions: F,
    Tooltip: _e,
    Spin: Ee,
    message: Re
  } = v, { Text: J } = te, { TextArea: Ye } = W, { useState: A, useMemo: se, useCallback: U, useRef: Ct } = e, {
    InfoCircleOutlined: ae,
    DownOutlined: Pe,
    RightOutlined: Ge,
    CheckCircleOutlined: le,
    FieldTimeOutlined: ie,
    FileTextOutlined: Oe
  } = N || {};
  function ze(t) {
    var a, l;
    const n = (l = (a = t == null ? void 0 : t.content) == null ? void 0 : a[0]) == null ? void 0 : l.data, o = n == null ? void 0 : n.arguments;
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
  function K(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function Ze(t) {
    if (t == null) return !0;
    const n = K(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function et(t, n) {
    try {
      const o = j(), a = {
        "Content-Type": "application/json"
      };
      return o && (a.Authorization = `Bearer ${o}`), (await fetch(B("/interaction"), {
        method: "POST",
        headers: a,
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
            (a) => (a == null ? void 0 : a.type) === "text" && (a == null ? void 0 : a.text)
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
    var s, r;
    if (!t || t.length < 2) return null;
    const n = (r = (s = t[1]) == null ? void 0 : s.data) == null ? void 0 : r.output, o = Ne(n);
    if (!o) return null;
    if (o.startsWith("Error:")) return o;
    const a = o.match(/^用户选择了「(.+?)」并确认部署$/);
    if (a) return `已确认部署「${a[1]}」`;
    const l = o.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/
    );
    if (l)
      return `已选择「${l[1]}」并调整：${l[2]}`;
    if (o === "用户确认部署") return "已确认部署";
    const d = o.match(/^用户要求调整资源[：:](.+)$/);
    return d ? `已反馈调整意见：${d[1]}` : "已确认";
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
  function we(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = K(t[0]).trim().toLowerCase();
    return nt.has(n);
  }
  function De(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = K(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function rt(t) {
    const n = [];
    let o = [];
    for (const a of t)
      o.push(a), De(a) && (n.push(o), o = []);
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
    var Ke, qe, Xe;
    const [n, o] = A("confirm"), [a, l] = A(""), [d, s] = A(!1), [r, p] = A(null), [O, g] = A(
      {}
    ), I = e.useRef(!1), $ = e.useRef(null), [, G] = A(0), _ = t == null ? void 0 : t.content, E = _ && _.length >= 2 && ((qe = (Ke = _[1]) == null ? void 0 : Ke.data) == null ? void 0 : qe.output), w = se(
      () => tt(_),
      [_]
    ), R = I.current || E || w !== null, i = se(() => {
      const S = ze(t), y = S == null ? void 0 : S.data;
      if (!y) return null;
      try {
        const m = typeof y == "string" ? JSON.parse(y) : y;
        let C;
        if (S.strategy_names)
          try {
            const T = typeof S.strategy_names == "string" ? JSON.parse(S.strategy_names) : S.strategy_names;
            C = Array.isArray(T) ? T : [];
          } catch {
            C = [];
          }
        else m != null && m.proposal_names ? C = m.proposal_names : C = [];
        const Q = C.length >= 2 ? C.length : 0;
        let k;
        if (Array.isArray(m) && m.length > 0)
          if (Array.isArray(m[0]) && m[0].length === 10 && !Array.isArray(m[0][0])) {
            const P = m.filter(
              (Y) => !we(Y)
            );
            if (P.filter(
              (Y) => De(Y)
            ).length >= 2)
              k = rt(P);
            else if (Q >= 2 && P.length >= Q * 2) {
              const Y = Math.ceil(P.length / Q);
              k = [];
              for (let ee = 0; ee < P.length; ee += Y)
                k.push(P.slice(ee, ee + Y));
            } else
              k = [P];
          } else
            k = m.map(
              (P) => P.filter(
                (Z) => Array.isArray(Z) && Z.length === 10 && !we(Z)
              )
            );
        else if (m != null && m.proposals)
          k = m.proposals.map(
            (T) => T.filter((P) => !we(P))
          );
        else
          return null;
        if (k = k.filter((T) => T.length > 0), k.length === 0) return null;
        const he = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (C.length < k.length)
          for (let T = C.length; T < k.length; T++)
            C.push(he[T] || `方案${T + 1}`);
        return { proposals: k, names: C };
      } catch {
        return null;
      }
    }, [t]), c = Ve(), u = (((Xe = i == null ? void 0 : i.proposals) == null ? void 0 : Xe.length) ?? 0) > 1, L = U(async () => {
      if (!c || R || !i) return;
      const S = u ? r : 0, y = i.names[S ?? 0] || `方案${(S ?? 0) + 1}`;
      let m;
      n === "confirm" ? m = `用户选择了「${y}」并确认部署` : m = `用户选择「${y}」并要求调整：${a.trim() || "未填写具体要求"}`, s(!0);
      const C = await et(c, m);
      s(!1), C ? (I.current = !0, n === "confirm" ? $.current = `已确认部署「${y}」` : $.current = `已选择「${y}」并调整：${a.trim()}`, G((Q) => Q + 1), Re.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : Re.error("操作失败，请重试");
    }, [
      c,
      R,
      i,
      n,
      a,
      r,
      u
    ]), Ce = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created";
    if (!i)
      return Ce ? e.createElement(
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
          J,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        M,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(J, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: oe, names: ke } = i, Te = Me.map((S, y) => ({
      title: S,
      dataIndex: `col_${y}`,
      key: `col_${y}`,
      render: (m) => ot(m),
      ellipsis: y < 3
    }));
    let me = "待确认", pe = "processing";
    R && (pe = "success", me = $.current || w || "已确认");
    const ve = e.createElement(
      D,
      {
        color: pe,
        style: { marginLeft: 4 }
      },
      me
    ), ge = e.createElement(
      H,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        J,
        { strong: !0, style: { fontSize: 14 } },
        R ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      ve
    ), ye = oe.map((S, y) => {
      const m = u ? r === y : !0, C = O[y] || !1, Q = (h) => {
        const X = K(h[0] || "").trim();
        return /^合计|^总计|^total/i.test(X);
      }, k = S.find(Q), he = S.filter((h) => !Q(h)), T = he.map((h) => ({
        type: K(h[0] || ""),
        purpose: K(h[1] || ""),
        spec: K(h[2] || ""),
        cost: h[9] ?? null
      })), P = k ? K(k[9] ?? "") : "", Z = S.map((h, X) => {
        const Qe = { key: X };
        return h.forEach((Et, wt) => {
          Qe[`col_${wt}`] = Et;
        }), Qe;
      }), Y = m ? "2px solid #1677ff" : "1px solid #e8e8e8", ee = m ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: y,
          style: {
            flex: 1,
            minWidth: 240,
            border: Y,
            borderRadius: 8,
            cursor: u ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: ee,
            background: "#fff"
          },
          onClick: u ? () => p(y) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            J,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            ke[y]
          ),
          ...T.map(
            (h, X) => e.createElement(
              "div",
              {
                key: X,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: X < T.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  h.type
                ),
                h.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  h.spec
                )
              ),
              !Ze(h.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                K(h.cost)
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
              onClick: (h) => {
                h.stopPropagation(), g((X) => ({
                  ...X,
                  [y]: !X[y]
                }));
              }
            },
            e.createElement(
              C && Pe ? Pe : Ge || "span",
              {
                style: { fontSize: 10 }
              }
            ),
            e.createElement(
              "span",
              null,
              `明细 · ${he.length} 项`
            )
          ),
          C && e.createElement(
            "div",
            {
              onClick: (h) => h.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(b, {
              columns: Te,
              dataSource: Z,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), f = e.createElement(
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
      ae ? e.createElement(ae, {
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
    ), z = !R && c && !(u && r === null) && e.createElement(
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
          e.createElement(ne, { checked: n === "confirm" }),
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
            e.createElement(ne, { checked: n === "adjust" }),
            e.createElement(
              "span",
              { style: { fontSize: 13 } },
              "调整资源"
            )
          ),
          n === "adjust" && e.createElement(Ye, {
            value: a,
            onChange: (S) => l(S.target.value),
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
          J,
          { type: "secondary", style: { fontSize: 11 } },
          u ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          x,
          {
            type: "primary",
            size: "small",
            loading: d,
            onClick: L,
            disabled: n === "adjust" && !a.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), Ie = u && r === null && !R && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, ge),
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
        ...ye
      ),
      Ie,
      f,
      !R && z
    );
  }
  function at({ data: t }) {
    const [n, o] = A(null), [a, l] = A(!1), d = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", s = se(() => {
      const i = ze(t);
      return (i == null ? void 0 : i.loop_dir) || null;
    }, [t]), r = se(() => {
      var c, u, L;
      const i = Ne((L = (u = (c = t == null ? void 0 : t.content) == null ? void 0 : c[1]) == null ? void 0 : u.data) == null ? void 0 : L.output);
      if (!i) return null;
      try {
        return JSON.parse(i);
      } catch {
        return null;
      }
    }, [t]), p = (r == null ? void 0 : r.status) === "ok", O = (r == null ? void 0 : r.status) === "error", g = O ? (r == null ? void 0 : r.message) || "未知错误" : null, I = U(async () => {
      if (s)
        try {
          const i = j(), c = {};
          i && (c.Authorization = `Bearer ${i}`);
          const u = await fetch(
            B(`/prd?loop_dir=${encodeURIComponent(s)}`),
            { headers: c }
          );
          if (!u.ok) {
            l(!0);
            return;
          }
          const L = await u.json();
          L && Array.isArray(L.userStories) ? (o(L), l(!1)) : l(!0);
        } catch {
          l(!0);
        }
    }, [s]);
    if (e.useEffect(() => {
      !d && p && s && I();
    }, [d, p, s, I]), d)
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
          J,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD..."
        )
      );
    if (O)
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
          J,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${g}`
        )
      );
    if (!p || a || !n) return null;
    const $ = n.userStories, G = [...$].sort(
      (i, c) => (i.priority || 99) - (c.priority || 99)
    ), _ = $.filter((i) => i.passes).length, E = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (i, c) => {
          if (c.passes) {
            const L = le ? e.createElement(le, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(_e, { title: "已完成" }, L);
          }
          const u = ie ? e.createElement(ie, {
            style: { color: "#faad14", fontSize: 18 }
          }) : "🕐";
          return e.createElement(_e, { title: "待处理" }, u);
        }
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (i) => e.createElement(D, { color: "blue" }, i)
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (i) => e.createElement(J, { strong: !0 }, i)
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (i, c) => {
          const u = c.priority;
          return e.createElement(
            D,
            { color: "default" },
            u != null ? String(u) : "-"
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
          const u = c.acceptanceCriteria;
          return typeof u == "string" ? e.createElement(
            "div",
            {
              style: { fontSize: 12, color: "#666", whiteSpace: "pre-wrap" }
            },
            u.length > 100 ? u.slice(0, 100) + "..." : u
          ) : Array.isArray(u) ? e.createElement(
            "div",
            { style: { fontSize: 12, color: "#666" } },
            u.length > 2 ? u.slice(0, 2).join(", ") + "..." : u.join(", ")
          ) : "-";
        }
      }
    ], w = e.createElement(
      H,
      { size: 8 },
      Oe ? e.createElement(Oe, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(J, { strong: !0 }, n.project || "PRD")
      )
    ), R = e.createElement(b, {
      columns: E,
      dataSource: G.map((i) => ({ ...i, key: i.id })),
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
      e.createElement("div", { style: { marginBottom: 8 } }, w),
      e.createElement(F, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: !1,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${_}/${$.length} 完成`
          }
        ]
      }),
      R,
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
        le ? e.createElement(le, {
          style: { color: "#52c41a", fontSize: 14 }
        }) : "✅",
        e.createElement("span", null, "已完成"),
        e.createElement("span", { style: { margin: "0 4px" } }, "·"),
        ie ? e.createElement(ie, {
          style: { color: "#faad14", fontSize: 14 }
        }) : "🕐",
        e.createElement("span", null, "待处理")
      )
    );
  }
  const {
    Form: q,
    Select: ce,
    Drawer: lt,
    Modal: it,
    Empty: ct,
    Badge: $e,
    Divider: dt,
    message: V
  } = v, {
    ApiOutlined: kt,
    PlusOutlined: Le,
    ReloadOutlined: de,
    DeleteOutlined: Be,
    LinkOutlined: je,
    DisconnectOutlined: Tt
  } = N || {}, { useEffect: He } = e, ue = "/a2a/agents";
  function Se() {
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
  async function fe(t, n) {
    const o = B(t), a = j == null ? void 0 : j(), l = Se(), d = {
      "Content-Type": "application/json",
      ...a ? { Authorization: `Bearer ${a}` } : {},
      ...l ? { "X-Agent-Id": l } : {}
    }, s = await fetch(o, {
      ...n,
      headers: { ...d, ...(n == null ? void 0 : n.headers) || {} }
    });
    if (!s.ok) {
      const r = await s.text().catch(() => "");
      throw new Error(r || `HTTP ${s.status}`);
    }
    return s.status === 204 || s.headers.get("content-length") === "0" ? null : s.json();
  }
  function ut(t) {
    var r;
    const { agent: n, onClick: o } = t, a = n.status === "connected", l = a ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", d = a ? "已连接" : n.status === "error" ? "错误" : "未连接", s = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      M,
      {
        hoverable: !0,
        onClick: o,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          H,
          null,
          e.createElement($e, { color: l }),
          e.createElement(
            "span",
            null,
            n.name || n.alias || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          D,
          { color: "blue" },
          s[n.auth_type] || n.auth_type
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
            (p, O) => e.createElement(
              D,
              { key: O, style: { fontSize: 11 } },
              p.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            D,
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
    const t = e.useRef(Se()), [n, o] = A(t.current);
    return He(() => {
      const a = () => {
        const d = Se();
        d !== t.current && (t.current = d, o(d));
      }, l = setInterval(a, 200);
      return window.addEventListener("storage", a), () => {
        clearInterval(l), window.removeEventListener("storage", a);
      };
    }, []), n;
  }
  function mt() {
    var ge, ye;
    const t = ft(), [n, o] = A([]), [a, l] = A(!0), [d, s] = A(!1), [r, p] = A(null), [O, g] = A(!1), [I, $] = A(!1), [G, _] = A(!1), [E] = q.useForm(), w = U(async () => {
      l(!0);
      try {
        const f = await fe(ue);
        o((f == null ? void 0 : f.agents) || []);
      } catch {
        o([]);
      } finally {
        l(!1);
      }
    }, []);
    He(() => {
      w();
    }, [t]);
    const R = U(() => {
      g(!0), p(null), s(!0), E.resetFields(), E.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [E]), i = U((f) => {
      g(!1), p(f), s(!0);
    }, []), c = U(() => {
      s(!1), p(null), g(!1), E.resetFields();
    }, [E]), u = U(async () => {
      let f;
      try {
        f = await E.validateFields();
      } catch {
        return;
      }
      const z = {
        url: String(f.url || "").trim(),
        alias: String(f.alias || "").trim() || void 0,
        auth_type: String(f.auth_type || ""),
        auth_token: String(f.auth_token || "")
      };
      if (z.url) {
        $(!0);
        try {
          await fe(ue, {
            method: "POST",
            body: JSON.stringify(z)
          }), V.success("A2A Agent 注册成功"), await w(), c();
        } catch (Ie) {
          V.error(Ie.message || "注册失败");
        } finally {
          $(!1);
        }
      }
    }, [E, w, c]), L = U(async () => {
      if (!r) return;
      const f = r.alias || r.url;
      it.confirm({
        title: `删除 ${f}`,
        content: "确定删除该远程 A2A Agent 吗？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await fe(`${ue}/${encodeURIComponent(f)}`, {
              method: "DELETE"
            }), V.success("A2A Agent 已删除"), await w(), c();
          } catch (z) {
            V.error(z.message || "删除失败");
          }
        }
      });
    }, [r, w, c]), Ce = U(async () => {
      if (!r) return;
      const f = r.alias || r.url;
      _(!0);
      try {
        const z = await fe(
          `${ue}/${encodeURIComponent(f)}/refresh`,
          {
            method: "POST"
          }
        );
        V.success("Agent Card 已刷新"), await w(), z && p(z);
      } catch (z) {
        V.error(z.message || "刷新失败");
      } finally {
        _(!1);
      }
    }, [r, w]), oe = ((ge = q.useWatch) == null ? void 0 : ge.call(q, "auth_type", E)) ?? "", ke = e.createElement(
      q,
      { form: E, layout: "vertical" },
      e.createElement(
        q.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: !0, message: "请输入 Agent URL" }]
        },
        e.createElement(W, {
          placeholder: "https://agent.example.com"
        })
      ),
      e.createElement(
        q.Item,
        { name: "alias", label: "别名" },
        e.createElement(W, { placeholder: "输入别名（可选）" })
      ),
      e.createElement(
        q.Item,
        { name: "auth_type", label: "认证类型" },
        e.createElement(
          ce,
          { allowClear: !0, placeholder: "无认证" },
          e.createElement(
            ce.Option,
            { value: "bearer" },
            "Bearer Token"
          ),
          e.createElement(ce.Option, { value: "api_key" }, "API Key"),
          e.createElement(
            ce.Option,
            { value: "gateway" },
            "阿里云Agent Hub"
          )
        )
      ),
      oe === "gateway" ? e.createElement(
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
      oe && oe !== "gateway" ? e.createElement(
        q.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(W.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), Te = r ? e.createElement(
      "div",
      null,
      e.createElement(
        F,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          F.Item,
          { label: "URL" },
          r.url
        ),
        e.createElement(
          F.Item,
          { label: "别名" },
          r.alias || "-"
        ),
        e.createElement(
          F.Item,
          { label: "Agent 名称" },
          r.name || "-"
        ),
        e.createElement(
          F.Item,
          { label: "状态" },
          e.createElement($e, {
            color: r.status === "connected" ? "#52c41a" : r.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: r.status === "connected" ? "已连接" : r.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          F.Item,
          { label: "认证类型" },
          r.auth_type ? e.createElement(
            D,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[r.auth_type] || r.auth_type
          ) : "无认证"
        ),
        e.createElement(
          F.Item,
          { label: "描述" },
          r.description || "-"
        ),
        e.createElement(
          F.Item,
          { label: "版本" },
          r.version || "-"
        )
      ),
      ((ye = r.skills) == null ? void 0 : ye.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...r.skills.map(
          (f, z) => e.createElement(
            M,
            { key: z, size: "small", style: { marginBottom: 8 } },
            e.createElement("strong", null, f.name),
            f.description ? e.createElement(
              "div",
              { style: { color: "#666", fontSize: 12 } },
              f.description
            ) : null
          )
        )
      ) : null,
      r.capabilities ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "能力"),
        e.createElement(
          H,
          null,
          e.createElement(
            D,
            {
              color: r.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            D,
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
        H,
        null,
        e.createElement(
          x,
          {
            type: "primary",
            icon: de ? e.createElement(de) : null,
            loading: G,
            onClick: Ce
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          x,
          {
            danger: !0,
            icon: Be ? e.createElement(Be) : null,
            onClick: L
          },
          "删除"
        )
      )
    ) : null, me = e.createElement(
      lt,
      {
        title: O ? "注册远程 A2A Agent" : (r == null ? void 0 : r.name) || (r == null ? void 0 : r.alias) || "Agent 详情",
        open: d,
        onClose: c,
        width: 480,
        footer: O ? e.createElement(
          H,
          { style: { float: "right" } },
          e.createElement(x, { onClick: c }, "取消"),
          e.createElement(
            x,
            { type: "primary", loading: I, onClick: u },
            "注册"
          )
        ) : null
      },
      O ? ke : Te
    ), pe = e.createElement(
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
          H,
          null,
          e.createElement(
            x,
            {
              icon: de ? e.createElement(de) : null,
              onClick: w,
              loading: a
            },
            "刷新列表"
          ),
          e.createElement(
            x,
            {
              type: "primary",
              icon: Le ? e.createElement(Le) : null,
              onClick: R
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
        ae ? e.createElement(ae, {
          style: { marginRight: 4, color: "#faad14" }
        }) : null,
        "当前 A2A 功能仅支持 CloudPaw 插件连接阿里云 Skills 门户 Agent，连接其他 Agent 可能存在不兼容问题。"
      )
    ), ve = a ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(Ee, { size: "large" })
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
        (f) => e.createElement(ut, {
          key: f.alias || f.url,
          agent: f,
          onClick: () => i(f)
        })
      )
    );
    return e.createElement(
      "div",
      { style: { padding: 24 } },
      pe,
      ve,
      me
    );
  }
  const pt = "__A2A_STREAM_START__", gt = "A2A_STREAM_START", re = /* @__PURE__ */ new Set();
  function xe(t) {
    return t ? t.includes(pt) || t.includes(gt) : !1;
  }
  function Ae(t) {
    var n, o;
    return t.getAttribute("data-msg-id") || t.getAttribute("data-message-id") || ((n = t.closest("[data-msg-id]")) == null ? void 0 : n.getAttribute("data-msg-id")) || ((o = t.closest("[data-message-id]")) == null ? void 0 : o.getAttribute("data-message-id")) || null;
  }
  function yt(t) {
    if (xe(t.innerHTML) || xe(t.textContent))
      return t;
    const n = document.createTreeWalker(
      t,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    for (; n.nextNode(); ) {
      const o = n.currentNode, a = o.nodeType === Node.TEXT_NODE ? o.textContent : o.innerHTML;
      if (xe(a)) {
        const l = o.nodeType === Node.TEXT_NODE ? o.parentElement : o;
        if (l) return l;
      }
    }
    return null;
  }
  async function be(t) {
    var p, O;
    const n = window.QwenPaw;
    if (!(n != null && n.host)) {
      console.warn("[a2a] QwenPaw.host not available");
      return;
    }
    const { getApiUrl: o, getApiToken: a } = n.host, l = o("/a2a/call/stream"), d = a();
    console.log("[a2a] Subscribing to SSE stream:", l);
    const s = document.createElement("div");
    s.style.cssText = "background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px;padding:12px 16px;margin:4px 0;font-size:13px;white-space:pre-wrap;word-break:break-word;color:#262626;min-height:24px;", s.textContent = "正在连接远程 Agent...", t.textContent = "", t.appendChild(s);
    const r = new AbortController();
    try {
      const g = {
        Accept: "text/event-stream"
      };
      d && (g.Authorization = `Bearer ${d}`);
      try {
        const E = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage"), w = (O = (p = JSON.parse(E || "{}")) == null ? void 0 : p.state) == null ? void 0 : O.selectedAgent;
        w && (g["X-Agent-Id"] = w);
      } catch {
      }
      console.log("[a2a] Fetching SSE with headers:", g);
      const I = await fetch(l, { headers: g, signal: r.signal });
      if (console.log("[a2a] SSE response status:", I.status), !I.ok) {
        const E = await I.text().catch(() => "");
        s.textContent = `SSE 连接失败 (${I.status}): ${E.slice(0, 100)}`, s.style.borderColor = "#ff4d4f", s.style.background = "#fff1f0";
        return;
      }
      if (!I.body) {
        s.textContent = "SSE 连接失败：无响应体", s.style.borderColor = "#ff4d4f", s.style.background = "#fff1f0";
        return;
      }
      const $ = I.body.getReader(), G = new TextDecoder();
      let _ = "";
      for (; ; ) {
        const { done: E, value: w } = await $.read();
        if (E) {
          console.log("[a2a] SSE stream ended (done)");
          break;
        }
        _ += G.decode(w, { stream: !0 });
        const R = _.split(`
`);
        _ = R.pop() || "";
        for (const i of R)
          if (i.startsWith("data: "))
            try {
              const c = JSON.parse(i.slice(6));
              if (console.log("[a2a] SSE event:", c), c.done) {
                c.error && (s.textContent = `错误: ${c.error}`, s.style.borderColor = "#ff4d4f", s.style.background = "#fff1f0"), console.log("[a2a] SSE done signal received");
                return;
              }
              typeof c.response_text == "string" && c.response_text && (s.textContent = c.response_text);
            } catch (c) {
              console.warn("[a2a] SSE parse error:", c, "line:", i);
            }
      }
    } catch (g) {
      (g == null ? void 0 : g.name) !== "AbortError" && (console.error("[a2a] SSE subscription error:", g), s.textContent = `连接出错: ${(g == null ? void 0 : g.message) || g}`, s.style.borderColor = "#ff4d4f", s.style.background = "#fff1f0");
    }
  }
  function ht() {
    console.log("[a2a] Initializing stream interceptor");
    function t(l) {
      if (l.nodeType !== Node.ELEMENT_NODE) return;
      const d = l, s = Ae(d);
      if (s && re.has(s)) return;
      const r = yt(d);
      r && (console.log("[a2a] Marker detected in DOM, msgId:", s), s && re.add(s), be(r));
    }
    new MutationObserver((l) => {
      for (const d of l) {
        for (const s of d.addedNodes)
          t(s);
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
          const p = Ae(r);
          if (p && re.has(p)) continue;
          console.log("[a2a] Marker found in periodic scan, msgId:", p), p && re.add(p), be(r);
        }
      }
    }, 500);
    window.addEventListener("beforeunload", () => clearInterval(o));
    const a = document.evaluate(
      "//text()[contains(., 'A2A_STREAM_START')]",
      document.body,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null
    );
    for (let l = 0; l < a.snapshotLength; l++) {
      const s = a.snapshotItem(l).parentElement;
      if (s) {
        const r = Ae(s);
        r && re.add(r), console.log("[a2a] Marker found in existing DOM, msgId:", r), be(s);
      }
    }
  }
  (Fe = (We = window.QwenPaw).registerToolRender) == null || Fe.call(We, "cloudpaw", {
    proposal_choice: st,
    manage_prd: at
  }), (Ue = (Je = window.QwenPaw).registerRoutes) == null || Ue.call(Je, "cloudpaw", [
    {
      path: "/a2a",
      component: mt,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), xt(), At(), ht();
}
function xt() {
  const e = "qwenpaw-last-used-agent", v = "qwenpaw-agent-storage", N = "cloudpaw-first-install", B = "cloud-orchestrator";
  if (localStorage.getItem(N)) return;
  localStorage.setItem(N, "true");
  function j() {
    localStorage.setItem(e, B);
    try {
      const M = localStorage.getItem(v);
      if (M) {
        const b = JSON.parse(M);
        b.state = b.state || {}, b.state.selectedAgent = B, localStorage.setItem(v, JSON.stringify(b));
      } else
        localStorage.setItem(
          v,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: B,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const M = sessionStorage.getItem(v);
      if (M) {
        const b = JSON.parse(M);
        b.state = b.state || {}, b.state.selectedAgent = B, sessionStorage.setItem(v, JSON.stringify(b));
      } else
        sessionStorage.setItem(
          v,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: B,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
  }
  j(), window.addEventListener(
    "beforeunload",
    () => {
      j();
    },
    { once: !0 }
  ), console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
  ), window.location.reload();
}
function At() {
  var H;
  const e = (H = window.QwenPaw) == null ? void 0 : H.modules;
  if (!e) return;
  const v = e["Chat/OptionsPanel/defaultConfig"];
  if (!(v != null && v.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const N = v.configProvider, B = N.getConfig.bind(N), j = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", M = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, b = {
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
  }, D = {
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
  function te() {
    const x = localStorage.getItem("language") || "";
    return x ? x.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (N.getGreeting = () => M[te()] || M.en, N.getDescription = () => b[te()] || b.en, N.getPrompts = () => D[te()] || D.en, N.getConfig = function(x) {
    var ne;
    const W = B(x);
    return {
      ...W,
      theme: {
        ...W.theme,
        leftHeader: {
          ...(ne = W.theme) == null ? void 0 : ne.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...W.welcome,
        avatar: j
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const x = document.createElement("style");
    x.id = "cloudpaw-welcome-style", x.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(x);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
St();
