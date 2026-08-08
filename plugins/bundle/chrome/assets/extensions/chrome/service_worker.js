const NATIVE_HOST = "com.qwenpaw.browser";
const JSONRPC_VERSION = "2.0";
const WATCHDOG_ALARM = "qwenpaw-native-watchdog";
const WATCHDOG_PERIOD_MINUTES = 0.5;
const FAST_RECONNECT_DEBOUNCE_MS = 10 * 1000;
const DEGRADE_AFTER_DISCONNECT_MS = 60 * 1000;
const CONTROL_TAB_GROUP_TITLE = "QwenPaw";
const CONTROL_TAB_GROUP_COLOR = "blue";
const EXTENSIONS_MANAGER_URL = "chrome://extensions";
const PROTECTED_BROWSER_SCHEMES = new Set([
  "brave:",
  "chrome:",
  "chrome-extension:",
  "devtools:",
  "edge:",
  "moz-extension:",
  "opera:",
  "vivaldi:",
]);
const LOCAL_QWENPAW_HOSTS = new Set([
  "127.0.0.1",
  "::1",
  "[::1]",
  "localhost",
]);
const RELOAD_COOLDOWN_MS = 1000;
const TAB_OWNERSHIP_OWNED = "owned";
const TAB_OWNERSHIP_BORROWED = "borrowed";
const TAB_OWNERSHIP_PENDING_CLAIM = "pending_claim";
const TAB_OWNERSHIP_PROTECTED = "protected";
const TAB_OWNERSHIP_ORPHANED = "orphaned";
const TAB_OWNERSHIP_RELEASED = "released";
const COMMAND_RECEIPT_PREFIX = "qwenpawCommandReceipt:";
const COMMAND_EVICTIONS_KEY = "qwenpawCommandReceiptEvictions";
const COMMAND_RECEIPT_TTL_MS = 5 * 60 * 1000;
const COMMAND_RECEIPT_CAPACITY = 256;
const LAST_DISCONNECT_KEY = "qwenpawLastDisconnect";
const DISCONNECT_REPORT_MAX_AGE_MS = 3600000;
// Bounded so 256 receipts plus metadata and evictions stay below
// chrome.storage.session's 10MB quota. Raise only after redoing that math.
const COMMAND_RESULT_MAX_BYTES = 32 * 1024;
// Identifies this service-worker instance. MV3 can terminate the worker at any
// time; a receipt whose epoch is no longer current proves its executor is gone.
// Extension-internal only: never sent on the wire.
const EXECUTOR_EPOCH = crypto.randomUUID();

if (typeof importScripts === "function") {
  try {
    importScripts("bridge_config.js");
  } catch (error) {
    // Optional local development config; production builds omit it.
  }
}

const bridgeConfig = globalThis.QWENPAW_BRIDGE_CONFIG || {};
const extensionBuild = bridgeConfig.build || {};
const LOCAL_QWENPAW_PORTS = new Set([
  String(Number(bridgeConfig.localPort) || 8088),
]);

let nmPort = null;
let nextNotificationId = 1;
let cleanupEpoch = 0;
let lastDisconnectReason = "";
let lastDisconnect = null;
let lastReloadAt = 0;
let lastFastReconnectAt = 0;
let disconnectedSince = null;
const managedTabs = new Set();
const createdTabs = new Set();
const tabMetadata = new Map();
const commandInflight = new Map();
const popupEventCounts = new Map();
const MAX_POPUP_EVENTS_PER_SOURCE = 8;

async function persistManagedTabs() {
  const persistedMetadata = {};
  for (const [tabId, metadata] of tabMetadata.entries()) {
    persistedMetadata[String(tabId)] = { ...metadata };
  }
  await chrome.storage.session.set({
    managedTabs: Array.from(managedTabs),
    createdTabs: Array.from(createdTabs),
    tabMetadata: persistedMetadata,
    disconnectedSince,
  });
}

async function restoreManagedTabs() {
  const data = await chrome.storage.session.get([
    "managedTabs",
    "createdTabs",
    "tabMetadata",
    "disconnectedSince",
    LAST_DISCONNECT_KEY,
  ]);
  const tabIds = Array.isArray(data.managedTabs) ? data.managedTabs : [];
  for (const tabId of tabIds) {
    managedTabs.add(tabId);
  }
  const createdTabIds = Array.isArray(data.createdTabs)
    ? data.createdTabs
    : [];
  for (const tabId of createdTabIds) {
    createdTabs.add(tabId);
  }
  const restoredMetadata = data.tabMetadata || {};
  for (const [rawTabId, metadata] of Object.entries(restoredMetadata)) {
    const tabId = Number(rawTabId);
    if (Number.isFinite(tabId) && metadata && typeof metadata === "object") {
      tabMetadata.set(tabId, { ...metadata, tabId });
    }
  }
  const restoredDisconnectedSince = Number(data.disconnectedSince);
  disconnectedSince =
    Number.isFinite(restoredDisconnectedSince) && restoredDisconnectedSince > 0
      ? restoredDisconnectedSince
      : null;
  const restoredLastDisconnect = data["qwenpawLastDisconnect"];
  if (
    restoredLastDisconnect &&
    typeof restoredLastDisconnect === "object" &&
    Number.isFinite(Number(restoredLastDisconnect.at))
  ) {
    lastDisconnect = {
      reason: String(restoredLastDisconnect.reason || ""),
      at: Number(restoredLastDisconnect.at),
    };
  }
}

