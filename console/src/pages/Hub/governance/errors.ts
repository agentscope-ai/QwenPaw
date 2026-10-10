import type { TFunction } from "i18next";

const errorKeys: Record<string, string> = {
  "Hub request failed": "requestFailed",
  "Failed to fetch": "requestFailed",
  "NetworkError when attempting to fetch resource.": "requestFailed",
  "Load failed": "requestFailed",
  "Configuration changed; refresh before saving": "changed",
  "Policy changed; refresh before saving": "changed",
  "An API key is required for a new connection": "keyRequired",
  "Connection does not exist": "connectionMissing",
  "Connection not found": "connectionMissing",
  "Unknown member": "memberMissing",
  "Unknown budget member": "memberMissing",
  "User not found": "memberMissing",
  "Budget timezone is fixed after first use": "timezoneFixed",
  "Choose an enabled all-member default": "defaultUnavailable",
  "Model is unavailable or not authorized": "modelUnavailable",
  "Batch already created; codes cannot replay": "batchExists",
  "Unknown model grant": "grantMissing",
  "Account is disabled": "accountDisabled",
  "Model budget bounds are unverified": "boundsUnverified",
  "Model provider connection is disabled": "connectionDisabled",
  hub_model_unavailable: "modelUnavailable",
  hub_budget_exceeded: "budgetExceeded",
  "Only ordinary member passwords can reset": "passwordMemberOnly",
};

export function governanceErrorMessage(error: unknown, t: TFunction): string {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  if (detail === "hub_model_discovery_failed") {
    return t("hub.governance.models.discoveryFailed");
  }
  const key = errorKeys[detail];
  return key
    ? t(`hub.governance.errors.${key}`)
    : detail || t("hub.governance.errors.requestFailed");
}
