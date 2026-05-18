const z = window.QwenPaw.host, t = z.React, Z = z.antd, A = z.getApiUrl, q = z.getApiToken, { Button: R, Card: ee, Space: N, Table: te, Typography: ne, message: f, Modal: ae, Checkbox: re } = Z, { Title: se, Text: w, Paragraph: oe } = ne;
function ie() {
  var i, o, l;
  try {
    const c = ((i = window.sessionStorage) == null ? void 0 : i.getItem("qwenpaw-agent-storage")) ?? ((o = window.localStorage) == null ? void 0 : o.getItem("qwenpaw-agent-storage"));
    if (!c) return null;
    const r = JSON.parse(c), h = (l = r == null ? void 0 : r.state) == null ? void 0 : l.selectedAgent;
    return typeof h == "string" && h ? h : null;
  } catch {
    return null;
  }
}
function O() {
  const i = {}, o = q == null ? void 0 : q();
  o && (i.Authorization = `Bearer ${o}`);
  const l = ie();
  return l && (i["X-Agent-Id"] = l), i;
}
async function _(i) {
  const o = await fetch(A(i), { headers: O() });
  if (!o.ok)
    throw new Error(`${o.status} ${await o.text()}`);
  return o.json();
}
async function J(i, o) {
  const l = await fetch(A(i), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...O() },
    body: JSON.stringify(o)
  }), c = await l.text();
  let r = null;
  try {
    r = c ? JSON.parse(c) : null;
  } catch {
    r = { raw: c };
  }
  if (!l.ok)
    throw new Error(typeof (r == null ? void 0 : r.detail) == "string" ? r.detail : c);
  return r;
}
const le = 192, ce = 208;
function pe({ folder: i }) {
  const o = t.useRef(null), [l, c] = t.useState(!1);
  return t.useEffect(() => {
    let r = !1;
    c(!1);
    const h = o.current;
    if (!h) return;
    const E = h.getContext("2d");
    if (E)
      return (async () => {
        try {
          const D = A(
            `/qwenpaw-pet/pets/${encodeURIComponent(i)}/spritesheet`
          ), P = await fetch(D, { headers: O() });
          if (!P.ok || r) throw new Error(String(P.status));
          const x = await P.blob(), b = await createImageBitmap(x);
          if (r) {
            b.close();
            return;
          }
          const S = 96, p = 104;
          h.width = S, h.height = p, E.imageSmoothingEnabled = !1, E.clearRect(0, 0, S, p), E.drawImage(b, 0, 0, le, ce, 0, 0, S, p), b.close();
        } catch {
          r || c(!0);
        }
      })(), () => {
        r = !0;
      };
  }, [i]), l ? t.createElement(w, { type: "secondary" }, "—") : t.createElement("canvas", {
    ref: o,
    width: 96,
    height: 104,
    style: {
      display: "block",
      borderRadius: 8,
      border: "1px solid rgba(0,0,0,0.08)",
      background: "rgba(0,0,0,0.02)",
      imageRendering: "pixelated"
    }
  });
}
function de() {
  const [i, o] = t.useState([]), [l, c] = t.useState(""), [r, h] = t.useState(null), [E, D] = t.useState(!1), [P, x] = t.useState(!1), [b, S] = t.useState(!0), [p, B] = t.useState(!1), [g, I] = t.useState([]), [T, C] = t.useState(!1), F = t.useRef(null), v = t.useCallback(async () => {
    D(!0);
    try {
      const [e, n] = await Promise.all([
        _("/qwenpaw-pet/pets"),
        _("/qwenpaw-pet/status")
      ]);
      o(e.pets || []), c(e.petsDir || ""), h(n.desktop ?? null);
    } catch (e) {
      f.error((e == null ? void 0 : e.message) || String(e));
    } finally {
      D(!1);
    }
  }, []);
  t.useEffect(() => {
    v();
  }, [v]);
  const W = async () => {
    try {
      const e = await J("/qwenpaw-pet/desktop/start", {}), n = e == null ? void 0 : e.desktop, a = [e == null ? void 0 : e.message, e == null ? void 0 : e.hint].filter(Boolean).join(" ");
      e != null && e.alreadyRunning && (n != null && n.ok) ? f.success(a || "Desktop pet is already running.") : (e == null ? void 0 : e.launchAttempted) === !1 && !(n != null && n.ok) ? f.error(a || "Could not start the desktop pet.") : n != null && n.ok ? f.success(a || "Desktop pet is ready.") : f.warning(
        a || "Desktop may still be starting; check pet-desktop.log if needed."
      ), await v();
    } catch (e) {
      f.error((e == null ? void 0 : e.message) || String(e));
    }
  }, U = () => {
    I([]), S(!0), C(!1), x(!0);
  }, L = async (e, n, a) => {
    const s = n ? `${n}/${e.name}` : e.name;
    if (e.isFile) {
      const d = await new Promise(
        (y, u) => e.file(y, u)
      );
      a.push({ file: d, path: s });
      return;
    }
    if (!e.isDirectory) return;
    const m = e.createReader();
    for (; ; ) {
      const d = await new Promise(
        (y, u) => m.readEntries(y, u)
      );
      if (d.length === 0) break;
      for (const y of d)
        await L(y, s, a);
    }
  }, G = async (e) => {
    var m, d, y;
    if (e.preventDefault(), C(!1), p) return;
    const n = (m = e.dataTransfer) == null ? void 0 : m.items, a = (d = e.dataTransfer) == null ? void 0 : d.files, s = [];
    if (n && n.length > 0)
      for (let u = 0; u < n.length; u++) {
        const k = n[u];
        if (k.kind !== "file") continue;
        const Q = (y = k.webkitGetAsEntry) == null ? void 0 : y.call(k);
        if (Q)
          await L(Q, "", s);
        else {
          const $ = k.getAsFile();
          $ && s.push({ file: $, path: $.name });
        }
      }
    else if (a)
      for (let u = 0; u < a.length; u++) {
        const k = a[u];
        s.push({ file: k, path: k.name });
      }
    if (s.length === 0) {
      f.warning("Drop a folder or a .zip file.");
      return;
    }
    I(s);
  }, H = (e) => {
    e.preventDefault(), p || C(!0);
  }, K = (e) => {
    e.preventDefault(), C(!1);
  }, j = () => {
    var e;
    p || (e = F.current) == null || e.click();
  }, M = (e) => {
    var s;
    const n = (s = e.target) == null ? void 0 : s.files;
    if (!n || n.length === 0) return;
    const a = [];
    for (let m = 0; m < n.length; m++) {
      const d = n[m];
      a.push({ file: d, path: d.name });
    }
    I(a), e.target.value = "";
  }, V = async () => {
    if (g.length === 0) {
      f.warning("Drop a folder or choose a .zip file first.");
      return;
    }
    B(!0);
    try {
      const e = new FormData();
      for (const { file: m, path: d } of g)
        e.append("files", m, d);
      e.append("replace", b ? "true" : "false");
      const n = await fetch(A("/qwenpaw-pet/import-pet-upload"), {
        method: "POST",
        headers: O(),
        body: e
      }), a = await n.text();
      let s = null;
      try {
        s = a ? JSON.parse(a) : null;
      } catch {
        s = { raw: a };
      }
      if (!n.ok)
        throw new Error(typeof (s == null ? void 0 : s.detail) == "string" ? s.detail : a);
      f.success(
        `Imported "${s.displayName || s.petId}" → ${s.path}`
      ), x(!1), I([]), await v();
    } catch (e) {
      f.error((e == null ? void 0 : e.message) || String(e));
    } finally {
      B(!1);
    }
  }, X = async (e) => {
    const n = e.folder;
    try {
      const a = await J("/qwenpaw-pet/switch-pet", { pet_id: n });
      if (a && a.ok === !1)
        throw new Error(a.error || a.detail || "switch failed");
      f.success(`Switched to "${e.displayName}" (${n})`), await v();
    } catch (a) {
      f.error((a == null ? void 0 : a.message) || String(a));
    }
  }, Y = [
    {
      title: "Preview",
      key: "preview",
      width: 112,
      render: (e, n) => t.createElement(pe, { key: n.folder, folder: n.folder })
    },
    { title: "Name", dataIndex: "displayName", key: "displayName" },
    { title: "Folder", dataIndex: "folder", key: "folder" },
    {
      title: "pet.json id",
      key: "manifestId",
      render: (e, n) => n.manifestId ? String(n.manifestId) : t.createElement(w, { type: "secondary" }, "—")
    },
    {
      title: "Action",
      key: "act",
      render: (e, n) => t.createElement(
        R,
        { type: "primary", size: "small", onClick: () => void X(n) },
        "Switch"
      )
    }
  ];
  return t.createElement(
    ee,
    { style: { maxWidth: 880, margin: "24px auto" } },
    t.createElement(
      N,
      { direction: "vertical", size: "large", style: { width: "100%" } },
      [
        t.createElement(
          "div",
          { key: "h" },
          t.createElement(
            se,
            { level: 3, style: { marginBottom: 4 } },
            "QwenPaw Pet"
          ),
          t.createElement(
            oe,
            { type: "secondary", style: { marginBottom: 0 } },
            "Installed pets live under your QwenPaw working directory. Start the desktop bridge, then switch the floating pet without restarting QwenPaw."
          )
        ),
        t.createElement(
          N,
          { key: "actions", wrap: !0 },
          t.createElement(
            R,
            { type: "primary", onClick: W },
            "Start desktop pet"
          ),
          t.createElement(R, { onClick: U }, "Import pet"),
          t.createElement(
            R,
            { onClick: () => void v(), loading: E },
            "Refresh"
          )
        ),
        t.createElement(
          "div",
          { key: "meta" },
          t.createElement(
            w,
            { type: "secondary" },
            "Pets directory: "
          ),
          t.createElement(w, { code: !0 }, l || "—")
        ),
        t.createElement(
          "div",
          { key: "dh" },
          t.createElement(w, { strong: !0 }, "Desktop health: "),
          t.createElement(
            w,
            { type: r != null && r.ok ? "success" : "warning" },
            r ? JSON.stringify(r) : "unknown (refresh)"
          )
        ),
        t.createElement(te, {
          key: "tbl",
          rowKey: "folder",
          loading: E,
          dataSource: i,
          columns: Y,
          pagination: !1,
          locale: {
            emptyText: "No pets found. Run: qwenpaw-pet install-pet …"
          }
        }),
        t.createElement(
          ae,
          {
            key: "import-modal",
            title: "Import pet",
            open: P,
            onOk: () => void V(),
            okText: "Import",
            okButtonProps: { loading: p },
            cancelButtonProps: { disabled: p },
            onCancel: () => {
              p || x(!1);
            },
            destroyOnClose: !0
          },
          t.createElement(
            N,
            { direction: "vertical", style: { width: "100%" } },
            t.createElement(
              "div",
              {
                role: "button",
                tabIndex: 0,
                onClick: j,
                onDrop: G,
                onDragOver: H,
                onDragLeave: K,
                onKeyDown: (e) => {
                  (e.key === "Enter" || e.key === " ") && (e.preventDefault(), j());
                },
                style: {
                  border: `2px dashed ${T ? "#1677ff" : "#d9d9d9"}`,
                  borderRadius: 8,
                  padding: "32px 16px",
                  textAlign: "center",
                  cursor: p ? "not-allowed" : "pointer",
                  background: T ? "rgba(22, 119, 255, 0.06)" : "#fafafa",
                  transition: "border-color .15s ease, background .15s ease",
                  userSelect: "none",
                  color: T ? "#1677ff" : void 0
                }
              },
              // Line-art cube icon (matches the dropzone reference)
              t.createElement(
                "svg",
                {
                  width: 48,
                  height: 48,
                  viewBox: "0 0 24 24",
                  fill: "none",
                  stroke: "currentColor",
                  strokeWidth: 1.5,
                  strokeLinecap: "round",
                  strokeLinejoin: "round",
                  style: {
                    display: "block",
                    margin: "0 auto 12px",
                    opacity: 0.7
                  }
                },
                t.createElement("path", {
                  d: "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"
                }),
                t.createElement("polyline", {
                  points: "3.27 6.96 12 12.01 20.73 6.96"
                }),
                t.createElement("line", {
                  x1: "12",
                  y1: "22.08",
                  x2: "12",
                  y2: "12"
                })
              ),
              t.createElement(
                "div",
                {
                  style: {
                    fontSize: 16,
                    fontWeight: 600,
                    marginBottom: 4
                  }
                },
                "Drop a folder or .zip file here"
              ),
              t.createElement(
                w,
                { type: "secondary" },
                "or click to choose a .zip"
              )
            ),
            t.createElement("input", {
              ref: F,
              type: "file",
              accept: ".zip,application/zip",
              style: { display: "none" },
              onChange: M
            }),
            g.length === 0 ? t.createElement(
              w,
              { type: "secondary", style: { fontSize: 12 } },
              "Folder or unzipped archive must contain pet.json and spritesheet.webp (1536×1872)."
            ) : t.createElement(
              w,
              null,
              g.length === 1 ? `Selected: ${g[0].path}` : `Selected: ${g.length} files (root: ${g[0].path.split("/")[0] || g[0].path})`
            ),
            t.createElement(
              re,
              {
                checked: b,
                onChange: (e) => S(!!e.target.checked),
                disabled: p
              },
              "Replace if a pet with the same id already exists"
            )
          )
        )
      ]
    )
  );
}
class fe {
  constructor() {
    this.id = "qwenpaw-pet";
  }
  setup() {
    var o, l;
    (l = (o = window.QwenPaw).registerRoutes) == null || l.call(o, this.id, [
      {
        path: "/plugin/qwenpaw-pet/pets",
        component: de,
        label: "Pet",
        icon: "🐾",
        priority: 42
      }
    ]);
  }
}
new fe().setup();
