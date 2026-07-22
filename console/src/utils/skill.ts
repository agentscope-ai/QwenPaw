import type { TFunction } from "i18next";
import type { SkillSyncStatus } from "../api/types";

// ─── Source / Built-in helpers ────────────────────────────────────────────────

export const getSkillDisplaySource = (source: string) =>
  source === "builtin" ? "builtin" : "customized";

export const isSkillBuiltin = (source?: string): boolean =>
  source === "builtin" ||
  (source?.startsWith("builtin:") ?? false) ||
  source === "system";

// ─── Pool sync-status helpers ─────────────────────────────────────────────────

export const getPoolBuiltinStatusLabel = (
  status: SkillSyncStatus | "" | undefined,
  t: TFunction,
) => {
  switch (status) {
    case "synced":
      return t("skillPool.statusUpToDate");
    case "outdated":
      return t("skillPool.statusOutdated");
    case "not_synced":
      return t("skillPool.statusNotSynced");
    case "conflict":
      return t("skillPool.statusConflict");
    default:
      return "-";
  }
};

export const getPoolBuiltinStatusTone = (
  status: SkillSyncStatus | "" | undefined,
) => {
  switch (status) {
    case "outdated":
      return "outdated";
    case "synced":
      return "synced";
    default:
      return "neutral";
  }
};

// ─── Install-origin helpers ────────────────────────────────────

export const INSTALLED_FROM_LABELS: Record<string, string> = {
  "skills-sh": "skills.sh",
  github: "GitHub",
  lobehub: "LobeHub",
  modelscope: "ModelScope",
  aliyun: "Aliyun",
  skillsmp: "SkillsMP",
  clawhub: "ClawHub",
  url: "URL",
  zip: "ZIP",
};

// Skills without a recorded origin (builtins, hand-created, legacy entries)
// have an empty installed_from and render as an empty string.
export const deriveInstalledFromLabel = (
  installed_from: string | undefined,
): string => {
  if (!installed_from) return "";
  return INSTALLED_FROM_LABELS[installed_from] ?? installed_from;
};