function jsonRpcResult(id, result) {
  return { jsonrpc: JSONRPC_VERSION, id, result };
}

function jsonRpcError(id, code, message, data) {
  const error = { code, message };
  if (data !== undefined) {
    error.data = data;
  }
  return { jsonrpc: JSONRPC_VERSION, id, error };
}

function postNative(message) {
  if (!nmPort) {
    return false;
  }

  try {
    nmPort.postMessage(message);
    return true;
  } catch (error) {
    console.warn("Failed to post native message", error);
    return false;
  }
}

function sendEvent(method, params) {
  postNative({
    jsonrpc: JSONRPC_VERSION,
    id: `evt-${nextNotificationId++}`,
    method,
    params: params || {},
  });
}

function hasControlInterest() {
  return managedTabs.size > 0 || createdTabs.size > 0 || tabMetadata.size > 0;
}

function tabProtocolMetadata(tabId) {
  const metadata = tabMetadata.get(Number(tabId));
  return metadata ? { ...metadata } : {};
}

async function storeTabProtocolMetadata(tabId, metadata) {
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  const normalized = {
    protocolVersion: Number(metadata.protocolVersion || 2),
    tabId: Number(tabId),
    ownerId: String(metadata.ownerId || ""),
    workspaceId: String(metadata.workspaceId || ""),
    ownershipState: String(metadata.ownershipState || ""),
    createdByQwenPaw: Boolean(metadata.createdByQwenPaw),
  };
  if (normalized.protocolVersion === 2) {
    if (!normalized.ownerId || !normalized.workspaceId) {
      throw new Error("ownerId and workspaceId are required");
    }
  }
  tabMetadata.set(Number(tabId), normalized);
  await persistManagedTabs();
  return { ...normalized };
}

async function removeTabProtocolMetadata(tabId) {
  tabMetadata.delete(Number(tabId));
  await persistManagedTabs();
}

function tabLifecycleEventParams(tab, extra) {
  const params = { ...(extra || {}) };
  const tabId =
    tab && tab.id !== undefined
      ? tab.id
      : params.tabId !== undefined
        ? params.tabId
        : params.id;

  if (tabId !== undefined) {
    params.id = tabId;
    params.tabId = tabId;
    params.managed = managedTabs.has(tabId);
    params.createdByQwenPaw = createdTabs.has(tabId);
    params.ownershipState = tabOwnershipState(tabId, tab);
    Object.assign(params, tabProtocolMetadata(tabId));
  }

  for (const key of [
    "url",
    "pendingUrl",
    "title",
    "active",
    "windowId",
    "index",
    "openerTabId",
    "status",
    "groupId",
  ]) {
    if (tab && tab[key] !== undefined) {
      params[key] = tab[key];
    }
  }

  return params;
}

function debuggerTarget(tabId) {
  return { tabId };
}

async function attachDebugger(tabId) {
  const tab = await chrome.tabs.get(tabId);
  assertTabNotProtected(tab);
  if (managedTabs.has(tabId)) {
    return {
      tabId,
      attached: true,
      alreadyAttached: true,
      ownershipState: TAB_OWNERSHIP_BORROWED,
    };
  }

  await new Promise((resolve, reject) => {
    chrome.debugger.attach(debuggerTarget(tabId), "1.3", () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }

      resolve();
    });
  });
  managedTabs.add(tabId);
  await persistManagedTabs();
  return { tabId, attached: true, ownershipState: TAB_OWNERSHIP_BORROWED };
}

async function detachDebugger(tabId) {
  await new Promise((resolve, reject) => {
    chrome.debugger.detach(debuggerTarget(tabId), () => {
      if (chrome.runtime.lastError) {
        const message = chrome.runtime.lastError.message || "";
        if (!message.includes("Debugger is not attached")) {
          reject(new Error(message));
          return;
        }
      }

      resolve();
    });
  });
  managedTabs.delete(tabId);
  await removeTabProtocolMetadata(tabId);
  return { tabId, detached: true, ownershipState: TAB_OWNERSHIP_RELEASED };
}

function sendCdp(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(
      debuggerTarget(tabId),
      method,
      params || {},
      (result) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        resolve(result || {});
      },
    );
  });
}

function isAttachableTab(tab) {
  const url = (tab && tab.url) || "";
  return (
    (url.startsWith("http://") || url.startsWith("https://")) &&
    !isProtectedTabUrl(url)
  );
}

