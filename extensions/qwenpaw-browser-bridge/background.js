/**
 * QwenPaw Browser Bridge - Service Worker
 *
 * Manages WebSocket connection to QwenPaw backend,
 * routes JSON-RPC commands, and controls Chrome tabs
 * via chrome.debugger CDP.
 */

// ---- State ----
let ws = null;
let wsUrl = "";
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;
const managedTabs = new Map(); // tabId -> { debuggerAttached, originalTitle }

// ---- Keepalive ----
chrome.alarms.create("keepalive", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive" && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ jsonrpc: "2.0", method: "ping" }));
  }
});

// ---- Settings ----
async function getSettings() {
  const result = await chrome.storage.local.get({
    host: "127.0.0.1",
    port: "8088",
    workspace: "default",
    autoConnect: true,
  });
  return result;
}

// ---- WebSocket connection ----
async function connect() {
  const settings = await getSettings();
  wsUrl = `ws://${settings.host}:${settings.port}/ws/browser?workspace=${settings.workspace}`;

  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    reconnectAttempts = 0;
    broadcastStatus("connected");
  };

  ws.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    handleRpcRequest(msg);
  };

  ws.onclose = () => {
    broadcastStatus("disconnected");
    scheduleReconnect();
  };

  ws.onerror = () => {
    broadcastStatus("disconnected");
  };
}

function disconnect() {
  if (ws) {
    ws.close();
    ws = null;
  }
  reconnectAttempts = 0;
  broadcastStatus("disconnected");
}

function scheduleReconnect() {
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
  reconnectAttempts++;
  setTimeout(() => connect(), delay);
}

function sendResponse(id, result) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, result }));
  }
}

function sendError(id, code, message) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }));
  }
}

// ---- JSON-RPC routing ----
async function handleRpcRequest(msg) {
  const { id, method, params } = msg;
  if (!method || !id) return;

  try {
    let result;
    switch (method) {
      case "tabs.list":
        result = await handleTabsList();
        break;
      case "tab.create":
        result = await handleTabCreate(params);
        break;
      case "tab.claim":
        result = await handleTabClaim(params);
        break;
      case "tab.release":
        result = await handleTabRelease(params);
        break;
      case "page.navigate":
        result = await handlePageNavigate(params);
        break;
      case "page.accessibilityTree":
        result = await handleAccessibilityTree(params);
        break;
      case "page.screenshot":
        result = await handleScreenshot(params);
        break;
      case "input.click":
        result = await handleClick(params);
        break;
      case "input.clickNode":
        result = await handleClickNode(params);
        break;
      case "input.type":
        result = await handleType(params);
        break;
      case "input.pressKey":
        result = await handlePressKey(params);
        break;
      case "runtime.evaluate":
        result = await handleEvaluate(params);
        break;
      default:
        sendError(id, -32601, `Method not found: ${method}`);
        return;
    }
    sendResponse(id, result);
  } catch (err) {
    sendError(id, -32000, err.message || String(err));
  }
}

// ---- Tab management ----
async function handleTabsList() {
  const tabs = await chrome.tabs.query({});
  return {
    tabs: tabs.map((t) => ({
      tabId: t.id,
      title: t.title || "",
      url: t.url || "",
      active: t.active,
      windowId: t.windowId,
    })),
  };
}

async function handleTabCreate(params) {
  const { url } = params || {};
  const tab = await chrome.tabs.create({ url: url || "about:blank", active: true });
  await attachDebugger(tab.id);
  managedTabs.set(tab.id, { debuggerAttached: true, originalTitle: tab.title || "" });
  await markTabAsTakeover(tab.id);
  return { tabId: tab.id, title: tab.title || "", url: tab.url || "" };
}

async function handleTabClaim(params) {
  const { tabId, showBanner } = params || {};
  if (!tabId) throw new Error("tabId required");
  await attachDebugger(tabId);
  const tab = await chrome.tabs.get(tabId);
  managedTabs.set(tabId, { debuggerAttached: true, originalTitle: tab.title || "" });
  await markTabAsTakeover(tabId);
  return { tabId, title: tab.title || "", url: tab.url || "" };
}

