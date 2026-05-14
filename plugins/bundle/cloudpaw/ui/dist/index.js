function ft() {
  var je, Me, Ne, He;
  const { React: e, antd: O, antdIcons: $, getApiUrl: H, getApiToken: W } = window.QwenPaw.host, {
    Card: L,
    Table: ue,
    Tag: T,
    Typography: de,
    Space: j,
    Button: B,
    Input: F,
    Radio: me,
    Collapse: yt,
    Descriptions: Q,
    Tooltip: be,
    Spin: pe,
    message: ve
  } = O, { Text: _ } = de, { TextArea: Ke } = F, { useState: E, useMemo: le, useCallback: Y, useRef: ht } = e, {
    InfoCircleOutlined: ge,
    DownOutlined: Ie,
    RightOutlined: qe,
    CheckCircleOutlined: ye,
    FieldTimeOutlined: he,
    FileTextOutlined: Te
  } = $ || {};
  function _e(t) {
    var a, u;
    const n = (u = (a = t == null ? void 0 : t.content) == null ? void 0 : a[0]) == null ? void 0 : u.data, l = n == null ? void 0 : n.arguments;
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
  function V(t) {
    return typeof t == "string" ? t : t && typeof t == "object" && "text" in t ? t.text : String(t ?? "");
  }
  function Qe(t) {
    if (t == null) return !0;
    const n = V(t).trim();
    return !!(!n || /^[¥$]?0+(\.0+)?$/.test(n) || /^[-–—]+$/.test(n));
  }
  async function Ye(t, n) {
    try {
      const l = W(), a = {
        "Content-Type": "application/json"
      };
      return l && (a.Authorization = `Bearer ${l}`), (await fetch(H("/interaction"), {
        method: "POST",
        headers: a,
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
            (a) => (a == null ? void 0 : a.type) === "text" && (a == null ? void 0 : a.text)
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
    const a = l.match(/^用户选择了「(.+?)」并确认部署$/);
    if (a) return `已确认部署「${a[1]}」`;
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
    const n = V(t[0]).trim().toLowerCase();
    return Xe.has(n);
  }
  function Re(t) {
    if (!Array.isArray(t) || t.length !== 10) return !1;
    const n = V(t[0]).trim();
    return /^(合计|总计|total)/i.test(n);
  }
  function Ze(t) {
    const n = [];
    let l = [];
    for (const a of t)
      l.push(a), Re(a) && (n.push(l), l = []);
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
    var We, Fe, Je;
    const [n, l] = E("confirm"), [a, u] = E(""), [m, s] = E(!1), [r, k] = E(null), [z, M] = E(
      {}
    ), N = e.useRef(!1), P = e.useRef(null), [, ee] = E(0), D = t == null ? void 0 : t.content, x = D && D.length >= 2 && ((Fe = (We = D[1]) == null ? void 0 : We.data) == null ? void 0 : Fe.output), S = le(
      () => Ve(D),
      [D]
    ), R = N.current || x || S !== null, i = le(() => {
      const h = _e(t), g = h == null ? void 0 : h.data;
      if (!g) return null;
      try {
        const p = typeof g == "string" ? JSON.parse(g) : g;
        let w;
        if (h.strategy_names)
          try {
            const C = typeof h.strategy_names == "string" ? JSON.parse(h.strategy_names) : h.strategy_names;
            w = Array.isArray(C) ? C : [];
          } catch {
            w = [];
          }
        else p != null && p.proposal_names ? w = p.proposal_names : w = [];
        const ne = w.length >= 2 ? w.length : 0;
        let A;
        if (Array.isArray(p) && p.length > 0)
          if (Array.isArray(p[0]) && p[0].length === 10 && !Array.isArray(p[0][0])) {
            const I = p.filter(
              (re) => !Ce(re)
            );
            if (I.filter(
              (re) => Re(re)
            ).length >= 2)
              A = Ze(I);
            else if (ne >= 2 && I.length >= ne * 2) {
              const re = Math.ceil(I.length / ne);
              A = [];
              for (let ce = 0; ce < I.length; ce += re)
                A.push(I.slice(ce, ce + re));
            } else
              A = [I];
          } else
            A = p.map(
              (I) => I.filter(
                (ie) => Array.isArray(ie) && ie.length === 10 && !Ce(ie)
              )
            );
        else if (p != null && p.proposals)
          A = p.proposals.map(
            (C) => C.filter((I) => !Ce(I))
          );
        else
          return null;
        if (A = A.filter((C) => C.length > 0), A.length === 0) return null;
        const Ae = ["方案一", "方案二", "方案三", "方案四", "方案五"];
        if (w.length < A.length)
          for (let C = w.length; C < A.length; C++)
            w.push(Ae[C] || `方案${C + 1}`);
        return { proposals: A, names: w };
      } catch {
        return null;
      }
    }, [t]), d = Ge(), c = (((Je = i == null ? void 0 : i.proposals) == null ? void 0 : Je.length) ?? 0) > 1, b = Y(async () => {
      if (!d || R || !i) return;
      const h = c ? r : 0, g = i.names[h ?? 0] || `方案${(h ?? 0) + 1}`;
      let p;
      n === "confirm" ? p = `用户选择了「${g}」并确认部署` : p = `用户选择「${g}」并要求调整：${a.trim() || "未填写具体要求"}`, s(!0);
      const w = await Ye(d, p);
      s(!1), w ? (N.current = !0, n === "confirm" ? P.current = `已确认部署「${g}」` : P.current = `已选择「${g}」并调整：${a.trim()}`, ee((ne) => ne + 1), ve.success(
        n === "confirm" ? "已确认部署方案" : "已提交调整意见"
      )) : ve.error("操作失败，请重试");
    }, [
      d,
      R,
      i,
      n,
      a,
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
          _,
          { type: "secondary", style: { fontSize: 13 } },
          "正在生成资源方案..."
        )
      ) : e.createElement(
        L,
        { size: "small", style: { margin: "4px 0" } },
        e.createElement(_, { type: "secondary" }, "无法解析方案数据")
      );
    const { proposals: te, names: ae } = i, oe = Pe.map((h, g) => ({
      title: h,
      dataIndex: `col_${g}`,
      key: `col_${g}`,
      render: (p) => et(p),
      ellipsis: g < 3
    }));
    let J = "待确认", U = "processing";
    R && (U = "success", J = P.current || S || "已确认");
    const K = e.createElement(
      T,
      {
        color: U,
        style: { marginLeft: 4 }
      },
      J
    ), v = e.createElement(
      j,
      { size: 8 },
      e.createElement("span", null, "☁️"),
      e.createElement(
        _,
        { strong: !0, style: { fontSize: 14 } },
        R ? "资源配置方案" : "请确认您的资源配置方案"
      ),
      K
    ), q = te.map((h, g) => {
      const p = c ? r === g : !0, w = z[g] || !1, ne = (y) => {
        const Z = V(y[0] || "").trim();
        return /^合计|^总计|^total/i.test(Z);
      }, A = h.find(ne), Ae = h.filter((y) => !ne(y)), C = Ae.map((y) => ({
        type: V(y[0] || ""),
        purpose: V(y[1] || ""),
        spec: V(y[2] || ""),
        cost: y[9] ?? null
      })), I = A ? V(A[9] ?? "") : "", ie = h.map((y, Z) => {
        const Ue = { key: Z };
        return y.forEach((dt, mt) => {
          Ue[`col_${mt}`] = dt;
        }), Ue;
      }), re = p ? "2px solid #1677ff" : "1px solid #e8e8e8", ce = p ? "0 0 0 2px #e6f4ff" : "none";
      return e.createElement(
        "div",
        {
          key: g,
          style: {
            flex: 1,
            minWidth: 240,
            border: re,
            borderRadius: 8,
            cursor: c ? "pointer" : "default",
            transition: "all 0.2s ease",
            boxShadow: ce,
            background: "#fff"
          },
          onClick: c ? () => k(g) : void 0
        },
        e.createElement(
          "div",
          { style: { padding: "10px 12px" } },
          // Proposal name
          e.createElement(
            _,
            {
              strong: !0,
              style: { fontSize: 14, display: "block", marginBottom: 8 }
            },
            ae[g]
          ),
          ...C.map(
            (y, Z) => e.createElement(
              "div",
              {
                key: Z,
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "4px 0",
                  borderBottom: Z < C.length - 1 ? "1px solid #f5f5f5" : "none"
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
                V(y.cost)
              )
            )
          ),
          // Total cost
          I && e.createElement(
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
              I
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
                y.stopPropagation(), M((Z) => ({
                  ...Z,
                  [g]: !Z[g]
                }));
              }
            },
            e.createElement(
              w && Ie ? Ie : qe || "span",
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
          w && e.createElement(
            "div",
            {
              onClick: (y) => y.stopPropagation(),
              style: { marginTop: 4, maxHeight: 260, overflow: "auto" }
            },
            e.createElement(ue, {
              columns: oe,
              dataSource: ie,
              pagination: !1,
              size: "small",
              scroll: { x: "max-content" }
            })
          )
        )
      );
    }), o = e.createElement(
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
    ), f = !R && d && !(c && r === null) && e.createElement(
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
            value: a,
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
          _,
          { type: "secondary", style: { fontSize: 11 } },
          c ? "一小时后未操作将自动选择第一个方案" : "一小时后未操作将自动确认部署"
        ),
        e.createElement(
          B,
          {
            type: "primary",
            size: "small",
            loading: m,
            onClick: b,
            disabled: n === "adjust" && !a.trim()
          },
          n === "confirm" ? "确认部署" : "提交调整"
        )
      )
    ), G = c && r === null && !R && e.createElement(
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
      e.createElement("div", { style: { marginBottom: 10 } }, v),
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
        ...q
      ),
      G,
      o,
      !R && f
    );
  }
  function nt({ data: t }) {
    const [n, l] = E(null), [a, u] = E(!1), m = (t == null ? void 0 : t.status) === "in_progress" || (t == null ? void 0 : t.status) === "created", s = le(() => {
      const i = _e(t);
      return (i == null ? void 0 : i.loop_dir) || null;
    }, [t]), r = le(() => {
      var d, c, b;
      const i = ze((b = (c = (d = t == null ? void 0 : t.content) == null ? void 0 : d[1]) == null ? void 0 : c.data) == null ? void 0 : b.output);
      if (!i) return null;
      try {
        return JSON.parse(i);
      } catch {
        return null;
      }
    }, [t]), k = (r == null ? void 0 : r.status) === "ok", z = (r == null ? void 0 : r.status) === "error", M = z ? (r == null ? void 0 : r.message) || "未知错误" : null, N = Y(async () => {
      if (s)
        try {
          const i = W(), d = {};
          i && (d.Authorization = `Bearer ${i}`);
          const c = await fetch(
            H(`/prd?loop_dir=${encodeURIComponent(s)}`),
            { headers: d }
          );
          if (!c.ok) {
            u(!0);
            return;
          }
          const b = await c.json();
          b && Array.isArray(b.userStories) ? (l(b), u(!1)) : u(!0);
        } catch {
          u(!0);
        }
    }, [s]);
    if (e.useEffect(() => {
      !m && k && s && N();
    }, [m, k, s, N]), m)
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
          _,
          { type: "secondary", style: { fontSize: 13 } },
          "正在更新 PRD..."
        )
      );
    if (z)
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
          _,
          { type: "danger", style: { fontSize: 13 } },
          `PRD 格式错误，将会修正：${M}`
        )
      );
    if (!k || a || !n) return null;
    const P = n.userStories, ee = [...P].sort(
      (i, d) => (i.priority || 99) - (d.priority || 99)
    ), D = P.filter((i) => i.passes).length, x = [
      {
        title: "状态",
        key: "status",
        width: 50,
        align: "center",
        render: (i, d) => {
          if (d.passes) {
            const b = ye ? e.createElement(ye, {
              style: { color: "#52c41a", fontSize: 18 }
            }) : "✅";
            return e.createElement(be, { title: "已完成" }, b);
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
        render: (i) => e.createElement(T, { color: "blue" }, i)
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        render: (i) => e.createElement(_, { strong: !0 }, i)
      },
      {
        title: "优先级",
        key: "priority",
        width: 70,
        render: (i, d) => {
          const c = d.priority;
          return e.createElement(
            T,
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
    ], S = e.createElement(
      j,
      { size: 8 },
      Te ? e.createElement(Te, { style: { color: "#1677ff" } }) : null,
      e.createElement(
        "span",
        { style: { fontSize: 14 } },
        e.createElement(_, { strong: !0 }, n.project || "PRD")
      )
    ), R = e.createElement(ue, {
      columns: x,
      dataSource: ee.map((i) => ({ ...i, key: i.id })),
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
      e.createElement("div", { style: { marginBottom: 8 } }, S),
      e.createElement(Q, {
        size: "small",
        column: { xs: 1, sm: 2, md: 3 },
        style: { marginBottom: 12 },
        bordered: !1,
        items: [
          {
            key: "progress",
            label: "进度",
            children: `${D}/${P.length} 完成`
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
    var te, ae, oe;
    const n = (t == null ? void 0 : t.status) || "", l = n === "in_progress" || n === "created", a = n === "completed" || n === "canceled" || n === "failed", u = e.useRef(null), m = le(() => {
      var U, K, v;
      const J = (v = (K = (U = t == null ? void 0 : t.content) == null ? void 0 : U[0]) == null ? void 0 : K.data) == null ? void 0 : v.arguments;
      if (!J) return null;
      try {
        return JSON.parse(J);
      } catch {
        return null;
      }
    }, [(oe = (ae = (te = t == null ? void 0 : t.content) == null ? void 0 : te[0]) == null ? void 0 : ae.data) == null ? void 0 : oe.arguments]), s = le(() => {
      var U;
      if (a && u.current) return u.current;
      const J = t == null ? void 0 : t.content;
      if (!Array.isArray(J)) return null;
      for (const K of J) {
        const v = (U = K == null ? void 0 : K.data) == null ? void 0 : U.output;
        if (!v) continue;
        let q = "";
        if (Array.isArray(v)) {
          const o = v.find(
            (f) => (f == null ? void 0 : f.type) === "text" && (f == null ? void 0 : f.text)
          );
          q = (o == null ? void 0 : o.text) || "";
        } else if (typeof v == "string")
          try {
            const o = JSON.parse(v);
            if (typeof o == "object" && (o != null && o.response_text))
              return o;
            if (Array.isArray(o)) {
              const f = o.find((G) => (G == null ? void 0 : G.type) === "text" && (G == null ? void 0 : G.text));
              f != null && f.text && (q = f.text);
            }
          } catch {
            q = v;
          }
        if (q)
          try {
            const o = JSON.parse(q);
            return a && (u.current = o), o;
          } catch {
            return null;
          }
      }
      return null;
    }, [t == null ? void 0 : t.content, a]), r = (m == null ? void 0 : m.agent_alias) || "", k = (m == null ? void 0 : m.agent_url) || "", z = r || k || "远程 Agent", M = (s == null ? void 0 : s.response_text) || "", N = (s == null ? void 0 : s.task_state) || "", P = (s == null ? void 0 : s.error) || "", ee = (s == null ? void 0 : s.event_count) || 0, D = {
      completed: "#52c41a",
      failed: "#ff4d4f",
      error: "#ff4d4f",
      canceled: "#faad14",
      working: "#1677ff"
    }, x = {
      completed: "已完成",
      failed: "失败",
      error: "出错",
      canceled: "已取消",
      working: "执行中"
    }, S = l ? "#1677ff" : D[N] || "#d9d9d9", R = l ? "执行中..." : x[N] || N || "完成", i = P ? `错误: ${P}` : M || "等待响应...", d = e.createElement(
      j,
      { size: 8 },
      e.createElement("span", null, "🔗"),
      e.createElement(
        _,
        { strong: !0, style: { fontSize: 14 } },
        `A2A 调用: ${z}`
      ),
      e.createElement(T, { color: S }, R)
    ), c = l && !M ? e.createElement(
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
        _,
        { style: { fontSize: 12, color: "#52c41a" } },
        `正在连接 ${z}...`
      )
    ) : null, b = l && M ? e.createElement(
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
        _,
        { style: { fontSize: 12, color: "#1677ff" } },
        `实时进度 (已接收 ${ee} 个事件):`
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
        _,
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
      b,
      fe,
      e.createElement(
        "div",
        {
          style: { fontSize: 11, color: "#8c8c8c", marginTop: 8 }
        },
        `事件数: ${ee}`,
        s != null && s.task_id ? ` | 任务ID: ${s.task_id.slice(0, 12)}...` : "",
        s != null && s.context_id ? ` | 会话: ${s.context_id.slice(0, 12)}...` : ""
      )
    );
  }
  const {
    Form: X,
    Select: Ee,
    Drawer: lt,
    Modal: st,
    Empty: at,
    Badge: Oe,
    Divider: ot,
    message: se
  } = O, {
    ApiOutlined: Et,
    PlusOutlined: $e,
    ReloadOutlined: xe,
    DeleteOutlined: Be,
    LinkOutlined: De,
    DisconnectOutlined: xt
  } = $ || {}, { useEffect: Le } = e, Se = "/a2a/agents";
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
  async function we(t, n) {
    const l = H(t), a = W == null ? void 0 : W(), u = ke(), m = {
      "Content-Type": "application/json",
      ...a ? { Authorization: `Bearer ${a}` } : {},
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
    const { agent: n, onClick: l } = t, a = n.status === "connected", u = a ? "#52c41a" : n.status === "error" ? "#ff4d4f" : "#d9d9d9", m = a ? "已连接" : n.status === "error" ? "错误" : "未连接", s = {
      gateway: "阿里云Agent Hub",
      bearer: "Bearer Token",
      api_key: "API Key"
    };
    return e.createElement(
      L,
      {
        hoverable: !0,
        onClick: l,
        size: "small",
        style: { cursor: "pointer" },
        title: e.createElement(
          j,
          null,
          e.createElement(Oe, { color: u }),
          e.createElement(
            "span",
            null,
            n.name || n.alias || n.url
          )
        ),
        extra: n.auth_type ? e.createElement(
          T,
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
          De ? e.createElement(De, { style: { marginRight: 4 } }) : null,
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
            (k, z) => e.createElement(
              T,
              { key: z, style: { fontSize: 11 } },
              k.name
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
          { style: { marginTop: 4, color: u, fontSize: 11 } },
          m,
          n.error ? ` - ${n.error}` : ""
        )
      )
    );
  }
  function ct() {
    const t = e.useRef(ke()), [n, l] = E(t.current);
    return Le(() => {
      const a = () => {
        const m = ke();
        m !== t.current && (t.current = m, l(m));
      }, u = setInterval(a, 200);
      return window.addEventListener("storage", a), () => {
        clearInterval(u), window.removeEventListener("storage", a);
      };
    }, []), n;
  }
  function ut() {
    var v, q;
    const t = ct(), [n, l] = E([]), [a, u] = E(!0), [m, s] = E(!1), [r, k] = E(null), [z, M] = E(!1), [N, P] = E(!1), [ee, D] = E(!1), [x] = X.useForm(), S = Y(async () => {
      u(!0);
      try {
        const o = await we(Se);
        l((o == null ? void 0 : o.agents) || []);
      } catch {
        l([]);
      } finally {
        u(!1);
      }
    }, []);
    Le(() => {
      S();
    }, [t]);
    const R = Y(() => {
      M(!0), k(null), s(!0), x.resetFields(), x.setFieldsValue({
        url: "",
        alias: "",
        auth_type: "",
        auth_token: ""
      });
    }, [x]), i = Y((o) => {
      M(!1), k(o), s(!0);
    }, []), d = Y(() => {
      s(!1), k(null), M(!1), x.resetFields();
    }, [x]), c = Y(async () => {
      let o;
      try {
        o = await x.validateFields();
      } catch {
        return;
      }
      const f = {
        url: String(o.url || "").trim(),
        alias: String(o.alias || "").trim() || void 0,
        auth_type: String(o.auth_type || ""),
        auth_token: String(o.auth_token || "")
      };
      if (f.url) {
        P(!0);
        try {
          await we(Se, {
            method: "POST",
            body: JSON.stringify(f)
          }), se.success("A2A Agent 注册成功"), await S(), d();
        } catch (G) {
          se.error(G.message || "注册失败");
        } finally {
          P(!1);
        }
      }
    }, [x, S, d]), b = Y(async () => {
      if (!r) return;
      const o = r.alias || r.url;
      st.confirm({
        title: `删除 ${o}`,
        content: "确定删除该远程 A2A Agent 吗？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: !0 },
        async onOk() {
          try {
            await we(`${Se}/${encodeURIComponent(o)}`, {
              method: "DELETE"
            }), se.success("A2A Agent 已删除"), await S(), d();
          } catch (f) {
            se.error(f.message || "删除失败");
          }
        }
      });
    }, [r, S, d]), fe = Y(async () => {
      if (!r) return;
      const o = r.alias || r.url;
      D(!0);
      try {
        const f = await we(
          `${Se}/${encodeURIComponent(o)}/refresh`,
          {
            method: "POST"
          }
        );
        se.success("Agent Card 已刷新"), await S(), f && k(f);
      } catch (f) {
        se.error(f.message || "刷新失败");
      } finally {
        D(!1);
      }
    }, [r, S]), te = ((v = X.useWatch) == null ? void 0 : v.call(X, "auth_type", x)) ?? "", ae = e.createElement(
      X,
      { form: x, layout: "vertical" },
      e.createElement(
        X.Item,
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
        X.Item,
        { name: "alias", label: "别名" },
        e.createElement(F, { placeholder: "输入别名（可选）" })
      ),
      e.createElement(
        X.Item,
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
      te === "gateway" ? e.createElement(
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
      te && te !== "gateway" ? e.createElement(
        X.Item,
        { name: "auth_token", label: "认证凭证" },
        e.createElement(F.Password, {
          placeholder: "Bearer Token 或 API Key"
        })
      ) : null
    ), oe = r ? e.createElement(
      "div",
      null,
      e.createElement(
        Q,
        { column: 1, bordered: !0, size: "small" },
        e.createElement(
          Q.Item,
          { label: "URL" },
          r.url
        ),
        e.createElement(
          Q.Item,
          { label: "别名" },
          r.alias || "-"
        ),
        e.createElement(
          Q.Item,
          { label: "Agent 名称" },
          r.name || "-"
        ),
        e.createElement(
          Q.Item,
          { label: "状态" },
          e.createElement(Oe, {
            color: r.status === "connected" ? "#52c41a" : r.status === "error" ? "#ff4d4f" : "#d9d9d9",
            text: r.status === "connected" ? "已连接" : r.status === "error" ? "错误" : "未连接"
          })
        ),
        e.createElement(
          Q.Item,
          { label: "认证类型" },
          r.auth_type ? e.createElement(
            T,
            { color: "blue" },
            {
              gateway: "阿里云Agent Hub",
              bearer: "Bearer Token",
              api_key: "API Key"
            }[r.auth_type] || r.auth_type
          ) : "无认证"
        ),
        e.createElement(
          Q.Item,
          { label: "描述" },
          r.description || "-"
        ),
        e.createElement(
          Q.Item,
          { label: "版本" },
          r.version || "-"
        )
      ),
      ((q = r.skills) == null ? void 0 : q.length) > 0 ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "技能"),
        ...r.skills.map(
          (o, f) => e.createElement(
            L,
            { key: f, size: "small", style: { marginBottom: 8 } },
            e.createElement("strong", null, o.name),
            o.description ? e.createElement(
              "div",
              { style: { color: "#666", fontSize: 12 } },
              o.description
            ) : null
          )
        )
      ) : null,
      r.capabilities ? e.createElement(
        "div",
        { style: { marginTop: 16 } },
        e.createElement("h4", null, "能力"),
        e.createElement(
          j,
          null,
          e.createElement(
            T,
            {
              color: r.capabilities.streaming ? "green" : "default"
            },
            "Streaming"
          ),
          e.createElement(
            T,
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
      e.createElement(ot, null),
      e.createElement(
        j,
        null,
        e.createElement(
          B,
          {
            type: "primary",
            icon: xe ? e.createElement(xe) : null,
            loading: ee,
            onClick: fe
          },
          "刷新 Agent Card"
        ),
        e.createElement(
          B,
          {
            danger: !0,
            icon: Be ? e.createElement(Be) : null,
            onClick: b
          },
          "删除"
        )
      )
    ) : null, J = e.createElement(
      lt,
      {
        title: z ? "注册远程 A2A Agent" : (r == null ? void 0 : r.name) || (r == null ? void 0 : r.alias) || "Agent 详情",
        open: m,
        onClose: d,
        width: 480,
        footer: z ? e.createElement(
          j,
          { style: { float: "right" } },
          e.createElement(B, { onClick: d }, "取消"),
          e.createElement(
            B,
            { type: "primary", loading: N, onClick: c },
            "注册"
          )
        ) : null
      },
      z ? ae : oe
    ), U = e.createElement(
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
          j,
          null,
          e.createElement(
            B,
            {
              icon: xe ? e.createElement(xe) : null,
              onClick: S,
              loading: a
            },
            "刷新列表"
          ),
          e.createElement(
            B,
            {
              type: "primary",
              icon: $e ? e.createElement($e) : null,
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
        ge ? e.createElement(ge, {
          style: { marginRight: 4, color: "#faad14" }
        }) : null,
        "当前 A2A 功能仅支持 CloudPaw 插件连接阿里云 Skills 门户 Agent，连接其他 Agent 可能存在不兼容问题。"
      )
    ), K = a ? e.createElement(
      "div",
      { style: { textAlign: "center", padding: 60 } },
      e.createElement(pe, { size: "large" })
    ) : n.length === 0 ? e.createElement(at, { description: "暂无注册的远程 A2A Agent" }) : e.createElement(
      "div",
      {
        style: {
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 12
        }
      },
      ...n.map(
        (o) => e.createElement(it, {
          key: o.alias || o.url,
          agent: o,
          onClick: () => i(o)
        })
      )
    );
    return e.createElement(
      "div",
      { style: { padding: 24 } },
      U,
      K,
      J
    );
  }
  (Me = (je = window.QwenPaw).registerToolRender) == null || Me.call(je, "cloudpaw", {
    proposal_choice: tt,
    manage_prd: nt,
    a2a_call: rt
  }), (He = (Ne = window.QwenPaw).registerRoutes) == null || He.call(Ne, "cloudpaw", [
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
  const e = "qwenpaw-last-used-agent", O = "qwenpaw-agent-storage", $ = "cloudpaw-first-install", H = "cloud-orchestrator";
  if (!localStorage.getItem($)) {
    localStorage.setItem($, "true"), localStorage.setItem(e, H);
    try {
      const W = localStorage.getItem(O);
      if (W) {
        const L = JSON.parse(W);
        L.state = L.state || {}, L.state.selectedAgent = H, localStorage.setItem(O, JSON.stringify(L));
      } else
        localStorage.setItem(
          O,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: H,
              agents: [],
              lastChatIdByAgent: {}
            }
          })
        );
    } catch {
    }
    try {
      sessionStorage.setItem(
        O,
        JSON.stringify({
          version: 0,
          state: {
            selectedAgent: H,
            agents: [],
            lastChatIdByAgent: {}
          }
        })
      );
    } catch {
    }
    console.info(
      "[cloudpaw] Set default agent to cloud-orchestrator for first-time user"
    ), window.location.reload();
  }
}
function gt() {
  var j;
  const e = (j = window.QwenPaw) == null ? void 0 : j.modules;
  if (!e) return;
  const O = e["Chat/OptionsPanel/defaultConfig"];
  if (!(O != null && O.configProvider)) {
    console.warn(
      "[cloudpaw] configProvider not found — skipping welcome/theme patch"
    );
    return;
  }
  const $ = O.configProvider, H = $.getConfig.bind($), W = "https://gw.alicdn.com/imgextra/i2/O1CN01pyXzjQ1EL1PuZMlSd_!!6000000000334-2-tps-288-288.png", L = {
    zh: "Hi, 我是 CloudPaw",
    en: "Hi, I'm CloudPaw",
    ja: "こんにちは、CloudPaw です",
    ru: "Привет, я CloudPaw"
  }, ue = {
    zh: "我可以帮助你部署云资源、管理基础设施，并在阿里云上编排服务。请在左上角下拉框选择「CloudPaw-Master」开启任务。对于复杂的长程任务，建议使用 /mission 命令启动 Mission Mode 来自动拆解和执行。",
    en: "I can help you deploy cloud resources, manage infrastructure, and orchestrate services on Alibaba Cloud. Please select 'CloudPaw-Master' from the dropdown in the top-left corner to get started. For complex, multi-step tasks, use /mission to start Mission Mode for automated decomposition and execution.",
    ja: "クラウドリソースのデプロイ、インフラの管理、Alibaba Cloudでのサービスオーケストレーションをお手伝いします。左上のドロップダウンから「CloudPaw-Master」を選択してタスクを開始してください。複雑なタスクには /mission コマンドで Mission Mode を起動し、自動分解・実行できます。",
    ru: "Я могу помочь вам развернуть облачные ресурсы и управлять инфраструктурой на Alibaba Cloud. Выберите 'CloudPaw-Master' в выпадающем списке в левом верхнем углу, чтобы начать. Для сложных задач используйте /mission для автоматической декомпозиции и выполнения."
  }, T = {
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
    const B = localStorage.getItem("language") || "";
    return B ? B.split("-")[0] : (navigator.language || "").split("-")[0] || "en";
  }
  $.getGreeting = () => L[de()] || L.en, $.getDescription = () => ue[de()] || ue.en, $.getPrompts = () => T[de()] || T.en, $.getConfig = function(B) {
    var me;
    const F = H(B);
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
  }, console.info("[cloudpaw] Patched welcome config & theme via configProvider");
}
ft();
