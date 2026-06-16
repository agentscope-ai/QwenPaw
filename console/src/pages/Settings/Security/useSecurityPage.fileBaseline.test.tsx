import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { useSecurityPage } from "./useSecurityPage";

vi.mock("./useToolGuard", () => ({
  useToolGuard: () => ({
    config: {},
    customRules: [],
    builtinRules: [],
    enabled: false,
    setEnabled: vi.fn(),
    mergedRules: [],
    rulesIntegrity: null,
    shellEvasionChecks: [],
    toggleShellEvasionCheck: vi.fn(),
    repairingRulesIntegrity: false,
    repairRulesIntegrity: vi.fn(),
    loading: false,
    error: null,
    fetchAll: vi.fn(),
  }),
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Form: antd.Form,
  };
});

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function createWrapper(initialEntry: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
    );
  };
}

describe("useSecurityPage persona deep link", () => {
  it("reads integrityProtection tab from search params", () => {
    const { result } = renderHook(() => useSecurityPage(), {
      wrapper: createWrapper("/security?tab=integrityProtection"),
    });
    expect(result.current.activeTab).toBe("integrityProtection");
  });

  it("defaults to toolGuard tab without query params", () => {
    const { result } = renderHook(() => useSecurityPage(), {
      wrapper: createWrapper("/security"),
    });
    expect(result.current.activeTab).toBe("toolGuard");
  });
});
