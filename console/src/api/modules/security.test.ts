import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { securityApi } from "./security";
import type { ToolGuardConfig, SkillScannerConfig } from "./security";
import { request } from "../request";

describe("securityApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getToolGuard calls GET /config/security/tool-guard", async () => {
    const config: ToolGuardConfig = {
      enabled: true,
      guarded_tools: null,
      denied_tools: [],
      custom_rules: [],
      disabled_rules: [],
      auto_denied_rules: [],
      shell_evasion_checks: {},
    };
    vi.mocked(request).mockResolvedValue(config);
    const result = await securityApi.getToolGuard();
    expect(request).toHaveBeenCalledWith("/config/security/tool-guard");
    expect(result).toEqual(config);
  });

  it("updateToolGuard sends PUT with config body", async () => {
    const config: ToolGuardConfig = {
      enabled: false,
      guarded_tools: ["shell"],
      denied_tools: ["rm"],
      custom_rules: [],
      disabled_rules: ["rule-1"],
      auto_denied_rules: ["dangerous-cmd"],
      shell_evasion_checks: { bash: true },
    };
    vi.mocked(request).mockResolvedValue(config);
    const result = await securityApi.updateToolGuard(config);
    expect(request).toHaveBeenCalledWith("/config/security/tool-guard", {
      method: "PUT",
      body: JSON.stringify(config),
    });
    expect(result).toEqual(config);
  });

  it("getBuiltinRules calls GET /config/security/tool-guard/builtin-rules", async () => {
    const rules = [
      {
        id: "r1",
        tools: [],
        params: [],
        category: "security",
        severity: "high",
        patterns: [],
        exclude_patterns: [],
        description: "test",
        remediation: "fix",
      },
    ];
    vi.mocked(request).mockResolvedValue(rules);
    const result = await securityApi.getBuiltinRules();
    expect(request).toHaveBeenCalledWith(
      "/config/security/tool-guard/builtin-rules",
    );
    expect(result).toEqual(rules);
  });

  it("updateFileGuard sends PUT with body", async () => {
    const body = { enabled: true, paths: ["/secret"] };
    vi.mocked(request).mockResolvedValue({ enabled: true, paths: ["/secret"] });
    const result = await securityApi.updateFileGuard(body);
    expect(request).toHaveBeenCalledWith("/config/security/file-guard", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    expect(result).toEqual({ enabled: true, paths: ["/secret"] });
  });

  it("getSkillScanner calls GET /config/security/skill-scanner", async () => {
    const config: SkillScannerConfig = {
      mode: "block",
      timeout: 30,
      whitelist: [],
    };
    vi.mocked(request).mockResolvedValue(config);
    const result = await securityApi.getSkillScanner();
    expect(request).toHaveBeenCalledWith("/config/security/skill-scanner");
    expect(result).toEqual(config);
  });

  it("clearBlockedHistory sends DELETE to blocked-history endpoint", async () => {
    vi.mocked(request).mockResolvedValue({ cleared: true });
    const result = await securityApi.clearBlockedHistory();
    expect(request).toHaveBeenCalledWith(
      "/config/security/skill-scanner/blocked-history",
      { method: "DELETE" },
    );
    expect(result).toEqual({ cleared: true });
  });

  it("addToWhitelist sends POST with skill_name and content_hash", async () => {
    vi.mocked(request).mockResolvedValue({
      whitelisted: true,
      skill_name: "my-skill",
    });
    const result = await securityApi.addToWhitelist("my-skill", "abc123");
    expect(request).toHaveBeenCalledWith(
      "/config/security/skill-scanner/whitelist",
      {
        method: "POST",
        body: JSON.stringify({
          skill_name: "my-skill",
          content_hash: "abc123",
        }),
      },
    );
    expect(result).toEqual({ whitelisted: true, skill_name: "my-skill" });
  });

  it("removeFromWhitelist sends DELETE with encoded skill name", async () => {
    vi.mocked(request).mockResolvedValue({
      removed: true,
      skill_name: "my/skill",
    });
    const result = await securityApi.removeFromWhitelist("my/skill");
    expect(request).toHaveBeenCalledWith(
      `/config/security/skill-scanner/whitelist/${encodeURIComponent(
        "my/skill",
      )}`,
      { method: "DELETE" },
    );
    expect(result).toEqual({ removed: true, skill_name: "my/skill" });
  });
});
