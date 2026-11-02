import type { TFunction } from "i18next";
import type { SettingsSearchTarget } from "@/plugins/settingsSearch";
import { CHANNEL_LABELS, getChannelLabel } from "@/utils/channel";
import { TOOL_PRESENTATION } from "@/pages/Agent/Tools/toolPresentation";
import {
  SETTINGS_SEARCH_GROUPS,
  settingsSearchGroup,
} from "./settingsSearchCatalog";

// Index user-facing settings, never configuration values or credentials.
// Keys reuse the same translations as their destination pages.
export const SETTINGS_SEARCH_KEYS: Record<string, string[]> = {
  general: [
    "settingsCenter.appearanceAndLanguage",
    "sidebar.settings.language",
    "sidebar.settings.theme",
    "sidebar.settings.desktopMode",
    "settingsCenter.customTheme",
    "settingsCenter.pages.navigation",
    "settingsCenter.chatDisplay",
    "settingsCenter.contentWidth",
    "settingsCenter.assistantDisplay",
    "settingsCenter.thinkingDisplay",
    "settingsCenter.toolDisplay",
  ],
  "cron-jobs": [
    "cronJobs.createJob",
    "cronJobs.scheduleTypeRecurring",
    "cronJobs.scheduleTypeOnce",
    "cronJobs.createFromTemplate",
    "cronJobs.scheduleTimezone",
    "cronJobs.executionModel",
    "cronJobs.dispatchChannel",
    "cronJobs.dispatchTargetUserId",
    "cronJobs.dispatchTargetSessionId",
    "cronJobs.saveResultToInbox",
    "cronJobs.silentDelivery",
    "cronJobs.runtimeShareSession",
    "cronJobs.runtimeMaxConcurrency",
    "cronJobs.runtimeTimeoutSeconds",
    "cronJobs.runtimeMisfireGraceSeconds",
  ],
  channels: [
    "channels.builtin",
    "channels.custom",
    "channels.pendingApprovals",
    "channels.manageAccessControl",
    "channels.accessControlDm",
    "channels.accessControlGroup",
    "channels.requireMention",
    "channels.whitelist",
    "channels.blacklist",
  ],
  heartbeat: [
    "heartbeat.enabled",
    "heartbeat.every",
    "heartbeat.timeoutSeconds",
    "heartbeat.instructionsTitle",
    "heartbeat.target",
    "heartbeat.activeHours",
  ],
  "agent-skills": [
    "skills.preload",
    "skills.importSkills",
    "skills.uploadSkill",
    "skills.downloadFromPool",
    "skills.batchOperation",
    "skills.filterByTag",
  ],
  tools: [
    "tools.groups.files",
    "tools.groups.web",
    "tools.groups.media",
    "tools.groups.agents",
    "tools.groups.runtime",
    "tools.groups.migration",
    "tools.asyncExecution",
    "tools.webSearchProviderLabel",
  ],
  mcp: ["mcp.qwenpawManaged", "mcp.create", "mcp.tools"],
  acp: ["acp.nodeSettings", "acp.nodePath", "acp.command", "acp.trusted"],
  import: [
    "portabilityImport.conversations",
    "portabilityImport.toolsSetup",
    "portabilityImport.chooseSources",
  ],
  "agent-config": [
    "models.primaryModel",
    "modelSelector.subagentModel",
    "models.defaultDecisionModel",
    "modelSelector.enableFallback",
    "modelSelector.chooseFallback",
    "agentConfig.agentLoopTitle",
    "agentConfig.llmRetryTitle",
    "agentConfig.llmRateLimiterTitle",
    "agentConfig.embeddingModelTitle",
    "agentConfig.embeddingBackend",
    "agentConfig.embeddingModelName",
    "agentConfig.embeddingDimensions",
    "agentConfig.embeddingEnableCache",
    "agentConfig.embeddingMaxCacheSize",
    "agentConfig.embeddingMaxInputLength",
    "agentConfig.embeddingMaxBatchSize",
    "agentConfig.embeddingHealthCheckTimeout",
    "agentConfig.toolExecutionLevelTitle",
    "agentConfig.language",
    "agentConfig.timezone",
    "agentConfig.toolResultCompactTitle",
    "agentConfig.memoryAutoRecordTitle",
    "agentConfig.rerankerTitle",
  ],
  marketplace: [
    "pluginManager.installed",
    "pluginManager.installBtn",
    "pluginManager.officialTitle",
  ],
  agents: [
    "agent.create",
    "agent.workspace",
    "agent.initialSkills",
    "agent.backend.typeTitle",
  ],
  models: [
    "models.providersTitle",
    "models.apiKey",
    "models.baseURL",
    "models.manageModels",
    "models.localRuntimeSectionTitle",
  ],
  "skill-pool": [
    "skillPool.automation",
    "skillPool.builtinAutoUpdate",
    "skillPool.autoSync",
    "skillPool.builtinLanguage",
    "skillPool.broadcast",
  ],
  environments: [
    "environments.liveSettings",
    "environments.customSettings",
    "environments.readonlySettings",
    "environments.addVariable",
  ],
  security: [
    "security.toolGuardTitle",
    "security.sandboxEnabled",
    "security.guardedTools",
    "security.deniedTools",
    "security.fileGuard.title",
    "security.skillScanner.title",
    "security.allowNoAuthHosts.title",
  ],
  "offload-policy": ["agentConfig.offloadPolicy.title"],
  "token-usage": [
    "tokenUsage.totalTokens",
    "tokenUsage.totalCalls",
    "tokenUsage.cacheHitRate",
    "tokenUsage.byAgent",
    "tokenUsage.byModel",
    "tokenUsage.byDate",
  ],
  backups: [
    "backup.create",
    "backup.import",
    "backup.restore",
    "backup.fullBackup",
    "backup.scopeSecrets",
  ],
  debug: [
    "debug.backend.title",
    "debug.backend.autoRefresh",
    "debug.backend.path",
  ],
  voice: [
    "voiceTranscription.audioModeLabel",
    "voiceTranscription.providerTypeLabel",
    "voiceTranscription.providerLabel",
  ],
};

