import type { TFunction } from "i18next";
import type { HealthCheckItem } from "../api/client";
import { RESERVED_SCAN_ITEM_IDS } from "./fixRisk";
import { getString, type HealthCheckRecord } from "./scanUi";

type DetailPattern = {
  test: RegExp;
  key: string;
};

/** Placeholder checks — hide from the health-check table. */
export const HIDDEN_PLACEHOLDER_ITEM_IDS = new Set([
  "web-authentication",
  ...RESERVED_SCAN_ITEM_IDS,
]);

/** Collapsed under “environment info” when viewing all items. */
export const ENVIRONMENT_INFO_ITEM_IDS = new Set([
  "python-version",
  "qwenpaw-version",
  "platform",
  "sqlite-library",
]);

const DETAIL_PATTERNS: DetailPattern[] = [
  { test: /index\.html missing/i, key: "indexHtmlMissing" },
  { test: /bot_token is empty/i, key: "channelTokenEmpty" },
  { test: /client_id\/client_secret incomplete/i, key: "channelCredentialsIncomplete" },
  { test: /app_id\/app_secret incomplete/i, key: "channelCredentialsIncomplete" },
  { test: /app_id\/client_secret incomplete/i, key: "channelCredentialsIncomplete" },
  { test: /tool_guard\.enabled is false/i, key: "toolGuardOff" },
  { test: /skill_scanner\.mode is off/i, key: "skillScannerOff" },
  { test: /file_guard\.enabled is false/i, key: "fileGuardOff" },
  { test: /below 0\.5 GiB free/i, key: "diskSpaceLow" },
  { test: /not found on PATH/i, key: "commandNotOnPath" },
  { test: /workspace_dir is not a directory/i, key: "workspaceMissing" },
  { test: /missing agent\.json/i, key: "agentJsonMissing" },
  { test: /no unknown root config keys/i, key: "noUnknownConfigKeys" },
  { test: /unreachable/i, key: "modelUnreachable" },
  { test: /API key is required/i, key: "apiKeyMissing" },
  { test: /base_url is not set/i, key: "baseUrlMissing" },
  { test: /provider not found/i, key: "providerNotFound" },
  { test: /discord enabled/i, key: "channelCredentialsIncomplete" },
  { test: /telegram enabled/i, key: "channelTokenEmpty" },
  { test: /feishu enabled/i, key: "channelCredentialsIncomplete" },
  { test: /dingtalk enabled/i, key: "channelCredentialsIncomplete" },
];

const GUIDANCE_PATTERNS: DetailPattern[] = [
  { test: /Fix the root config\.json/i, key: "fixRootConfig" },
  { test: /Complete credentials for enabled channels/i, key: "completeChannelCredentials" },
  { test: /Build console\/ or run a confirmed rebuild/i, key: "rebuildConsole" },
  { test: /Create or initialize the QwenPaw working directory/i, key: "createWorkingDir" },
  { test: /Free disk space/i, key: "freeDiskSpace" },
  { test: /Review disabled security controls/i, key: "reviewSecurityControls" },
  { test: /Configure embedding credentials/i, key: "configureEmbedding" },
  { test: /Fix provider\/model configuration/i, key: "fixProviderModel" },
  { test: /Use the same host\/port as the running server/i, key: "matchApiHost" },
  { test: /Fix filesystem permissions/i, key: "fixPermissions" },
  { test: /Reconcile enabled skills/i, key: "reconcileSkills" },
  { test: /Review obsolete config/i, key: "reviewObsoleteConfig" },
];

function pickPatternKey(
  text: string,
  patterns: DetailPattern[],
): string | null {
  const hit = patterns.find((pattern) => pattern.test.test(text));
  return hit?.key ?? null;
}

function looksLikeEnglishTechnical(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) {
    return false;
  }
  const asciiLetters = (trimmed.match(/[A-Za-z]/g) ?? []).length;
  return asciiLetters / trimmed.length > 0.55;
}

export function isVisibleCheckItem(item: HealthCheckItem): boolean {
  if (HIDDEN_PLACEHOLDER_ITEM_IDS.has(item.id)) {
    return false;
  }
  if (item.deep_only && item.status === "skipped") {
    return false;
  }
  return true;
}

export function isIssueItem(item: HealthCheckItem): boolean {
  return item.status === "risk" || item.status === "suggestion";
}

export function formatDetailSummary(
  record: HealthCheckRecord | HealthCheckItem,
  t: TFunction,
): string {
  const itemId = getString(record, "id");
  const status = getString(record, "status");
  const detail = getString(record, "detail");

  if (status === "ok") {
    const okKey = `security.healthCheck.details.${itemId}.ok`;
    const translated = t(okKey, {
      defaultValue: "",
      value: detail,
    });
    if (translated) {
      return translated;
    }
  }

  const patternKey = pickPatternKey(detail, DETAIL_PATTERNS);
  if (patternKey) {
    return t(`security.healthCheck.details.patterns.${patternKey}`, {
      defaultValue: "",
      detail,
    });
  }

  const issueKey = `security.healthCheck.details.${itemId}.issue`;
  const issueText = t(issueKey, { defaultValue: "", detail });
  if (issueText) {
    return issueText;
  }

  if (!detail) {
    return t("security.healthCheck.details.fallbackEmpty");
  }

  if (looksLikeEnglishTechnical(detail)) {
    return t("security.healthCheck.details.fallback");
  }

  return detail;
}

export function formatGuidance(
  record: HealthCheckRecord | HealthCheckItem,
  t: TFunction,
): string {
  const status = getString(record, "status");
  if (status === "ok") {
    return "—";
  }

  const risk = getString(record, "risk");
  const recommendation = getString(record, "recommendation");
  const combined = [risk, recommendation].filter(Boolean).join("\n");
  const itemId = getString(record, "id");

  const itemKey = `security.healthCheck.guidance.${itemId}`;
  const itemGuidance = t(itemKey, { defaultValue: "" });
  if (itemGuidance) {
    return itemGuidance;
  }

  const patternKey = pickPatternKey(combined, GUIDANCE_PATTERNS);
  if (patternKey) {
    return t(`security.healthCheck.guidance.patterns.${patternKey}`, {
      defaultValue: "",
    });
  }

  if (combined && !looksLikeEnglishTechnical(combined)) {
    return combined;
  }

  if (status === "risk" || status === "suggestion") {
    return t("security.healthCheck.guidance.manualFallback");
  }

  return "—";
}

export function statusTagColor(status: string): string {
  switch (status) {
    case "ok":
      return "green";
    case "risk":
      return "red";
    case "suggestion":
      return "orange";
    default:
      return "default";
  }
}