async function handleTabRelease(params) {
  const { tabId } = params || {};
  if (!tabId) throw new Error("tabId required");
  await detachDebugger(tabId);
  restoreTabAppearance(tabId);
  managedTabs.delete(tabId);
  return { tabId, released: true };
}

// ---- chrome.debugger helpers ----
function attachDebugger(tabId) {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, "1.3", () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve();
      }
    });
  });
}

function detachDebugger(tabId) {
  return new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      resolve();
    });
  });
}

function sendCDP(tabId, method, params = {}) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(result);
      }
    });
  });
}

// ---- CDP actions ----
async function handlePageNavigate(params) {
  const { tabId, url } = params || {};
  if (!tabId || !url) throw new Error("tabId and url required");
  ensureManaged(tabId);
  const result = await sendCDP(tabId, "Page.navigate", { url });
  return { frameId: result.frameId || "" };
}

async function handleAccessibilityTree(params) {
  const { tabId } = params || {};
  if (!tabId) throw new Error("tabId required");
  ensureManaged(tabId);
  const result = await sendCDP(tabId, "Accessibility.getFullAXTree", {});
  const nodes = result.nodes || [];
  const snapshot = convertAXTreeToRefs(nodes);
  return { snapshot, nodeCount: nodes.length };
}

async function handleScreenshot(params) {
  const { tabId, fullPage } = params || {};
  if (!tabId) throw new Error("tabId required");
  ensureManaged(tabId);
  const cdpParams = { format: "png" };
  if (fullPage) {
    const metrics = await sendCDP(tabId, "Page.getLayoutMetrics", {});
    const { width, height } = metrics.contentSize || metrics.cssContentSize || {};
    if (width && height) {
      await sendCDP(tabId, "Emulation.setDeviceMetricsOverride", {
        width: Math.ceil(width),
        height: Math.ceil(height),
        deviceScaleFactor: 1,
        mobile: false,
      });
      cdpParams.captureBeyondViewport = true;
    }
  }
  const result = await sendCDP(tabId, "Page.captureScreenshot", cdpParams);
  if (fullPage) {
    await sendCDP(tabId, "Emulation.clearDeviceMetricsOverride", {});
  }
  return { data: result.data, format: "png" };
}

async function handleClick(params) {
  const { tabId, x, y, button, clickCount } = params || {};
  if (!tabId) throw new Error("tabId required");
  ensureManaged(tabId);
  const btn = button || "left";
  const count = clickCount || 1;

  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mousePressed", x, y, button: btn, clickCount: count,
  });
  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x, y, button: btn, clickCount: count,
  });
  return { clicked: true, x, y };
}

async function handleClickNode(params) {
  const { tabId, backendNodeId } = params || {};
  if (!tabId || !backendNodeId) throw new Error("tabId and backendNodeId required");
  ensureManaged(tabId);

  const resolved = await sendCDP(tabId, "DOM.resolveNode", { backendNodeId });
  const objectId = resolved.object.objectId;
  const boxModel = await sendCDP(tabId, "DOM.getBoxModel", { backendNodeId });
  const content = boxModel.model.content;
  const cx = (content[0] + content[4]) / 2;
  const cy = (content[1] + content[5]) / 2;

  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mousePressed", x: cx, y: cy, button: "left", clickCount: 1,
  });
  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x: cx, y: cy, button: "left", clickCount: 1,
  });
  return { clicked: true, x: cx, y: cy, backendNodeId };
}

async function handleType(params) {
  const { tabId, text } = params || {};
  if (!tabId) throw new Error("tabId required");
  ensureManaged(tabId);
  await sendCDP(tabId, "Input.insertText", { text: text || "" });
  return { typed: true, length: (text || "").length };
}

