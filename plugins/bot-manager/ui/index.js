/**
 * Bot 管理器 - 前端
 * 统一管理多个渠道 Bot 配置，当前支持微信(扫码) + 钉钉(凭据)
 * 渠道定义集中管理，新增渠道只需在 CHANNEL_DEFS 加一个条目
 */
(function () {
  'use strict';

  if (!window.QwenPaw || !window.QwenPaw.host) {
    console.error("[bot-manager] QwenPaw not ready");
    return;
  }

  var QP = window.QwenPaw;
  var React = QP.host.React;
  var h = React.createElement;
  var useState = React.useState;
  var useEffect = React.useEffect;
  var useRef = React.useRef;

  var PLUGIN_ID = "bot-manager";

  // ============ 图标 ============
  var WechatIcon = function (p) {
    return h("svg", Object.assign({ width: "24", height: "24", viewBox: "0 0 24 24", fill: "currentColor" }, p || {}),
      h("path", { d: "M8.5,14.5c0.6,0,1.2-0.1,1.8-0.2c0.5,0.9,1.5,1.5,2.7,1.5c0.4,0,0.8-0.1,1.2-0.2l2.4,1.3c0.2,0.1,0.4,0,0.5-0.2c0.1-0.2,0-0.4-0.2-0.5l-1.8-1c0.4-0.4,0.7-0.9,0.7-1.5c0-1.6-1.6-2.9-3.5-2.9c-1.9,0-3.5,1.3-3.5,2.9S6.6,14.5,8.5,14.5z M17.8,12.6c-3.4,0-6.2,2.4-6.2,5.2c0,2.9,2.8,5.2,6.2,5.2s6.2-2.4,6.2-5.2C24,14.9,21.2,12.6,17.8,12.6z", fill: "#07C160" })
    );
  };
  var DingtalkIcon = function (p) {
    return h("svg", Object.assign({ width: "24", height: "24", viewBox: "0 0 1024 1024", fill: "currentColor" }, p || {}), [
      h("path", { d: "M571.7 473.5l63.5-62.6c4-3.9 1.4-7.6-2.6-7.6h-52.4l-49.5 50.6c-2.1 2.2-3.3 5.1-3.3 8.2v18.8c0 6.3 5.1 11.4 11.4 11.4h84.8c5.6 0 8.5-6.7 4.5-10.7l-56.4-58.1z", fill: "#0089FF" }),
      h("path", { d: "M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm153.7 546.3c-1.4 6.1-7.5 9.9-13.6 8.5l-8.1-1.9c-5.9-1.4-9.7-7.1-8.7-13.1 6-35.7-8.8-67.4-40.3-86.1-5.7-3.4-7.6-10.8-4.2-16.5l4.3-7.2c3.4-5.7 10.8-7.6 16.6-4.3 40.6 24.2 62.6 66.3 54.3 120.6zm-89.5-86.4c-19.3-11.8-42.9-16.2-65.5-12.9-6.3.9-12.1-3.4-13.2-9.7l-1.4-8.4c-1-6.2 3.1-12.1 9.3-13.3 28.9-5.6 59.3 0 84 15.3 7.1 4.4 9.3 13.7 4.9 20.8l-4.7 7.6c-4.3 7.1-13.6 9.4-20.7 5l2.3-4z", fill: "#0089FF" })
    ]);
  };

  // ============ 渠道定义（核心可扩展结构） ============
  // 新增渠道：在此添加一个条目即可，无需改其他代码
  var CHANNEL_DEFS = {
    wechat: {
      name: "微信",
      icon: WechatIcon,
      color: "#07C160",
      binding: "qrcode",
      credentialLabel: "Token",
      hasCreds: function (c) { return !!c.bot_token; },
      columns: [
        { key: "bot_prefix", label: "前缀" },
        { key: "dm_policy", label: "私聊策略" },
        { key: "group_policy", label: "群聊策略" },
      ],
      editFields: [
        { key: "bot_prefix", label: "Bot 前缀", type: "input", placeholder: "如: [助手]" },
        { key: "dm_policy", label: "私聊策略", type: "select", options: [["open", "开放"], ["whitelist", "白名单"], ["closed", "关闭"]] },
        { key: "group_policy", label: "群聊策略", type: "select", options: [["open", "开放"], ["whitelist", "白名单"], ["closed", "关闭"]] },
      ],
      batchFields: [
        { key: "enabled", label: "启用状态", type: "select-tri", options: [["true", "启用"], ["false", "禁用"]] },
        { key: "bot_prefix", label: "Bot 前缀", type: "input" },
      ],
      credentialHint: "Token 必须通过扫码获取，不可手动输入",
    },
    dingtalk: {
      name: "钉钉",
      icon: DingtalkIcon,
      color: "#0089FF",
      binding: "manual",
      credentialLabel: "凭据",
      hasCreds: function (c) { return !!(c.client_id && c.client_secret); },
      columns: [
        { key: "message_type", label: "消息类型" },
        { key: "bot_prefix", label: "前缀" },
      ],
      credentialFields: [
        { key: "client_id", label: "Client ID (AppKey)", type: "text", placeholder: "钉钉开放平台 → AppKey" },
        { key: "client_secret", label: "Client Secret (AppSecret)", type: "password", placeholder: "钉钉开放平台 → AppSecret" },
        { key: "robot_code", label: "Robot Code（可选）", type: "text", placeholder: "机器人的 robot_code" },
      ],
      editFields: [
        { key: "bot_prefix", label: "Bot 前缀", type: "input", placeholder: "如: [助手]" },
        { key: "message_type", label: "消息类型", type: "select", options: [["markdown", "Markdown"], ["text", "纯文本"]] },
        { key: "cron_message_type", label: "Cron 消息类型", type: "select", options: [["markdown", "Markdown"], ["text", "纯文本"]] },
        { key: "streaming_enabled", label: "流式回复", type: "switch" },
        { key: "share_session_in_group", label: "群聊共享会话", type: "switch" },
        { key: "at_sender_on_reply", label: "回复@发送者", type: "switch" },
        { key: "card_auto_layout", label: "卡片自动排版", type: "switch" },
        { key: "card_template_id", label: "卡片模板 ID", type: "input", placeholder: "钉钉互动卡片模板 ID" },
        { key: "endpoint", label: "自定义 Endpoint", type: "input", placeholder: "留空使用默认" },
      ],
      batchFields: [
        { key: "enabled", label: "启用状态", type: "select-tri", options: [["true", "启用"], ["false", "禁用"]] },
        { key: "message_type", label: "消息类型", type: "select-tri", options: [["markdown", "Markdown"], ["text", "纯文本"]] },
        { key: "bot_prefix", label: "Bot 前缀", type: "input" },
      ],
      credentialHint: "获取方式：登录钉钉开放平台（open.dingtalk.com）→ 创建应用 → 添加「机器人」能力 → 复制 AppKey 和 AppSecret",
    },
  };

  // ============ API ============
  function fetchApi(path, options) {
    var url = QP.host.getApiUrl("/plugins/bot-manager" + path);
    return fetch(url, options).then(function (r) {
      if (!r.ok) throw new Error("API " + r.status);
      return r.json();
    });
  }

  function notify(type, msg) {
    var colors = { success: "#52c41a", error: "#ff4d4f", warning: "#faad14" };
    var icons = { success: "✓", error: "✗", warning: "⚠" };
    var n = document.createElement("div");
    n.style.cssText = "position:fixed;top:20px;right:20px;background:#fff;border-left:4px solid " + (colors[type] || "#1890ff") + ";padding:14px 18px;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:9999;display:flex;gap:10px;font-size:14px;animation:bmIn .3s ease;";
    n.innerHTML = '<span style="color:' + (colors[type] || "#1890ff") + ';font-weight:bold">' + (icons[type] || "ℹ") + "</span><span>" + msg + "</span>";
    var s = document.createElement("style"); s.textContent = "@keyframes bmIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}";
    document.head.appendChild(s); document.body.appendChild(n);
    setTimeout(function () { n.style.animation = "bmIn .3s reverse"; setTimeout(function () { n.parentNode && n.parentNode.removeChild(n); }, 300); }, 2500);
  }

  // ============ 小组件 ============
  function ToggleSwitch(props) {
    var on = props.checked;
    return h("div", {
      style: { width: "40px", height: "22px", borderRadius: "22px", position: "relative", cursor: "pointer", background: on ? "#0089FF" : "#d9d9d9", transition: "background .3s" },
      onClick: function () { props.onChange(!on); }
    }, h("div", { style: { width: "18px", height: "18px", borderRadius: "50%", background: "#fff", position: "absolute", top: "2px", left: on ? "20px" : "2px", transition: "left .3s" } }));
  }

  // ============ 扫码 Hook（用于 qrcode 渠道） ============
  function useQrCode(config) {
    var channel = config.channel;
    var onSuccess = config.onSuccess || function () {};
    var onError = config.onError || function () {};
    var onStatus = config.onStatusChange || function () {};

    var [img, setImg] = useState("");
    var [loading, setLoading] = useState(false);
    var timer = useRef(null);
    var done = useRef(false);

    function stop() { if (timer.current) { clearTimeout(timer.current); timer.current = null; } }

    function reset() { stop(); setImg(""); done.current = false; }

    function poll(token) {
      timer.current = setTimeout(function () {
        var url = QP.host.getApiUrl("/config/channels/" + channel + "/qrcode/status?token=" + encodeURIComponent(token));
        fetch(url, { headers: QP.host.getAuthHeaders ? QP.host.getAuthHeaders() : {} })
          .then(function (r) { return r.ok ? r.json() : Promise.reject("status " + r.status); })
          .then(function (res) {
            onStatus(res.status, res);
            if (res.status === "confirmed") {
              if (done.current) return;
              done.current = true; setImg("");
              var creds = res.credentials || {};
              var bt = creds.bot_token || res.bot_token || creds.token || res.token;
              if (bt) { var c = res.credentials || {}; c.bot_token = bt; onSuccess(c); }
              else onError("token not found");
            } else if (res.status === "expired" || res.status === "fail") {
              setImg(""); onError(res.status);
            } else { poll(token); }
          })
          .catch(function () { poll(token); });
      }, 2000);
    }

    function fetchQr() {
      reset(); setLoading(true);
      var url = QP.host.getApiUrl("/config/channels/" + channel + "/qrcode");
      fetch(url, { headers: QP.host.getAuthHeaders ? QP.host.getAuthHeaders() : {} })
        .then(function (r) { return r.ok ? r.json() : Promise.reject("qrcode " + r.status); })
        .then(function (res) {
          if (!res || !res.qrcode_img) { onError("fetch"); return; }
          setImg(res.qrcode_img); poll(res.poll_token);
        })
        .catch(function () { onError("fetch"); })
        .finally(function () { setLoading(false); });
    }

    useEffect(function () { return stop; }, []);
    return { img: img, loading: loading, fetchQr: fetchQr, stopPoll: stop, reset: reset };
  }

  // ============ 样式 ============
  var S = {
    container: { padding: "20px", maxWidth: "1200px", margin: "0 auto" },
    header: { marginBottom: "20px", borderBottom: "1px solid #eee", paddingBottom: "15px" },
    title: { fontSize: "24px", fontWeight: "bold", marginBottom: "6px", display: "flex", alignItems: "center", gap: "10px" },
    subtitle: { color: "#666", fontSize: "14px" },
    tabs: { display: "flex", gap: "8px", marginBottom: "16px" },
    tab: function (active, color) {
      return { padding: "8px 20px", borderRadius: "6px", cursor: "pointer", border: "1px solid " + (active ? color : "#d9d9d9"), background: active ? color : "#fff", color: active ? "#fff" : "#333", fontWeight: active ? "600" : "400", display: "flex", alignItems: "center", gap: "6px", fontSize: "14px" };
    },
    stats: { display: "flex", gap: "16px", marginBottom: "16px" },
    statCard: { background: "#f5f5f5", padding: "14px", borderRadius: "8px", minWidth: "120px" },
    statValue: { fontSize: "24px", fontWeight: "bold", color: "#0089FF" },
    statLabel: { fontSize: "12px", color: "#666" },
    toolbar: { display: "flex", gap: "10px", marginBottom: "14px", alignItems: "center" },
    btn: { padding: "8px 16px", border: "1px solid #d9d9d9", borderRadius: "4px", cursor: "pointer", background: "#fff", fontSize: "14px" },
    btnPrimary: function (c) { return { padding: "8px 16px", border: "none", borderRadius: "4px", cursor: "pointer", background: c || "#0089FF", color: "#fff", fontSize: "14px" }; },
    table: { width: "100%", borderCollapse: "collapse", background: "#fff", borderRadius: "8px", overflow: "hidden" },
    th: { padding: "12px", textAlign: "left", borderBottom: "1px solid #eee", background: "#fafafa", fontWeight: "600" },
    td: { padding: "12px", borderBottom: "1px solid #eee" },
    badge: { padding: "4px 8px", borderRadius: "4px", fontSize: "12px", fontWeight: "500" },
    badgeOk: { background: "#52c41a", color: "#fff" },
    badgeNo: { background: "#faad14", color: "#fff" },
    badgeOff: { background: "#ff4d4f", color: "#fff" },
    actBtn: function (primary, color) { return { padding: "4px 8px", margin: "0 2px", border: primary ? "none" : "1px solid #d9d9d9", borderRadius: "4px", cursor: "pointer", background: primary ? (color || "#0089FF") : "#fff", color: primary ? "#fff" : "#333", fontSize: "12px" }; },
    modal: { position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 },
    modalContent: { background: "#fff", padding: "24px", borderRadius: "8px", minWidth: "420px", maxWidth: "560px", maxHeight: "85vh", overflowY: "auto" },
    modalTitle: { fontSize: "18px", fontWeight: "bold", marginBottom: "16px" },
    formGroup: { marginBottom: "16px" },
    label: { display: "block", marginBottom: "6px", fontWeight: "500", fontSize: "14px" },
    input: { width: "100%", padding: "8px", border: "1px solid #d9d9d9", borderRadius: "4px", boxSizing: "border-box" },
    select: { width: "100%", padding: "8px", border: "1px solid #d9d9d9", borderRadius: "4px", boxSizing: "border-box" },
    switchRow: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0" },
    actions: { display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "20px" },
    empty: { textAlign: "center", padding: "40px", color: "#999" },
    loading: { textAlign: "center", padding: "40px", color: "#666" },
    error: { color: "#ff4d4f", padding: "20px", background: "#fff2f0", borderRadius: "4px" },
    hint: { background: "#e3f2fd", border: "1px solid #2196f3", borderRadius: "4px", padding: "10px 14px", fontSize: "13px", color: "#1565c0", marginTop: "12px", lineHeight: "1.6" },
  };

  // ============ 动态字段渲染器 ============
  function FieldRenderer(props) {
    var field = props.field;
    var value = props.value;
    var onChange = props.onChange;
    var chDef = props.chDef;

    if (field.type === "input") {
      return h("input", { style: S.input, type: "text", value: value || "", onChange: function (e) { onChange(e.target.value); }, placeholder: field.placeholder || "" });
    }
    if (field.type === "text" || field.type === "password") {
      return h("input", { style: S.input, type: field.type === "password" ? (props.showSecret ? "text" : "password") : "text", value: value || "", onChange: function (e) { onChange(e.target.value); }, placeholder: field.placeholder || "" });
    }
    if (field.type === "select") {
      return h("select", { style: S.select, value: value || "", onChange: function (e) { onChange(e.target.value); } },
        (field.options || []).map(function (opt) { return h("option", { key: opt[0], value: opt[0] }, opt[1]); })
      );
    }
    if (field.type === "switch") {
      return h("div", { style: S.switchRow },
        h("span", { style: { fontSize: "14px" } }, field.label),
        h(ToggleSwitch, { checked: !!value, onChange: onChange })
      );
    }
    return null;
  }

  // ============ 主组件 ============
  function BotManager() {
    var channelKeys = Object.keys(CHANNEL_DEFS);
    var [currentChannel, setCurrentChannel] = useState(channelKeys[0]);
    var [agents, setAgents] = useState([]);
    var [loading, setLoading] = useState(true);
    var [error, setError] = useState(null);
    var [selected, setSelected] = useState([]);
    var [showBatch, setShowBatch] = useState(false);
    var [editing, setEditing] = useState(null);
    var [credentialAgent, setCredentialAgent] = useState(null);
    var [scanningAgent, setScanningAgent] = useState(null);
    var [status, setStatus] = useState(null);
    var [showGuide, setShowGuide] = useState(false);

    var chDef = CHANNEL_DEFS[currentChannel];

    // — 扫码相关状态（仅 qrcode 渠道用） —
    var [scanErr, setScanErr] = useState(null);
    var [scanOk, setScanOk] = useState(false);
    var [scanStatus, setScanStatus] = useState("");
    var scanAgentRef = useRef(null);

    // ── 数据加载 ──
    function loadAgents() {
      setLoading(true);
      fetchApi("/" + currentChannel + "/agents")
        .then(function (d) { setAgents(d.agents || []); setLoading(false); })
        .catch(function (e) { setError(e.message); setLoading(false); });
    }

    function loadStatus() {
      fetchApi("/" + currentChannel + "/status")
        .then(function (d) { if (d && typeof d.total_agents !== "undefined") setStatus(d); })
        .catch(function () {});
    }

    useEffect(function () { loadAgents(); setSelected([]); setStatus(null); }, [currentChannel]);
    useEffect(function () { if (agents.length >= 0) { var e = 0, w = 0; agents.forEach(function (a) { if (a.enabled) e++; if (a.has_credentials) w++; }); setStatus({ total_agents: agents.length, enabled_agents: e, agents_with_credentials: w }); } }, [agents]);

    // ── 操作 ──
    function toggleAgent(id) { fetchApi("/" + currentChannel + "/agents/" + id + "/toggle", { method: "POST" }).then(loadAgents).catch(function (e) { notify("error", "切换失败: " + e.message); }); }
    function clearCreds(id) { if (!confirm("确定清除凭据？")) return; fetchApi("/" + currentChannel + "/agents/" + id + "/clear-credentials", { method: "POST" }).then(function () { loadAgents(); notify("success", "凭据已清除"); }).catch(function (e) { notify("error", "清除失败: " + e.message); }); }

    function updateAgent(id, config) {
      return fetchApi("/" + currentChannel + "/agents/" + id + "/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) })
        .then(function () { setEditing(null); setCredentialAgent(null); loadAgents(); notify("success", "配置已保存"); })
        .catch(function (e) { notify("error", "保存失败: " + e.message); throw e; });
    }

    function doBatch(body) {
      fetchApi("/" + currentChannel + "/agents/batch-update", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function () { setShowBatch(false); setSelected([]); loadAgents(); notify("success", "批量更新完成"); })
        .catch(function (e) { notify("error", "批量更新失败: " + e.message); });
    }

    function toggleSel(id) { setSelected(function (p) { return p.indexOf(id) >= 0 ? p.filter(function (x) { return x !== id; }) : p.concat([id]); }); }
    function selectAll() { setSelected(selected.length === agents.length ? [] : agents.map(function (a) { return a.agent_id; })); }

    // ── 扫码逻辑 ──
    var qrHook = useQrCode({
      channel: currentChannel,
      onSuccess: function (creds) {
        var id = scanAgentRef.current;
        if (!id || !creds) return;
        var token = creds.bot_token || creds.token || creds.access_token;
        if (!token) return;
        setScanOk(true); setScanStatus("confirmed"); qrHook.stopPoll();
        var url = QP.host.getApiUrl("/plugins/bot-manager/" + currentChannel + "/agents/" + id + "/config");
        var headers = QP.host.getAuthHeaders ? QP.host.getAuthHeaders() : {};
        headers["Content-Type"] = "application/json";
        fetch(url, { method: "POST", headers: headers, body: JSON.stringify({ bot_token: token, enabled: true }) })
          .then(function (r) { return r.json(); })
          .then(function () { notify("success", "绑定成功！"); setTimeout(function () { setScanningAgent(null); scanAgentRef.current = null; setScanErr(null); setScanOk(false); setScanStatus(""); loadAgents(); }, 1200); })
          .catch(function (e) { setScanOk(false); setScanStatus("fail"); setScanErr({ type: "error", message: "保存失败: " + e.message }); });
      },
      onError: function (t) { qrHook.stopPoll(); setScanOk(false); setScanStatus("fail"); setScanErr({ type: t === "expired" ? "warning" : "error", message: t === "expired" ? "二维码已过期" : t === "fetch" ? "获取二维码失败" : "绑定失败: " + t }); },
      onStatusChange: function (s) { setScanStatus(s); }
    });

    function startScan(agent) { setScanningAgent(agent); scanAgentRef.current = agent.agent_id; qrHook.fetchQr(); }
    function cancelScan() { qrHook.stopPoll(); qrHook.reset(); setScanningAgent(null); scanAgentRef.current = null; setScanErr(null); setScanOk(false); setScanStatus(""); }

    // ── 渲染：渠道 Tab ──
    function renderTabs() {
      return h("div", { style: S.tabs },
        channelKeys.map(function (key) {
          var def = CHANNEL_DEFS[key];
          var active = key === currentChannel;
          return h("div", { key: key, style: S.tab(active, def.color), onClick: function () { setCurrentChannel(key); } },
            h(def.icon, { width: 18, height: 18 }), def.name
          );
        })
      );
    }

    // ── 渲染：扫码弹窗 ──
    function ScanModal() {
      var statusText = scanOk ? "✅ 绑定成功！" : qrHook.loading ? "正在获取二维码..." : scanStatus === "scanned" ? "⏳ 等待确认..." : qrHook.img ? "请使用" + chDef.name + "扫码绑定" : "准备中...";
      var statusColor = scanOk ? "#52c41a" : scanStatus === "scanned" ? "#faad14" : qrHook.img ? chDef.color : "#666";

      return h("div", { style: S.modal },
        h("div", { style: Object.assign({}, S.modalContent, { maxWidth: "400px", textAlign: "center" }) },
          h("div", { style: S.modalTitle }, scanOk ? "✅ 扫码成功" : "📱 扫码绑定" + chDef.name + " - " + scanningAgent.name),
          !scanOk && !scanStatus !== "scanned" && scanErr && h("div", { style: { background: scanErr.type === "error" ? "#fff2f0" : "#fff7e6", border: "1px solid " + (scanErr.type === "error" ? "#ffccc7" : "#ffe58f"), borderRadius: "4px", padding: "10px", marginBottom: "12px", fontSize: "13px", color: scanErr.type === "error" ? "#cf1322" : "#d46b08" } }, scanErr.message),
          !scanOk && scanStatus !== "scanned" && h("div", { style: { background: "#f5f5f5", borderRadius: "8px", padding: "16px", marginBottom: "12px" } },
            qrHook.img ? h("img", { src: "data:image/png;base64," + qrHook.img, alt: "二维码", style: { width: "200px", height: "200px", display: "block", margin: "0 auto", borderRadius: "4px" } })
              : h("div", { style: { width: "200px", height: "200px", margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "center", background: "#e8e8e8", borderRadius: "4px", color: "#999" } }, qrHook.loading ? "加载中..." : "点击获取二维码")
          ),
          h("div", { style: { fontSize: "16px", fontWeight: "500", color: statusColor } }, statusText),
          h("div", { style: S.actions, justifyContent: "center" },
            !scanOk && !qrHook.img && !qrHook.loading && h("button", { style: S.btnPrimary(chDef.color), onClick: function () { setScanErr(null); qrHook.fetchQr(); } }, scanErr ? "重新获取" : "获取二维码"),
            h("button", { style: S.btn, onClick: cancelScan }, scanOk ? "关闭" : "取消")
          )
        )
      );
    }

    // ── 渲染：凭据输入弹窗（manual 渠道） ──
    function CredentialModal() {
      var [form, setForm] = useState({});
      var [showSecret, setShowSecret] = useState(false);
      useEffect(function () {
        var init = {};
        (chDef.credentialFields || []).forEach(function (f) { init[f.key] = credentialAgent[f.key] || ""; });
        setForm(init);
      }, []);

      function submit(e) {
        e.preventDefault();
        var update = {}; var hasNew = false;
        chDef.credentialFields.forEach(function (f) {
          var val = form[f.key] || "";
          if (val.trim()) { update[f.key] = val.trim(); hasNew = true; }
          else if (f.key === "client_id" && val.trim()) { update[f.key] = val.trim(); }
        });
        if (!hasNew && !credentialAgent.has_credentials) { notify("warning", "请填写凭据"); return; }
        update.enabled = true;
        updateAgent(credentialAgent.agent_id, update);
      }

      return h("div", { style: S.modal },
        h("div", { style: S.modalContent },
          h("div", { style: S.modalTitle }, "🔑 配置" + chDef.name + "凭据 - " + credentialAgent.name),
          h("form", { onSubmit: submit },
            (chDef.credentialFields || []).map(function (f) {
              var isPwd = f.type === "password";
              return h("div", { key: f.key, style: S.formGroup },
                h("label", { style: S.label }, f.label, isPwd && credentialAgent.has_credentials ? h("span", { style: { fontSize: "12px", color: "#999", marginLeft: "8px" } }, "（留空不修改）") : ""),
                h(FieldRenderer, { field: f, value: form[f.key], showSecret: showSecret, onChange: function (v) { setForm(Object.assign({}, form, { [f.key]: v })); }, chDef: chDef }),
                isPwd && h("label", { style: { display: "flex", alignItems: "center", gap: "6px", marginTop: "6px", fontSize: "12px", color: "#666", cursor: "pointer" } },
                  h("input", { type: "checkbox", checked: showSecret, onChange: function (e) { setShowSecret(e.target.checked); } }), "显示密文")
              );
            }),
            chDef.credentialHint && h("div", { style: S.hint }, chDef.credentialHint),
            h("div", { style: S.actions },
              h("button", { style: S.btn, onClick: function () { setCredentialAgent(null); } }, "取消"),
              h("button", { style: S.btnPrimary(chDef.color), type: "submit" }, "保存并启用")
            )
          )
        )
      );
    }

    // ── 渲染：编辑弹窗（动态字段） ──
    function EditModal() {
      var [form, setForm] = useState({});
      useEffect(function () {
        var init = { enabled: editing.enabled };
        chDef.editFields.forEach(function (f) { init[f.key] = editing[f.key] !== undefined ? editing[f.key] : (f.type === "switch" ? false : ""); });
        setForm(init);
      }, []);

      function setF(k, v) { setForm(Object.assign({}, form, { [k]: v })); }

      function submit() { updateAgent(editing.agent_id, form); }

      return h("div", { style: S.modal },
        h("div", { style: S.modalContent },
          h("div", { style: S.modalTitle }, "编辑" + chDef.name + "配置 - " + editing.name),
          h("div", { style: S.formGroup },
            h("label", { style: S.label }, "启用状态"),
            h("select", { style: S.select, value: form.enabled ? "true" : "false", onChange: function (e) { setF("enabled", e.target.value === "true"); } },
              h("option", { value: "true" }, "已启用"), h("option", { value: "false" }, "已禁用"))
          ),
          chDef.editFields.map(function (f) {
            if (f.type === "switch") { return h("div", { key: f.key }, h(FieldRenderer, { field: f, value: form[f.key], onChange: function (v) { setF(f.key, v); }, chDef: chDef })); }
            return h("div", { key: f.key, style: S.formGroup },
              h("label", { style: S.label }, f.label),
              h(FieldRenderer, { field: f, value: form[f.key], onChange: function (v) { setF(f.key, v); }, chDef: chDef })
            );
          }),
          h("div", { style: S.hint }, "如需配置更多高级选项，请前往「控制 → 频道 → " + chDef.name + "」"),
          h("div", { style: S.actions },
            h("button", { style: S.btn, onClick: function () { setEditing(null); } }, "取消"),
            h("button", { style: S.btnPrimary(chDef.color), onClick: submit }, "保存")
          )
        )
      );
    }

    // ── 渲染：批量操作弹窗 ──
    function BatchModal() {
      var [form, setForm] = useState({});

      function submit() {
        var body = { agent_ids: selected };
        Object.keys(form).forEach(function (k) { if (form[k] !== "" && form[k] !== null) body[k] = k === "enabled" ? form[k] === "true" : form[k]; });
        doBatch(body);
      }

      return h("div", { style: S.modal },
        h("div", { style: S.modalContent },
          h("div", { style: S.modalTitle }, "批量更新 (" + selected.length + " 个)"),
          (chDef.batchFields || []).map(function (f) {
            return h("div", { key: f.key, style: S.formGroup },
              h("label", { style: S.label }, f.label + "（留空不修改）"),
              f.type === "input" ? h("input", { style: S.input, type: "text", value: form[f.key] || "", onChange: function (e) { setF(f.key, e.target.value); }, placeholder: "如: [助手]" })
                : h("select", { style: S.select, value: form[f.key] || "", onChange: function (e) { setF(f.key, e.target.value); } },
                  [h("option", { value: "" }, "-- 不修改 --")].concat((f.options || []).map(function (o) { return h("option", { key: o[0], value: o[0] }, o[1]); })))
            );
            function setF(k, v) { setForm(Object.assign({}, form, { [k]: v })); }
          }),
          h("div", { style: S.actions },
            h("button", { style: S.btn, onClick: function () { setShowBatch(false); } }, "取消"),
            h("button", { style: S.btnPrimary(chDef.color), onClick: submit }, "批量更新")
          )
        )
      );
    }

    // ── 主渲染 ──
    if (loading) return h("div", { style: S.loading }, "加载中...");
    if (error) return h("div", { style: S.error }, "错误: " + error);

    return h("div", { style: S.container },
      h("div", { style: S.header },
        h("div", { style: S.title }, "🤖 Bot 管理器"),
        h("div", { style: S.subtitle }, "统一管理微信、钉钉等渠道 Bot 配置"),
        h("button", { onClick: function () { setShowGuide(!showGuide); }, style: { marginTop: "10px", padding: "6px 14px", background: chDef.color, color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "13px" } }, showGuide ? "收起说明 ▲" : "查看说明 ▼")
      ),

      showGuide && h("div", { style: { background: "#f0f7ff", borderRadius: "8px", padding: "16px", marginBottom: "16px", fontSize: "13px", color: "#555", lineHeight: "1.7" } }, [
        h("strong", { key: "t" }, "使用指南"),
        h("br", { key: "b1" }),
        "• 切换上方 Tab 选择渠道（" + channelKeys.map(function (k) { return CHANNEL_DEFS[k].name; }).join(" / ") + "）",
        h("br", { key: "b2" }),
        chDef.binding === "qrcode" ? "• 点击「扫码绑定」获取二维码，用" + chDef.name + "扫码即可绑定" : "• 点击「🔑 配置凭据」手动输入" + chDef.name + " AppKey/AppSecret",
        h("br", { key: "b3" }),
        "• 点击「编辑」修改消息类型、开关等配置",
        h("br", { key: "b4" }),
        "• 勾选多个智能体后可批量操作",
        h("br", { key: "b5" }),
        "• 新增渠道：在 backend/channels.py 注册适配器 + ui/index.js 的 CHANNEL_DEFS 添加条目",
      ]),

      renderTabs(),

      // 统计
      status && h("div", { style: S.stats },
        h("div", { style: S.statCard }, h("div", { style: S.statValue }, status.total_agents || 0), h("div", { style: S.statLabel }, "智能体总数")),
        h("div", { style: S.statCard }, h("div", { style: Object.assign({}, S.statValue, { color: "#52c41a" }) }, status.enabled_agents || 0), h("div", { style: S.statLabel }, "已启用" + chDef.name)),
        h("div", { style: S.statCard }, h("div", { style: Object.assign({}, S.statValue, { color: "#faad14" }) }, status.agents_with_credentials || 0), h("div", { style: S.statLabel }, "已配置凭据"))
      ),

      // 工具栏
      h("div", { style: S.toolbar },
        h("button", { style: S.btn, onClick: loadAgents }, "🔄 刷新"),
        h("button", { style: S.btn, onClick: selectAll }, selected.length === agents.length ? "取消全选" : "全选"),
        selected.length > 0 && h("button", { style: S.btnPrimary(chDef.color), onClick: function () { setShowBatch(true); } }, "批量更新 (" + selected.length + ")")
      ),

      // 表格
      agents.length === 0 ? h("div", { style: S.empty }, "暂无智能体") :
        h("table", { style: S.table },
          h("thead", null, h("tr", null,
            h("th", { style: S.th }, h("input", { type: "checkbox", checked: selected.length === agents.length && agents.length > 0, onChange: selectAll })),
            h("th", { style: S.th }, "智能体"),
            h("th", { style: S.th }, "状态"),
            h("th", { style: S.th }, chDef.credentialLabel),
            chDef.columns.map(function (col) { return h("th", { key: col.key, style: S.th }, col.label); }),
            h("th", { style: S.th }, "操作")
          )),
          h("tbody", null, agents.map(function (a) {
            return h("tr", { key: a.agent_id },
              h("td", { style: S.td }, h("input", { type: "checkbox", checked: selected.indexOf(a.agent_id) >= 0, onChange: function () { toggleSel(a.agent_id); } })),
              h("td", { style: S.td }, h("div", null, a.name), h("div", { style: { fontSize: "12px", color: "#999" } }, a.agent_id)),
              h("td", { style: S.td }, h("span", { style: Object.assign({}, S.badge, a.enabled ? S.badgeOk : S.badgeOff) }, a.enabled ? "已启用" : "已禁用")),
              h("td", { style: S.td }, h("span", { style: Object.assign({}, S.badge, a.has_credentials ? S.badgeOk : S.badgeNo) }, a.has_credentials ? "已配置" : "未配置")),
              chDef.columns.map(function (col) { return h("td", { key: col.key, style: S.td }, a[col.key] || "-"); }),
              h("td", { style: S.td },
                // 凭据按钮
                h("button", { style: S.actBtn(true, chDef.color), onClick: function () { chDef.binding === "qrcode" ? startScan(a) : setCredentialAgent(a); } }, chDef.binding === "qrcode" ? "📱 扫码绑定" : "🔑 配置凭据"),
                // 启用/禁用
                h("button", { style: S.actBtn(), onClick: function () { toggleAgent(a.agent_id); } }, a.enabled ? "禁用" : "启用"),
                // 编辑
                h("button", { style: S.actBtn(), onClick: function () { setEditing(a); } }, "编辑"),
                // 清除
                a.has_credentials && h("button", { style: Object.assign({}, S.actBtn(), { color: "#ff4d4f" }), onClick: function () { clearCreds(a.agent_id); } }, "清除")
              )
            );
          }))
        ),

      // 弹窗
      scanningAgent && h(ScanModal),
      credentialAgent && h(CredentialModal),
      editing && h(EditModal),
      showBatch && h(BatchModal)
    );
  }

  // ============ 注册 ============
  if (QP.registerRoutes) { try { QP.registerRoutes(PLUGIN_ID, [{ path: "/apps/" + PLUGIN_ID, component: BotManager, label: "Bot 管理器", icon: function () { return h("span", null, "🤖"); } }]); console.info("[" + PLUGIN_ID + "] registerRoutes OK"); } catch (e) { console.warn("[" + PLUGIN_ID + "] registerRoutes:", e); } }
  if (QP.menu && QP.menu.add) { try { QP.menu.add(PLUGIN_ID, [{ id: PLUGIN_ID + ".menu", location: "primary.settings", label: "Bot 管理", icon: function () { return h("span", null, "🤖"); }, route: PLUGIN_ID + ".home", order: 49 }]); console.info("[" + PLUGIN_ID + "] menu.add OK"); } catch (e) { console.warn("[" + PLUGIN_ID + "] menu.add:", e); } }
  if (QP.route && QP.route.add) { try { QP.route.add(PLUGIN_ID, [{ id: PLUGIN_ID + ".home", path: "/plugin/" + PLUGIN_ID, component: BotManager }]); console.info("[" + PLUGIN_ID + "] route.add OK"); } catch (e) { console.warn("[" + PLUGIN_ID + "] route.add:", e); } }
})();