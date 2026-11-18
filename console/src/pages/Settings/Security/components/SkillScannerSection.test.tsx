// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SkillScannerSection } from "./SkillScannerSection";

const { removeBlockedEntry, addToWhitelist } = vi.hoisted(() => ({
  removeBlockedEntry: vi.fn().mockResolvedValue(true),
  addToWhitelist: vi.fn().mockResolvedValue(true),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@agentscope-ai/design", async () => await vi.importActual("antd"));
vi.mock("../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { success: vi.fn(), error: vi.fn() } }),
}));
vi.mock("../useSkillScanner", () => ({
  useSkillScanner: () => ({
    config: { mode: "block", timeout: 60 },
    blockedHistory: Array.from({ length: 11 }, (_, index) => ({
      skill_name: `skill-${index}`,
      content_hash: `hash-${index}`,
      action: "blocked",
      blocked_at: "2026-09-25T00:00:00Z",
      findings: [],
    })),
    whitelist: [],
    loading: false,
    updateConfig: vi.fn(),
    addToWhitelist,
    removeFromWhitelist: vi.fn(),
    removeBlockedEntry,
    clearBlockedHistory: vi.fn(),
  }),
}));

describe("SkillScannerSection pagination", () => {
  it("uses the original record index for removal and allowing on the second page", async () => {
    render(<SkillScannerSection />);
    expect(screen.queryByText("skill-10")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("2"));
    expect(await screen.findByText("skill-10")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "security.skillScanner.scanAlerts.remove",
      }),
    );
    expect(removeBlockedEntry).toHaveBeenLastCalledWith(10);
    fireEvent.click(
      screen.getByRole("button", {
        name: "security.skillScanner.scanAlerts.allowSkill",
      }),
    );
    await waitFor(() =>
      expect(addToWhitelist).toHaveBeenCalledWith("skill-10", "hash-10"),
    );
    expect(removeBlockedEntry).toHaveBeenLastCalledWith(10);
  });
});