async function handlePressKey(params) {
  const { tabId, key } = params || {};
  if (!tabId || !key) throw new Error("tabId and key required");
  ensureManaged(tabId);

  const keyMap = {
    Enter: { code: "Enter", keyCode: 13, key: "Enter" },
    Tab: { code: "Tab", keyCode: 9, key: "Tab" },
    Escape: { code: "Escape", keyCode: 27, key: "Escape" },
    Backspace: { code: "Backspace", keyCode: 8, key: "Backspace" },
    ArrowUp: { code: "ArrowUp", keyCode: 38, key: "ArrowUp" },
    ArrowDown: { code: "ArrowDown", keyCode: 40, key: "ArrowDown" },
    ArrowLeft: { code: "ArrowLeft", keyCode: 37, key: "ArrowLeft" },
    ArrowRight: { code: "ArrowRight", keyCode: 39, key: "ArrowRight" },
  };
  const mapped = keyMap[key] || { code: `Key${key.toUpperCase()}`, keyCode: key.charCodeAt(0), key };

  await sendCDP(tabId, "Input.dispatchKeyEvent", {
    type: "keyDown", ...mapped, windowsVirtualKeyCode: mapped.keyCode,
  });
  await sendCDP(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", ...mapped, windowsVirtualKeyCode: mapped.keyCode,
  });
  return { pressed: true, key };
}

async function handleEvaluate(params) {
  const { tabId, expression } = params || {};
  if (!tabId || !expression) throw new Error("tabId and expression required");
  ensureManaged(tabId);
  const result = await sendCDP(tabId, "Runtime.evaluate", {
    expression, returnByValue: true, awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Evaluation error");
  }
  return { value: result.result ? result.result.value : null };
}

// ---- AX Tree conversion ----
function convertAXTreeToRefs(nodes) {
  let refCounter = 0;
  const lines = [];

  for (const node of nodes) {
    const role = node.role ? node.role.value : "";
    if (!role || role === "none" || role === "generic") continue;

    const name = node.name ? node.name.value : "";
    const ignored = node.ignored || false;
    if (ignored) continue;

    refCounter++;
    const ref = `e${refCounter}`;
    let line = `[ref=${ref}] ${role}`;
    if (name) line += ` "${name}"`;

    if (node.properties) {
      for (const prop of node.properties) {
        if (prop.name === "value" && prop.value && prop.value.value) {
          line += ` value="${prop.value.value}"`;
        }
      }
    }
    lines.push(line);
  }
  return lines.join("\n");
}

// ---- Utilities ----
function ensureManaged(tabId) {
  if (!managedTabs.has(tabId)) {
    throw new Error(`Tab ${tabId} is not managed. Use tab.claim first.`);
  }
}

// ---- Tab appearance: Tab Group + in-page gradient border ----
const tabGroupMap = new Map(); // tabId -> groupId

const GRADIENT_BORDER_JS = `
(function(){
  if(document.getElementById('__qp_glow__')) return 'exists';
  var el=document.createElement('div');
  el.id='__qp_glow__';
  el.style.cssText='position:fixed;inset:0;z-index:2147483647;pointer-events:none;'
    +'border:3px solid transparent;'
    +'border-image:linear-gradient(135deg,#f97316,#fb923c,#fdba74,#f97316) 1;'
    +'box-shadow:inset 0 0 20px rgba(249,115,22,0.08);';
  document.documentElement.appendChild(el);
  return 'injected';
})()`;

const REMOVE_BORDER_JS = `
(function(){
  var el=document.getElementById('__qp_glow__');
  if(el)el.remove();
  return 'removed';
})()`;

async function markTabAsTakeover(tabId) {
  if (!managedTabs.has(tabId)) return;

  // 1) Tab Group (browser tab bar level)
  if (!tabGroupMap.has(tabId)) {
    try {
      const gid = await chrome.tabs.group({ tabIds: [tabId] });
      await chrome.tabGroups.update(gid, {
        color: "orange",
        title: "QwenPaw",
        collapsed: false,
      });
      tabGroupMap.set(tabId, gid);
      console.log("[QwenPaw] grouped tab", tabId);
    } catch (e) {
      console.error("[QwenPaw] group failed:", e.message);
    }
  }

  // 2) In-page gradient orange border (page level)
  const info = managedTabs.get(tabId);
  if (info?.debuggerAttached) {
    sendCDP(tabId, "Runtime.evaluate", {
      expression: GRADIENT_BORDER_JS,
      returnByValue: true,
    }).then((r) => {
      console.log("[QwenPaw] border on tab", tabId, ":", r?.result?.value);
    }).catch(() => {
      // CDP failed, try chrome.scripting fallback
      chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          if (document.getElementById("__qp_glow__")) return;
          var el = document.createElement("div");
          el.id = "__qp_glow__";
          el.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none;border:3px solid transparent;border-image:linear-gradient(135deg,#f97316,#fb923c,#fdba74,#f97316) 1;";
          document.documentElement.appendChild(el);
        },
      }).catch(() => {});
    });
  }
}

