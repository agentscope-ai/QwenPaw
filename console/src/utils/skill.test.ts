/**
 * Skill source / automation / install-origin helpers used across the
 * skill pool UI. Pure presentation logic; defects here mislabel skill
 * state (e.g. show "synced" for a stale builtin).
 */
import { describe, it, expect } from "vitest";
import {
  getSkillDisplaySource,
  isSkillBuiltin,
  getPoolSkillAutomationState,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  INSTALLED_FROM_LABELS,
  deriveInstalledFromLabel,
} from "./skill";

describe("getSkillDisplaySource", () => {
  it("maps builtin to builtin", () => {
    expect(getSkillDisplaySource("builtin")).toBe("builtin");
  });

  it("maps any other source to customized", () => {
    expect(getSkillDisplaySource("custom")).toBe("customized");
    expect(getSkillDisplaySource("")).toBe("customized");
  });
});

describe("isSkillBuiltin", () => {
  it("recognizes the plain builtin source", () => {
    expect(isSkillBuiltin("builtin")).toBe(true);
  });

  it("recognizes prefixed builtin sources", () => {
    expect(isSkillBuiltin("builtin:browser")).toBe(true);
  });

  it("recognizes the system source as builtin", () => {
    expect(isSkillBuiltin("system")).toBe(true);
  });

  it("treats custom sources as non-builtin", () => {
    expect(isSkillBuiltin("custom")).toBe(false);
  });

  it("treats undefined as non-builtin", () => {
    expect(isSkillBuiltin(undefined)).toBe(false);
  });
});

describe("getPoolSkillAutomationState", () => {
  it("customized skill with sync off is off", () => {
    expect(
      getPoolSkillAutomationState({
        source: "custom",
        auto_sync: false,
        auto_update: true,
      }),
    ).toBe("off");
  });

  it("customized skill ignores auto_update and follows auto_sync", () => {
    expect(
      getPoolSkillAutomationState({
        source: "custom",
        auto_sync: true,
        auto_update: false,
      }),
    ).toBe("on");
  });

  it("builtin with both flags aligned on is on", () => {
    expect(
      getPoolSkillAutomationState({
        source: "builtin",
        auto_sync: true,
        auto_update: true,
      }),
    ).toBe("on");
  });

  it("builtin with both flags aligned off is off", () => {
    expect(
      getPoolSkillAutomationState({
        source: "builtin",
        auto_sync: false,
        auto_update: false,
      }),
    ).toBe("off");
  });

  it("builtin with divergent flags is mixed", () => {
    expect(
      getPoolSkillAutomationState({
        source: "builtin",
        auto_sync: true,
        auto_update: false,
      }),
    ).toBe("mixed");
    expect(
      getPoolSkillAutomationState({
        source: "builtin",
        auto_sync: false,
        auto_update: true,
      }),
    ).toBe("mixed");
  });

  it("treats missing flags as false", () => {
    expect(getPoolSkillAutomationState({ source: "builtin" })).toBe("off");
  });
});

describe("getPoolBuiltinStatusLabel", () => {
  // t stub returns the key so assertions read the translation key used
  const t = ((key: string) => key) as any;

  it("maps each known sync status to its translation key", () => {
    expect(getPoolBuiltinStatusLabel("synced", t)).toBe(
      "skillPool.statusUpToDate",
    );
    expect(getPoolBuiltinStatusLabel("outdated", t)).toBe(
      "skillPool.statusOutdated",
    );
    expect(getPoolBuiltinStatusLabel("not_synced", t)).toBe(
      "skillPool.statusNotSynced",
    );
    expect(getPoolBuiltinStatusLabel("conflict", t)).toBe(
      "skillPool.statusConflict",
    );
  });

  it("renders a dash for empty or unknown status", () => {
    expect(getPoolBuiltinStatusLabel("", t)).toBe("-");
    expect(getPoolBuiltinStatusLabel(undefined, t)).toBe("-");
    expect(getPoolBuiltinStatusLabel("-", t)).toBe("-");
  });
});

describe("getPoolBuiltinStatusTone", () => {
  it("maps outdated to the outdated tone", () => {
    expect(getPoolBuiltinStatusTone("outdated")).toBe("outdated");
  });

  it("maps synced to the synced tone", () => {
    expect(getPoolBuiltinStatusTone("synced")).toBe("synced");
  });

  it("uses neutral for every other status", () => {
    expect(getPoolBuiltinStatusTone("not_synced")).toBe("neutral");
    expect(getPoolBuiltinStatusTone("conflict")).toBe("neutral");
    expect(getPoolBuiltinStatusTone("")).toBe("neutral");
    expect(getPoolBuiltinStatusTone(undefined)).toBe("neutral");
  });
});

describe("deriveInstalledFromLabel", () => {
  it("maps known install origins to display labels", () => {
    expect(deriveInstalledFromLabel("qwenpaw")).toBe("QwenPaw");
    expect(deriveInstalledFromLabel("skills-sh")).toBe("skills.sh");
    expect(deriveInstalledFromLabel("github")).toBe("GitHub");
  });

  it("passes through unknown origins verbatim", () => {
    expect(deriveInstalledFromLabel("some-new-hub")).toBe("some-new-hub");
  });

  it("renders an empty string for missing origin", () => {
    expect(deriveInstalledFromLabel(undefined)).toBe("");
    expect(deriveInstalledFromLabel("")).toBe("");
  });

  it("covers every documented origin key", () => {
    expect(Object.keys(INSTALLED_FROM_LABELS).sort()).toEqual(
      [
        "aliyun",
        "clawhub",
        "github",
        "lobehub",
        "modelscope",
        "qwenpaw",
        "skills-sh",
        "skillsmp",
        "url",
        "zip",
      ].sort(),
    );
  });
});
