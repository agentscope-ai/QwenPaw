// @vitest-environment jsdom
/**
 * Sidebar.test.tsx — regression for A#84552933 (missing apps nav entry)
 *
 * The "Apps" (marketplace/apps) navigation entry must be present in the
 * sidebar's agent-scoped menu. We test the builtinMenu data directly
 * because the full Sidebar component has heavy dependencies.
 *
 * Strategy:
 *   1. Verify BUILTIN_MENU contains an entry with id "core.marketplace"
 *      (the apps/marketplace navigation entry).
 *   2. Verify its location is "primary.agentScoped" so it shows in sidebar.
 *   3. Verify its label resolves to a non-empty string (i18n).
 *   4. Verify it has a route defined for navigation.
 */
import { describe, expect, it, vi } from "vitest";

// Mock heavy dependencies before importing builtinMenu
vi.mock("@agentscope-ai/icons", () => {
  const stub = () => null;
  return {
    SparkAgentLine: stub,
    SparkBarChartLine: stub,
    SparkBrowseLine: stub,
    SparkDataLine: stub,
    SparkDateLine: stub,
    SparkDebugLine: stub,
    SparkEmailLine: stub,
    SparkInternetLine: stub,
    SparkMagicWandLine: stub,
    SparkMcpMcpLine: stub,
    SparkMicLine: stub,
    SparkModePlazaLine: stub,
    SparkModifyLine: stub,
    SparkMyApplicationLine: stub,
    SparkOtherLine: stub,
    SparkSaveLine: stub,
    SparkScanLine: stub,
    SparkToolLine: stub,
    SparkUserGroupLine: stub,
    SparkVoiceChat01Line: stub,
    SparkWifiLine: stub,
  };
});
vi.mock("lucide-react", () => {
  const stub = () => null;
  return { GitBranch: stub, Files: stub };
});
vi.mock("i18next", () => ({
  default: { t: (key: string, fallback?: string) => fallback ?? key },
  t: (key: string, fallback?: string) => fallback ?? key,
}));
vi.mock("@/plugins/registry/store", () => ({
  menuRegistry: {
    addBuiltIn: vi.fn(),
    addBuiltin: vi.fn(),
  },
}));

import { BUILTIN_MENU } from "./registry/builtinMenu";

describe("Sidebar navigation — A#84552933 应用导航入口", () => {
  it("contains the marketplace/apps entry in agent-scoped menu", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.marketplace",
    );
    expect(appsEntry).toBeDefined();
    expect(appsEntry!.location).toBe("primary.agentScoped");
  });

  it("marketplace entry has a valid route for navigation", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.marketplace",
    );
    expect(appsEntry).toBeDefined();
    expect(appsEntry!.route).toBeTruthy();
    expect(appsEntry!.route).toBe("core.marketplace");
  });

  it("marketplace label resolves to a non-empty string", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.marketplace",
    );
    expect(appsEntry).toBeDefined();
    // label is a function () => string (navLabel pattern)
    const label =
      typeof appsEntry!.label === "function"
        ? (appsEntry!.label as () => string)()
        : String(appsEntry!.label);
    expect(label).toBeTruthy();
    expect(label.length).toBeGreaterThan(0);
  });

  it("marketplace entry has an icon defined", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.marketplace",
    );
    expect(appsEntry).toBeDefined();
    expect(appsEntry!.icon).toBeDefined();
  });

  it("agent-scoped menu has at least one entry for core navigation", () => {
    const agentScoped = BUILTIN_MENU.filter(
      (item) => item.location === "primary.agentScoped",
    );
    // Must have inbox, marketplace, and workspace-group at minimum
    const ids = agentScoped.map((item) => item.id);
    expect(ids).toContain("core.inbox");
    expect(ids).toContain("core.marketplace");
  });
});