for (const group of SETTINGS_SEARCH_GROUPS) {
  SETTINGS_SEARCH_KEYS[group.page] = [
    ...new Set([...SETTINGS_SEARCH_KEYS[group.page], ...group.keys]),
  ];
}

const SEARCH_LABEL_KEYS: Record<string, string> = {
  "skills.importSkills": "skills.importHub",
  "skills.uploadSkill": "skills.uploadZip",
  "models.localRuntimeSectionTitle": "models.localCustomGroup",
  "agentConfig.toolResultCompactTitle":
    "agentConfig.toolResultPruningCollapseLabel",
};

export function settingsSearchLabel(key: string, t: TFunction) {
  return t(SEARCH_LABEL_KEYS[key] ?? key);
}

export interface SettingsSearchAvailability {
  strategy?: string;
  memoryBackend?: string;
}

export function settingsSearchUnavailableReason(
  page: string,
  key: string,
  context: SettingsSearchAvailability | undefined,
  t: TFunction,
) {
  if (page !== "agent-config") return undefined;
  if (
    [
      "agentConfig.toolResultCompactRecentN",
      "agentConfig.toolResultCompactOldThreshold",
      "agentConfig.exemptFileExtensions",
      "agentConfig.exemptToolNames",
    ].includes(key) &&
    context?.strategy !== "native"
  ) {
    return t("settingsCenter.searchNativeContextOnly");
  }
  if (
    key === "agentConfig.historyRetentionDays" &&
    context?.strategy === "native"
  )
    return t("settingsCenter.searchScrollContextOnly");
  if (
    context?.memoryBackend &&
    context.memoryBackend !== "remelight" &&
    (key.startsWith("agentConfig.embedding") ||
      key.startsWith("agentConfig.reranker") ||
      (key.startsWith("agentConfig.memory") &&
        key !== "agentConfig.memoryManagerBackend") ||
      ["agentConfig.dreamCron", "agentConfig.autoMaxResults"].includes(key))
  )
    return t("settingsCenter.searchReMeOnly");
  return undefined;
}

export const normalizeSettingsSearch = (value: string) =>
  value.normalize("NFKC").toLocaleLowerCase().trim();

export function matchesSettingsSearch(query: string, text: string) {
  const haystack = normalizeSettingsSearch(text);
  return normalizeSettingsSearch(query)
    .split(/\s+/)
    .every((word) => haystack.includes(word));
}

export function searchSettingsItems(
  pageKey: string,
  query: string,
  t: TFunction,
  pageContext = "",
) {
  if (!query.trim()) return [];
  return (SETTINGS_SEARCH_KEYS[pageKey] ?? []).filter((key) =>
    matchesSettingsSearch(
      query,
      `${pageContext} ${
        MODEL_ROUTING_KEYS.has(key) ? t("modelSelector.agentModelSettings") : ""
      } ${settingsSearchPath(key, t, undefined, pageKey).join(
        " ",
      )} ${settingsSearchPath(key, t, "en", pageKey).join(
        " ",
      )} ${settingsSearchLabel(key, t)} ${
        SETTINGS_SEARCH_ALIASES[key] ?? ""
      } ${t(key)} ${t(key, {
        lng: "en",
      })} ${t(`${key}Hint`, {
        defaultValue: "",
      })} ${t(`${key}Tooltip`, { defaultValue: "" })}`,
    ),
  );
}

