import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type {
  ToolGuardConfig,
  ToolGuardRule,
} from "../../../api/modules/security";

const hoisted = vi.hoisted(() => {
  const apiMocks = {
    getToolGuard: vi.fn(),
    getBuiltinRules: vi.fn(),
  };
  return { apiMocks };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

import { useToolGuard } from "./useToolGuard";

const { apiMocks } = hoisted;

function makeConfig(overrides: Partial<ToolGuardConfig> = {}): ToolGuardConfig {
  return {
    enabled: true,
    guarded_tools: ["execute_shell_command"],
    denied_tools: ["rm"],
    custom_rules: [],
    disabled_rules: [],
    auto_denied_rules: [],
    shell_evasion_checks: {},
    ...overrides,
  };
}

function makeRule(overrides: Partial<ToolGuardRule> = {}): ToolGuardRule {
  return {
    id: "r1",
    tools: ["execute_shell_command"],
    params: [],
    category: "command_injection",
    severity: "HIGH",
    patterns: ["rm -rf"],
    exclude_patterns: [],
    description: "",
    remediation: "",
    ...overrides,
  };
}

describe("useToolGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getToolGuard.mockReset();
    apiMocks.getBuiltinRules.mockReset();
  });

  it("mounts and loads config/builtinRules, sets disabledRules/autoDenyRules/customRules, loading false", async () => {
    const cfg = makeConfig({
      enabled: false,
      custom_rules: [makeRule({ id: "custom1" })],
      disabled_rules: ["d1"],
      auto_denied_rules: ["a1"],
      shell_evasion_checks: { check_a: true },
    });
    apiMocks.getToolGuard.mockResolvedValue(cfg);
    apiMocks.getBuiltinRules.mockResolvedValue([makeRule({ id: "builtin1" })]);

    const { result } = renderHook(() => useToolGuard());

    expect(result.current.loading).toBe(true);
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.config).toEqual(cfg);
    expect(result.current.enabled).toBe(false);
    expect(result.current.builtinRules).toHaveLength(1);
    expect(result.current.builtinRules[0].id).toBe("builtin1");
    expect(result.current.customRules).toHaveLength(1);
    expect(result.current.customRules[0].id).toBe("custom1");
    expect(result.current.disabledRules.has("d1")).toBe(true);
    expect(result.current.autoDenyRules.has("a1")).toBe(true);
    expect(result.current.shellEvasionChecks).toEqual({ check_a: true });
    expect(result.current.error).toBeNull();
  });

  it("fetchAll failure sets error and loading false", async () => {
    apiMocks.getToolGuard.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useToolGuard());

    await waitFor(() => {
      expect(result.current.error).toBe("network down");
    });
    expect(result.current.loading).toBe(false);
  });

  it("toggleRule removes from disabledRules when currentlyDisabled=true, adds when false", async () => {
    apiMocks.getToolGuard.mockResolvedValue(
      makeConfig({ disabled_rules: ["r1"] }),
    );
    apiMocks.getBuiltinRules.mockResolvedValue([]);

    const { result } = renderHook(() => useToolGuard());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.disabledRules.has("r1")).toBe(true);

    act(() => {
      result.current.toggleRule("r1", true);
    });
    expect(result.current.disabledRules.has("r1")).toBe(false);

    act(() => {
      result.current.toggleRule("r2", false);
    });
    expect(result.current.disabledRules.has("r2")).toBe(true);
  });

  it("deleteCustomRule removes from customRules, disabledRules and autoDenyRules", async () => {
    apiMocks.getToolGuard.mockResolvedValue(
      makeConfig({
        custom_rules: [makeRule({ id: "c1" }), makeRule({ id: "c2" })],
        disabled_rules: ["c1"],
        auto_denied_rules: ["c1"],
      }),
    );
    apiMocks.getBuiltinRules.mockResolvedValue([]);

    const { result } = renderHook(() => useToolGuard());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.customRules).toHaveLength(2);
    expect(result.current.disabledRules.has("c1")).toBe(true);
    expect(result.current.autoDenyRules.has("c1")).toBe(true);

    act(() => {
      result.current.deleteCustomRule("c1");
    });

    expect(result.current.customRules).toHaveLength(1);
    expect(result.current.customRules[0].id).toBe("c2");
    expect(result.current.disabledRules.has("c1")).toBe(false);
    expect(result.current.autoDenyRules.has("c1")).toBe(false);
  });

  it("toggleShellEvasionCheck sets the check value", async () => {
    apiMocks.getToolGuard.mockResolvedValue(makeConfig());
    apiMocks.getBuiltinRules.mockResolvedValue([]);

    const { result } = renderHook(() => useToolGuard());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.shellEvasionChecks).toEqual({});

    act(() => {
      result.current.toggleShellEvasionCheck("quote_check", true);
    });
    expect(result.current.shellEvasionChecks).toEqual({ quote_check: true });

    act(() => {
      result.current.toggleShellEvasionCheck("quote_check", false);
    });
    expect(result.current.shellEvasionChecks).toEqual({ quote_check: false });
  });

  it("buildSaveBody returns array form of Sets and null guarded_tools when config.guarded_tools is null", async () => {
    apiMocks.getToolGuard.mockResolvedValue(
      makeConfig({
        enabled: true,
        guarded_tools: null,
        disabled_rules: ["d1", "d2"],
        auto_denied_rules: ["a1"],
        shell_evasion_checks: { check_a: true },
        custom_rules: [makeRule({ id: "c1" })],
      }),
    );
    apiMocks.getBuiltinRules.mockResolvedValue([]);

    const { result } = renderHook(() => useToolGuard());
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const body = result.current.buildSaveBody();

    expect(body).toEqual({
      enabled: true,
      guarded_tools: null,
      denied_tools: ["rm"],
      custom_rules: [expect.objectContaining({ id: "c1" })],
      disabled_rules: ["d1", "d2"],
      auto_denied_rules: ["a1"],
      shell_evasion_checks: { check_a: true },
    });
    expect(Array.isArray(body.disabled_rules)).toBe(true);
    expect(Array.isArray(body.auto_denied_rules)).toBe(true);
  });
});
