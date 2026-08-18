/**
 * Zero-dependency string tables for the QwenPaw-Data shell.
 *
 * `en` is the schema: `zh` is typed against its keys, so a missing or
 * extra translation fails typecheck instead of falling back at runtime.
 * The active language is the same `localStorage["language"]` value the
 * embedded Context console's i18next reads, keeping one toggle in charge
 * of both surfaces.
 */

export type Language = "en" | "zh";

const en = {
  // App chrome
  "nav.aria": "QwenPaw-Data navigation",
  "nav.analyze": "Analyze",
  "nav.manage": "Manage",
  "topbar.modelSettings": "Model settings",
  "toast.sourceUpdated": "Default data source updated",
  "toast.sourceAll": "Using all available context",

  // Status panel
  "status.openDetails": "Open runtime status details",
  "status.waitingFirstCheck": "Waiting for first check",
  "status.checked": "Checked {time}",
  "status.label.ready": "Ready",
  "status.label.degraded": "Degraded",
  "status.label.unavailable": "Unavailable",
  "status.label.checking": "Checking",
  "status.category.core": "Core",
  "status.category.data": "Data",
  "status.category.graph": "Graph",
  "status.category.skills": "Skills",
  "status.detail.ready": "{ready}/{total} ready",
  "status.detail.checking": "Checking",
  "status.detail.sourceReady": "Source ready",
  "status.detail.sourceUnavailable": "Source unavailable",
  "status.detail.sourcesReady": "{ready}/{total} sources ready",
  "status.detail.noSources": "No sources discovered",
  "status.detail.groundingReady": "Grounding ready",
  "status.detail.optionalUnavailable": "Optional unavailable",
  "status.detail.notConfigured": "Not configured",
  "status.detail.skillsLoaded": "{count} loaded",
  "status.detail.loaded": "Loaded",
  "status.detail.requiredReady": "{ready}/{total} required services ready",
  "status.detail.discovering": "Discovering dependencies",
  "status.detail.contextUnavailable": "Context service unavailable",

  // Chat workspace
  "chat.aria": "Data analysis chat",
  "chat.sourceSelect": "Default data source for analysis",
  "chat.allContext": "All available context",
  "chat.restoring": "Restoring your analysis…",
  "chat.welcomeTitle": "What would you like to understand?",
  "chat.welcomeBody":
    "QwenPaw-Data can retrieve semantic definitions, inspect " +
    "relationships, and run governed queries through the selected " +
    "data source.",
  "chat.starter.domains":
    "Summarize the key business domains and their north-star metrics.",
  "chat.starter.movement":
    "Find the largest week-over-week movement and explain possible drivers.",
  "chat.starter.retention":
    "Show which datasets can answer a customer retention question.",
  "chat.you": "You",
  "chat.analyzing": "Analyzing",
  "chat.placeholder":
    "Ask about a metric, trend, dataset, or business question…",
  "chat.send": "Send",
  "chat.hint":
    "QwenPaw-Data may execute read-only queries. Verify important decisions.",
  "chat.noTextResponse": "The analysis completed without a text response.",
  "chat.analysisFailed": "QwenPaw-Data analysis failed",

  // Analysis trace
  "trace.live": "Live analysis",
  "trace.steps": "Analysis trace · {count} {stepWord}",
  "trace.step": "step",
  "trace.stepPlural": "steps",
  "trace.showingRows": "Showing the first {count} rows.",
  "trace.rows": "{count} {rowWord}",
  "trace.row": "row",
  "trace.rowPlural": "rows",
  "trace.queryFailed": "Query failed",

  // Tool labels
  "tool.listDomains": "List business domains",
  "tool.exploreEntity": "Explore semantic entity",
  "tool.searchContext": "Search governed context",
  "tool.executeSql": "Execute governed SQL",

  // Session history
  "history.aria": "Session history",
  "history.sessions": "Sessions",
  "history.newChat": "+ New chat",
  "history.creating": "Creating…",
  "history.dialogueName": "Dialogue name",
  "history.actionsFor": "Actions for {name}",
  "history.pin": "Pin",
  "history.unpin": "Unpin",
  "history.rename": "Rename",
  "history.archive": "Archive",
  "history.delete": "Delete",
  "history.confirmDelete": "Confirm delete",
  "history.collapse": "Collapse session history",
  "history.expand": "Expand session history",
  "history.newAnalysis": "New analysis",
  "history.previousAnalysis": "Previous analysis",

  // Session errors and toasts
  "session.legacyFallback":
    "Dialogue management is unavailable; using legacy history",
  "session.restoreFailed": "Could not restore the analysis history",
  "session.createFailed": "Could not create a new dialogue. {detail}",
  "session.actionFailed": "Could not {action} the dialogue. {detail}",
  "session.action.pin": "pin",
  "session.action.rename": "rename",
  "session.action.archive": "archive",
  "session.action.delete": "delete",
  "session.action.replace": "replace",

  // Analysis error surfaces
  "error.modelNotConfigured":
    "No language model is configured for this QwenPaw workspace. " +
    "Open Settings → Models, configure and activate a model, then retry.",
  "error.modelUnauthorized":
    "The configured language model rejected its credentials. " +
    "Open Settings → Models, update the API key, then retry.",
  "error.agentReloading":
    "The QwenPaw-Data agent is reloading (this happens briefly after an " +
    "app update). Please retry in a few seconds.",
  "error.analysisFallback": "I could not run that analysis. {detail}",
} as const;

