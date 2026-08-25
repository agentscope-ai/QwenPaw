/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Hoisted mock refs (shared across vi.mock factories)
// ---------------------------------------------------------------------------
const hoisted = vi.hoisted(() => {
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  };
  const apiMocks = {
    listSkillPoolSkills: vi.fn(),
    listSkillWorkspaces: vi.fn(),
    getPoolBuiltinNotice: vi.fn(),
    refreshSkillPool: vi.fn(),
    listPoolBuiltinSources: vi.fn(),
    getPoolSkill: vi.fn(),
    saveSkillPoolSkill: vi.fn(),
    createSkillPoolSkill: vi.fn(),
    deleteSkillPoolSkill: vi.fn(),
    uploadSkillPoolZip: vi.fn(),
    importPoolSkillFromHub: vi.fn(),
    downloadSkillPoolSkill: vi.fn(),
    updatePoolSkillAutoUpdate: vi.fn(),
    updatePoolBuiltin: vi.fn(),
    importSelectedPoolBuiltins: vi.fn(),
    updatePoolSkillTags: vi.fn(),
    getBlockedHistory: vi.fn(),
    getSkillScanner: vi.fn(),
    batchDeletePoolSkills: vi.fn(),
  };
  const modalConfirmMock = vi.fn();
  const invalidateSkillCacheMock = vi.fn();
  const parseErrorDetailMock = vi.fn();
  const handleScanErrorMock = vi.fn().mockReturnValue(false);
  const checkScanWarningsMock = vi.fn().mockResolvedValue(undefined);
  const stableT = (k: string) => k;
  const formMock = {
    resetFields: vi.fn(),
    setFieldsValue: vi.fn(),
    validateFields: vi.fn(),
  };
  return {
    messageMock,
    apiMocks,
    modalConfirmMock,
    invalidateSkillCacheMock,
    parseErrorDetailMock,
    handleScanErrorMock,
    checkScanWarningsMock,
    stableT,
    formMock,
  };
});

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const passThrough = ({ children, ...props }: Record<string, unknown>) =>
    React.createElement("div", props, children as React.ReactNode);
  const Modal = Object.assign(passThrough, {
    confirm: hoisted.modalConfirmMock,
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  });
  const Form = Object.assign(passThrough, {
    useForm: () => [hoisted.formMock],
  });
  return { __esModule: true, Modal, Form };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: hoisted.stableT,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../api/modules/skill", () => ({
  __esModule: true,
  invalidateSkillCache: hoisted.invalidateSkillCacheMock,
}));

vi.mock("../../../utils/error", () => ({
  __esModule: true,
  parseErrorDetail: hoisted.parseErrorDetailMock,
}));

vi.mock("../../../utils/scanError", () => ({
  __esModule: true,
  handleScanError: hoisted.handleScanErrorMock,
  checkScanWarnings: hoisted.checkScanWarningsMock,
  showScanErrorModal: vi.fn(),
}));

vi.mock("../../../utils/agentDisplayName", () => ({
  getAgentDisplayName: (ws: { name?: string }) => ws.name || ws.id,
}));

vi.mock("../../Agent/Skills/components", async () => {
  const React = await import("react");
  return {
    __esModule: true,
    parseFrontmatter: (content: string) => {
      const nameMatch = content.match(/name:\s*(.+)/);
      const descMatch = content.match(/description:\s*(.+)/);
      if (!nameMatch || !descMatch) return null;
      return { name: nameMatch[1].trim(), description: descMatch[1].trim() };
    },
    useConflictRenameModal: () => ({
      showConflictRenameModal: vi.fn().mockResolvedValue(null),
      conflictRenameModal: React.createElement("div", null, "conflict-modal"),
    }),
  };
});

vi.mock("../../../stores/uploadLimitStore", () => ({
  useUploadLimitStore: {
    getState: () => ({ uploadMaxSizeMb: null }),
  },
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({
    selectedAgent: "agent-1",
    agents: [{ id: "agent-1" }],
  }),
}));

import { useSkillPool } from "./useSkillPool";

