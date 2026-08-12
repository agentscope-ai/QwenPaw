export type ComputerUseLocale = "en" | "zh";

const messages = {
  en: {
    routeLabel: "Computer Use",
    title: "Computer Use",
    ready: "Runtime ready",
    unavailable: "Runtime unavailable",
    refresh: "Refresh",
    stop: "Stop automation",
    feature: "Enable Computer Use",
    enabledMsg: "Computer Use enabled",
    disabledMsg: "Computer Use disabled; running automation stopped",
    application: "Application",
    applicationId: "Application ID",
    revoke: "Revoke access",
    revokeConfirm: "Revoke this application access?",
    empty: "No applications are always allowed.",
    approvalTitle: "Application access",
    unknownApplication: "Unknown application",
    risk: "Risk",
    deny: "Deny",
    allowSession: "Allow for this session",
    allowAlways: "Always allow",
    failed: "Action failed.",
    accessManagement: "Access management",
    version: "Version",
    decision: {
      deny: "Access denied.",
      session: "Access allowed for this session.",
      always: "Application always allowed.",
    },
  },
  zh: {
    routeLabel: "电脑操作",
    title: "电脑操作",
    ready: "运行环境已就绪",
    unavailable: "运行环境不可用",
    refresh: "刷新",
    stop: "停止自动化",
    feature: "启用电脑操作",
    enabledMsg: "已启用电脑操作",
    disabledMsg: "已关闭电脑操作，正在进行的自动化已停止",
    application: "应用",
    applicationId: "应用标识",
    revoke: "撤销授权",
    revokeConfirm: "撤销这个应用的授权？",
    empty: "暂未允许任何应用长期访问。",
    approvalTitle: "应用访问请求",
    unknownApplication: "未知应用",
    risk: "风险",
    deny: "拒绝",
    allowSession: "仅本次会话允许",
    allowAlways: "始终允许",
    failed: "操作失败。",
    accessManagement: "授权管理",
    version: "版本",
    decision: {
      deny: "已拒绝访问。",
      session: "已允许本次会话访问。",
      always: "已始终允许该应用。",
    },
  },
} as const;

export type MessageKey = keyof typeof messages.en;
export type DecisionKey = `decision.${keyof typeof messages.en.decision}`;

export function resolveLocale(
  value: string | null | undefined,
): ComputerUseLocale {
  return value?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function t(
  selectedLocale: ComputerUseLocale,
  key: MessageKey | DecisionKey,
): string {
  if (key.startsWith("decision.")) {
    const decision = key.slice(
      "decision.".length,
    ) as keyof typeof messages.en.decision;
    return messages[selectedLocale].decision[decision];
  }
  return messages[selectedLocale][key as MessageKey] as string;
}
