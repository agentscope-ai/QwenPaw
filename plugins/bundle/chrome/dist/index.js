const A = {
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
    copied: "已复制",
    chrome_disconnected: "重载扩展，或重新打开目标浏览器标签页。",
    browser_backend_unavailable: "后端可用后刷新状态。",
    chrome_action_runtime_missing: "重启 QwenPaw，或重新加载 Chrome 插件。",
    isolated_backend_unavailable: "安装或重启隔离浏览器运行时。"
  }
};
function q() {
  var t;
  try {
    return ((t = window.localStorage) == null ? void 0 : t.getItem("language")) ?? null;
  } catch {
    return null;
  }
}
function U(t = q()) {
  return String(t || "").trim().split("-")[0].toLowerCase() === "zh" ? "zh" : "en";
}
function r(t, n, o) {
  let l = A[t][n] ?? A.en[n];
  if (o)
    for (const [i, m] of Object.entries(o))
      l = l.split(`{${i}}`).join(String(m));
  return l;
}
const x = window.QwenPaw.host, e = x.React, K = x.antd, Y = x.getApiUrl, R = x.getApiToken, { Alert: J, Button: u, Collapse: Z, Space: ye, Spin: X, Typography: ee, message: C } = K, { Text: d, Title: H } = ee, te = {
  extension_bridge: "checkExtensionBridge",
  nm_host: "checkNmHost",
  extension_assets: "checkExtensionAssets",
  bridge_lifecycle: "checkBridgeLifecycle"
}, ne = {
  reinstall_nm_host: "repairReinstallNmHost",
  reload_unpacked_extension: "repairReloadUnpackedExtension",
  wait_or_restart_chrome: "repairWaitOrRestartChrome",
  reload_extension: "repairReloadExtension"
}, s = {
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
function re(t) {
  return {
    ...s,
    chromeIcon: {
      ...s.chromeIcon,
      boxShadow: t.boxShadowSecondary
    },
    panel: {
      ...s.panel,
      background: t.colorBgContainer,
      border: `1px solid ${t.colorBorderSecondary}`,
      boxShadow: t.boxShadowTertiary
    },
    methodTile: {
      ...s.methodTile,
      background: t.colorBgContainer,
      border: `1px solid ${t.colorBorderSecondary}`
    },
    disabledTile: {
      ...s.disabledTile,
      background: t.colorFillQuaternary,
      border: `1px dashed ${t.colorBorder}`
    },
    statusCopy: { ...s.statusCopy, color: t.colorTextSecondary },
    badge: {
      ...s.badge,
      border: `1px solid ${t.colorPrimaryBorder}`,
      color: t.colorPrimaryText,
      background: t.colorPrimaryBg
    },
    installBox: {
      ...s.installBox,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillQuaternary
    },
    installTipsBox: {
      ...s.installTipsBox,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillTertiary
    },
    installBoxNote: {
      ...s.installBoxNote,
      color: t.colorTextTertiary
    },
    stepIndex: {
      ...s.stepIndex,
      color: t.colorText,
      background: t.colorFillTertiary
    },
    stepLine: { ...s.stepLine, color: t.colorTextSecondary },
    stepControl: {
      ...s.stepControl,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillSecondary,
      color: t.colorText,
      boxShadow: t.boxShadowSecondary
    },
    stepControlPrimary: {
      ...s.stepControlPrimary,
      borderColor: t.colorPrimary,
      background: t.colorPrimary,
      color: t.colorTextLightSolid
    },
    stepControlBlue: {
      ...s.stepControlBlue,
      borderColor: t.colorPrimaryBorder,
      background: t.colorPrimaryBg,
      color: t.colorPrimaryText
    },
    stepControlPlaceholder: {
      ...s.stepControlPlaceholder,
      color: t.colorTextSecondary,
      background: t.colorFillSecondary
    },
    osTabs: {
      ...s.osTabs,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorFillQuaternary
    },
    osTab: { ...s.osTab, color: t.colorTextSecondary },
    osTabActive: {
      ...s.osTabActive,
      background: t.colorBgContainer,
      color: t.colorText,
      boxShadow: t.boxShadowSecondary
    },
    shortcutSteps: {
      ...s.shortcutSteps,
      border: `1px solid ${t.colorBorderSecondary}`,
      background: t.colorBgContainer,
      color: t.colorTextSecondary
    },
    tipDot: {
      ...s.tipDot,
      background: t.colorFillTertiary,
      color: t.colorText
    },
    checkTile: {
      ...s.checkTile,
      border: `1px solid ${t.colorSuccessBorder}`,
      background: t.colorSuccessBg
    },
    advanced: { ...s.advanced, background: t.colorBgContainer },
    advancedValue: {
      ...s.advancedValue,
      background: t.colorFillQuaternary,
      border: `1px solid ${t.colorBorderSecondary}`,
      color: t.colorText
    }
  };
}
function b() {
  const { token: t } = x.antd.theme.useToken();
  return e.useMemo(() => re(t), [t]);
}
function oe() {
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
function ae() {
  const t = {}, n = R == null ? void 0 : R();
  return n && (t.Authorization = `Bearer ${n}`), t;
}
async function S(t, n) {
  const o = await fetch(Y(t), {
    ...n,
    headers: {
      ...(n == null ? void 0 : n.headers) || {},
      ...ae()
    }
  }), l = await o.text(), i = l ? JSON.parse(l) : null;
  if (!o.ok)
    throw new Error(
      typeof (i == null ? void 0 : i.detail) == "string" ? i.detail : o.statusText
    );
  return i;
}
function ie() {
  return S("/chrome/install-status");
}
async function le() {
  try {
    return await S("/browser/chrome/status");
  } catch {
    return null;
  }
}
async function se() {
  try {
    return await S("/browser/chrome/self-test", {
      method: "POST"
    });
  } catch {
    return null;
  }
}
function ce(t) {
  return S("/chrome/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(t)
  });
}
function de() {
  return S(
    "/chrome/open-chrome-extensions",
    {
      method: "POST"
    }
  );
}
function pe(t, n) {
  if (!t)
    return r(n, "justNow");
  const o = new Date(t).getTime();
  if (Number.isNaN(o))
    return r(n, "justNow");
  const l = Math.max(0, Math.floor((Date.now() - o) / 6e4));
  return l < 1 ? r(n, "justNow") : l < 60 ? r(n, "minutesAgo", { count: l }) : r(n, "hoursAgo", { count: Math.floor(l / 60) });
}
function me(t, n) {
  const o = ne[n];
  return o ? r(t, o) : "";
}
function F({ ready: t }) {
  const { token: n } = x.antd.theme.useToken(), o = b();
  return /* @__PURE__ */ e.createElement(
    "span",
    {
      "aria-hidden": "true",
      style: {
        ...o.statusDot,
        background: t ? n.colorSuccess : n.colorWarning
      }
    }
  );
}
function Q({ name: t, size: n }) {
  const o = b(), l = {
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
        ...o.inlineIcon,
        width: n,
        height: n,
        flex: `0 0 ${n}px`
      } : o.inlineIcon,
      ...l
    },
    i[t]
  );
}
function T({
  icon: t,
  label: n,
  loading: o,
  onClick: l,
  tone: i = "default",
  iconOnly: m = !1
}) {
  const p = b(), g = i === "primary" ? p.stepControlPrimary : i === "blue" ? p.stepControlBlue : i === "placeholder" ? p.stepControlPlaceholder : null;
  return /* @__PURE__ */ e.createElement(
    u,
    {
      "aria-label": m ? n : void 0,
      loading: o,
      onClick: l,
      style: {
        ...p.stepControl,
        ...g,
        ...m ? p.stepControlIconOnly : null
      },
      title: m ? n : void 0,
      type: "text"
    },
    /* @__PURE__ */ e.createElement(Q, { name: t, size: m ? 16 : void 0 }),
    m ? null : n
  );
}
function he() {
  var l, i;
  const t = ((l = window.navigator) == null ? void 0 : l.platform) || "", n = ((i = window.navigator) == null ? void 0 : i.userAgent) || "", o = `${t} ${n}`.toLowerCase();
  return o.includes("mac") ? "mac" : o.includes("win") ? "windows" : "linux";
}
function ue({
  locale: t,
  onCopy: n,
  status: o
}) {
  const l = b(), i = [
    { key: "extension_dir", label: "extensionDir" },
    { key: "native_manifest_path", label: "nativeManifest" },
    { key: "native_host_path", label: "nativeHost" },
    { key: "config_path", label: "config" }
  ], m = (o == null ? void 0 : o.bridge_endpoint) || "not ready";
  return /* @__PURE__ */ e.createElement(
    Z,
    {
      style: l.advanced,
      items: [
        {
          key: "advanced",
          label: r(t, "advancedInfo"),
          children: /* @__PURE__ */ e.createElement("div", { style: l.advancedRows }, i.map((p) => {
            const g = (o == null ? void 0 : o[p.key]) || "-";
            return /* @__PURE__ */ e.createElement("div", { key: p.key, style: l.advancedRow }, /* @__PURE__ */ e.createElement(d, { type: "secondary" }, r(t, p.label)), /* @__PURE__ */ e.createElement("code", { style: l.advancedValue }, g), /* @__PURE__ */ e.createElement(
              u,
              {
                disabled: !(o != null && o[p.key]),
                onClick: () => n(g)
              },
              r(t, "copyPath")
            ));
          }), /* @__PURE__ */ e.createElement("div", { style: l.advancedRow }, /* @__PURE__ */ e.createElement(d, { type: "secondary" }, r(t, "bridgeEndpoint")), /* @__PURE__ */ e.createElement("code", { style: l.advancedValue }, m), /* @__PURE__ */ e.createElement(u, { onClick: () => n(m) }, r(t, "copyPath"))))
        }
      ]
    }
  );
}
function ge() {
  var D;
  const t = b(), n = U(), [o, l] = e.useState(null), [i, m] = e.useState(null), [p, g] = e.useState(null), [f, I] = e.useState(!0), [$, _] = e.useState(!1), [M, w] = e.useState(null), [L, j] = e.useState(!1), [W, z] = e.useState(() => he()), y = e.useCallback(
    async (a) => {
      a != null && a.silent || I(!0), w(null);
      try {
        const [c, E] = await Promise.all([
          ie(),
          le()
        ]);
        return l(c), m(E), c;
      } catch (c) {
        const E = c instanceof Error ? c.message : String(c);
        return w(E), null;
      } finally {
        a != null && a.silent || I(!1);
      }
    },
    []
  );
  e.useEffect(() => {
    y();
  }, [y]);
  const v = e.useCallback(
    async (a) => {
      if (o != null && o.extension_dir && o.installed && !(a != null && a.refresh))
        return o;
      _(!0), w(null);
      try {
        const c = await ce({
          install_mode: "unpacked"
        });
        return l(c), a != null && a.silent || C.success(r(n, "installSuccess")), c;
      } catch (c) {
        const E = c instanceof Error ? c.message : String(c);
        return w(E), a != null && a.silent || C.error(r(n, "installFailed")), null;
      } finally {
        _(!1);
      }
    },
    [n, o]
  ), P = e.useCallback(
    async (a) => {
      var c;
      await ((c = navigator.clipboard) == null ? void 0 : c.writeText(a)), C.success(r(n, "copied"));
    },
    [n]
  ), G = e.useCallback(async () => {
    const a = await v({ refresh: !0 });
    a != null && a.extension_dir && await P(a.extension_dir);
  }, [P, v]), k = e.useCallback(async () => {
    const a = await de();
    !a.opened && a.error && C.warning(a.error);
  }, []), V = {
    mac: ["shortcutMacStep1", "shortcutMacStep2"],
    windows: ["shortcutWindowsStep1", "shortcutWindowsStep2"],
    linux: ["shortcutLinuxStep1", "shortcutLinuxStep2"]
  };
  e.useEffect(() => {
    f || L || o != null && o.extension_dir || (j(!0), v({ silent: !0 }));
  }, [f, v, L, o == null ? void 0 : o.extension_dir]);
  const h = !!(o != null && o.installed && (i != null && i.connected)), B = !!(o != null && o.installed && !(i != null && i.connected));
  return e.useEffect(() => {
    if (!h) {
      g(null);
      return;
    }
    let a = !1;
    return se().then((c) => {
      a || g(c ?? (i == null ? void 0 : i.last_self_test) ?? null);
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
  }, [h, y]), /* @__PURE__ */ e.createElement("div", { style: t.page }, /* @__PURE__ */ e.createElement("div", { style: t.shell }, /* @__PURE__ */ e.createElement("div", { style: t.panel }, /* @__PURE__ */ e.createElement("div", { style: t.statusBlock }, /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement("div", { style: t.header }, /* @__PURE__ */ e.createElement("div", { style: t.titleRow }, /* @__PURE__ */ e.createElement("span", { style: t.chromeIcon }), /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement(H, { level: 3, style: { margin: 0 } }, r(n, "pageTitle")), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, r(n, "pageSubtitle"))))), /* @__PURE__ */ e.createElement("div", { style: { marginTop: 22 } }, /* @__PURE__ */ e.createElement("div", { style: t.statusTitleRow }, h || B ? /* @__PURE__ */ e.createElement(F, { ready: h }) : null, /* @__PURE__ */ e.createElement(H, { level: 4, style: { margin: 0 } }, r(
    n,
    h ? "readyTitle" : B ? "awaitingTitle" : "installTitle"
  ))), /* @__PURE__ */ e.createElement("div", { style: t.statusCopy }, h ? r(n, "readyDescription", {
    version: (i == null ? void 0 : i.extension_version) || r(n, "versionUnknown"),
    connectedSince: pe(
      i == null ? void 0 : i.connected_since,
      n
    )
  }) : B ? r(n, "awaitingDescription") : (o == null ? void 0 : o.recovery_copy) || r(n, "installDescription")))), /* @__PURE__ */ e.createElement("div", { style: t.actions }, h ? /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement(
    u,
    {
      loading: f,
      onClick: () => void y()
    },
    r(n, "refreshStatus")
  ), /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      onClick: () => void k()
    },
    r(n, "openChrome")
  )) : /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      loading: f,
      onClick: () => void y()
    },
    r(n, "installedRefresh")
  ))), M ? /* @__PURE__ */ e.createElement(
    J,
    {
      showIcon: !0,
      type: "error",
      message: M,
      style: { marginTop: 16 }
    }
  ) : null, h ? /* @__PURE__ */ e.createElement("div", { style: t.section }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "checksTitle")), (D = p == null ? void 0 : p.checks) != null && D.length ? /* @__PURE__ */ e.createElement("div", { style: t.checkGrid }, p.checks.filter((a) => a.name !== "semantic_control").map((a) => /* @__PURE__ */ e.createElement("div", { key: a.name, style: t.checkTile }, /* @__PURE__ */ e.createElement("div", { style: t.checkTitle }, /* @__PURE__ */ e.createElement(F, { ready: a.passed }), /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(
    n,
    te[a.name] ?? "checkExtensionBridge"
  ))), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, a.passed ? r(n, "checkReady") : `${a.message} ${me(
    n,
    a.repair_action
  )}`.trim())))) : /* @__PURE__ */ e.createElement(d, { type: "secondary" }, r(n, "checksPending"))) : /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("div", { style: t.section }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "installMethodsTitle")), /* @__PURE__ */ e.createElement("div", { style: t.methodGrid }, /* @__PURE__ */ e.createElement("div", { style: t.methodTile }, /* @__PURE__ */ e.createElement("div", { style: t.methodHeader }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "localMethodTitle")), /* @__PURE__ */ e.createElement("span", { style: t.badge }, r(n, "recommendedBadge"))), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, r(n, "localMethodDescription")), /* @__PURE__ */ e.createElement(
    u,
    {
      type: "primary",
      onClick: () => void k()
    },
    /* @__PURE__ */ e.createElement(Q, { name: "chromeExtensions" }),
    r(n, "openChromeExtensionsPage")
  )), /* @__PURE__ */ e.createElement("div", { style: t.disabledTile, "aria-disabled": "true" }, /* @__PURE__ */ e.createElement("div", { style: t.methodHeader }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "chromeWebStoreTitle")), /* @__PURE__ */ e.createElement("span", { style: t.badge }, r(n, "comingSoon"))), /* @__PURE__ */ e.createElement(d, { type: "secondary" }, r(n, "chromeWebStoreDescription")), /* @__PURE__ */ e.createElement(u, { disabled: !0 }, r(n, "comingSoon"))))), /* @__PURE__ */ e.createElement("div", { style: t.section }, /* @__PURE__ */ e.createElement("div", { style: t.installSupportGrid }, /* @__PURE__ */ e.createElement("div", { style: t.installBox }, /* @__PURE__ */ e.createElement("div", { style: t.installBoxHead }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "localStepsTitle")), /* @__PURE__ */ e.createElement("span", { style: t.installBoxNote }, r(n, "localStepsOnce"))), /* @__PURE__ */ e.createElement("ol", { style: t.steps }, /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "1"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "openExtensionsStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, r(n, "openExtensionsPrefix"), /* @__PURE__ */ e.createElement(
    T,
    {
      icon: "chromeExtensions",
      label: r(n, "openExtensionsAction"),
      onClick: () => void k(),
      tone: "blue"
    }
  ), r(n, "openExtensionsSuffix")))), /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "2"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "developerModeStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, r(n, "developerModePrefix"), /* @__PURE__ */ e.createElement(
    T,
    {
      icon: "sliders",
      label: r(n, "developerModeAction"),
      tone: "placeholder"
    }
  ), r(n, "developerModeSuffix")))), /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "3"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "loadUnpackedStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, r(n, "loadUnpackedPrefix"), /* @__PURE__ */ e.createElement(
    T,
    {
      icon: "folderPlus",
      label: r(n, "loadUnpackedAction"),
      tone: "placeholder"
    }
  ), r(n, "loadUnpackedSuffix")))), /* @__PURE__ */ e.createElement("li", { style: t.stepItem }, /* @__PURE__ */ e.createElement("span", { style: t.stepIndex }, "4"), /* @__PURE__ */ e.createElement("div", { style: t.stepBody }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "pastePathStepTitle")), /* @__PURE__ */ e.createElement("div", { style: t.stepLine }, r(n, "pastePathGuide")))))), /* @__PURE__ */ e.createElement(
    "aside",
    {
      "aria-label": r(n, "shortcutTipsTitle"),
      style: t.installTipsBox
    },
    /* @__PURE__ */ e.createElement("div", { style: t.installBoxHead }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "shortcutTipsTitle")), /* @__PURE__ */ e.createElement("span", { style: t.installBoxNote }, r(n, "shortcutTipsScope"))),
    /* @__PURE__ */ e.createElement("div", { style: t.shortcutBox }, /* @__PURE__ */ e.createElement("div", { style: t.shortcutHead }, /* @__PURE__ */ e.createElement(d, { strong: !0 }, r(n, "currentSystem")), /* @__PURE__ */ e.createElement("div", { style: t.osTabs, role: "tablist" }, [
      ["mac", "macOS"],
      ["windows", "Windows"],
      ["linux", "Linux"]
    ].map(([a, c]) => /* @__PURE__ */ e.createElement(
      "button",
      {
        key: a,
        onClick: () => z(a),
        style: {
          ...t.osTab,
          ...W === a ? t.osTabActive : null
        },
        type: "button"
      },
      c
    )))), /* @__PURE__ */ e.createElement("ol", { style: t.shortcutSteps }, /* @__PURE__ */ e.createElement("li", { style: t.shortcutStep }, /* @__PURE__ */ e.createElement("span", { style: t.tipDot }, "1"), /* @__PURE__ */ e.createElement("div", { style: t.shortcutStepCopy }, /* @__PURE__ */ e.createElement("span", null, r(n, "shortcutCopyPathPrefix")), /* @__PURE__ */ e.createElement(
      T,
      {
        icon: "copy",
        label: r(n, "qwenpawExtensionPath"),
        loading: $,
        onClick: () => void G(),
        tone: "blue",
        iconOnly: !0
      }
    ), /* @__PURE__ */ e.createElement("span", null, r(n, "shortcutCopyPathSuffix")))), V[W].map(
      (a, c) => /* @__PURE__ */ e.createElement("li", { key: a, style: t.shortcutStep }, /* @__PURE__ */ e.createElement("span", { style: t.tipDot }, c + 2), /* @__PURE__ */ e.createElement("span", null, r(n, a)))
    )))
  )))), /* @__PURE__ */ e.createElement(
    ue,
    {
      locale: n,
      onCopy: (a) => void P(a),
      status: o
    }
  )), f && !o ? /* @__PURE__ */ e.createElement(X, null) : null));
}
var N, O;
(O = (N = window.QwenPaw).registerRoutes) == null || O.call(N, "chrome", [
  {
    path: "/plugin/chrome",
    component: ge,
    label: r(U(), "routeLabel"),
    icon: /* @__PURE__ */ e.createElement(oe, null),
    priority: 40
  }
]);
