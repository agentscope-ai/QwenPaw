/** Preset workspace-relative paths shown in the file baseline protection file list. */

export interface FileBaselinePathCandidate {
  path: string;
  labelKey: string;
  descriptionKey: string;
}

export const FILE_BASELINE_PRESET_PATHS: FileBaselinePathCandidate[] = [
  {
    path: "SOUL.md",
    labelKey: "security.integrityProtection.pathPresets.soul",
    descriptionKey: "security.integrityProtection.pathDescriptions.soul",
  },
  {
    path: "AGENTS.md",
    labelKey: "security.integrityProtection.pathPresets.agents",
    descriptionKey: "security.integrityProtection.pathDescriptions.agents",
  },
  {
    path: "PROFILE.md",
    labelKey: "security.integrityProtection.pathPresets.profile",
    descriptionKey: "security.integrityProtection.pathDescriptions.profile",
  },
  {
    path: "HEARTBEAT.md",
    labelKey: "security.integrityProtection.pathPresets.heartbeat",
    descriptionKey: "security.integrityProtection.pathDescriptions.heartbeat",
  },
];

export const FILE_BASELINE_PRESET_PATH_SET = new Set(
  FILE_BASELINE_PRESET_PATHS.map((item) => item.path),
);
