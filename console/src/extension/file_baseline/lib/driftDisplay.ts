import type { TFunction } from "i18next";

export function getFileBaselineDriftTitle(
  t: TFunction,
  provenance?: string,
): string {
  if (provenance === "startup_scan") {
    return t("security.integrityProtection.fileBaselineDriftAlertTitleStartup");
  }
  return t("security.integrityProtection.fileBaselineDriftAlertTitle");
}

export function getFileBaselineDriftBody(t: TFunction, path: string): string {
  return t("security.integrityProtection.fileBaselineDriftAlertBody", { path });
}

export function getFileBaselineProtectionChannelName(t: TFunction): string {
  return t("security.integrityProtection.fileBaselineProtectionChannel");
}