function isProtectedTabUrl(url) {
  const value = String(url || "").trim();
  if (!value) {
    return false;
  }
  let parsed = null;
  try {
    parsed = new URL(value);
  } catch (_error) {
    return false;
  }
  if (PROTECTED_BROWSER_SCHEMES.has(parsed.protocol)) {
    return true;
  }
  if (parsed.protocol === "about:" && value.toLowerCase() !== "about:blank") {
    return true;
  }
  return (
    LOCAL_QWENPAW_HOSTS.has(parsed.hostname) &&
    LOCAL_QWENPAW_PORTS.has(parsed.port)
  );
}

function assertTabNotProtected(tab) {
  if (isProtectedTabUrl(tab && tab.url)) {
    const error = new Error("PROTECTED_TAB_REQUIRES_EXPLICIT_OVERRIDE");
    error.code = "PROTECTED_TAB_REQUIRES_EXPLICIT_OVERRIDE";
    error.tabId = tab && tab.id;
    error.url = (tab && tab.url) || "";
    throw error;
  }
}

async function assertTabControllable(tabId) {
  const tab = await chrome.tabs.get(tabId);
  assertTabNotProtected(tab);
  if (!managedTabs.has(tabId)) {
    const error = new Error("CDP_REQUIRES_ATTACHED_TAB");
    error.code = "CDP_REQUIRES_ATTACHED_TAB";
    throw error;
  }
}

function tabOwnershipState(tabId, tab) {
  const metadata = tabProtocolMetadata(tabId);
  if (metadata.ownershipState) {
    return metadata.ownershipState;
  }
  if (createdTabs.has(tabId)) {
    return TAB_OWNERSHIP_OWNED;
  }
  if (managedTabs.has(tabId)) {
    return TAB_OWNERSHIP_BORROWED;
  }
  if (isProtectedTabUrl(tab && tab.url)) {
    return TAB_OWNERSHIP_PROTECTED;
  }
  if (tab && tab.createdByQwenPaw) {
    return TAB_OWNERSHIP_ORPHANED;
  }
  return "";
}

async function listTabs(queryInfo) {
  const tabs = await chrome.tabs.query(queryInfo || {});
  const liveTabIds = new Set(
    tabs
      .filter((tab) => tab && tab.id !== undefined)
      .map((tab) => tab.id),
  );
  let prunedCreatedTabs = false;
  for (const tabId of Array.from(createdTabs)) {
    if (!liveTabIds.has(tabId)) {
      createdTabs.delete(tabId);
      prunedCreatedTabs = true;
    }
  }
  if (prunedCreatedTabs) {
    await persistManagedTabs();
  }

  const groupCache = new Map();
  const attachGroupInfo = async (tab) => {
    if (
      !tab ||
      !Number.isInteger(tab.groupId) ||
      tab.groupId < 0 ||
      !chrome.tabGroups ||
      !chrome.tabGroups.get
    ) {
      return {};
    }
    if (!groupCache.has(tab.groupId)) {
      try {
        groupCache.set(tab.groupId, await chrome.tabGroups.get(tab.groupId));
      } catch (error) {
        groupCache.set(tab.groupId, null);
      }
    }
    const group = groupCache.get(tab.groupId);
    if (!group) {
      return {};
    }
    return {
      tabGroupId: group.id,
      tabGroupTitle: group.title || "",
      tabGroupColor: group.color || "",
    };
  };

  const visibleTabs = tabs.filter(isAttachableTab);
  return Promise.all(
    visibleTabs.map(async (tab) => {
      const metadata =
        tab && tab.id !== undefined ? tabProtocolMetadata(tab.id) : {};
      return {
        ...tab,
        ...(await attachGroupInfo(tab)),
        managed:
          tab && tab.id !== undefined ? managedTabs.has(tab.id) : false,
        createdByQwenPaw:
          metadata.createdByQwenPaw !== undefined
            ? metadata.createdByQwenPaw
            : tab && tab.id !== undefined
              ? createdTabs.has(tab.id)
              : false,
        ownershipState:
          metadata.ownershipState ||
          (tab && tab.id !== undefined ? tabOwnershipState(tab.id, tab) : ""),
        ...metadata,
      };
    }),
  );
}

async function groupControlTab(tab) {
  if (!tab || tab.id === undefined) {
    return tab;
  }
  if (!chrome.tabs.group || !chrome.tabGroups || !chrome.tabGroups.update) {
    return tab;
  }

  try {
    const groupId = await chrome.tabs.group({ tabIds: tab.id });
    await chrome.tabGroups.update(groupId, {
      title: CONTROL_TAB_GROUP_TITLE,
      color: CONTROL_TAB_GROUP_COLOR,
    });
  } catch (error) {
    console.warn("Failed to group control tab", error);
  }

  return tab;
}