async function restoreTabAppearance(tabId) {
  // Remove tab group
  const gid = tabGroupMap.get(tabId);
  if (gid != null) {
    try { await chrome.tabs.ungroup(tabId); } catch {}
    tabGroupMap.delete(tabId);
  }
  // Remove in-page border
  const info = managedTabs.get(tabId);
  if (info?.debuggerAttached) {
    sendCDP(tabId, "Runtime.evaluate", {
      expression: REMOVE_BORDER_JS,
      returnByValue: true,
    }).catch(() => {});
  }
}

function injectBanner(tabId) {
  markTabAsTakeover(tabId);
}

function removeBanner(tabId) {
  restoreTabAppearance(tabId);
}

// ---- Status broadcast ----
function broadcastStatus(status) {
  chrome.runtime.sendMessage({ type: "STATUS_UPDATE", status }).catch(() => {});
}

// ---- Listen for messages from content/popup ----
chrome.runtime.onMessage.addListener((msg, sender, sendResp) => {
  if (msg.type === "GET_STATUS") {
    sendResp({
      connected: ws && ws.readyState === WebSocket.OPEN,
      managedTabs: Array.from(managedTabs.keys()),
    });
    return true;
  }
  if (msg.type === "CONNECT") {
    connect();
    sendResp({ ok: true });
    return true;
  }
  if (msg.type === "DISCONNECT") {
    disconnect();
    sendResp({ ok: true });
    return true;
  }
  if (msg.type === "HITL_PAUSE") {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ jsonrpc: "2.0", method: "hitl.paused", params: {} }));
    }
    sendResp({ ok: true });
    return true;
  }
  if (msg.type === "HITL_RESUME") {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ jsonrpc: "2.0", method: "hitl.resumed", params: {} }));
    }
    sendResp({ ok: true });
    return true;
  }
  if (msg.type === "HITL_STOP") {
    for (const tabId of managedTabs.keys()) {
      detachDebugger(tabId);
      removeBanner(tabId);
    }
    managedTabs.clear();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ jsonrpc: "2.0", method: "hitl.stopped", params: {} }));
    }
    sendResp({ ok: true });
    return true;
  }
  return false;
});

// ---- Tab lifecycle ----
chrome.tabs.onRemoved.addListener((tabId) => {
  if (managedTabs.has(tabId)) {
    managedTabs.delete(tabId);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        jsonrpc: "2.0", method: "tab.closed", params: { tabId },
      }));
    }
  }
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (managedTabs.has(tabId) && changeInfo.url) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        jsonrpc: "2.0", method: "tab.navigated",
        params: { tabId, url: changeInfo.url },
      }));
    }
  }
  if (managedTabs.has(tabId) && changeInfo.status === "complete") {
    markTabAsTakeover(tabId);
  }
});

// ---- Auto-connect on startup ----
getSettings().then((s) => {
  if (s.autoConnect) connect();
});
