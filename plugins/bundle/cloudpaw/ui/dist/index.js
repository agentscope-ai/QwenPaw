function ft() {
  var je, Ne, Me, Je;
  const { React: e, antd: v, antdIcons: L, getApiUrl: N, getApiToken: W } = window.QwenPaw.host, {
    Card: D,
    Table: x,
    Tag: P,
    Typography: de,
    Space: M,
    Button: E,
    Input: F,
    Radio: me,
    Collapse: yt,
    Descriptions: Y,
    Tooltip: be,
    Spin: pe,
    message: ve
  } = v, { Text: R } = de, { TextArea: Ke } = F, { useState: w, useMemo: se, useCallback: V, useRef: ht } = e, {
    InfoCircleOutlined: ge,
    DownOutlined: Ie,
    RightOutlined: qe,
    CheckCircleOutlined: ye,
    FieldTimeOutlined: he,
    FileTextOutlined: Te
  } = L || {};
  function _e(t) {
    var o, u;
    const n = (u = (o = t == null ? void 0 : t.content) == null ? void 0 : o[0]) == null ? void 0 : u.data, l = n == null ? void 0 : n.arguments;
    if (typeof l == "string")
      try {
        return JSON.parse(l);
      } catch {
        return {};
      }
    return l ?? {};
  }
  function Ge() {
    return window.currentSessionId ?? null;
  }
  function X(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function Qe(t) {
    if (t == null) return !0;
    const n = X(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function Ye(t, n) {
    try {
      const l = W(), o = {
        "Content-Type": "application/json"
      };
      return l && (o.Authorization = `Bearer ${l}`), (await fetch(N("/interaction"), {
        method: "POST",
        headers: o,
        body: JSON.stringify({ session_id: t, result: n })
      })).ok;
    } catch {
      return !1;
    }
  }
  function ze(t) {
    if (!t) return null;
    if (typeof t == "string")
      try {
        const n = JSON.parse(t);
        if (Array.isArray(n)) {
          const l = n.find(
            (o) => (o == null ? void 0 : o.type) === "text" && (o == null ? void 0 : o.text)
          );
          return (l == null ? void 0 : l.text) ?? null;
        }
        if (typeof n == "string") return n;
      } catch {
        return t;
      }
    if (Array.isArray(t)) {
      const n = t.find((l) => (l == null ? void 0 : l.type) === "text" && (l == null ? void 0 : l.text));
      return (n == null ? void 0 : n.text) ?? null;
    }
    return null;
  }
  function Ve(t) {
    var s, r;
    if (!t || t.length < 2) return null;
    const n = (r = (s = t[1]) == null ? void 0 : s.data) == null ? void 0 : r.output, l = ze(n);
    if (!l) return null;
    if (l.startsWith("Error:")) return l;
    const o = l.match(/^用户选择了「(.+?)」并确认部署$/);
    if (o) return `已确认部署「${o[1]}」`;
    const u = l.match(
      /^用户选择「(.+?)」并要求调整[：:](.+)$/
    );
    if (u)
      return `已选择「${u[1]}」并调整：${u[2]}`;
    if (l === "用户确认部署") return "已确认部署";
    const m = l.match(/^用户要求调整资源[：:](.+)$/);
    return m ? `已反馈调整意见：${m[1]}` : "已确认";
  }
  const Pe = [
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
  ], Xe = new Set(
    Pe.map((t) => t.toLowerCase())
  );
  function Ce(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = X(t[0]).trim().toLowerCase();
    return Xe.has(n);
  }
  function Re(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = X(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function Ze(t) {
    const n = [];
    let l = [];
    for (const o of t)
      l.push(o), Re(o) && (n.push(l), l = []);
    return l.length > 0 && (n.length > 0 ? n[n.length - 1].push(...l) : n.push(l)), n.length > 0 ? n : [t];
  }
  function et(t) {
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
  function tt({ data: t }) {
    var He, We, Fe;
    const [n, l] = w("confirm"), [o, u] = w(""), [m, s] = w(!1), [r, I] = w(null), [O, J] = w(
      {}
    ), H = e.useRef(!1), $ = e.useRef(null), [, te] = w(0), j = t == null ? void 0 : t.content, S = j && j.length >= 2 && ((We = (He = j[1]) == null ? void 0 : He.data) == null ? void 0 : We.output), A = se(
      () => Ve(j),
      [j]
    ), B = H.current || S || A !== null, i = se(() => {
      const h = _e(t), g = h == null ? void 0 : h.data;
      if (!g) return null;
      try {
        const p = typeof g == "string" ? JSON.parse(g) : g;
        let C;
        if (h.strategy_names)
          try {
            const b = typeof h.strategy_names == "string" ? JSON.parse(h.strategy_names) : h.strategy_names;
            C = Array.isArray(b) ? b : [];
          } catch {
            C = [];
          }
        else p != null && p.proposal_names ? C = p.proposal_names : C = [];
        const re = C.length >= 2 ? C.length : 0;
        let k;
        if (Array.isArray(p) && p.length > 0)
          if (Array.isArray(p[0]) && p[0].length === 10 && !Array.isArray(p[0][0])) {
            const z = p.filter(
              (le) => !Ce(le)
            );
            if (z.filter(
              (le) => Re(le)
            ).length >= 2)
              k = Ze(z);
            else if (re >= 2 && z.length >= re * 2) {
              const le = Math.ceil(z.length / re);
              k = [];
              for (let ue = 0; ue < z.length; ue += le)
                k.push(z.slice(ue, ue + le));
            } else
              k = [z];
          } else
            k = p.map(
              (z) => z.filter(
                (ce) => Array.isArray(ce) && ce.length === 10 && !Ce(ce)
              )
            );
        else if (p != null && p.proposals)
          k = p.proposals.map(
            (b) => b.filter((z) => !Ce(z))
          );
        else
          return null;
        if (k = k.filter((b) => b.length > 0), k.length === 0) return null;
        const Ae = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (C.length < k.length)
          for (let b = C.length; b < k.length; b++)
            C.push(Ae[b] || `方案${b + 1}`);
        return { proposals: k, names: C };
      } catch {
        return null;
      }
    }, [t]), d = Ge(), c = (((Fe = i == null ? void 0 : i.proposals) == null ? void 0 : Fe.length) ?? 0) > 1, T = V(async () => {
      if (!d || B || !i) return;
      const h = c ? r : 0, g = i.names[h ?? 0] || `方案${(h ?? 0) + 1}`;
      let p;
      n === "confirm" ? p = `用户选择了「${g}」并确认部署` : p = `用户选择「${g}」并要求调整：${o.trim() || "未填写具体要求"}`, s(!0);
      const C = await Ye(d, p);
      s(!1), C ? (H.current = !0, n === "confirm" ? $.current = `已确认部署「${g}」` : $.current = `已选择「${g}」并调整：${o.trim()}`, te((re) => re + 1), ve.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : ve.error("操作失败，请重试");
    }, [
      d,
      B,
      i,
      n,
      o,
      r,
      c
    ]), fe = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created";
    if (!i)
      return fe ? e.createElement(
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
          R,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        D,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(R, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: ne, names: ae } = i, ie = Pe.map((h, g) => ({
      title: h,
      dataIndex: `col_${g}`,
      key: `col_${g}`,
      render: (p) => et(p),
      ellipsis: g < 3
    }));
    let U = "待确认", K = "processing";
    B && (K = "success", U = $.current || A || "已确认");
    const q = e.createElement(
      P,
      {
        color: K,
        style: { marginLeft: 4 }
      },
      U
    ), _ = e.createElement(
      M,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        R,
        { strong: !0, style: { fontSize: 14 } },
        B ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      q
    ), G = ne.map((h, g) => {
      const p = c ? r === g : !0, C = O[g] || !1, re = (y) => {
        const ee = X(y[0] || "").trim();
        return /^合计|^总计|^total/i.test(ee);
      }, k = h.find(re), Ae = h.filter((y) => !re(y)), b = Ae.map((y) => ({
        type: X(y[0] || ""),
        purpose: X(y[1] || ""),
        spec: X(y[2] || ""),
        cost: y[9] ?? null
      })), z = k ? X(k[9] ?? "") : "", ce = h.map((y, ee) => {
        const Ue = { key: ee };
        return y.forEach((dt, mt) => {
          Ue[`col_${mt}`] = dt;
        }), Ue;
      }), le = p ? "2px solid #1677ff" : "1px solid #e8e8e8", ue = p ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: g,
          style: {
            flex: 1,
            minWidth: 240,
            border: le,
            borderRadius: 8,
            cursor: c ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: ue,
            background: "#fff"
          },
          onClick: c ? () => I(g) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            R,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            ae[g]
          ),
          ...b.map(
            (y, ee) => e.createElement(
              "div",
              {
                key: ee,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: ee < b.length - 1 ? "1px solid #f5f5f5" : "none"
                }
              },
              e.createElement(
                "div",
                { style: { flex: 1, minWidth: 0 } },
                e.createElement(
                  "span",
                  { style: { fontSize: 12, color: "#262626" } },
                  y.type
                ),
                y.spec && e.createElement(
                  "span",
                  {
                    style: { fontSize: 11, color: "#8c8c8c", marginLeft: 6 }
                  },
                  y.spec
                )
              ),
              !Qe(y.cost) && e.createElement(
                "span",
                {
                  style: {
                    fontSize: 12,
                    color: "#595959",
                    flexShrink: 0,
                    marginLeft: 8
                  }
                },
                X(y.cost)
              )
            )
          ),
          // Total cost
          z && e.createElement(
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
              z
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
              onClick: (y) => {
                y.stopPropagation(), J((ee) => ({
                  ...ee,
                  [g]: !ee[g]
                }));
              }
            },
            e.createElement(
              C && Ie ? Ie : qe || "span",
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
          C && e.createElement(
            "div",
            {
              onClick: (y) => y.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(x, {
              columns: ie,
              dataSource: ce,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), a = e.createElement(
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
    ), f = !B && d && !(c && r === null) && e.createElement(
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
            onClick: () => l("confirm")
          },
          e.createElement(me, { checked: n === "confirm" }),
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
              onClick: () => l("adjust")
            },
            e.createElement(me, { checked: n === "adjust" }),
            e.createElement(
              "span",
              { style: { fontSize: 13 } },
              "调整资源"
            )
          ),
          n === "adjust" && e.createElement(Ke, {
            value: o,
            onChange: (h) => u(h.target.value),
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
          R,
          { type: "secondary", style: { fontSize: 11 } },
          c ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          E,
          {
            type: "primary",
            size: "small",
            loading: m,
            onClick: T,
            disabled: n === "adjust" && !o.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), Q = c && r === null && !B && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, _),
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
        ...G
      ),
      Q,
      a,
      !B && f
    );
  }
  function nt({ data: t }) {
    const [n, l] = w(null), [o, u] = w(!1), m = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", s = se(() => {
      const i = _e(t);
      return (i == null ? void 0 : i.loop_dir) || null;
    }, [t]), r = se(() => {
      var d, c, T;
      const i = ze((T = (c = (d = t == null ? void 0 : t.content) == null ? void 0 : d[1]) == null ? void 0 : c.data) == null ? void 0 : T.output);
      if (!i) return null;
      try {
        return JSON.parse(i);
      } catch {
        return null;
      }
    }, [t]), I = (r == null ? void 0 : r.status) === "ok", O = (r == null ? void 0 : r.status) === "error", J = O ? (r == null ? void 0 : r.message) || "未知错误" : null, H = V(async () => {
      if (s)
        try {
          const i = W(), d = {};
          i && (d.Authorization = `Bearer ${i}`);
          const c = await fetch(
            N(`/prd?loop_dir=${encodeURIComponent(s)}`),
            { headers: d }
          );
          if (!c.ok) {
            u(!0);
            return;
          }
          const T = await c.json();
          T && Array.isArray(T.userStories) ? (l(T), u(!1)) : u(!0);
        } catch {
          u(!0);
        }
    }, [s]);
    if (e.useEffect(() => {
      !m && I && s && H();
    }, [m, I, s, H]), m)
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
          R,
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
          R,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${J}`
        )
      );
    if (!I || o || !n) return null;
    const $ = n.userStories, te = [...$].sort(
      (i, d) => (i.priority || 99) - (d.priority || 99)
    ), j = $.filter((i) => i.passes).length, S = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (i, d) => {
          if (d.passes) {
            const T = ye ? e.createElement(ye, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(be, { title: "已完成" }, T);
          }
          const c = he ? e.createElement(he, {
            style: { color: "#faad14", fontSize: 18 }
          }) : "🕐";
          return e.createElement(be, { title: "待处理" }, c);
        }
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 85,
        render: (i) => e.createElement(P, { color: "blue" }, i)
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (i) => e.createElement(R, { strong: !0 }, i)
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (i, d) => {
          const c = d.priority;
          return e.createElement(
            P,
            { color: "default" },
            c != null ? String(c) : "-"
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
        render: (i, d) => {
          const c = d.acceptanceCriteria;
          return typeof c == "string" ? e.createElement(
            "div",
            {
              style: { fontSize: 12, color: "#666", whiteSpace: "pre-wrap" }
            },
            c.length > 100 ? c.slice(0, 100) + "..." : c
          ) : Array.isArray(c) ? e.createElement(
            "div",
            { style: { fontSize: 12, color: "#666" } },
            c.length > 2 ? c.slice(0, 2).join(", ") + "..." : c.join(", ")
          ) : "-";
        }
      }
    ], A = e.createElement(
      M,
      { size: 8 },
      Te ? e.createElement(Te, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(R, { strong: !0 }, n.project || "PRD")
      )
    ), B = e.createElement(x, {
      columns: S,
      dataSource: te.map((i) => ({ ...i, key: i.id })),
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
      e.createElement("div", { style: { marginBottom: 8 } }, A),
      e.createElement(Y, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: !1,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${j}/${$.length} 完成`
          }
        ]
      }),
      B,
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
  function rt({ data: t }) {
    var ne, ae, ie;
    const n = (t == null ? void 0 : t.status) || "", l = n === "in_progress" || n === "created", o = n === "completed" || n === "canceled" || n === "failed", u = e.useRef(null), m = se(() => {
      var K, q, _;
      const U = (_ = (q = (K = t == null ? void 0 : t.content) == null ? void 0 : K[0]) == null ? void 0 : q.data) == null ? void 0 : _.arguments;
      if (!U) return null;
      try {
        return JSON.parse(U);
      } catch {
        return null;
      }
    }, [(ie = (ae = (ne = t == null ? void 0 : t.content) == null ? void 0 : ne[0]) == null ? void 0 : ae.data) == null ? void 0 : ie.arguments]), s = se(() => {
      var K;
      if (o && u.current) return u.current;
      const U = t == null ? void 0 : t.content;
      if (!Array.isArray(U)) return null;
      for (const q of U) {
        const _ = (K = q == null ? void 0 : q.data) == null ? void 0 : K.output;
        if (!_) continue;
        let G = "";
        if (Array.isArray(_)) {
          const a = _.find(
            (f) => (f == null ? void 0 : f.type) === "text" && (f == null ? void 0 : f.text)
          );
          G = (a == null ? void 0 : a.text) || "";
        } else if (typeof _ == "string")
          try {
            const a = JSON.parse(_);
            if (typeof a == "object" && (a != null && a.response_text))
              return a;
            if (Array.isArray(a)) {
              const f = a.find((Q) => (Q == null ? void 0 : Q.type) === "text" && (Q == null ? void 0 : Q.text));
              f != null && f.text && (G = f.text);
            }
          } catch {
            G = _;
          }
        if (G)
          try {
            const a = JSON.parse(G);
            return o && (u.current = a), a;
          } catch {
            return null;
          }
      }
      return null;
    }, [t == null ? void 0 : t.content, o]), r = (m == null ? void 0 : m.agent_alias) || "", I = (m == null ? void 0 : m.agent_url) || "", O = r || I || "远程 Agent", J = (s == null ? void 0 : s.response_text) || "", H = (s == null ? void 0 : s.task_state) || "", $ = (s == null ? void 0 : s.error) || "", te = (s == null ? void 0 : s.event_count) || 0, j = {
      completed: "#52c41a",
      failed: "#ff4d4f",
      error: "#ff4d4f",
      canceled: "#faad14",
      working: "#1677ff"
    }, S = {
      completed: "已完成",
      failed: "失败",
      error: "出错",
      canceled: "已取消",
      working: "执行中"
    }, A = l ? "#1677ff" : j[H] || "#d9d9d9", B = l ? "执行中..." : S[H] || H || "完成", i = $ ? `错误: ${$}` : J || "等待响应...", d = e.createElement(
      M,
      { size: 8 },
      e.createElement("span", null, "🔗"),
      e.createElement(
        R,
        { strong: !0, style: { fontSize: 14 } },
        `A2A 调用: ${O}`
      ),
      e.createElement(P, { color: A }, B)
    ), c = l && !J ? e.createElement(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          marginBottom: 12,
          background: "#f6ffed",
          border: "1px solid #b7eb8f",
          borderRadius: 6
        }
      },
      e.createElement(pe, { size: "small" }),
      e.createElement(
        R,
        { style: { fontSize: 12, color: "#52c41a" } },
        `正在连接 ${O}...`
      )
    ) : null, T = l && J ? e.createElement(
      "div",
      {
        style: {
          background: "#e6f4ff",
          border: "1px solid #91caff",
          borderRadius: 6,
          padding: "8px 12px",
          marginBottom: 12
        }
      },
      e.createElement(
        R,
        { style: { fontSize: 12, color: "#1677ff" } },
        `实时进度 (已接收 ${te} 个事件):`
      )
    ) : null, fe = e.createElement(
      "div",
      {
        style: {
          background: "#fafafa",
          border: "1px solid #d9d9d9",
          borderRadius: 6,
          padding: "12px 16px"
        }
      },
      e.createElement(
        R,
        {
          style: {
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word"
          }
        },
        i
      )
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
      e.createElement("div", { style: { marginBottom: 12 } }, d),
      c,
      T,
      fe,
      e.createElement(
        "div",
        {
          style: { fontSize: 11, color: "#8c8c8c", marginTop: 8 }
        },
        `事件数: ${te}`,
        s != null && s.task_id ? ` | 任务ID: ${s.task_id.slice(0, 12)}...` : "",
        s != null && s.context_id ? ` | 会话: ${s.context_id.slice(0, 12)}...` : ""
      )
    );
  }
  const {
    Form: Z,
    Select: Ee,
    Drawer: lt,
    Modal: st,
    Empty: ot,
    Badge: Oe,
    Divider: at,
    message: oe
  } = v, {
    ApiOutlined: Et,
    PlusOutlined: $e,
    ReloadOutlined: we,
    DeleteOutlined: Be,
    LinkOutlined: Le,
    DisconnectOutlined: wt
  } = L || {}, { useEffect: De } = e, xe = "/a2a/agents";
  function ke() {
    var t;
    try {
      const n = sessionStorage.getItem("qwenpaw-agent-storage") || localStorage.getItem("qwenpaw-agent-storage");
      if (n) {
        const l = JSON.parse(n);
        return ((t = l == null ? void 0 : l.state) == null ? void 0 : t.selectedAgent) || null;
      }
    } catch {
    }
    return null;
  }
  async function Se(t, n) {
    const l = N(t), o = W == null ? void 0 : W(), u = ke(), m = {
      "Content-Type": "application/json",
      ...o ? { Authorization: `Bearer ${o}` } : {},
      ...u ? { "X-Agent-Id": u } : {}
    }, s = await fetch(l, {
      ...n,
      headers: { ...m, ...(n == null ? void 0 : n.headers) || {} }
    });
    if (!s.ok) {
      const r = await s.text().catch(() => "");
      throw new Error(r || `HTTP ${s.status}`);
    }
    return s.status === 204 || s.headers.get("content-length") === "0" ? null : s.json();
  }
  function it(t) {
    var r;
    const { agent: n, onClick: l } = t, o = n.status === "connected", u = o ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", m = o ? "已连接" : n.status === "error" ? "错误" : "未连接", s = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      D,
      {
        hoverable: !0,
        onClick: l,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          M,
          null,
          e.createElement(Oe, { color: u }),
          e.createElement(
            "span",
            null,
            n.name || n.alias || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          P,
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
          Le ? e.createElement(Le, { style: { marginRight: 4 } }) : null,
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
            (I, O) => e.createElement(
              P,
              { key: O, style: { fontSize: 11 } },
              I.name
            )
          ),
          n.skills.length > 3 ? e.createElement(
            P,
            { style: { fontSize: 11 } },
            `+${n.skills.length - 3}`
          ) : null
        ) : null,
        e.createElement(
          "div",
          { style: { marginTop: 4, color: u, fontSize: 11 } },
          m,
          n.error ? ` - ${n.error}` : ""
        )
      )
    );
  }
  function ct() {
    const t = e.useRef(ke()), [n, l] = w(t.current);
    return De(() => {
      const o = () => {
        const m = ke();
        m !== t.current && (t.current = m, l(m));
      }, u = setInterval(o, 200);
      return window.addEventListener("storage", o), () => {
        clearInterval(u), window.removeEventListener("storage", o);
      };
    }, []), n;
  }
  function ut() {
    var _, G;
    const t = ct(), [n, l] = w([]), [o, u] = w(!0), [m, s] = w(!1), [r, I] = w(null), [O, J] = w(!1), [H, $] = w(!1), [te, j] = w(!1), [S] = Z.useForm(), A = V(async () => {
      u(!0);
      try {
        const a = await Se(xe);
        l((a == null ? void 0 : a.agents) || []);
      } catch {
        l([]);
      } finally {
        u(!1);
      }
    }, []);
    De(() => {
      A();
    }, [t]);
    const B = V(() => {
      J(!0), I(null), s(!0), S.resetFields(), S.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [S]), i = V((a) => {
      J(!1), I(a), s(!0);
    }, []), d = V(() => {
      s(!1), I(null), J(!1), S.resetFields();
    }, [S]), c = V(async () => {
      let a;
      try {
        a = await S.validateFields();
      } catch {
        return;
      }
      const f = {
        url: String(a.url || "").trim(),
        alias: String(a.alias || "").trim() || void 0,
        auth_type: String(a.auth_type || ""),
        auth_token: String(a.auth_token || "")
      };
      if (f.url) {
        $(!0);
        try {
          await Se(xe, {
            method: "POST",
            body: JSON.stringify(f)
          }), oe.success("A2A Agent 注册成功"), await A(), d();
        } catch (Q) {
          oe.error(Q.message || "注册失败");
        } finally {
          $(!1);
        }
      }
    }, [S, A, d]), T = V(async () => {
      if (!r) return;
      const a = r.alias || r.url;
      st.confirm({
        title: `删除 ${a}`,
        content: "确定删除该远程 A2A Agent 吗？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await Se(`${xe}/${encodeURIComponent(a)}`, {
              method: "DELETE"
            }), oe.success("A2A Agent 已删除"), await A(), d();
          } catch (f) {
            oe.error(f.message || "删除失败");
          }
        }
      });
    }, [r, A, d]), fe = V(async () => {
      if (!r) return;
      const a = r.alias || r.url;
      j(!0);
      try {
        const f = await Se(
          `${xe}/${encodeURIComponent(a)}/refresh`,
          {
            method: "POST"
          }
        );
        oe.success("Agent Card 已刷新"), await A(), f && I(f);
      } catch (f) {
        oe.error(f.message || "刷新失败");
      } finally {
        j(!1);
      }
    }, [r, A]), ne = ((_ = Z.useWatch) == null ? void 0 : _.call(Z, "auth_type", S)) ?? "", ae = e.createElement(
      Z,
      { form: S, layout: "vertical" },
      e.createElement(
        Z.Item,
        {
          name: "url",
          label: "Agent URL",
          rules: [{ required: !0, message: "请输入 Agent URL" }]
        },
        e.createElement(F, {
          placeholder: "https://agent.example.com"
        })
      ),
      e.createElement(
        Z.Item,
        { name: "alias", label: "别名" },
        e.createElement(F, { placeholder: "输入别名（可选）" })
      ),
      e.createElement(
        Z.Item,
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
      ne === "gateway" ? e.createElement(
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
      ne && ne !== "gateway" ? e.createElement(
        Z.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(F.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), ie = r ? e.createElement(
      "div",
      null,
      e.createElement(
        Y,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          Y.Item,
          { label: "URL" },
          r.url
        ),
        e.createElement(
          Y.Item,
          { label: "别名" },
          r.alias || "-"
        ),
        e.createElement(
          Y.Item,
          { label: "Agent 名称" },
          r.name || "-"
        ),
        e.createElement(
          Y.Item,
          { label: "状态" },
          e.createElement(Oe, {
            color: r.status === "connected" ? "#52c41a" : r.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: r.status === "connected" ? "已连接" : r.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          Y.Item,
          { label: "认证类型" },
          r.auth_type ? e.createElement(
            P,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[r.auth_type] || r.auth_type
          ) : "无认证"
        ),
        e.createElement(
          Y.Item,
          { label: "描述" },
          r.description || "-"
        ),
        e.createElement(
          Y.Item,
          { label: "版本" },
          r.version || "-"
        )
      ),
      ((G = r.skills) == null ? void 0 : G.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...r.skills.map(
          (a, f) => e.createElement(
            D,
            { key: f, size: "small", style: { marginBottom: 8 } },
            e.createElement("strong", null, a.name),
            a.description ? e.createElement(
              "div",
              { style: { color: "#666", fontSize: 12 } },
              a.description
            ) : null
          )
        )
      ) : null,
      r.capabilities ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "能力"),
        e.createElement(
          M,
          null,
          e.createElement(
            P,
            {
              color: r.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            P,
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
      e.createElement(at, null),
      e.createElement(
        M,
        null,
        e.createElement(
          E,
          {
            type: "primary",
            icon: we ? e.createElement(we) : null,
            loading: te,
            onClick: fe
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          E,
          {
            danger: !0,
            icon: Be ? e.createElement(Be) : null,
            onClick: T
          },
          "删除"
        )
      )
    ) : null, U = e.createElement(
      lt,
      {
        title: O ? "注册远程 A2A Agent" : (r == null ? void 0 : r.name) || (r == null ? void 0 : r.alias) || "Agent 详情",
        open: m,
        onClose: d,
        width: 480,
        footer: O ? e.createElement(
          M,
          { style: { float: "right" } },
          e.createElement(E, { onClick: d }, "取消"),
          e.createElement(
            E,
            { type: "primary", loading: H, onClick: c },
            "注册"
          )
        ) : null
      },
      O ? ae : ie
    ), K = e.createElement(
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
          M,
          null,
          e.createElement(
            E,
            {
              icon: we ? e.createElement(we) : null,
              onClick: A,
              loading: o
            },
            "刷新列表"
          ),
          e.createElement(
            E,
            {
              type: "primary",
              icon: $e ? e.createElement($e) : null,
              onClick: B
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
    ), q = o ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(pe, { size: "large" })
    ) : n.length === 0 ? e.createElement(ot, { description: "暂无注册的远程 A2A Agent" }) : e.createElement(
      "div",
      {
        style: {
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 12
        }
      },
      ...n.map(
        (a) => e.createElement(it, {
          key: a.alias || a.url,
          agent: a,
          onClick: () => i(a)
        })
      )
    );
    return e.createElement(
      "div",
      { style: { padding: 24 } },
      K,
      q,
      U
    );
  }
  (Ne = (je = window.QwenPaw).registerToolRender) == null || Ne.call(je, "cloudpaw", {
    proposal_choice: tt,
    manage_prd: nt,
    a2a_call: rt
  }), (Je = (Me = window.QwenPaw).registerRoutes) == null || Je.call(Me, "cloudpaw", [
    {
      path: "/a2a",
      component: ut,
      label: "A2A",
      icon: "🔗",
      priority: 10
    }
  ]), pt(), gt();
}
function pt() {
  const e = "qwenpaw-last-used-agent", v = "qwenpaw-agent-storage", L = "cloudpaw-first-install", N = "cloud-orchestrator";
  if (localStorage.getItem(L)) return;
  localStorage.setItem(L, "true");
  function W() {
    localStorage.setItem(e, N);
    try {
      const D = localStorage.getItem(v);
      if (D) {
        const x = JSON.parse(D);
        x.state = x.state || {}, x.state.selectedAgent = N, localStorage.setItem(v, JSON.stringify(x));
      } else
        localStorage.setItem(
          v,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: N,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      const D = sessionStorage.getItem(v);
      if (D) {
        const x = JSON.parse(D);
        x.state = x.state || {}, x.state.selectedAgent = N, sessionStorage.setItem(v, JSON.stringify(x));
      } else
        sessionStorage.setItem(
          v,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: N,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
  }
  W(), window.addEventListener(
    "beforeunload",
    () => {
      W();
    },
    { once: !0 }
  ), console.info(
    "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
  ), window.location.reload();
}
function gt() {
  var M;
  const e = (M = window.QwenPaw) == null ? void 0 : M.modules;
  if (!e) return;
  const v = e["Chat/OptionsPanel/defaultConfig"];
  if (!(v != null && v.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const L = v.configProvider, N = L.getConfig.bind(L), W = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", D = {
    zh: "CloudPaw 插件提示",
    en: "CloudPaw Plugin Tips",
    ja: "CloudPaw プラグインのヒント",
    ru: "Подсказки плагина CloudPaw"
  }, x = {
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
  }, P = {
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
  function de() {
    const E = localStorage.getItem("language") || "";
    return E ? E.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  if (L.getGreeting = () => D[de()] || D.en, L.getDescription = () => x[de()] || x.en, L.getPrompts = () => P[de()] || P.en, L.getConfig = function(E) {
    var me;
    const F = N(E);
    return {
      ...F,
      theme: {
        ...F.theme,
        leftHeader: {
          ...(me = F.theme) == null ? void 0 : me.leftHeader,
          title: "Work with CloudPaw"
        }
      },
      welcome: {
        ...F.welcome,
        avatar: W
      }
    };
  }, !document.getElementById("cloudpaw-welcome-style")) {
    const E = document.createElement("style");
    E.id = "cloudpaw-welcome-style", E.textContent = `
      [class*="chat-anywhere-welcome-default"] [class*="description"],
      [class*="message-list-welcome"] [class*="description"] {
        white-space: pre-line !important;
        text-align: center !important;
      }
    `, document.head.appendChild(E);
  }
  console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
ft();