async function createTab(params) {
  const protocolVersion = Number(params && params.protocolVersion ? params.protocolVersion : 2);
  const ownerId = String((params && params.ownerId) || "");
  const workspaceId = String(
    (params && (params.workspaceId || params.workspace)) || "",
  );
  if (protocolVersion === 2 && (!ownerId || !workspaceId)) {
    throw new Error("ownerId and workspaceId are required");
  }
  const tab = await chrome.tabs.create({
    url: params && params.url ? params.url : "about:blank",
    active:
      params && params.active !== undefined ? Boolean(params.active) : false,
  });
  const controlTab = await groupControlTab(tab);
  if (controlTab && controlTab.id !== undefined) {
    createdTabs.add(controlTab.id);
    await storeTabProtocolMetadata(controlTab.id, {
      protocolVersion,
      ownerId,
      workspaceId,
      ownershipState: TAB_OWNERSHIP_PENDING_CLAIM,
      createdByQwenPaw: true,
    });
    await persistManagedTabs();
  }
  return {
    ...controlTab,
    ...(
      controlTab && controlTab.id !== undefined
        ? tabProtocolMetadata(controlTab.id)
        : {}
    ),
    createdByQwenPaw: true,
    workspace: workspaceId,
  };
}

async function openExtensionsManager() {
  // This must remain separate from createTab(): the extensions manager is a
  // user-owned Chrome page, not a QwenPaw-controlled browser session tab.
  const tab = await chrome.tabs.create({
    url: EXTENSIONS_MANAGER_URL,
    active: true,
  });
  return {
    opened: true,
    tabId: tab && tab.id !== undefined ? tab.id : null,
  };
}

async function commitTabMetadata(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  const current = tabProtocolMetadata(tabId);
  const ownerId = String((params && params.ownerId) || current.ownerId || "");
  const workspaceId = String(
    (params && params.workspaceId) || current.workspaceId || "",
  );
  if (current.ownerId && current.ownerId !== ownerId) {
    throw new Error("ownerId mismatch");
  }
  if (current.workspaceId && current.workspaceId !== workspaceId) {
    throw new Error("workspaceId mismatch");
  }
  createdTabs.add(Number(tabId));
  return storeTabProtocolMetadata(tabId, {
    protocolVersion: Number(current.protocolVersion || 2),
    ownerId,
    workspaceId,
    ownershipState: TAB_OWNERSHIP_OWNED,
    createdByQwenPaw: true,
  });
}

async function ensureTabAvailable(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  // Do NOT switch the active tab. CDP commands work via the debugger channel
  // regardless of tab visibility. Switching tabs disrupts the user's browsing.
  // Just verify the tab exists and return its current state.
  const tab = await chrome.tabs.get(tabId);
  assertTabNotProtected(tab);
  return {
    tabId,
    active: tab && tab.active,
    windowId: tab && tab.windowId,
    ownershipState: tabOwnershipState(tabId, tab),
  };
}

async function activateTab(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  const existing = await chrome.tabs.get(tabId);
  assertTabNotProtected(existing);
  const tab = existing.active
    ? existing
    : await chrome.tabs.update(tabId, { active: true });
  return {
    tabId,
    active: Boolean(tab && tab.active),
    windowId: tab && tab.windowId,
    ownershipState: tabOwnershipState(tabId, tab),
  };
}

async function closeTab(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }

  if (managedTabs.has(tabId)) {
    try {
      await detachDebugger(tabId);
    } catch (error) {
      console.debug(
        "Failed to detach debugger before closing tab",
        tabId,
        error,
      );
      managedTabs.delete(tabId);
      await persistManagedTabs();
    }
  }

  await chrome.tabs.remove(tabId);
  managedTabs.delete(tabId);
  createdTabs.delete(tabId);
  await removeTabProtocolMetadata(tabId);
  return { tabId, closed: true, ownershipState: TAB_OWNERSHIP_RELEASED };
}

async function runSelfDegradation() {
  for (const tabId of Array.from(managedTabs)) {
    try {
      await detachDebugger(tabId);
    } catch (error) {
      console.warn("Failed to detach tab during self-degradation", tabId, error);
    }
  }
}

// Core instructions invoke cleanupOrphans; conservative self-degradation is the
// single autonomous exemption and never closes tabs.
async function cleanupOrphans(reason) {
  const epoch = ++cleanupEpoch;
  const managedTabIds = Array.from(managedTabs);
  const createdTabIds = Array.from(createdTabs);

  for (const tabId of managedTabIds) {
    if (epoch !== cleanupEpoch) {
      break;
    }

    try {
      await detachDebugger(tabId);
    } catch (error) {
      console.warn("Failed to detach tab during cleanup", tabId, error);
      managedTabs.delete(tabId);
      await persistManagedTabs();
    }

  }

  for (const tabId of createdTabIds) {
    if (epoch !== cleanupEpoch) {
      break;
    }

    try {
      await chrome.tabs.remove(tabId);
      sendEvent("tabs.reconciled", {
        tabId,
        ownershipState: TAB_OWNERSHIP_RELEASED,
        reconciliationReason: reason || "startup",
        closed: true,
      });
    } catch (error) {
      console.warn("Failed to close owned orphan tab", tabId, error);
    } finally {
      createdTabs.delete(tabId);
      managedTabs.delete(tabId);
      await removeTabProtocolMetadata(tabId);
    }
  }
}

