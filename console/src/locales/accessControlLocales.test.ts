import { describe, expect, it } from "vitest";

import en from "./en.json";
import zh from "./zh.json";

// Every translation key the access-control drawers render (whitelist /
// blacklist table and the pending-approvals table).
const requiredPaths = [
  "channels.actions",
  "channels.addUser",
  "channels.addUserPlaceholder",
  "channels.approve",
  "channels.approveSuccess",
  "channels.batchApprove",
  "channels.batchApproveConfirm",
  "channels.batchDeny",
  "channels.batchDenyConfirm",
  "channels.batchDismiss",
  "channels.batchDismissConfirm",
  "channels.batchRemove",
  "channels.batchRemoveConfirm",
  "channels.batchSuccess",
  "channels.blacklist",
  "channels.channel",
  "channels.deny",
  "channels.denySuccess",
  "channels.dismiss",
  "channels.dismissSuccess",
  "channels.filterByChannel",
  "channels.firstMessage",
  "channels.manageAccessControl",
  "channels.noBlacklistUsers",
  "channels.noPendingApprovals",
  "channels.noWhitelistUsers",
  "channels.operationFailed",
  "channels.pendingApprovals",
  "channels.remark",
  "channels.remarkPlaceholder",
  "channels.selectedCount",
  "channels.time",
  "channels.userAdded",
  "channels.userId",
  "channels.userRemoved",
  "channels.username",
  "channels.usernamePlaceholder",
  "channels.whitelist",
] as const;

function getTranslation(locale: Record<string, unknown>, path: string): string {
  const value = path.split(".").reduce<unknown>((current, key) => {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    return (current as Record<string, unknown>)[key];
  }, locale);
  return typeof value === "string" ? value : "";
}

function interpolationKeys(value: string): string[] {
  return Array.from(value.matchAll(/{{(\w+)}}/g), (match) => match[1]).sort();
}

describe("access control locale coverage", () => {
  it.each(requiredPaths)("provides Chinese text for %s", (path) => {
    const translation = getTranslation(zh, path);

    expect(translation).not.toBe("");
    expect(translation).toMatch(/[\u3400-\u9fff]/u);
  });

  it.each(requiredPaths)("keeps interpolation parity for %s", (path) => {
    expect(interpolationKeys(getTranslation(zh, path))).toEqual(
      interpolationKeys(getTranslation(en, path)),
    );
  });
});
