import { describe, it, expect } from "vitest";
import { defaultCreateScope, buildPreRestoreScope, buildScope } from "./scope";

describe("defaultCreateScope", () => {
  it("returns the full-mode defaults with the provided agent ids", () => {
    const scope = defaultCreateScope(["a1", "a2"]);
    expect(scope).toEqual({
      backupMode: "full",
      selectedAgents: ["a1", "a2"],
      globalConfig: true,
      includeSkillPool: true,
      includeSecrets: false,
    });
  });

  it("echoes back the provided agent ids (no copy semantics required)", () => {
    const ids = ["x"];
    expect(defaultCreateScope(ids).selectedAgents).toBe(ids);
  });
});

describe("buildPreRestoreScope", () => {
  it("builds a name prefixed with [pre-restore] and the expected scope", () => {
    const result = buildPreRestoreScope(["a1", "a2"]);
    expect(result.name.startsWith("[pre-restore] Backup ")).toBe(true);
    expect(result.description).toBe("backup.preRestoreBackupDesc");
    expect(result.scope).toEqual({
      include_agents: true,
      include_global_config: true,
      include_secrets: false,
      include_skill_pool: true,
    });
    expect(result.agents).toEqual(["a1", "a2"]);
  });
});

describe("buildScope — full mode", () => {
  it("forces every include_* flag true and keeps the selected agents", () => {
    const { scope, agents } = buildScope("full", ["a1"], false, false, false);
    expect(scope).toEqual({
      include_agents: true,
      include_global_config: true,
      include_secrets: true,
      include_skill_pool: true,
    });
    expect(agents).toEqual(["a1"]);
  });
});

describe("buildScope — partial mode", () => {
  it("respects individual toggles and selected agents when non-empty", () => {
    const { scope, agents } = buildScope(
      "partial",
      ["a1", "a2"],
      true,
      true,
      true,
    );
    expect(scope).toEqual({
      include_agents: true,
      include_global_config: true,
      include_secrets: true,
      include_skill_pool: true,
    });
    expect(agents).toEqual(["a1", "a2"]);
  });

  it("sets include_agents=false and agents=[] when no agents selected", () => {
    const { scope, agents } = buildScope("partial", [], true, false, false);
    expect(scope).toEqual({
      include_agents: false,
      include_global_config: true,
      include_secrets: false,
      include_skill_pool: false,
    });
    expect(agents).toEqual([]);
  });
});