async function ensureWatchdogAlarm() {
  const alarm = await chrome.alarms.get(WATCHDOG_ALARM);
  if (!alarm) {
    chrome.alarms.create(WATCHDOG_ALARM, {
      periodInMinutes: WATCHDOG_PERIOD_MINUTES,
    });
  }
}

function runtimeLastErrorMessage() {
  const lastError = chrome.runtime.lastError;
  return lastError && lastError.message ? lastError.message : "";
}

function extensionStatusPayload() {
  return {
    ok: true,
    connected: Boolean(nmPort),
    nativeHost: NATIVE_HOST,
    managedTabsCount: managedTabs.size,
    lastDisconnectReason,
    version: chrome.runtime.getManifest().version,
  };
}

function requiredCommandText(value, fieldName) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    throw new Error(`command_identity_invalid:${fieldName}`);
  }
  return normalized;
}

function commandReceiptKey(sessionId, commandId) {
  return COMMAND_RECEIPT_PREFIX + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(commandId);
}

async function commandReceipt(sessionId, commandId) {
  const key = commandReceiptKey(sessionId, commandId);
  const stored = await chrome.storage.session.get([key]);
  return stored[key] || null;
}

async function persistCommandReceipt(receipt) {
  if (!["RECEIVED", "RUNNING", "COMPLETED"].includes(receipt.state)) {
    throw new Error("command_receipt_state_invalid");
  }
  const key = commandReceiptKey(receipt.sessionId, receipt.commandId);
  await chrome.storage.session.set({
    [key]: boundedReceiptForStorage(receipt),
  });
  return receipt;
}

function boundedReceiptForStorage(receipt) {
  if (receipt.result === null || receipt.result === undefined) {
    return receipt;
  }
  let serialized;
  try {
    serialized = JSON.stringify(receipt.result);
  } catch (error) {
    serialized = undefined;
  }
  const resultBytes = serialized === undefined
    ? null : new TextEncoder().encode(serialized).length;
  if (resultBytes !== null && resultBytes <= COMMAND_RESULT_MAX_BYTES) {
    return receipt;
  }
  const { result, ...rest } = receipt;
  return { ...rest, result: null, resultTruncated: true, resultBytes };
}

async function recordCommandEvictions(evictions) {
  if (!evictions.length) return;
  const stored = await chrome.storage.session.get([COMMAND_EVICTIONS_KEY]);
  const prior = Array.isArray(stored[COMMAND_EVICTIONS_KEY])
    ? stored[COMMAND_EVICTIONS_KEY] : [];
  await chrome.storage.session.set({
    [COMMAND_EVICTIONS_KEY]: [...prior, ...evictions].slice(
      -COMMAND_RECEIPT_CAPACITY,
    ),
  });
}

async function sweepCommandReceipts() {
  const stored = await chrome.storage.session.get(null);
  const now = Date.now();
  const receipts = Object.entries(stored)
    .filter(([key, value]) =>
      key.startsWith(COMMAND_RECEIPT_PREFIX) && value &&
      typeof value === "object")
    .sort((left, right) =>
      Number(left[1].updatedAt || 0) - Number(right[1].updatedAt || 0));
  const expired = receipts.filter(([, receipt]) =>
    now - Number(receipt.updatedAt || 0) > COMMAND_RECEIPT_TTL_MS);
  const live = receipts.filter(([, receipt]) =>
    now - Number(receipt.updatedAt || 0) <= COMMAND_RECEIPT_TTL_MS);
  const excess = live.slice(
    0, Math.max(0, live.length - COMMAND_RECEIPT_CAPACITY),
  );
  const removed = [...expired, ...excess];
  if (!removed.length) return;
  await chrome.storage.session.remove(removed.map(([key]) => key));
  const expiredKeys = new Set(expired.map(([key]) => key));
  await recordCommandEvictions(removed.map(([key, receipt]) => ({
    sessionId: receipt.sessionId,
    commandId: receipt.commandId,
    commandFingerprint: receipt.commandFingerprint,
    reason: expiredKeys.has(key) ? "TTL" : "CAPACITY",
    observedAt: now,
  })));
}