export type StringKey = keyof typeof en;

const zh: Record<StringKey, string> = {
  "nav.aria": "QwenPaw-Data 导航",
  "nav.analyze": "分析",
  "nav.manage": "管理",
  "topbar.modelSettings": "模型设置",
  "toast.sourceUpdated": "默认数据源已更新",
  "toast.sourceAll": "已使用全部可用上下文",

  "status.openDetails": "打开运行时状态详情",
  "status.waitingFirstCheck": "等待首次检查",
  "status.checked": "检查于 {time}",
  "status.label.ready": "就绪",
  "status.label.degraded": "部分可用",
  "status.label.unavailable": "不可用",
  "status.label.checking": "检查中",
  "status.category.core": "核心",
  "status.category.data": "数据",
  "status.category.graph": "图谱",
  "status.category.skills": "技能",
  "status.detail.ready": "{ready}/{total} 就绪",
  "status.detail.checking": "检查中",
  "status.detail.sourceReady": "数据源就绪",
  "status.detail.sourceUnavailable": "数据源不可用",
  "status.detail.sourcesReady": "{ready}/{total} 个数据源就绪",
  "status.detail.noSources": "未发现数据源",
  "status.detail.groundingReady": "图谱就绪",
  "status.detail.optionalUnavailable": "可选服务不可用",
  "status.detail.notConfigured": "未配置",
  "status.detail.skillsLoaded": "已加载 {count} 个",
  "status.detail.loaded": "已加载",
  "status.detail.requiredReady": "{ready}/{total} 个必需服务就绪",
  "status.detail.discovering": "正在发现依赖",
  "status.detail.contextUnavailable": "Context 服务不可用",

  "chat.aria": "数据分析对话",
  "chat.sourceSelect": "分析使用的默认数据源",
  "chat.allContext": "全部可用上下文",
  "chat.restoring": "正在恢复你的分析…",
  "chat.welcomeTitle": "你想分析什么？",
  "chat.welcomeBody":
    "QwenPaw-Data 可以检索语义定义、洞察实体关系，并通过所选数据源执行治理查询。",
  "chat.starter.domains": "总结核心业务域及其北极星指标。",
  "chat.starter.movement": "找出周环比波动最大的指标，并解释可能的原因。",
  "chat.starter.retention": "哪些数据集可以回答客户留存问题？",
  "chat.you": "你",
  "chat.analyzing": "分析中",
  "chat.placeholder": "询问指标、趋势、数据集或业务问题…",
  "chat.send": "发送",
  "chat.hint": "QwenPaw-Data 可能执行只读查询。重要决策请自行核实。",
  "chat.noTextResponse": "分析已完成，但没有文本回复。",
  "chat.analysisFailed": "QwenPaw-Data 分析失败",

  "trace.live": "实时分析",
  "trace.steps": "分析轨迹 · {count} {stepWord}",
  "trace.step": "步",
  "trace.stepPlural": "步",
  "trace.showingRows": "仅显示前 {count} 行。",
  "trace.rows": "{count} {rowWord}",
  "trace.row": "行",
  "trace.rowPlural": "行",
  "trace.queryFailed": "查询失败",

  "tool.listDomains": "列出业务域",
  "tool.exploreEntity": "探索语义实体",
  "tool.searchContext": "检索治理上下文",
  "tool.executeSql": "执行治理 SQL",

  "history.aria": "会话历史",
  "history.sessions": "会话",
  "history.newChat": "+ 新会话",
  "history.creating": "创建中…",
  "history.dialogueName": "会话名称",
  "history.actionsFor": "{name} 的操作",
  "history.pin": "置顶",
  "history.unpin": "取消置顶",
  "history.rename": "重命名",
  "history.archive": "归档",
  "history.delete": "删除",
  "history.confirmDelete": "确认删除",
  "history.collapse": "收起会话历史",
  "history.expand": "展开会话历史",
  "history.newAnalysis": "新分析",
  "history.previousAnalysis": "历史分析",

  "session.legacyFallback": "会话管理不可用，已使用旧版历史",
  "session.restoreFailed": "无法恢复分析历史",
  "session.createFailed": "无法创建新会话。{detail}",
  "session.actionFailed": "无法{action}会话。{detail}",
  "session.action.pin": "置顶",
  "session.action.rename": "重命名",
  "session.action.archive": "归档",
  "session.action.delete": "删除",
  "session.action.replace": "替换",

  "error.modelNotConfigured":
    "当前 QwenPaw 工作区未配置语言模型。请打开 设置 → 模型，配置并激活一个模型后重试。",
  "error.modelUnauthorized":
    "配置的语言模型拒绝了凭据。请打开 设置 → 模型，更新 API Key 后重试。",
  "error.agentReloading":
    "QwenPaw-Data 智能体正在重新加载（应用更新后会短暂出现）。请几秒后重试。",
  "error.analysisFallback": "无法完成本次分析。{detail}",
};

const TABLES: Record<Language, Record<StringKey, string>> = { en, zh };

export type StringParams = Record<string, string | number>;

export function translate(
  language: Language,
  key: StringKey,
  params?: StringParams,
): string {
  let text: string = TABLES[language][key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

export function stringKeys(): StringKey[] {
  return Object.keys(en) as StringKey[];
}

/** BCP 47 tag for locale-sensitive date and number formatting. */
export function localeTag(language: Language): string {
  return language === "zh" ? "zh-CN" : "en-US";
}