// Switch only navigation tabs; search never opens or executes a setting action.
export const SETTINGS_SEARCH_TABS: Record<string, string> = {
  "agentConfig.reactAgentTitle": "runtimeDesign.workspace",
  "agentConfig.agentLoopTitle": "runtimeDesign.execution",
  "agentConfig.toolExecutionLevelTitle": "runtimeDesign.execution",
  "agentConfig.llmRetryTitle": "runtimeDesign.recovery",
  "agentConfig.llmRateLimiterTitle": "runtimeDesign.recovery",
  "agentConfig.embeddingModelTitle": "runtimeDesign.memory",
  "agentConfig.embeddingBackend": "runtimeDesign.memory",
  "agentConfig.embeddingModelName": "runtimeDesign.memory",
  "agentConfig.embeddingDimensions": "runtimeDesign.memory",
  "agentConfig.embeddingEnableCache": "runtimeDesign.memory",
  "agentConfig.embeddingMaxCacheSize": "runtimeDesign.memory",
  "agentConfig.embeddingMaxInputLength": "runtimeDesign.memory",
  "agentConfig.embeddingMaxBatchSize": "runtimeDesign.memory",
  "agentConfig.embeddingHealthCheckTimeout": "runtimeDesign.memory",
  "agentConfig.language": "runtimeDesign.workspace",
  "agentConfig.timezone": "runtimeDesign.workspace",
  "agentConfig.maxIters": "runtimeDesign.execution",
  "agentConfig.maxInputLength": "runtimeDesign.workspace",
  "agentConfig.contextManagementTitle": "runtimeDesign.context",
  "agentConfig.contextCompactTitle": "runtimeDesign.context",
  "agentConfig.toolResultCompactTitle": "runtimeDesign.context",
  "agentConfig.memorySummaryTitle": "runtimeDesign.memory",
  "agentConfig.memoryAutoRecordTitle": "runtimeDesign.memory",
  "agentConfig.rerankerTitle": "runtimeDesign.memory",
  "models.primaryModel": "runtimeDesign.workspace",
  "modelSelector.subagentModel": "runtimeDesign.workspace",
  "models.defaultDecisionModel": "runtimeDesign.workspace",
  "modelSelector.enableFallback": "runtimeDesign.workspace",
  "modelSelector.chooseFallback": "runtimeDesign.workspace",
  "security.sandboxEnabled": "security.toolGuardTitle",
  "security.guardedTools": "security.toolGuardTitle",
  "security.deniedTools": "security.toolGuardTitle",
};

const CRON_SEARCH_TABS: Record<string, string> = {
  "cronJobs.scheduleTimezone": "schedule",
  "cronJobs.executionModel": "delivery",
  "cronJobs.dispatchChannel": "delivery",
  "cronJobs.dispatchTargetUserId": "delivery",
  "cronJobs.dispatchTargetSessionId": "delivery",
  "cronJobs.saveResultToInbox": "delivery",
  "cronJobs.silentDelivery": "delivery",
  "cronJobs.runtimeShareSession": "runtime",
  "cronJobs.runtimeMaxConcurrency": "runtime",
  "cronJobs.runtimeTimeoutSeconds": "runtime",
  "cronJobs.runtimeMisfireGraceSeconds": "runtime",
};

const MODEL_ROUTING_KEYS = new Set([
  "models.primaryModel",
  "modelSelector.subagentModel",
  "models.defaultDecisionModel",
  "modelSelector.enableFallback",
  "modelSelector.chooseFallback",
]);

const SETTINGS_SEARCH_ALIASES: Record<string, string> = {
  "runtimeDesign.workspace": "ReAct 智能体 ReAct Agent",
  "runtimeDesign.context":
    "上下文管理 上下文压缩配置 Context Management Context Compact Config",
  "runtimeDesign.memory": "长期记忆配置 Long-term Memory Config",
  "models.maxInputLengthLabel": "最大输入长度 Max Input Length context window",
  "environments.liveSettings":
    "QwenPaw 已知配置 QwenPaw settings known settings",
  "mcp.form.transport": "Stdio Streamable HTTP SSE",
  "acp.env": "客户端环境变量 client environment variables",
  "cronJobs.scheduleTimezone": "调度时区 任务时区 schedule timezone",
  "modelSelector.subagentModel": "Sub-agent model",
  "cronJobs.runtimeMisfireGraceSeconds": "misfire grace",
  "channels.whitelist": "频道白名单 allowlist whitelist",
  "channels.blacklist": "频道黑名单 denylist blacklist",
  "acp.nodePath": "Node.js 路径 Node path",
};