async function runReceiptCommand(params, executor) {
  const sessionId = requiredCommandText(params.sessionId, "sessionId");
  const commandId = requiredCommandText(params.commandId, "commandId");
  const commandFingerprint = requiredCommandText(
    params.commandFingerprint, "commandFingerprint",
  );
  await sweepCommandReceipts();
  const key = commandReceiptKey(sessionId, commandId);
  const inflight = commandInflight.get(key);
  if (inflight) {
    if (inflight.commandFingerprint !== commandFingerprint) {
      throw new Error("command_fingerprint_mismatch");
    }
    return inflight.promise;
  }
  const promise = (async () => {
    const existing = await commandReceipt(sessionId, commandId);
    if (existing) {
      if (existing.commandFingerprint !== commandFingerprint) {
        throw new Error("command_fingerprint_mismatch");
      }
      // A stale RECEIVED receipt is the ledger's proof that its executor
      // never crossed the durable RUNNING barrier. RUNNING remains
      // non-retriable: its outcome is unknown, and honesty beats convenience.
      const provenNotStarted = existing.state === "RECEIVED" &&
        existing.executorEpoch !== EXECUTOR_EPOCH;
      if (!provenNotStarted) {
        return existing;
      }
    }
    const createdAt = Date.now();
    await persistCommandReceipt({
      sessionId, commandId, commandFingerprint, state: "RECEIVED",
      executorEpoch: EXECUTOR_EPOCH, result: null, createdAt, updatedAt: createdAt,
    });
    // The execution barrier is not redundant: RUNNING must be durable before
    // invoking the executor, the only later evidence separating never started
    // from an outcome whose result is unknown.
    await persistCommandReceipt({
      sessionId, commandId, commandFingerprint, state: "RUNNING",
      executorEpoch: EXECUTOR_EPOCH, result: null, createdAt, updatedAt: Date.now(),
    });
    const result = await executor();
    return persistCommandReceipt({
      sessionId, commandId, commandFingerprint, state: "COMPLETED",
      executorEpoch: EXECUTOR_EPOCH, result, createdAt, updatedAt: Date.now(),
    });
  })();
  commandInflight.set(key, { commandFingerprint, promise });
  try {
    return await promise;
  } finally {
    commandInflight.delete(key);
  }
}

async function executeClosedCommand(params) {
  const payload = params.payload || {};
  if (params.commandType === "CDP") {
    return sendCdp(payload.tabId, payload.method, payload.params || {});
  }
  throw new Error("command_type_unsupported");
}

async function executeCommand(params) {
  const receipt = await runReceiptCommand(params, () =>
    executeClosedCommand(params));
  return { receipt: publicReceipt(receipt) };
}

// executorEpoch is an internal executor-generation marker. It never crosses
// the wire: the host must not be able to depend on it.
function publicReceipt(receipt) {
  if (!receipt) return null;
  const { executorEpoch, ...rest } = receipt;
  return rest;
}

async function queryCommandStatus(params) {
  const sessionId = requiredCommandText(params.sessionId, "sessionId");
  const targetCommandId = requiredCommandText(
    params.targetCommandId, "targetCommandId",
  );
  const targetCommandFingerprint = requiredCommandText(
    params.targetCommandFingerprint, "targetCommandFingerprint",
  );
  const targetReceipt = await commandReceipt(sessionId, targetCommandId);
  if (targetReceipt &&
      targetReceipt.commandFingerprint !== targetCommandFingerprint) {
    throw new Error("command_fingerprint_mismatch");
  }
  const stored = await chrome.storage.session.get([COMMAND_EVICTIONS_KEY]);
  const evictions = Array.isArray(stored[COMMAND_EVICTIONS_KEY])
    ? stored[COMMAND_EVICTIONS_KEY] : [];
  const evicted = evictions.some((item) =>
    item.sessionId === sessionId &&
    item.commandId === targetCommandId &&
    item.commandFingerprint === targetCommandFingerprint);
  let observedState = "UNKNOWN";
  if (targetReceipt) {
    if (targetReceipt.state === "COMPLETED") {
      observedState = "COMPLETED";
    } else if (
      targetReceipt.state === "RECEIVED" &&
      targetReceipt.executorEpoch !== EXECUTOR_EPOCH
    ) {
      observedState = "NOT_STARTED";
    } else if (
      ["RECEIVED", "RUNNING"].includes(targetReceipt.state) &&
      targetReceipt.executorEpoch === EXECUTOR_EPOCH
    ) {
      observedState = "IN_FLIGHT";
    } else if (
      targetReceipt.state === "RUNNING" &&
      targetReceipt.executorEpoch !== EXECUTOR_EPOCH
    ) {
      observedState = "ABANDONED";
    }
  } else if (evicted) {
    observedState = "LOST";
  }
  return {
    targetReceipt: publicReceipt(targetReceipt),
    targetCommandFact: {
      observedState,
    },
  };
}