const { apiMocks, invalidateSkillCacheMock, messageMock, parseErrorDetailMock } =
  hoisted;

function poolSkill(overrides: Record<string, unknown> = {}) {
  return {
    name: "test-skill",
    description: "A test skill",
    tags: [],
    source: "local" as const,
    ...overrides,
  };
}

describe("useSkillPool — install/upload refreshes list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkillPoolSkills.mockResolvedValue([]);
    apiMocks.listSkillWorkspaces.mockResolvedValue([]);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: false,
      fingerprint: "",
      total_changes: 0,
    });
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
    parseErrorDetailMock.mockReturnValue(null);
    hoisted.handleScanErrorMock.mockReturnValue(false);
    hoisted.checkScanWarningsMock.mockResolvedValue(undefined);
  });

  it("handleZipImport: calls invalidateSkillCache + loadData after successful import", async () => {
    const importedNames = ["skill-a", "skill-b"];
    apiMocks.uploadSkillPoolZip.mockResolvedValue({
      count: 2,
      imported: importedNames,
    });
    // After import, loadData(true) is called which re-fetches pool skills
    apiMocks.listSkillPoolSkills
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValueOnce(
        importedNames.map((n) => poolSkill({ name: n })),
      );

    const { result } = renderHook(() => useSkillPool());

    // Wait for initial load
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Simulate zip file selection
    const file = new File(["PK"], "skills.zip", { type: "application/zip" });
    const fakeEvent = {
      target: { files: [file], value: "" },
    } as unknown as React.ChangeEvent<HTMLInputElement>;

    await act(async () => {
      await result.current.handleZipImport(fakeEvent);
    });

    // invalidateSkillCache should be called with pool: true
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({ pool: true });
    // Success message shown
    expect(messageMock.success).toHaveBeenCalled();
    // Data reloaded (listSkillPoolSkills called at least twice: initial + after import)
    expect(apiMocks.listSkillPoolSkills.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("handleConfirmImport: calls invalidateSkillCache + loadData after successful hub import", async () => {
    apiMocks.importPoolSkillFromHub.mockResolvedValue({ name: "hub-skill" });
    apiMocks.listSkillPoolSkills
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValueOnce([poolSkill({ name: "hub-skill" })]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleConfirmImport("https://example.com/skill.zip");
    });

    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({ pool: true });
    expect(messageMock.success).toHaveBeenCalled();
    expect(apiMocks.listSkillPoolSkills.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("handleRefresh: calls invalidateSkillCache with pool+workspaces then reloads", async () => {
    apiMocks.refreshSkillPool.mockResolvedValue([poolSkill({ name: "refreshed" })]);
    apiMocks.listSkillPoolSkills.mockResolvedValueOnce([]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleRefresh();
    });

    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({
      pool: true,
      workspaces: true,
    });
    expect(apiMocks.refreshSkillPool).toHaveBeenCalled();
  });

  it("handleDelete: on confirm, calls invalidateSkillCache + loadData", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.deleteSkillPoolSkill.mockResolvedValue(undefined);
    apiMocks.listSkillPoolSkills.mockResolvedValueOnce([]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleDelete(poolSkill({ name: "delete-me" }));
    });

    expect(apiMocks.deleteSkillPoolSkill).toHaveBeenCalledWith("delete-me");
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({ pool: true });
    expect(messageMock.success).toHaveBeenCalled();
  });

  it("handleBatchDeletePool: calls invalidateSkillCache + loadData after batch delete", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.batchDeletePoolSkills.mockResolvedValue({
      results: { "skill-a": { success: true }, "skill-b": { success: true } },
    });
    apiMocks.listSkillPoolSkills.mockResolvedValueOnce([]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Select some skills first
    act(() => {
      result.current.togglePoolSelect("skill-a");
      result.current.togglePoolSelect("skill-b");
    });

    await act(async () => {
      await result.current.handleBatchDeletePool();
    });

    expect(apiMocks.batchDeletePoolSkills).toHaveBeenCalledWith([
      "skill-a",
      "skill-b",
    ]);
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({ pool: true });
  });
});
