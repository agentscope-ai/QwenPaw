/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useSkillScanner } from "./useSkillScanner";
import type {
  SkillScannerConfig,
  BlockedSkillRecord,
} from "../../../api/modules/security";

// ---------------------------------------------------------------------------
// Skill scanner warning display — regression for A#80732993
// (Skill scanner alert logic: blocked vs warned states, allowlist management,
//  and history clearing. Only logic branches are tested, not CSS overflow.)
// ---------------------------------------------------------------------------

const {
  mockGetSkillScanner,
  mockGetBlockedHistory,
  mockUpdateSkillScanner,
  mockAddToWhitelist,
  mockRemoveFromWhitelist,
  mockRemoveBlockedEntry,
  mockClearBlockedHistory,
} = vi.hoisted(() => ({
  mockGetSkillScanner: vi.fn(),
  mockGetBlockedHistory: vi.fn(),
  mockUpdateSkillScanner: vi.fn(),
  mockAddToWhitelist: vi.fn(),
  mockRemoveFromWhitelist: vi.fn(),
  mockRemoveBlockedEntry: vi.fn(),
  mockClearBlockedHistory: vi.fn(),
}));

vi.mock("../../../api", () => ({
  default: {
    getSkillScanner: mockGetSkillScanner,
    getBlockedHistory: mockGetBlockedHistory,
    updateSkillScanner: mockUpdateSkillScanner,
    addToWhitelist: mockAddToWhitelist,
    removeFromWhitelist: mockRemoveFromWhitelist,
    removeBlockedEntry: mockRemoveBlockedEntry,
    clearBlockedHistory: mockClearBlockedHistory,
  },
}));

const defaultConfig: SkillScannerConfig = {
  mode: "block",
  timeout: 30,
  whitelist: [
    {
      skill_name: "safe-skill",
      content_hash: "abc123",
      added_at: "2026-01-01T00:00:00Z",
    },
  ],
};

const blockedHistory: BlockedSkillRecord[] = [
  {
    skill_name: "dangerous-skill",
    content_hash: "def456",
    action: "blocked",
    blocked_at: "2026-01-15T10:00:00Z",
    findings: [
      {
        severity: "high",
        title: "Unsafe eval",
        description: "Uses eval()",
        file_path: "index.js",
        line_number: 42,
        rule_id: "no-eval",
      },
    ],
    max_severity: "high",
  },
  {
    skill_name: "suspicious-skill",
    content_hash: "ghi789",
    action: "warned",
    blocked_at: "2026-01-16T12:00:00Z",
    findings: [],
    max_severity: "",
  },
];

describe("useSkillScanner (A#80732993)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSkillScanner.mockResolvedValue(defaultConfig);
    mockGetBlockedHistory.mockResolvedValue(blockedHistory);
  });

  it("loads config and blocked history on mount", async () => {
    const { result } = renderHook(() => useSkillScanner());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.config).toEqual(defaultConfig);
    expect(result.current.blockedHistory).toHaveLength(2);
    expect(result.current.whitelist).toHaveLength(1);
  });

  it("distinguishes blocked vs warned actions in history", async () => {
    const { result } = renderHook(() => useSkillScanner());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const blocked = result.current.blockedHistory.find(
      (r) => r.skill_name === "dangerous-skill",
    );
    const warned = result.current.blockedHistory.find(
      (r) => r.skill_name === "suspicious-skill",
    );

    expect(blocked?.action).toBe("blocked");
    expect(warned?.action).toBe("warned");
    // blocked entry has findings
    expect(blocked?.findings).toHaveLength(1);
    expect(blocked?.findings[0].title).toBe("Unsafe eval");
    // warned entry has no findings
    expect(warned?.findings).toHaveLength(0);
  });

  it("updates config mode from block to warn", async () => {
    const updatedConfig = { ...defaultConfig, mode: "warn" as const };
    mockUpdateSkillScanner.mockResolvedValue(updatedConfig);

    const { result } = renderHook(() => useSkillScanner());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean | undefined = false;
    await act(async () => {
      success = await result.current.updateConfig({ mode: "warn" });
    });

    expect(success).toBe(true);
    expect(mockUpdateSkillScanner).toHaveBeenCalledWith({
      ...defaultConfig,
      mode: "warn",
    });
    expect(result.current.config?.mode).toBe("warn");
  });

  it("adds a skill to whitelist and refreshes data", async () => {
    mockAddToWhitelist.mockResolvedValue(undefined);
    // After addToWhitelist, fetchAll is called again
    mockGetSkillScanner.mockResolvedValueOnce(defaultConfig);
    mockGetBlockedHistory.mockResolvedValueOnce(blockedHistory);

    const { result } = renderHook(() => useSkillScanner());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success = false;
    await act(async () => {
      success = await result.current.addToWhitelist(
        "dangerous-skill",
        "def456",
      );
    });

    expect(success).toBe(true);
    expect(mockAddToWhitelist).toHaveBeenCalledWith(
      "dangerous-skill",
      "def456",
    );
  });

  it("clears blocked history", async () => {
    mockClearBlockedHistory.mockResolvedValue(undefined);

    const { result } = renderHook(() => useSkillScanner());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success = false;
    await act(async () => {
      success = await result.current.clearBlockedHistory();
    });

    expect(success).toBe(true);
    expect(mockClearBlockedHistory).toHaveBeenCalled();
    expect(result.current.blockedHistory).toEqual([]);
  });

  it("returns false when updateConfig fails", async () => {
    mockUpdateSkillScanner.mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useSkillScanner());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean | undefined = true;
    await act(async () => {
      success = await result.current.updateConfig({ timeout: 60 });
    });

    expect(success).toBe(false);
    // Config should remain unchanged
    expect(result.current.config?.timeout).toBe(30);
  });

  it("handles initial load failure gracefully", async () => {
    mockGetSkillScanner.mockRejectedValue(new Error("Server error"));
    mockGetBlockedHistory.mockRejectedValue(new Error("Server error"));

    const { result } = renderHook(() => useSkillScanner());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toContain("Server error");
    expect(result.current.config).toBeNull();
    expect(result.current.blockedHistory).toEqual([]);
  });
});