async function handleMessage(message) {
  const id = message && message.id !== undefined ? message.id : null;
  const params = message && message.params ? message.params : {};

  try {
    switch (message && message.method) {
      case "command.execute":
        return jsonRpcResult(id, await executeCommand(params));
      case "command.status":
        return jsonRpcResult(id, await queryCommandStatus(params));
      case "cdp.send":
        // Page.captureScreenshot works on background tabs when a debugger is
        // attached: chrome.debugger.attach() keeps the renderer alive and CDP
        // forces a synchronous composite before capture. No tab activation
        // needed — same mechanism that headless Chrome relies on.
        await assertTabControllable(params.tabId);
        return jsonRpcResult(
          id,
          await sendCdp(params.tabId, params.method, params.params || {}),
        );
      case "tabs.list":
        return jsonRpcResult(id, await listTabs(params.query || {}));
      case "tab.attach":
        return jsonRpcResult(id, await attachDebugger(params.tabId));
      case "tab.detach":
        return jsonRpcResult(id, await detachDebugger(params.tabId));
      case "tab.ensure":
        return jsonRpcResult(id, await ensureTabAvailable(params));
      case "tab.activate":
        return jsonRpcResult(id, await activateTab(params));
      case "tab.close":
        return jsonRpcResult(id, await closeTab(params));
      case "tab.create":
        return jsonRpcResult(id, await createTab(params));
      case "extension.open_extensions_manager":
        return jsonRpcResult(id, await openExtensionsManager());
      case "tab.metadata.commit":
        return jsonRpcResult(id, await commitTabMetadata(params));
      case "banner.show":
      case "banner.hide":
        return jsonRpcResult(id, {
          ok: false, error_code: "capability_missing",
          message: "Banner rendering is not provided by this extension.",
        });
      case "file.upload":
        return jsonRpcResult(id, {
          ok: false, error_code: "capability_missing",
          message: "File upload is handled by QwenPaw's Chrome connection.",
        });
      case "download.read":
        return jsonRpcResult(id, {
          ok: false,
          error_code: "capability_missing",
          message:
            "Download artifacts are collected through Chrome CDP events.",
        });
      case "dialog.set":
        return jsonRpcResult(id, {
          ok: false,
          error_code: "capability_missing",
          message: "Dialog handling is provided by the core control stack.",
        });
      default:
        return jsonRpcError(id, -32601, "Method not found");
    }
  } catch (error) {
    return jsonRpcError(id, -32000, error.message || String(error));
  }
}

function connectNative() {
  if (nmPort) {
    return;
  }

  let port = null;
  try {
    cleanupEpoch++;
    port = chrome.runtime.connectNative(NATIVE_HOST);
    nmPort = port;
    lastDisconnectReason = "";
  } catch (error) {
    console.warn("Failed to connect native host", error);
    nmPort = null;
    return;
  }

  port.onMessage.addListener(async (message) => {
    // Defensive: connectNative is already queued behind ready, but future
    // callers must not bypass the gate.
    await ready;
    if (port !== nmPort) {
      return;
    }

    if (disconnectedSince) {
      disconnectedSince = null;
      void persistManagedTabs();
    }

    const response = await handleMessage(message);
    postNative(response);
  });

  port.onDisconnect.addListener(async () => {
    // runtime.lastError only exists in the synchronous callback scope.
    const disconnectReason = runtimeLastErrorMessage();
    // Defensive: connectNative is already queued behind ready, but future
    // callers must not bypass the gate.
    await ready;
    if (disconnectReason) {
      console.warn("Native host disconnected", disconnectReason);
    }

    if (port !== nmPort) {
      return;
    }

    lastDisconnectReason = disconnectReason;
    lastDisconnect = { reason: disconnectReason, at: Date.now() };
    void chrome.storage.session.set({ [LAST_DISCONNECT_KEY]: lastDisconnect });
    nmPort = null;
    if (!disconnectedSince) {
      disconnectedSince = Date.now();
      void persistManagedTabs();
    }
    sendEvent(
      "bridge.disconnected",
      disconnectReason ? { reason: disconnectReason } : {},
    );
    const now = Date.now();
    if (now - lastFastReconnectAt >= FAST_RECONNECT_DEBOUNCE_MS) {
      lastFastReconnectAt = now;
      void ready.then(() => connectNative());
    }
  });

  const connectedParams = {
    version: chrome.runtime.getManifest().version,
    extensionBuild,
  };
  if (lastDisconnect) {
    if (Date.now() - lastDisconnect.at <= DISCONNECT_REPORT_MAX_AGE_MS) {
      connectedParams.lastDisconnect = lastDisconnect;
    } else {
      console.warn("Stored Native Messaging disconnect reason expired");
    }
    lastDisconnect = null;
    void chrome.storage.session.remove(LAST_DISCONNECT_KEY);
  }
  sendEvent("bridge.connected", connectedParams);
}

chrome.debugger.onEvent.addListener(async (source, method, params) => {
  await ready;
  if (!source || source.tabId === undefined || !managedTabs.has(source.tabId)) {
    return;
  }

  sendEvent("cdp.event", {
    tabId: source.tabId,
    method,
    params: params || {},
  });
});

chrome.debugger.onDetach.addListener(async (source, reason) => {
  await ready;
  if (!source || source.tabId === undefined) {
    return;
  }

  managedTabs.delete(source.tabId);
  await persistManagedTabs();
  sendEvent("tab.detached", {
    tabId: source.tabId,
    reason,
  });
});

