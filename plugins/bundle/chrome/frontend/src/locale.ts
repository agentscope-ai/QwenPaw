export type ChromeLocale = "zh" | "en";

const messages = {
  en: {
    routeLabel: "Chrome",
    pageTitle: "Chrome",
    pageSubtitle: "Connect QwenPaw to this Chrome browser.",
    loading: "Checking Chrome connection...",
    refreshStatus: "Refresh Status",
    installedRefresh: "I've installed it, refresh status",
    versionUnknown: "unknown",
    installTitle: "Install Chrome Extension",
    installDescription:
      "Load the local extension, then return here to confirm the connection.",
    readyTitle: "Chrome Connected",
    readyDescription: "Version {version}. Connected {connectedSince}.",
    awaitingTitle: "Extension installed, waiting for Chrome",
    awaitingDescription:
      "The extension is installed. Keep Chrome running; the bridge will connect automatically.",
    openChrome: "Open Chrome",
    installMethodsTitle: "Install method",
    localMethodTitle: "Local install",
    recommendedBadge: "Recommended",
    localMethodDescription:
      "Use the extension files included with QwenPaw for this local browser.",
    openChromeExtensionsPage: "Open Chrome extensions page",
    chromeWebStoreTitle: "Chrome Web Store",
    chromeWebStoreDescription:
      "The store listing is not available yet. Use local install for now.",
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
    pastePathGuide:
      "Follow the Quick paste path tips on the right to copy the path, paste it, and open the folder.",
    qwenpawExtensionPath: "Copy QwenPaw extension path",
    shortcutTipsTitle: "Quick paste path tips",
    shortcutTipsScope: "Use when selecting folder",
    currentSystem: "Current system",
    shortcutCopyPathPrefix: "Click",
    shortcutCopyPathSuffix:
      "button to copy the QwenPaw extension path to your clipboard.",
    shortcutMacStep1:
      "Press Cmd + Shift + G, paste the path, then press Enter.",
    shortcutMacStep2: "After the folder is selected, click Open.",
    shortcutWindowsStep1:
      "Click the address bar, paste the path, then press Enter.",
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
    repairReloadUnpackedExtension:
      "Reload the unpacked extension in chrome://extensions.",
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
    chrome_disconnected:
      "Reload the extension or reopen the target browser tab.",
    browser_backend_unavailable:
      "Refresh the status after the backend is available.",
    chrome_action_runtime_missing:
      "Restart QwenPaw or reload the Chrome plugin.",
    isolated_backend_unavailable:
      "Install or restart the isolated browser runtime.",
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
    pastePathGuide:
      "请按右侧“快捷粘贴路径 Tips”的步骤完成复制、粘贴并打开目录。",
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
    repairReloadUnpackedExtension:
      "在 chrome://extensions 重新加载已解压的扩展。",
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
    isolated_backend_unavailable: "安装或重启隔离浏览器运行时。",
  },
} as const;

export type MessageKey = keyof typeof messages.en;

export function readConsoleLanguage(): string | null {
  try {
    return window.localStorage?.getItem("language") ?? null;
  } catch {
    return null;
  }
}

export function resolveChromeLocale(
  language: string | null | undefined = readConsoleLanguage(),
): ChromeLocale {
  const base = String(language || "")
    .trim()
    .split("-")[0]
    .toLowerCase();
  return base === "zh" ? "zh" : "en";
}

export function t(
  locale: ChromeLocale,
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  let text: string = messages[locale][key] ?? messages.en[key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}