export function settingsSearchPath(
  key: string,
  t: TFunction,
  lng?: string,
  page?: string,
) {
  const keys: string[] = [];
  const group = SETTINGS_SEARCH_GROUPS.find(
    (group) => (!page || group.page === page) && group.keys.includes(key),
  );
  if (group) return [t(group.path, { lng })];
  if (MODEL_ROUTING_KEYS.has(key))
    keys.push("runtimeDesign.workspace", "models.llmTitle");
  else if (CRON_SEARCH_TABS[key]) {
    keys.push(
      {
        schedule: "cronJobs.scheduleType",
        delivery: "heartbeat.target",
        runtime: "common.advancedSettings",
      }[CRON_SEARCH_TABS[key]]!,
    );
  } else if (["channels.whitelist", "channels.blacklist"].includes(key)) {
    keys.push("channels.manageAccessControl");
  } else if (
    [
      "channels.accessControlDm",
      "channels.accessControlGroup",
      "channels.requireMention",
    ].includes(key)
  ) {
    keys.push("channels.advancedSettings");
  } else if (key === "acp.nodePath") keys.push("acp.nodeSettings");
  else if (SETTINGS_SEARCH_TABS[key]) keys.push(SETTINGS_SEARCH_TABS[key]);
  return keys.map((part) => t(part, { lng }));
}