chrome.webNavigation.onCreatedNavigationTarget.addListener(async (details) => {
  await ready;
  if (!details || !managedTabs.has(details.sourceTabId)) {
    return;
  }

  const count = (popupEventCounts.get(details.sourceTabId) || 0) + 1;
  popupEventCounts.set(details.sourceTabId, count);
  if (count > MAX_POPUP_EVENTS_PER_SOURCE) {
    sendEvent("webNavigation.popupOverflow", {
      sourceTabId: details.sourceTabId,
      count,
      cap: MAX_POPUP_EVENTS_PER_SOURCE,
      outcome: "PARTIAL",
      executionTruth: "UNCERTAIN",
    });
    return;
  }

  sendEvent("webNavigation.createdNavigationTarget", {
    tabId: details.tabId,
    sourceTabId: details.sourceTabId,
    url: details.url || "",
    frameId: details.frameId,
    timeStamp: details.timeStamp,
  });
});

chrome.tabs.onCreated.addListener(async (tab) => {
  await ready;
  if (!hasControlInterest()) {
    return;
  }

  sendEvent("tabs.created", tabLifecycleEventParams(tab));
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  await ready;
  if (
    !hasControlInterest() &&
    !managedTabs.has(tabId) &&
    !createdTabs.has(tabId)
  ) {
    return;
  }

  sendEvent(
    "tabs.updated",
    tabLifecycleEventParams(tab, {
      tabId,
      changeInfo: changeInfo || {},
    }),
  );
});

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  await ready;
  if (!hasControlInterest()) {
    return;
  }

  sendEvent("tabs.activated", activeInfo || {});
});

chrome.tabs.onRemoved.addListener(async (tabId, removeInfo) => {
  await ready;
  const wasManaged = managedTabs.has(tabId);
  const wasCreated = createdTabs.has(tabId);
  if (!wasManaged && !wasCreated) {
    return;
  }
  sendEvent("tabs.removed", {
    tabId,
    ...(removeInfo || {}),
    managed: wasManaged,
    createdByQwenPaw: wasCreated,
    ownershipState: TAB_OWNERSHIP_RELEASED,
  });
  managedTabs.delete(tabId);
  createdTabs.delete(tabId);
  tabMetadata.delete(Number(tabId));
  popupEventCounts.delete(tabId);
  void persistManagedTabs();
});

function externalMessageOrigin(sender) {
  if (sender && sender.origin) {
    return sender.origin;
  }
  if (sender && sender.url) {
    try {
      return new URL(sender.url).origin;
    } catch (error) {
      return "";
    }
  }
  return "";
}

function isLocalQwenPawExternalOrigin(origin) {
  try {
    const parsed = new URL(origin);
    return (
      parsed.protocol === "http:" &&
      LOCAL_QWENPAW_HOSTS.has(parsed.hostname) &&
      LOCAL_QWENPAW_PORTS.has(parsed.port)
    );
  } catch (error) {
    return false;
  }
}

function handleExternalMessage(message, sender, sendResponse) {
  if (!isLocalQwenPawExternalOrigin(externalMessageOrigin(sender))) {
    sendResponse({ ok: false, error: "origin_not_allowed" });
    return false;
  }

  switch (message && message.method) {
    case "status.get":
      sendResponse(extensionStatusPayload());
      return false;
    case "bridge.connect":
      if (!nmPort) {
        void ready.then(() => connectNative());
      }
      sendResponse(extensionStatusPayload());
      return false;
    case "extension.reload":
      if (Date.now() - lastReloadAt < RELOAD_COOLDOWN_MS) {
        sendResponse({ ok: false, error: "reload_rate_limited" });
        return false;
      }
      lastReloadAt = Date.now();
      sendResponse({
        ok: true,
        reloading: true,
        version: chrome.runtime.getManifest().version,
      });
      setTimeout(() => chrome.runtime.reload(), 0);
      return false;
    default:
      sendResponse({ ok: false, error: "method_not_allowed" });
      return false;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.source === "qwenpaw-chrome-popup") {
    if (message.method === "status.get") {
      if (!nmPort) {
        void ready.then(() => connectNative());
      }
      sendResponse(extensionStatusPayload());
      return false;
    }
  }

  return false;
});

chrome.runtime.onMessageExternal.addListener(handleExternalMessage);

chrome.alarms.onAlarm.addListener(async (alarm) => {
  await ready;
  if (!alarm || alarm.name !== WATCHDOG_ALARM) {
    return;
  }
  if (!nmPort) {
    connectNative();
    if (
      disconnectedSince &&
      Date.now() - disconnectedSince >= DEGRADE_AFTER_DISCONNECT_MS &&
      managedTabs.size > 0
    ) {
      void runSelfDegradation();
    }
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void ready.then(() => connectNative());
});

chrome.runtime.onStartup.addListener(() => {
  void ready.then(() => connectNative());
});

// MV3 reruns this top level with empty in-memory state after every wake.
// persistManagedTabs is a full overwrite, so event handlers must wait until
// restoration finishes before they read or change managed-tab state.
const ready = (async () => {
  try {
    await ensureWatchdogAlarm();
    await restoreManagedTabs();
  } catch (error) {
    console.warn("Startup restore failed; continuing with empty state", error);
  }
})();
void ready.then(() => connectNative());
