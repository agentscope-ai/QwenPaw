import type { TFunction } from "i18next";

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
  ],
  channels: [
    "channels.builtin",
    "channels.custom",
    "channels.pendingApprovals",
    "channels.manageAccessControl",
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
  mcp: ["mcp.qwenpawManaged", "mcp.providerManaged", "mcp.create", "mcp.tools"],
  acp: ["acp.nodeSettings", "acp.command", "acp.trusted"],
  import: [
    "portabilityImport.conversations",
    "portabilityImport.toolsSetup",
    "portabilityImport.chooseSources",
  ],
  "agent-config": [
    "agentConfig.reactAgentTitle",
    "agentConfig.agentLoopTitle",
    "agentConfig.llmRetryTitle",
    "agentConfig.llmRateLimiterTitle",
    "agentConfig.contextManagementTitle",
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
    "agentConfig.maxIters",
    "agentConfig.maxInputLength",
    "agentConfig.contextCompactTitle",
    "agentConfig.toolResultCompactTitle",
    "agentConfig.memorySummaryTitle",
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
    "models.localModelsTitle",
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
    "environments.qwenpawSettings",
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
) {
  if (!query.trim()) return [];
  return (SETTINGS_SEARCH_KEYS[pageKey] ?? []).filter((key) =>
    matchesSettingsSearch(
      query,
      `${t(key)} ${t(key, { lng: "en" })} ${t(`${key}Hint`, {
        defaultValue: "",
      })} ${t(`${key}Tooltip`, { defaultValue: "" })}`,
    ),
  );
}

// Switch only navigation tabs; search never opens or executes a setting action.
export const SETTINGS_SEARCH_TABS: Record<string, string> = {
  "agentConfig.embeddingBackend": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingModelName": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingDimensions": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingEnableCache": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingMaxCacheSize": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingMaxInputLength": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingMaxBatchSize": "agentConfig.embeddingModelTitle",
  "agentConfig.embeddingHealthCheckTimeout": "agentConfig.embeddingModelTitle",
  "agentConfig.language": "agentConfig.reactAgentTitle",
  "agentConfig.timezone": "agentConfig.reactAgentTitle",
  "agentConfig.maxIters": "agentConfig.reactAgentTitle",
  "agentConfig.maxInputLength": "agentConfig.reactAgentTitle",
  "agentConfig.contextCompactTitle": "agentConfig.lightContextTitle",
  "agentConfig.toolResultCompactTitle": "agentConfig.lightContextTitle",
  "agentConfig.memorySummaryTitle": "agentConfig.remeLightMemoryTitle",
  "agentConfig.memoryAutoRecordTitle": "agentConfig.remeLightMemoryTitle",
  "agentConfig.rerankerTitle": "agentConfig.remeLightMemoryTitle",
  "security.sandboxEnabled": "security.toolGuardTitle",
  "security.guardedTools": "security.toolGuardTitle",
  "security.deniedTools": "security.toolGuardTitle",
};
