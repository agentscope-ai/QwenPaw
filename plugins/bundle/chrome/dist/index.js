const F = {
  en: {
    routeLabel: "Chrome",
    pageTitle: "Chrome",
    pageSubtitle: "Connect QwenPaw to this Chrome browser.",
    loading: "Checking Chrome connection...",
    refreshStatus: "Refresh Status",
    installedRefresh: "I've installed it, refresh status",
    versionUnknown: "unknown",
    installTitle: "Install Chrome Extension",
    installDescription: "Load the local extension, then return here to confirm the connection.",
    readyTitle: "Chrome Connected",
    readyDescription: "Version {version}. Connected {connectedSince}.",
    awaitingTitle: "Extension installed, waiting for Chrome",
    awaitingDescription: "The extension is installed. Keep Chrome running; the bridge will connect automatically.",
    openChrome: "Open Chrome",
    installMethodsTitle: "Install method",
    localMethodTitle: "Local install",
    recommendedBadge: "Recommended",
    localMethodDescription: "Use the extension files included with QwenPaw for this local browser.",
    openChromeExtensionsPage: "Open Chrome extensions page",
    chromeWebStoreTitle: "Chrome Web Store",
    chromeWebStoreDescription: "The store listing is not available yet. Use local install for now.",
    comingSoon: "Coming soon",
    localStepsTitle: "Local install steps",
    localStepsOnce: "Only once",
    openExtensionsStepTitle: "Open extensions page",
    openExtensionsPrefix: "Click",
    openExtensionsAction: "Chrome extensions page",
    openExtensionsSuffix: "to open extension management.",
    developerModeStepTitle: "Enable Developer mode",
    developerModePrefix: "Turn on",
    developerModeAction: "Developer mode",
    developerModeSuffix: "in the upper-right corner.",
    loadUnpackedStepTitle: "Click load button",
    loadUnpackedPrefix: "Click",
    loadUnpackedAction: "Load unpacked",
    loadUnpackedSuffix: "in Chrome.",
    pastePathStepTitle: "Paste path and open",
    pastePathGuide: "Follow the Quick paste path tips on the right to copy the path, paste it, and open the folder.",
    qwenpawExtensionPath: "Copy QwenPaw extension path",
    shortcutTipsTitle: "Quick paste path tips",
    shortcutTipsScope: "Use when selecting folder",
    currentSystem: "Current system",
    shortcutCopyPathPrefix: "Click",
    shortcutCopyPathSuffix: "button to copy the QwenPaw extension path to your clipboard.",
    shortcutMacStep1: "Press Cmd + Shift + G, paste the path, then press Enter.",
    shortcutMacStep2: "After the folder is selected, click Open.",
    shortcutWindowsStep1: "Click the address bar, paste the path, then press Enter.",
    shortcutWindowsStep2: "After the folder is selected, click Select Folder.",
    shortcutLinuxStep1: "Press Ctrl + L, paste the path, then press Enter.",
    shortcutLinuxStep2: "After the folder is selected, click Open.",
    stepOpen: "Open chrome://extensions and enable Developer mode.",
    stepLoad: "Choose Load unpacked and select the QwenPaw extension folder.",
    stepVerify: "Return here and refresh the status.",
    directoryLabel: "QwenPaw built-in extension folder",
    directoryHint: "Path is available from copy or advanced information.",
    openExtensionFolder: "Open Folder",
    copyPath: "Copy Path",
    advancedInfo: "Advanced information",
    extensionDir: "Extension folder",
    nativeManifest: "Local connection config",
    nativeHost: "Local connection helper",
    config: "Local settings file",
    bridgeEndpoint: "Connection endpoint",
    checksTitle: "Connection checks",
    checkExtensionBridge: "Extension bridge",
    checkNmHost: "Native Messaging host",
    checkExtensionAssets: "Extension assets",
    checkBridgeLifecycle: "Bridge lifecycle",
    checkReady: "Ready",
    checkFailed: "Needs attention",
    checksPending: "Connection checks are not available yet. Refresh to retry.",
    repairReinstallNmHost: "Reinstall the Native Messaging host.",
    repairReloadUnpackedExtension: "Reload the unpacked extension in chrome://extensions.",
    repairWaitOrRestartChrome: "Wait a moment or restart Chrome.",
    repairReloadExtension: "Reload the extension.",
    version: "Extension version",
    connected: "Connected",
    justNow: "just now",
    minutesAgo: "{count} minutes ago",
    hoursAgo: "{count} hours ago",
    installSuccess: "Extension files ready",
    installFailed: "Extension setup failed",
    repairBrowserConnector: "Repair Browser Connector",
    repairSuccess: "Browser Connector repaired. Waiting for Chrome to reconnect.",
    copied: "Copied",
    chrome_disconnected: "Reload the extension or reopen the target browser tab.",
    browser_backend_unavailable: "Refresh the status after the backend is available.",
    chrome_action_runtime_missing: "Restart QwenPaw or reload the Chrome plugin.",
    isolated_backend_unavailable: "Install or restart the isolated browser runtime."
  },
  zh: {
    routeLabel: "Chrome浏览器",
    pageTitle: "Chrome",
    pageSubtitle: "将 QwenPaw 连接到此 Chrome 浏览器。",
    loading: "正在检查 Chrome 连接...",
    refreshStatus: "刷新状态",
    installedRefresh: "我已安装，刷新状态",
    versionUnknown: "未知",
    installTitle: "安装 Chrome 扩展",
    installDescription: "加载本地扩展后，回到这里确认连接状态。",
    readyTitle: "Chrome 已连接",
    readyDescription: "版本 {version}。连接于 {connectedSince}。",
    awaitingTitle: "扩展已安装，等待 Chrome 连接",
    awaitingDescription: "扩展已安装。保持 Chrome 运行，桥接将自动建立连接。",
    openChrome: "打开 Chrome",
    installMethodsTitle: "安装方式",
    localMethodTitle: "本地安装",
    recommendedBadge: "推荐",
    localMethodDescription: "使用 QwenPaw 自带扩展文件连接当前本地浏览器。",
    openChromeExtensionsPage: "打开 Chrome 扩展页",
    chromeWebStoreTitle: "Chrome Web Store",
    chromeWebStoreDescription: "官方商店版本尚未发布。当前请使用本地安装。",
    comingSoon: "Coming soon",
    localStepsTitle: "本地安装步骤",
    localStepsOnce: "只需要完成一次",
    openExtensionsStepTitle: "打开扩展页",
    openExtensionsPrefix: "点击",
    openExtensionsAction: "Chrome 扩展页",
    openExtensionsSuffix: "进入扩展管理页面。",
    developerModeStepTitle: "开启开发者模式",
    developerModePrefix: "在页面右上角打开",
    developerModeAction: "开发者模式",
    developerModeSuffix: "开关。",
    loadUnpackedStepTitle: "点击加载按钮",
    loadUnpackedPrefix: "点击 Chrome 页面里的",
    loadUnpackedAction: "加载已解压的扩展程序",
    loadUnpackedSuffix: "。",
    pastePathStepTitle: "粘贴路径并打开",
    pastePathGuide: "请按右侧“快捷粘贴路径 Tips”的步骤完成复制、粘贴并打开目录。",
    qwenpawExtensionPath: "复制 QwenPaw 扩展路径",
    shortcutTipsTitle: "快捷粘贴路径 Tips",
    shortcutTipsScope: "选择目录时使用",
    currentSystem: "当前系统",
    shortcutCopyPathPrefix: "点击",
    shortcutCopyPathSuffix: "按钮复制 QwenPaw 扩展路径到剪贴板。",
    shortcutMacStep1: "按 Cmd + Shift + G，粘贴路径并回车。",
    shortcutMacStep2: "确认定位到目录后，点击“打开”。",
    shortcutWindowsStep1: "点击地址栏，粘贴路径并回车。",
    shortcutWindowsStep2: "确认定位到目录后，点击“选择文件夹”。",
    shortcutLinuxStep1: "按 Ctrl + L，粘贴路径并回车。",
    shortcutLinuxStep2: "确认定位到目录后，点击“打开”。",
    stepOpen: "打开 chrome://extensions，并启用开发者模式。",
    stepLoad: "选择“加载已解压的扩展程序”，并选择 QwenPaw 扩展目录。",
    stepVerify: "回到此页面并刷新状态。",
    directoryLabel: "QwenPaw 自带扩展目录",
    directoryHint: "完整路径可通过复制或高级信息查看。",
    openExtensionFolder: "打开目录",
    copyPath: "复制路径",
    advancedInfo: "高级信息",
    extensionDir: "扩展目录",
    nativeManifest: "本机连接配置",
    nativeHost: "本机连接助手",
    config: "本地设置文件",
    bridgeEndpoint: "连接端点",
    checksTitle: "连接检查",
    checkExtensionBridge: "扩展桥接",
    checkNmHost: "Native Messaging 宿主",
    checkExtensionAssets: "扩展资产",
    checkBridgeLifecycle: "桥接生命周期",
    checkReady: "就绪",
    checkFailed: "需要处理",
    checksPending: "连接检查结果暂不可用，请刷新重试。",
    repairReinstallNmHost: "重新安装 Native Messaging 宿主。",
    repairReloadUnpackedExtension: "在 chrome://extensions 重新加载已解压的扩展。",
    repairWaitOrRestartChrome: "稍候片刻或重启 Chrome。",
    repairReloadExtension: "重新加载扩展。",
    version: "扩展版本",
    connected: "连接时间",
    justNow: "刚刚",
    minutesAgo: "{count} 分钟前",
    hoursAgo: "{count} 小时前",
    installSuccess: "扩展文件已准备好",
    installFailed: "扩展设置失败",
    repairBrowserConnector: "修复浏览器连接器",
    repairSuccess: "浏览器连接器已修复，正在等待 Chrome 重新连接。",
    copied: "已复制",
    chrome_disconnected: "重载扩展，或重新打开目标浏览器标签页。",
    browser_backend_unavailable: "后端可用后刷新状态。",
    chrome_action_runtime_missing: "重启 QwenPaw，或重新加载 Chrome 插件。",
    isolated_backend_unavailable: "安装或重启隔离浏览器运行时。"
  }
};
function Y() {
  var t;
  try {
    return ((t = window.localStorage) == null ? void 0 : t.getItem("language")) ?? null;
  } catch {
    return null;
  }
}
function j(t = Y()) {
  return String(t || "").trim().split("-")[0].toLowerCase() === "zh" ? "zh" : "en";
}
function o(t, n, r) {
  let l = F[t][n] ?? F.en[n];
  if (r)
    for (const [i, m] of Object.entries(r))
      l = l.split(`{${i}}`).join(String(m));
  return l;
}
const x = window.QwenPaw.host, e = x.React, J = x.antd, Z = x.getApiUrl, _ = x.getApiToken, { Alert: N, Button: u, Collapse: X, Space: xe, Spin: ee, Typography: te, message: b } = J, { Text: d, Title: O } = te, ne = {
  extension_bridge: "checkExtensionBridge",
  nm_host: "checkNmHost",
  extension_assets: "checkExtensionAssets",
  bridge_lifecycle: "checkBridgeLifecycle"
}, re = {
  reinstall_nm_host: "repairReinstallNmHost",
  reload_unpacked_extension: "repairReloadUnpackedExtension",
  wait_or_restart_chrome: "repairWaitOrRestartChrome",
  reload_extension: "repairReloadExtension"
}, c = {
  page: {
    minHeight: "100%",
    overflowY: "auto",
    padding: 24,
    background: "transparent"
  },
  shell: {
    width: "min(100%, 900px)",
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 16
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    flexWrap: "wrap"
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    minWidth: 0
  },
  chromeIcon: {
    position: "relative",
    width: 42,
    height: 42,
    flex: "0 0 42px",
    borderRadius: "50%",
    background: "radial-gradient(circle at center, #fff 0 18%, transparent 19%), radial-gradient(circle at center, #1a73e8 0 36%, transparent 37%), conic-gradient(#ea4335 0 34%, #fbbc04 0 67%, #34a853 0 100%)"
  },
  panel: {
    borderRadius: 8,
    padding: 24
  },
  statusBlock: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: 20,
    alignItems: "start"
  },
  statusTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 8
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    flexShrink: 0
  },
  statusCopy: {
    maxWidth: 610,
    lineHeight: 1.55
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
    flexWrap: "wrap"
  },
  section: {
    marginTop: 22,
    display: "flex",
    flexDirection: "column",
    gap: 12
  },
  methodGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12
  },
  methodTile: {
    minHeight: 128,
    padding: 14,
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  disabledTile: {
    minHeight: 128,
    padding: 14,
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    gap: 10,
    opacity: 0.72
  },
  methodHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8
  },
  badge: {
    minHeight: 22,
    padding: "1px 8px",
    borderRadius: 999,
    fontSize: 12,
    whiteSpace: "nowrap"
  },
  installSupportGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 16,
    alignItems: "stretch"
  },
  installBox: {
    flex: "1.55 1 520px",
    minWidth: 0,
    padding: 16,
    borderRadius: 8
  },
  installTipsBox: {
    flex: "0.85 1 280px",
    minWidth: 0,
    padding: 16,
    borderRadius: 8
  },
  installBoxHead: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 14,
    flexWrap: "wrap"
  },
  installBoxNote: {
    fontSize: 12,
    lineHeight: "18px",
    whiteSpace: "nowrap"
  },
  steps: {
    margin: 0,
    padding: 0,
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: 13
  },
  stepItem: {
    display: "grid",
    gridTemplateColumns: "28px minmax(0, 1fr)",
    gap: 10,
    alignItems: "start"
  },
  stepIndex: {
    width: 28,
    height: 28,
    borderRadius: 8,
    display: "grid",
    placeItems: "center",
    fontSize: 13,
    fontWeight: 700
  },
  stepBody: {
    minWidth: 0
  },
  stepLine: {
    marginTop: 5,
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexWrap: "wrap",
    fontSize: 13,
    lineHeight: "26px"
  },
  stepControl: {
    height: 26,
    borderRadius: 7,
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "0 9px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
    whiteSpace: "nowrap"
  },
  stepControlPrimary: {},
  stepControlIconOnly: {
    width: 34,
    margin: "0 4px",
    padding: 0,
    justifyContent: "center",
    gap: 0,
    verticalAlign: "middle"
  },
  stepControlBlue: {},
  stepControlPlaceholder: {
    cursor: "default"
  },
  inlineIcon: {
    width: 14,
    height: 14,
    flex: "0 0 14px"
  },
  shortcutBox: {
    width: "100%",
    minWidth: 0
  },
  shortcutHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    flexWrap: "wrap",
    marginBottom: 14
  },
  osTabs: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    width: "min(100%, 210px)",
    padding: 2,
    borderRadius: 8,
    overflow: "hidden"
  },
  osTab: {
    height: 26,
    border: 0,
    borderRadius: 6,
    background: "transparent",
    padding: "0 8px",
    cursor: "pointer",
    fontSize: 12,
    lineHeight: "26px",
    whiteSpace: "nowrap",
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis"
  },
  osTabActive: {
    fontWeight: 700
  },
  shortcutSteps: {
    margin: 0,
    padding: "11px 12px",
    listStyle: "none",
    display: "grid",
    gap: 8,
    borderRadius: 8,
    fontSize: 13,
    lineHeight: "18px"
  },
  shortcutStep: {
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    gap: 8,
    alignItems: "start"
  },
  shortcutStepCopy: {
    display: "block",
    minWidth: 0,
    lineHeight: "26px"
  },
  tipDot: {
    width: 18,
    height: 18,
    borderRadius: 999,
    display: "inline-grid",
    placeItems: "center",
    fontSize: 11,
    fontWeight: 700,
    lineHeight: "18px"
  },
  checkGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12
  },
  checkTile: {
    minHeight: 86,
    padding: 14,
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    gap: 8
  },
  checkTitle: {
    display: "flex",
    alignItems: "center",
    gap: 8
  },
  advanced: {
    marginTop: 18,
    borderRadius: 8
  },
  advancedRows: {
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  advancedRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr) auto",
    gap: 8,
    alignItems: "center"
  },
  advancedValue: {
    minWidth: 0,
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    lineHeight: 1.45,
    borderRadius: 4,
    padding: "4px 8px"
  }
};
function oe(t) {
  return {
    ...c,
    chromeIcon: {
      ...c.chromeIcon,
      boxShadow: t.boxShadowSecondary
    },
    panel: {
      ...c.panel,
      background: t.colorBgContainer,
      border: `1px solid ${t.colorBorderSecondary}`,
      boxShadow: t.boxShadowTertiary
    },
    methodTile: {
      ...c.methodTile,
      background: t.colorBgContainer,
      border: `1px solid ${t.colorBorderSecondary}`
    },
    disabledTile: {
      ...c.disabledTile,
      background: t.colorFillQuaternary,
      border: `1px dashed ${t.colorBorder}`
    },
    statusCopy: { ...c.statusCopy, color: t.colorTextSecondary },
    badge: {
      ...c.badge,
      border: `1px solid ${t.colorPrimaryBorder}`,
      color: t.colorPrimaryText,
      background: t.colorPrimaryBg
    },
    installBox: {
      ...c.installBox,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillQuaternary
    },
    installTipsBox: {
      ...c.installTipsBox,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillTertiary
    },
    installBoxNote: {
      ...c.installBoxNote,
      color: t.colorTextTertiary
    },
    stepIndex: {
      ...c.stepIndex,
      color: t.colorText,
      background: t.colorFillTertiary
    },
    stepLine: { ...c.stepLine, color: t.colorTextSecondary },
    stepControl: {
      ...c.stepControl,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillSecondary,
      color: t.colorText,
      boxShadow: t.boxShadowSecondary
    },
    stepControlPrimary: {
      ...c.stepControlPrimary,
      borderColor: t.colorPrimary,
      background: t.colorPrimary,
      color: t.colorTextLightSolid
    },
    stepControlBlue: {
      ...c.stepControlBlue,
      borderColor: t.colorPrimaryBorder,
      background: t.colorPrimaryBg,
      color: t.colorPrimaryText
    },
    stepControlPlaceholder: {
      ...c.stepControlPlaceholder,
      color: t.colorTextSecondary,
      background: t.colorFillSecondary
    },
    osTabs: {
      ...c.osTabs,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillQuaternary
    },
    osTab: { ...c.osTab, color: t.colorTextSecondary },
    osTabActive: {
      ...c.osTabActive,
      background: t.colorBgContainer,
      color: t.colorText,
      boxShadow: t.boxShadowSecondary
    },
    shortcutSteps: {
      ...c.shortcutSteps,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorBgContainer,
      color: t.colorTextSecondary
    },
    tipDot: {
      ...c.tipDot,
      background: t.colorFillTertiary,
      color: t.colorText
    },
    checkTile: {
      ...c.checkTile,
      border: `1px solid ${t.colorSuccessBorder}`,
      background: t.colorSuccessBg
    },
    advanced: { ...c.advanced, background: t.colorBgContainer },
    advancedValue: {
      ...c.advancedValue,
      background: t.colorFillQuaternary,
      border: `1px solid ${t.colorBorderSecondary}`,
      color: t.colorText
    }
  };
}
function S() {
  const { token: t } = x.antd.theme.useToken();
  return e.useMemo(() => oe(t), [t]);
}
function ae() {
  return /* @__PURE__ */ e.createElement(
    "svg",
    {
      "aria-hidden": "true",
      focusable: "false",
      viewBox: "0 0 24 24",
      width: 16,
      height: 16,
      fill: "none",
      stroke: "currentColor",
      strokeWidth: 2,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      shapeRendering: "geometricPrecision"
    },
    /* @__PURE__ */ e.createElement("circle", { cx: 12, cy: 12, r: 9 }),
    /* @__PURE__ */ e.createElement("circle", { cx: 12, cy: 12, r: 3.375 }),
    /* @__PURE__ */ e.createElement("line", { x1: 12, y1: 8.625, x2: 20.344, y2: 8.625 }),
    /* @__PURE__ */ e.createElement("line", { x1: 9.075, y1: 13.688, x2: 4.903, y2: 6.459 }),
    /* @__PURE__ */ e.createElement("line", { x1: 14.925, y1: 13.688, x2: 10.753, y2: 20.916 })
  );
}
function ie() {
  const t = {}, n = _ == null ? void 0 : _();
  return n && (t.Authorization = `Bearer ${n}`), t;
}
async function v(t, n) {
  const r = await fetch(Z(t), {
    ...n,
    headers: {
      ...(n == null ? void 0 : n.headers) || {},
      ...ie()
    }
  }), l = await r.text(), i = l ? JSON.parse(l) : null;
  if (!r.ok)
    throw new Error(
      typeof (i == null ? void 0 : i.detail) == "string" ? i.detail : r.statusText
    );
  return i;
}
function le() {
  return v("/chrome/install-status");
}
async function se() {
  try {
    return await v("/browser/chrome/status");
  } catch {
    return null;
  }
}
async function ce() {
  try {
    return await v("/browser/chrome/self-test", {
      method: "POST"
    });
  } catch {
    return null;
  }
}
function de(t) {
  return v("/chrome/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(t)
  });
}
function pe() {
  return v(
    "/chrome/open-chrome-extensions",
    {
      method: "POST"
    }
  );
}
function me(t, n) {
  if (!t)
    return o(n, "justNow");
  const r = new Date(t).getTime();
  if (Number.isNaN(r))
    return o(n, "justNow");
  const l = Math.max(0, Math.floor((Date.now() - r) / 6e4));
  return l < 1 ? o(n, "justNow") : l < 60 ? o(n, "minutesAgo", { count: l }) : o(n, "hoursAgo", { count: Math.floor(l / 60) });
}
function he(t, n) {
  const r = re[n];
  return r ? o(t, r) : "";
}
function U({ ready: t }) {
  const { token: n } = x.antd.theme.useToken(), r = S();
  return /* @__PURE__ */ e.createElement(
    "span",
    {
      "aria-hidden": "true",
      style: {
        ...r.statusDot,
        background: t ? n.colorSuccess : n.colorWarning
      }
    }
  );
}
function z({ name: t, size: n }) {
  const r = S(), l = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, i = {
    chromeExtensions: /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("path", { d: "M8 6h12v12H8z" }), /* @__PURE__ */ e.createElement("path", { d: "M4 10h4M4 14h4" })),
    copy: /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("rect", { x: "9", y: "9", width: "11", height: "11", rx: "2" }), /* @__PURE__ */ e.createElement("path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" })),
    folderPlus: /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("path", { d: "M12 5v14" }), /* @__PURE__ */ e.createElement("path", { d: "M5 12h14" }), /* @__PURE__ */ e.createElement("path", { d: "M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" })),
    sliders: /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("path", { d: "M4 7h10" }), /* @__PURE__ */ e.createElement("path", { d: "M20 7h-2" }), /* @__PURE__ */ e.createElement("circle", { cx: "16", cy: "7", r: "2" }), /* @__PURE__ */ e.createElement("path", { d: "M20 17H10" }), /* @__PURE__ */ e.createElement("path", { d: "M4 17h2" }), /* @__PURE__ */ e.createElement("circle", { cx: "8", cy: "17", r: "2" }))
  };
  return /* @__PURE__ */ e.createElement(
    "svg",
    {
      viewBox: "0 0 24 24",
      style: n ? {
        ...r.inlineIcon,
        width: n,
        height: n,
        flex: `0 0 ${n}px`
      } : r.inlineIcon,
      ...l
    },
    i[t]
  );
}
function T({
  icon: t,
  label: n,
  loading: r,
  onClick: l,
  tone: i = "default",
  iconOnly: m = !1
}) {
  const p = S(), g = i === "primary" ? p.stepControlPrimary : i === "blue" ? p.stepControlBlue : i === "placeholder" ? p.stepControlPlaceholder : null;
  return /* @__PURE__ */ e.createElement(
    u,
    {
      "aria-label": m ? n : void 0,
      loading: r,
      onClick: l,
      style: {
        ...p.stepControl,
        ...g,
        ...m ? p.stepControlIconOnly : null
      },
      title: m ? n : void 0,
      type: "text"
    },
    /* @__PURE__ */ e.createElement(z, { name: t, size: m ? 16 : void 0 }),
    m ? null : n
  );
}
function ue() {
  var l, i;
  const t = ((l = window.navigator) == null ? void 0 : l.platform) || "", n = ((i = window.navigator) == null ? void 0 : i.userAgent) || "", r = `${t} ${n}`.toLowerCase();
  return r.includes("mac") ? "mac" : r.includes("win") ? "windows" : "linux";
}
function ge({
  locale: t,
  onCopy: n,
  status: r
}) {
  const l = S(), i = [
    { key: "extension_dir", label: "extensionDir" },
    { key: "native_manifest_path", label: "nativeManifest" },
    { key: "native_host_path", label: "nativeHost" },
    { key: "config_path", label: "config" }
  ], m = (r == null ? void 0 : r.bridge_endpoint) || "not ready";
  return /* @__PURE__ */ e.createElement(
    X,
    {
      style: l.advanced,
      items: [
        {
          key: "advanced",
          label: o(t, "advancedInfo"),
          children: /* @__PURE__ */ e.createElement("div", { style: l.advancedRows }, i.map((p) => {
            const g = (r == null ? void 0 : r[p.key]) || "-";
            return /* @__PURE__ */ e.createElement("div", { key: p.key, style: l.advancedRow }, /* @__PURE__ */ e.createElement(d, { type: "secondary" }, o(t, p.label)), /* @__PURE__ */ e.createElement("code", { style: l.advancedValue }, g), /* @__PURE__ */ e.createElement(
              u,
              {
                disabled: !(r != null && r[p.key]),
                onClick: () => n(g)
              },
              o(t, "copyPath")
            ));
          }), /* @__PURE__ */ e.createElement("div", { style: l.advancedRow }, /* @__PURE__ */ e.createElement(d, { type: "secondary" }, o(t, "bridgeEndpoint")), /* @__PURE__ */ e.createElement("code", { style: l.advancedValue }, m), /* @__PURE__ */ e.createElement(u, { onClick: () => n(m) }, o(t, "copyPath"))))
        }
      ]
    }
  );
}
function ye() {
  var H;
  const t = S(), n = j(), [r, l] = e.useState(null), [i, m] = e.useState(null), [p, g] = e.useState(null), [f, R] = e.useState(!0), [I, M] = e.useState(!1), [L, C] = e.useState(null), [W, G] = e.useState(!1), [D, V] = e.useState(() => ue()), y = e.useCallback(
    async (a) => {
      a != null && a.silent || R(!0), C(null);
      try {
        const [s, w] = await Promise.all([
          le(),
          se()
        ]);
        return l(s), m(w), s;
      } catch (s) {
        const w = s instanceof Error ? s.message : String(s);
        return C(w), null;
      } finally {
        a != null && a.silent || R(!1);
      }
    },
    []
  );
  e.useEffect(() => {
    y();
  }, [y]);
  const E = e.useCallback(
    async (a) => {
      if (r != null && r.extension_dir && r.installed && !(a != null && a.refresh))
        return r;
      M(!0), C(null);
      try {
        const s = await de({
          install_mode: "unpacked",
          reset: !1
        });
        return l(s), a != null && a.silent || (s.native_host_repair_required ? b.error(
          s.native_host_repair_instruction || o(n, "installFailed")
        ) : b.success(
          o(
            n,
            r != null && r.native_host_repair_required ? "repairSuccess" : "installSuccess"
          )
        )), s;
      } catch (s) {
        const w = s instanceof Error ? s.message : String(s);
        return C(w), a != null && a.silent || b.error(o(n, "installFailed")), null;
      } finally {
        M(!1);
      }
    },
    [n, r]
  ), P = e.useCallback(
    async (a) => {
      var s;
      await ((s = navigator.clipboard) == null ? void 0 : s.writeText(a)), b.success(o(n, "copied"));
    },
    [n]
  ), q = e.useCallback(async () => {
    const a = await E({ refresh: !0 });
    a != null && a.extension_dir && await P(a.extension_dir);
  }, [P, E]), k = e.useCallback(async () => {
    const a = await pe();
    !a.opened && a.error && b.warning(a.error);
  }, []), K = {
    mac: ["shortcutMacStep1", "shortcutMacStep2"],
    windows: ["shortcutWindowsStep1", "shortcutWindowsStep2"],
    linux: ["shortcutLinuxStep1", "shortcutLinuxStep2"]
  };
  e.useEffect(() => {
    f || W || r != null && r.extension_dir || (G(!0), E({ silent: !0 }));
  }, [f, E, W, r == null ? void 0 : r.extension_dir]);
  const h = !!(r != null && r.installed && (i != null && i.connected)), A = !!(r != null && r.native_host_repair_required && !(i != null && i.connected)), B = !!(r != null && r.installed && !(i != null && i.connected));
  return e.useEffect(() => {
    if (!h) {
      g(null);
      return;
    }
    let a = !1;
    return ce().then((s) => {
      a || g(s ?? (i == null ? void 0 : i.last_self_test) ?? null);
    }), () => {
      a = !0;
    };
  }, [h, i == null ? void 0 : i.last_self_test]), e.useEffect(() => {
    if (h)
      return;
    const a = window.setInterval(() => {
      y({ silent: !0 });
    }, 5e3);
    return () => {
      window.clearInterval(a);
    };
  }, [h, y]), /* @__PURE__ */ e.createElement("div", { style: t.page }, /* @__PURE__ */ e.createElement("div", { style: t.shell }, /* @__PURE__ */ e.createElement("div", { style: t.panel }, /* @__PURE__ */ e.createElement("div", { style: t.statusBlock }, /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement("div", { style: t.header }, /* @__PURE__ */ e.createElement("div", { style: t.titleRow }, /* @__PURE__ */ e.createElement("span", { style: t.chromeIcon }), /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement(O, { level: 3, style: { margin: 0 } }, o(n, "pageTitle")), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, o(n, "pageSubtitle"))))), /* @__PURE__ */ e.createElement("div", { style: { marginTop: 22 } }, /* @__PURE__ */ e.createElement("div", { style: t.statusTitleRow }, h || B ? /* @__PURE__ */ e.createElement(U, { ready: h }) : null, /* @__PURE__ */ e.createElement(O, { level: 4, style: { margin: 0 } }, o(
    n,
    h ? "readyTitle" : B ? "awaitingTitle" : "installTitle"
  ))), /* @__PURE__ */ e.createElement("div", { style: t.statusCopy }, h ? o(n, "readyDescription", {
    version: (i == null ? void 0 : i.extension_version) || o(n, "versionUnknown"),
    connectedSince: me(
      i == null ? void 0 : i.connected_since,
      n
    )
  }) : B ? o(n, "awaitingDescription") : (r == null ? void 0 : r.recovery_copy) || o(n, "installDescription")))), /* @__PURE__ */ e.createElement("div", { style: t.actions }, h ? /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement(
    u,
    {
      loading: f,
      onClick: () => void y()
    },
    o(n, "refreshStatus")
  ), /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      onClick: () => void k()
    },
    o(n, "openChrome")
  )) : A ? /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      loading: I,
      onClick: () => void E({ refresh: !0 })
    },
    o(n, "repairBrowserConnector")
  ) : /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      loading: f,
      onClick: () => void y()
    },
    o(n, "installedRefresh")
  ))), L ? /* @__PURE__ */ e.createElement(
    N,
    {
      showIcon: !0,
      type: "error",
      message: L,
      style: { marginTop: 16 }
    }
  ) : null, A && (r != null && r.native_host_repair_instruction) ? /* @__PURE__ */ e.createElement(
    N,
    {
      showIcon: !0,
      type: "error",
      message: r == null ? void 0 : r.native_host_repair_instruction,
      style: { marginTop: 16 }
    }
  ) : null, h ? /* @__PURE__ */ e.createElement("div", { style: t.section }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "checksTitle")), (H = p == null ? void 0 : p.checks) != null && H.length ? /* @__PURE__ */ e.createElement("div", { style: t.checkGrid }, p.checks.filter((a) => a.name !== "semantic_control").map((a) => /* @__PURE__ */ e.createElement("div", { key: a.name, style: t.checkTile }, /* @__PURE__ */ e.createElement("div", { style: t.checkTitle }, /* @__PURE__ */ e.createElement(U, { ready: a.passed }), /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(
    n,
    ne[a.name] ?? "checkExtensionBridge"
  ))), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, a.passed ? o(n, "checkReady") : `${a.message} ${he(
    n,
    a.repair_action
  )}`.trim())))) : /* @__PURE__ */ e.createElement(d, { type: "secondary" }, o(n, "checksPending"))) : /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("div", { style: t.section }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "installMethodsTitle")), /* @__PURE__ */ e.createElement("div", { style: t.methodGrid }, /* @__PURE__ */ e.createElement("div", { style: t.methodTile }, /* @__PURE__ */ e.createElement("div", { style: t.methodHeader }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "localMethodTitle")), /* @__PURE__ */ e.createElement("span", { style: t.badge }, o(n, "recommendedBadge"))), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, o(n, "localMethodDescription")), /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      onClick: () => void k()
    },
    /* @__PURE__ */ e.createElement(z, { name: "chromeExtensions" }),
    o(n, "openChromeExtensionsPage")
  )), /* @__PURE__ */ e.createElement("div", { style: t.disabledTile, "aria-disabled": "true" }, /* @__PURE__ */ e.createElement("div", { style: t.methodHeader }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "chromeWebStoreTitle")), /* @__PURE__ */ e.createElement("span", { style: t.badge }, o(n, "comingSoon"))), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, o(n, "chromeWebStoreDescription")), /* @__PURE__ */ e.createElement(u, { disabled: !0 }, o(n, "comingSoon"))))), /* @__PURE__ */ e.createElement("div", { style: t.section }, /* @__PURE__ */ e.createElement("div", { style: t.installSupportGrid }, /* @__PURE__ */ e.createElement("div", { style: t.installBox }, /* @__PURE__ */ e.createElement("div", { style: t.installBoxHead }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "localStepsTitle")), /* @__PURE__ */ e.createElement("span", { style: t.installBoxNote }, o(n, "localStepsOnce"))), /* @__PURE__ */ e.createElement("ol", { style: t.steps }, /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "1"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "openExtensionsStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, o(n, "openExtensionsPrefix"), /* @__PURE__ */ e.createElement(
    T,
    {
      icon: "chromeExtensions",
      label: o(n, "openExtensionsAction"),
      onClick: () => void k(),
      tone: "blue"
    }
  ), o(n, "openExtensionsSuffix")))), /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "2"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "developerModeStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, o(n, "developerModePrefix"), /* @__PURE__ */ e.createElement(
    T,
    {
      icon: "sliders",
      label: o(n, "developerModeAction"),
      tone: "placeholder"
    }
  ), o(n, "developerModeSuffix")))), /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "3"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "loadUnpackedStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, o(n, "loadUnpackedPrefix"), /* @__PURE__ */ e.createElement(
    T,
    {
      icon: "folderPlus",
      label: o(n, "loadUnpackedAction"),
      tone: "placeholder"
    }
  ), o(n, "loadUnpackedSuffix")))), /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "4"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "pastePathStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, o(n, "pastePathGuide")))))), /* @__PURE__ */ e.createElement(
    "aside",
    {
      "aria-label": o(n, "shortcutTipsTitle"),
      style: t.installTipsBox
    },
    /* @__PURE__ */ e.createElement("div", { style: t.installBoxHead }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "shortcutTipsTitle")), /* @__PURE__ */ e.createElement("span", { style: t.installBoxNote }, o(n, "shortcutTipsScope"))),
    /* @__PURE__ */ e.createElement("div", { style: t.shortcutBox }, /* @__PURE__ */ e.createElement("div", { style: t.shortcutHead }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, o(n, "currentSystem")), /* @__PURE__ */ e.createElement("div", { style: t.osTabs, role: "tablist" }, [
      ["mac", "macOS"],
      ["windows", "Windows"],
      ["linux", "Linux"]
    ].map(([a, s]) => /* @__PURE__ */ e.createElement(
      "button",
      {
        key: a,
        onClick: () => V(a),
        style: {
          ...t.osTab,
          ...D === a ? t.osTabActive : null
        },
        type: "button"
      },
      s
    )))), /* @__PURE__ */ e.createElement("ol", { style: t.shortcutSteps }, /* @__PURE__ */ e.createElement("li", { style: t.shortcutStep }, /* @__PURE__ */ e.createElement("span", { style: t.tipDot }, "1"), /* @__PURE__ */ e.createElement("div", { style: t.shortcutStepCopy }, /* @__PURE__ */ e.createElement("span", null, o(n, "shortcutCopyPathPrefix")), /* @__PURE__ */ e.createElement(
      T,
      {
        icon: "copy",
        label: o(n, "qwenpawExtensionPath"),
        loading: I,
        onClick: () => void q(),
        tone: "blue",
        iconOnly: !0
      }
    ), /* @__PURE__ */ e.createElement("span", null, o(n, "shortcutCopyPathSuffix")))), K[D].map(
      (a, s) => /* @__PURE__ */ e.createElement("li", { key: a, style: t.shortcutStep }, /* @__PURE__ */ e.createElement("span", { style: t.tipDot }, s + 2), /* @__PURE__ */ e.createElement("span", null, o(n, a)))
    )))
  )))), /* @__PURE__ */ e.createElement(
    ge,
    {
      locale: n,
      onCopy: (a) => void P(a),
      status: r
    }
  )), f && !r ? /* @__PURE__ */ e.createElement(ee, null) : null));
}
var Q, $;
($ = (Q = window.QwenPaw).registerRoutes) == null || $.call(Q, "chrome", [
  {
    path: "/plugin/chrome",
    component: ye,
    label: o(j(), "routeLabel"),
    icon: /* @__PURE__ */ e.createElement(ae, null),
    priority: 40
  }
]);