export function settingsSearchTarget(
  page: string,
  key: string,
  t: TFunction,
): SettingsSearchTarget {
  const target: SettingsSearchTarget = {
    page,
    label: settingsSearchLabel(key, t),
    tab: SETTINGS_SEARCH_TABS[key] ? t(SETTINGS_SEARCH_TABS[key]) : undefined,
  };
  if (MODEL_ROUTING_KEYS.has(key)) target.targetId = key;
  if (CRON_SEARCH_TABS[key])
    Object.assign(target, {
      targetId: key,
      tabId: CRON_SEARCH_TABS[key],
      surface: "cron-job",
    });
  if (
    [
      "channels.accessControlDm",
      "channels.accessControlGroup",
      "channels.requireMention",
    ].includes(key)
  )
    Object.assign(target, { targetId: key, surface: "channel" });
  if (["channels.whitelist", "channels.blacklist"].includes(key))
    Object.assign(target, {
      targetId: key,
      tabId: key.split(".")[1],
      surface: "channel-acl",
    });
  if (key === "acp.nodePath")
    Object.assign(target, { targetId: key, surface: "node" });

  const group = settingsSearchGroup(page, key);
  if (group)
    Object.assign(target, {
      tab: group.tab ? t(group.tab) : target.tab,
      tabId: group.tabId,
      surface: group.surface,
      hint: group.hint ? t(group.hint) : undefined,
    });

  const runtimeTab =
    target.tab &&
    Object.entries({
      workspace: "reactAgent",
      execution: "agentLoop",
      recovery: "llmRetry",
      context: "lightContext",
      memory: "remeLightMemory",
    }).find(([id]) => t(`runtimeDesign.${id}`) === target.tab);
  if (page === "agent-config" && runtimeTab) {
    target.tabId = runtimeTab[0];
    target.query = { tab: runtimeTab[1] };
  }
  if (key.startsWith("runtimeDesign.")) target.targetId = key;
  const modules: Record<string, string> = {
    "agentConfig.reactAgentTitle": "reactAgent",
    "agentConfig.agentLoopTitle": "agentLoop",
    "agentConfig.llmRetryTitle": "llmRetry",
    "agentConfig.llmRateLimiterTitle": "llmRateLimiter",
    "agentConfig.contextManagementTitle": "lightContext",
    "agentConfig.contextCompactTitle": "lightContext",
    "agentConfig.embeddingModelTitle": "embeddingModel",
    "agentConfig.toolExecutionLevelTitle": "toolExecutionLevel",
    "agentConfig.memorySummaryTitle": "remeLightMemory",
  };
  if (modules[key]) target.targetId = `runtime:${modules[key]}`;
  if (page === "marketplace") {
    target.query = {
      tab: "plugins",
      view: key === "pluginManager.officialTitle" ? "official" : "installed",
    };
    if (key !== "pluginManager.installBtn") target.tab = t(key);
  }
  if (key === "models.localRuntimeSectionTitle") {
    target.tabId = "local";
    target.targetId = "models.localCustomGroup";
  }
  if (key === "models.manageModels") target.targetId = key;
  if (key === "models.apiKey") target.label = "API Key";
  if (group?.surface === "theme") target.targetId = key;
  if (
    [
      "skills.importSkills",
      "skills.uploadSkill",
      "skills.downloadFromPool",
    ].includes(key)
  ) {
    target.targetId = SEARCH_LABEL_KEYS[key] ?? key;
    target.surface = "skill-add";
  }
  const surfaces: Record<string, string> = {
    "skills.preload": "skill",
    "tools.webSearchProviderLabel": "web-search",
    "acp.command": "acp-client",
    "acp.trusted": "acp-client",
    "agent.workspace": "agent",
    "agent.initialSkills": "agent",
    "agent.backend.typeTitle": "agent",
    "skillPool.automation": "pool-skill",
    "skillPool.builtinAutoUpdate": "pool-skill",
    "skillPool.autoSync": "pool-skill",
    "skillPool.builtinLanguage": "pool-skill",
    "backup.fullBackup": "backup",
    "backup.scopeSecrets": "backup",
  };
  if (surfaces[key]) {
    target.surface = surfaces[key];
    target.hint = t("settingsCenter.searchSelectObject");
  }
  if (key === "skills.preload" || (page === "skill-pool" && surfaces[key]))
    target.targetId = key;
  const prerequisites: Record<string, string> = {
    "skillPool.builtinLanguage": "settingsCenter.searchBuiltinSkillLanguage",
    "skillPool.builtinAutoUpdate": "settingsCenter.searchBuiltinSkillUpdate",
    "backup.scopeSecrets": "settingsCenter.searchBackupSecrets",
    "voiceTranscription.providerLabel": "settingsCenter.searchWhisperProvider",
  };
  if (prerequisites[key]) target.hint = t(prerequisites[key]);
  if (key === "models.manageModels")
    target.hint = t("settingsCenter.searchSelectObject");
  if (page === "import" && key !== "portabilityImport.chooseSources")
    target.hint = t("settingsCenter.searchSelectObject");
  if (page === "agent-config" && runtimeTab?.[0] === "memory")
    target.hint = t("settingsCenter.searchConditionalSetting");
  if (key === "tools.webSearchProviderLabel") {
    target.targetId = key;
    target.hint = undefined;
  }
  if (key === "tools.asyncExecution") target.targetId = key;
  if (key === "tools.asyncExecution")
    target.hint = t("settingsCenter.searchToolAvailability");
  if (key === "settingsCenter.mcpJsonConfig") {
    target.targetId = key;
    target.surface = "mcp-json";
  }
  if (key.startsWith("tools.browser")) target.targetId = "tool:browser";
  if (key.startsWith("tools.browser"))
    target.hint = t("settingsCenter.searchToolAvailability");
  if (key.startsWith("tools.groups.")) target.targetId = key;
  if (key === "voiceTranscription.providerTypeLabel") {
    target.hint = t("settingsCenter.searchConditionalSetting");
  }
  return target;
}

export function searchToolNames(query: string, t: TFunction, context: string) {
  if (!query.trim()) return [];
  return Object.keys(TOOL_PRESENTATION).flatMap((name) => {
    const label = t(`tools.catalog.${name}.name`, { defaultValue: name });
    const english = t(`tools.catalog.${name}.name`, {
      lng: "en",
      defaultValue: name,
    });
    if (!matchesSettingsSearch(query, `${context} ${name} ${label} ${english}`))
      return [];
    return [
      {
        id: `tool:${name}`,
        label,
        path: t("nav.tools"),
        target: {
          page: "tools",
          label,
          targetId: `tool:${name}`,
          hint: t("settingsCenter.searchToolAvailability"),
        },
      },
    ];
  });
}

export function searchChannelNames(
  query: string,
  t: TFunction,
  context: string,
  customNames: Record<string, string> = {},
) {
  if (!query.trim()) return [];
  return Object.entries({ ...CHANNEL_LABELS, ...customNames }).flatMap(
    ([key, english]) => {
      const label = key in CHANNEL_LABELS ? getChannelLabel(key, t) : english;
      if (
        !matchesSettingsSearch(query, `${context} ${label} ${english} ${key}`)
      )
        return [];
      return [
        {
          id: `channel:${key}`,
          label,
          path: label,
          target: {
            page: "channels",
            label,
            targetId: `channel:${key}`,
            channelKey: key,
            surface: "channel" as const,
          },
        },
      ];
    },
  );
}
