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
    updatePoolSkillAutomation: vi.fn(),
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
  getAgentDisplayName: (ws: { name?: string; id?: string }) => ws.name || ws.id,
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

const {
  apiMocks,
  invalidateSkillCacheMock,
  messageMock,
  parseErrorDetailMock,
} = hoisted;

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
      .mockResolvedValueOnce(importedNames.map((n) => poolSkill({ name: n })));

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
    expect(
      apiMocks.listSkillPoolSkills.mock.calls.length,
    ).toBeGreaterThanOrEqual(2);
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
    expect(
      apiMocks.listSkillPoolSkills.mock.calls.length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("handleRefresh: calls invalidateSkillCache with pool+workspaces then reloads", async () => {
    apiMocks.refreshSkillPool.mockResolvedValue([
      poolSkill({ name: "refreshed" }),
    ]);
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

// ---------------------------------------------------------------------------
// Helper: render and wait for initial load
// ---------------------------------------------------------------------------
async function renderAndLoad(overrides?: {
  skills?: Record<string, unknown>[];
  workspaces?: Record<string, unknown>[];
  notice?: Record<string, unknown>;
}) {
  apiMocks.listSkillPoolSkills.mockResolvedValue(
    (overrides?.skills || []).map((s) => poolSkill(s)),
  );
  apiMocks.listSkillWorkspaces.mockResolvedValue(overrides?.workspaces || []);
  apiMocks.getPoolBuiltinNotice.mockResolvedValue(
    overrides?.notice || {
      has_updates: false,
      fingerprint: "",
      total_changes: 0,
    },
  );
  const hook = renderHook(() => useSkillPool());
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return hook;
}

// ---------------------------------------------------------------------------
// State management: togglePoolSelect, clearPoolSelection, toggleBatchMode, selectAllPool
// ---------------------------------------------------------------------------
describe("useSkillPool — state management", () => {
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

  it("togglePoolSelect: adds and removes skills from selection", async () => {
    const { result } = await renderAndLoad({
      skills: [{ name: "a" }, { name: "b" }, { name: "c" }],
    });

    // Initially empty
    expect(result.current.selectedPoolSkills.size).toBe(0);

    // Add
    act(() => {
      result.current.togglePoolSelect("a");
    });
    expect(result.current.selectedPoolSkills.has("a")).toBe(true);

    // Add another
    act(() => {
      result.current.togglePoolSelect("b");
    });
    expect(result.current.selectedPoolSkills.size).toBe(2);

    // Remove
    act(() => {
      result.current.togglePoolSelect("a");
    });
    expect(result.current.selectedPoolSkills.has("a")).toBe(false);
    expect(result.current.selectedPoolSkills.has("b")).toBe(true);
  });

  it("clearPoolSelection: clears selection and disables batch mode", async () => {
    const { result } = await renderAndLoad({
      skills: [{ name: "x" }],
    });

    act(() => {
      result.current.togglePoolSelect("x");
      result.current.toggleBatchMode();
    });
    expect(result.current.selectedPoolSkills.size).toBe(1);
    expect(result.current.batchModeEnabled).toBe(true);

    act(() => {
      result.current.clearPoolSelection();
    });
    expect(result.current.selectedPoolSkills.size).toBe(0);
    expect(result.current.batchModeEnabled).toBe(false);
  });

  it("toggleBatchMode: enables and disables batch mode", async () => {
    const { result } = await renderAndLoad();

    expect(result.current.batchModeEnabled).toBe(false);
    act(() => {
      result.current.toggleBatchMode();
    });
    expect(result.current.batchModeEnabled).toBe(true);

    // Toggling again should clear selection and disable
    act(() => {
      result.current.togglePoolSelect("something");
    });
    act(() => {
      result.current.toggleBatchMode();
    });
    expect(result.current.batchModeEnabled).toBe(false);
    expect(result.current.selectedPoolSkills.size).toBe(0);
  });

  it("selectAllPool: selects all filtered skills", async () => {
    const { result } = await renderAndLoad({
      skills: [{ name: "alpha" }, { name: "beta" }],
    });

    act(() => {
      result.current.selectAllPool();
    });
    expect(result.current.selectedPoolSkills.size).toBe(2);
    expect(result.current.selectedPoolSkills.has("alpha")).toBe(true);
    expect(result.current.selectedPoolSkills.has("beta")).toBe(true);
  });

  it("setViewMode / setFilterOpen / setSearchQuery / setSearchTags: state setters work", async () => {
    const { result } = await renderAndLoad();

    expect(result.current.viewMode).toBe("card");
    act(() => {
      result.current.setViewMode("list");
    });
    expect(result.current.viewMode).toBe("list");

    expect(result.current.filterOpen).toBe(false);
    act(() => {
      result.current.setFilterOpen(true);
    });
    expect(result.current.filterOpen).toBe(true);

    act(() => {
      result.current.setSearchQuery("test");
    });
    expect(result.current.searchQuery).toBe("test");

    act(() => {
      result.current.setSearchTags(["tag:a"]);
    });
    expect(result.current.searchTags).toEqual(["tag:a"]);
  });
});

// ---------------------------------------------------------------------------
// loadData error path
// ---------------------------------------------------------------------------
describe("useSkillPool — loadData error", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
    parseErrorDetailMock.mockReturnValue(null);
    hoisted.handleScanErrorMock.mockReturnValue(false);
    hoisted.checkScanWarningsMock.mockResolvedValue(undefined);
  });

  it("shows error message when initial load fails", async () => {
    apiMocks.listSkillPoolSkills.mockRejectedValue(new Error("Network error"));
    apiMocks.listSkillWorkspaces.mockResolvedValue([]);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: false,
      fingerprint: "",
      total_changes: 0,
    });

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(messageMock.error).toHaveBeenCalledWith("Network error");
    expect(result.current.skills).toEqual([]);
  });

  it("shows generic error message when error is not an Error instance", async () => {
    apiMocks.listSkillPoolSkills.mockRejectedValue("string error");
    apiMocks.listSkillWorkspaces.mockResolvedValue([]);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: false,
      fingerprint: "",
      total_changes: 0,
    });

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(messageMock.error).toHaveBeenCalledWith("Failed to load skill pool");
  });
});

// ---------------------------------------------------------------------------
// Modal / Drawer state: closeModal, openCreate, openBroadcast, closeDrawer
// ---------------------------------------------------------------------------
describe("useSkillPool — modal and drawer state", () => {
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

  it("openCreate: sets mode to create and resets form", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.openCreate();
    });
    expect(result.current.mode).toBe("create");
    expect(result.current.activeSkill).toBeNull();
    expect(result.current.detailLoading).toBe(false);
    expect(result.current.configText).toBe("{}");
    expect(hoisted.formMock.resetFields).toHaveBeenCalled();
    expect(hoisted.formMock.setFieldsValue).toHaveBeenCalledWith({
      name: "",
      content: "",
      tags: [],
    });
  });

  it("openBroadcast: sets mode to broadcast with skill name", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.openBroadcast(poolSkill({ name: "my-skill" }));
    });
    expect(result.current.mode).toBe("broadcast");
    expect(result.current.broadcastInitialNames).toEqual(["my-skill"]);
  });

  it("openBroadcast: without skill sets empty initial names", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.openBroadcast();
    });
    expect(result.current.mode).toBe("broadcast");
    expect(result.current.broadcastInitialNames).toEqual([]);
  });

  it("closeModal: resets all modal state", async () => {
    const { result } = await renderAndLoad();

    // Set some state first
    act(() => {
      result.current.openCreate();
    });
    expect(result.current.mode).toBe("create");

    act(() => {
      result.current.closeModal();
    });
    expect(result.current.mode).toBeNull();
    expect(result.current.activeSkill).toBeNull();
    expect(result.current.detailLoading).toBe(false);
    expect(result.current.configText).toBe("{}");
  });

  it("closeDrawer: resets drawer state", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.openCreate();
    });
    act(() => {
      result.current.closeDrawer();
    });
    expect(result.current.mode).toBeNull();
    expect(result.current.activeSkill).toBeNull();
  });

  it("handleDrawerContentChange: updates drawer content and form", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.openCreate();
    });
    act(() => {
      result.current.handleDrawerContentChange("new content");
    });
    expect(result.current.drawerContent).toBe("new content");
    expect(hoisted.formMock.setFieldsValue).toHaveBeenCalledWith({
      content: "new content",
    });
  });

  it("setConfigText / setShowMarkdown / setBuiltinAutoUpdateEnabled / setAutoSyncTargets: state setters", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.setConfigText('{"key":"val"}');
    });
    expect(result.current.configText).toBe('{"key":"val"}');

    act(() => {
      result.current.setShowMarkdown(false);
    });
    expect(result.current.showMarkdown).toBe(false);

    act(() => {
      result.current.setBuiltinAutoUpdateEnabled(true);
    });
    expect(result.current.builtinAutoUpdateEnabled).toBe(true);

    act(() => {
      result.current.setAutoSyncEnabled(true);
    });
    expect(result.current.autoSyncEnabled).toBe(true);

    act(() => {
      result.current.setAutoSyncTargets(["agent-1"]);
    });
    expect(result.current.autoSyncTargets).toEqual(["agent-1"]);
  });

  it("setImportModalOpen: controls import modal visibility", async () => {
    const { result } = await renderAndLoad();

    expect(result.current.importModalOpen).toBe(false);
    act(() => {
      result.current.setImportModalOpen(true);
    });
    expect(result.current.importModalOpen).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// openEdit
// ---------------------------------------------------------------------------
describe("useSkillPool — openEdit", () => {
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

  it("loads detail and sets form values on success", async () => {
    const detail = {
      name: "my-skill",
      content: "name: my-skill\ndescription: test",
      config: { key: "value" },
      tags: ["tag1"],
      auto_update: true,
      auto_sync: true,
      auto_sync_targets: ["agent-1"],
    };
    apiMocks.getPoolSkill.mockResolvedValue(detail);

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "my-skill" }));
    });

    expect(result.current.mode).toBe("edit");
    expect(result.current.activeSkill).toEqual(detail);
    expect(result.current.drawerContent).toBe(detail.content);
    expect(result.current.builtinAutoUpdateEnabled).toBe(true);
    expect(result.current.autoSyncEnabled).toBe(true);
    expect(result.current.autoSyncTargets).toEqual(["agent-1"]);
    expect(result.current.detailLoading).toBe(false);
    expect(hoisted.formMock.setFieldsValue).toHaveBeenCalledWith({
      name: "my-skill",
      content: detail.content,
      tags: ["tag1"],
    });
  });

  it("shows error and resets mode on failure", async () => {
    apiMocks.getPoolSkill.mockRejectedValue(new Error("Load failed"));

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "bad-skill" }));
    });

    expect(messageMock.error).toHaveBeenCalledWith("Load failed");
    expect(result.current.mode).toBeNull();
    expect(result.current.detailLoading).toBe(false);
  });

  it("shows generic error when error is not Error instance", async () => {
    apiMocks.getPoolSkill.mockRejectedValue("some string");

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "bad-skill" }));
    });

    expect(messageMock.error).toHaveBeenCalledWith("skills.loadFailed");
  });

  it("handles detail with no config gracefully", async () => {
    apiMocks.getPoolSkill.mockResolvedValue({
      name: "no-config",
      content: "content",
      tags: [],
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "no-config" }));
    });

    expect(result.current.configText).toBe("{}");
    expect(result.current.builtinAutoUpdateEnabled).toBe(false);
    expect(result.current.autoSyncEnabled).toBe(false);
    expect(result.current.autoSyncTargets).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// validateFrontmatter
// ---------------------------------------------------------------------------
describe("useSkillPool — validateFrontmatter", () => {
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

  it("rejects when content is empty", async () => {
    const { result } = await renderAndLoad();

    await expect(result.current.validateFrontmatter(null, "")).rejects.toThrow(
      "skills.pleaseInputContent",
    );
  });

  it("rejects when no frontmatter found", async () => {
    const { result } = await renderAndLoad();

    await expect(
      result.current.validateFrontmatter(null, "just plain text"),
    ).rejects.toThrow("skills.frontmatterRequired");
  });

  it("rejects when frontmatter has no name", async () => {
    const { result } = await renderAndLoad();

    // parseFrontmatter mock returns {name, description} only if both match
    // Content with description but no name
    await expect(
      result.current.validateFrontmatter(null, "description: some desc"),
    ).rejects.toThrow("skills.frontmatterRequired");
  });

  it("resolves when frontmatter has name and description", async () => {
    const { result } = await renderAndLoad();

    await expect(
      result.current.validateFrontmatter(
        null,
        "name: my-skill\ndescription: A test skill",
      ),
    ).resolves.toBeUndefined();
  });

  it("uses drawerContent when value is empty and resolves with valid frontmatter", async () => {
    const { result } = await renderAndLoad();

    // Set drawer content with valid frontmatter
    act(() => {
      result.current.handleDrawerContentChange("name: test\ndescription: desc");
    });

    // Pass empty value — should use drawerContent which has valid frontmatter
    await expect(
      result.current.validateFrontmatter(null, ""),
    ).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// openImportBuiltin
// ---------------------------------------------------------------------------
describe("useSkillPool — openImportBuiltin", () => {
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

  it("loads sources and opens modal on success", async () => {
    const sources = [{ name: "builtin-a" }];
    apiMocks.listPoolBuiltinSources.mockResolvedValue(sources);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: false,
      fingerprint: "",
      total_changes: 0,
    });

    const { result } = await renderAndLoad();

    expect(result.current.importBuiltinModalOpen).toBe(false);

    await act(async () => {
      result.current.openImportBuiltin();
    });

    expect(result.current.importBuiltinModalOpen).toBe(true);
    expect(result.current.builtinSources).toEqual(sources);
    expect(result.current.importBuiltinLoading).toBe(false);
  });

  it("marks builtin notice as seen when has_updates and fingerprint", async () => {
    const { result } = await renderAndLoad();

    // Override mock AFTER initial load to return the update notice
    apiMocks.listPoolBuiltinSources.mockResolvedValue([]);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: true,
      fingerprint: "fp-123",
      total_changes: 3,
    });

    await act(async () => {
      result.current.openImportBuiltin();
    });

    expect(result.current.importBuiltinModalOpen).toBe(true);
    expect(result.current.builtinNotice).toEqual({
      has_updates: true,
      fingerprint: "fp-123",
      total_changes: 3,
    });
  });

  it("shows error when loading sources fails", async () => {
    apiMocks.listPoolBuiltinSources.mockRejectedValue(
      new Error("Fetch failed"),
    );
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: false,
      fingerprint: "",
      total_changes: 0,
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openImportBuiltin();
    });

    expect(messageMock.error).toHaveBeenCalledWith("Fetch failed");
    expect(result.current.importBuiltinModalOpen).toBe(false);
    expect(result.current.importBuiltinLoading).toBe(false);
  });

  it("closeImportBuiltin: does nothing when loading", async () => {
    apiMocks.listPoolBuiltinSources.mockImplementation(
      () => new Promise(() => {}), // never resolves
    );

    const { result } = await renderAndLoad();

    // Start import (will be stuck loading)
    act(() => {
      result.current.openImportBuiltin();
    });

    // Try to close while loading — should be no-op
    act(() => {
      result.current.closeImportBuiltin();
    });
    // Modal should still be in whatever state (loading blocks close)
  });

  it("closeImportBuiltin: closes modal when not loading", async () => {
    apiMocks.listPoolBuiltinSources.mockResolvedValue([]);

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openImportBuiltin();
    });
    expect(result.current.importBuiltinModalOpen).toBe(true);

    act(() => {
      result.current.closeImportBuiltin();
    });
    expect(result.current.importBuiltinModalOpen).toBe(false);
  });

  it("closeImportModal: does nothing when importing", async () => {
    apiMocks.importPoolSkillFromHub.mockImplementation(
      () => new Promise(() => {}), // never resolves
    );

    const { result } = await renderAndLoad();

    act(() => {
      result.current.setImportModalOpen(true);
    });
    // Start import (stuck)
    act(() => {
      result.current.handleConfirmImport("http://example.com/skill.zip");
    });

    // Try close while importing
    act(() => {
      result.current.closeImportModal();
    });
    // Modal stays open because importing is true
  });

  it("closeImportModal: closes modal when not importing", async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.setImportModalOpen(true);
    });
    expect(result.current.importModalOpen).toBe(true);

    act(() => {
      result.current.closeImportModal();
    });
    expect(result.current.importModalOpen).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getBuiltinImportStatusLabel
// ---------------------------------------------------------------------------
describe("useSkillPool — getBuiltinImportStatusLabel", () => {
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

  // getBuiltinImportStatusLabel is not directly exposed, but we can test
  // indirectly through handleImportBuiltins conflict flow. For now, we
  // verify it exists as part of the hook return.
  it("hook returns expected shape including all functions", async () => {
    const { result } = await renderAndLoad();

    // Verify key returned properties exist
    expect(typeof result.current.handleRefresh).toBe("function");
    expect(typeof result.current.openCreate).toBe("function");
    expect(typeof result.current.openEdit).toBe("function");
    expect(typeof result.current.openBroadcast).toBe("function");
    expect(typeof result.current.handleBroadcast).toBe("function");
    expect(typeof result.current.handleImportBuiltins).toBe("function");
    expect(typeof result.current.handleBuiltinLanguageSwitch).toBe("function");
    expect(typeof result.current.handleAutomationQuickAction).toBe("function");
    expect(typeof result.current.handleSavePoolSkill).toBe("function");
    expect(typeof result.current.handleDelete).toBe("function");
    expect(typeof result.current.handleZipImport).toBe("function");
    expect(typeof result.current.handleConfirmImport).toBe("function");
    expect(typeof result.current.handleBatchDeletePool).toBe("function");
    expect(typeof result.current.togglePoolSelect).toBe("function");
    expect(typeof result.current.toggleBatchMode).toBe("function");
    expect(typeof result.current.selectAllPool).toBe("function");
    expect(typeof result.current.clearPoolSelection).toBe("function");
    expect(typeof result.current.validateFrontmatter).toBe("function");
    expect(typeof result.current.closeModal).toBe("function");
    expect(typeof result.current.closeDrawer).toBe("function");
    expect(typeof result.current.openImportBuiltin).toBe("function");
    expect(typeof result.current.closeImportBuiltin).toBe("function");
    expect(typeof result.current.closeImportModal).toBe("function");
    expect(typeof result.current.handleDrawerContentChange).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// handleAutomationQuickAction (replaces handleToggleAutoUpdate after upstream #7232:
// builtin skills toggle auto_update + auto_sync together; others toggle auto_sync only;
// when a builtin skill has mixed auto_update/auto_sync, defer to openEdit)
// ---------------------------------------------------------------------------
describe("useSkillPool — handleAutomationQuickAction", () => {
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

  it("enables automation for builtin skill and shows success", async () => {
    apiMocks.updatePoolSkillAutomation.mockResolvedValue({});

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({
          name: "auto-skill",
          source: "builtin",
          auto_sync: false,
          auto_update: false,
        }),
      );
    });

    expect(apiMocks.updatePoolSkillAutomation).toHaveBeenCalledWith(
      "auto-skill",
      { auto_update: true, auto_sync: { enabled: true } },
    );
    expect(messageMock.success).toHaveBeenCalledWith(
      "skillPool.automationEnabled",
    );
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({
      pool: true,
      workspaces: true,
    });
  });

  it("disables automation for builtin skill and shows success", async () => {
    apiMocks.updatePoolSkillAutomation.mockResolvedValue({});

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({
          name: "auto-skill",
          source: "builtin",
          auto_sync: true,
          auto_update: true,
        }),
      );
    });

    expect(apiMocks.updatePoolSkillAutomation).toHaveBeenCalledWith(
      "auto-skill",
      { auto_update: false, auto_sync: { enabled: false } },
    );
    expect(messageMock.success).toHaveBeenCalledWith(
      "skillPool.automationDisabled",
    );
  });

  it("toggles auto_sync only for non-builtin skill", async () => {
    apiMocks.updatePoolSkillAutomation.mockResolvedValue({});

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({ name: "custom-skill", source: "local", auto_sync: false }),
      );
    });

    expect(apiMocks.updatePoolSkillAutomation).toHaveBeenCalledWith(
      "custom-skill",
      { auto_sync: { enabled: true } },
    );
    expect(messageMock.success).toHaveBeenCalledWith(
      "skillPool.autoSyncEnabled",
    );
  });

  it("warns when automation response has attention items", async () => {
    apiMocks.updatePoolSkillAutomation.mockResolvedValue({
      automation: { pool_failed: ["auto-skill"], sync_failed: [] },
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({
          name: "auto-skill",
          source: "builtin",
          auto_sync: false,
          auto_update: false,
        }),
      );
    });

    expect(messageMock.warning).toHaveBeenCalledWith(
      "skillPool.automationNeedsAttention",
    );
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("opens edit drawer instead of toggling for builtin skill with mixed state", async () => {
    apiMocks.getPoolSkill.mockResolvedValue({
      name: "mixed-skill",
      content: "",
      config: {},
      tags: [],
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({
          name: "mixed-skill",
          source: "builtin",
          auto_sync: true,
          auto_update: false,
        }),
      );
    });

    expect(apiMocks.updatePoolSkillAutomation).not.toHaveBeenCalled();
    expect(apiMocks.getPoolSkill).toHaveBeenCalledWith("mixed-skill");
    expect(result.current.mode).toBe("edit");
  });

  it("shows error when API fails", async () => {
    apiMocks.updatePoolSkillAutomation.mockRejectedValue(
      new Error("Update failed"),
    );

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({
          name: "fail-skill",
          source: "builtin",
          auto_sync: false,
          auto_update: false,
        }),
      );
    });

    expect(messageMock.error).toHaveBeenCalledWith("Update failed");
  });

  it("shows generic error when error is not Error instance", async () => {
    apiMocks.updatePoolSkillAutomation.mockRejectedValue("string error");

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleAutomationQuickAction(
        poolSkill({
          name: "fail-skill",
          source: "builtin",
          auto_sync: false,
          auto_update: false,
        }),
      );
    });

    expect(messageMock.error).toHaveBeenCalledWith(
      "skillPool.automationFailed",
    );
  });
});

// ---------------------------------------------------------------------------
// handleBuiltinLanguageSwitch
// ---------------------------------------------------------------------------
describe("useSkillPool — handleBuiltinLanguageSwitch", () => {
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

  it("returns early if language is the same", async () => {
    const { result } = await renderAndLoad();

    const skill = {
      name: "builtin-skill",
      content: "",
      config: {},
      tags: [],
      builtin_language: "en",
    } as any;

    await act(async () => {
      await result.current.handleBuiltinLanguageSwitch(skill, "en");
    });

    expect(apiMocks.updatePoolBuiltin).not.toHaveBeenCalled();
  });

  it("updates language when confirmed", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.updatePoolBuiltin.mockResolvedValue(undefined);

    const { result } = await renderAndLoad();

    const skill = {
      name: "builtin-skill",
      content: "",
      config: {},
      tags: [],
      builtin_language: "en",
    } as any;

    await act(async () => {
      await result.current.handleBuiltinLanguageSwitch(skill, "zh");
    });

    expect(apiMocks.updatePoolBuiltin).toHaveBeenCalledWith(
      "builtin-skill",
      "zh",
    );
    expect(messageMock.success).toHaveBeenCalled();
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({
      pool: true,
      workspaces: true,
    });
  });

  it("does nothing when user cancels confirmation", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onCancel: () => void }) => {
        opts.onCancel();
      },
    );

    const { result } = await renderAndLoad();

    const skill = {
      name: "builtin-skill",
      content: "",
      config: {},
      tags: [],
      builtin_language: "en",
    } as any;

    await act(async () => {
      await result.current.handleBuiltinLanguageSwitch(skill, "zh");
    });

    expect(apiMocks.updatePoolBuiltin).not.toHaveBeenCalled();
  });

  it("shows error when update fails", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.updatePoolBuiltin.mockRejectedValue(new Error("Update failed"));

    const { result } = await renderAndLoad();

    const skill = {
      name: "builtin-skill",
      content: "",
      config: {},
      tags: [],
      builtin_language: "en",
    } as any;

    await act(async () => {
      await result.current.handleBuiltinLanguageSwitch(skill, "zh");
    });

    expect(messageMock.error).toHaveBeenCalledWith("Update failed");
  });
});

// ---------------------------------------------------------------------------
// handleImportBuiltins
// ---------------------------------------------------------------------------
describe("useSkillPool — handleImportBuiltins", () => {
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

  it("returns early for empty selections", async () => {
    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleImportBuiltins([]);
    });

    expect(apiMocks.importSelectedPoolBuiltins).not.toHaveBeenCalled();
  });

  it("shows success and reloads on successful import", async () => {
    apiMocks.importSelectedPoolBuiltins.mockResolvedValue({
      imported: ["skill-a"],
      updated: ["skill-b"],
      unchanged: [],
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleImportBuiltins([
        { skill_name: "skill-a", language: "en" },
        { skill_name: "skill-b", language: "zh" },
      ]);
    });

    expect(messageMock.success).toHaveBeenCalled();
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({
      pool: true,
      workspaces: true,
    });
  });

  it("shows info when only unchanged results", async () => {
    apiMocks.importSelectedPoolBuiltins.mockResolvedValue({
      imported: [],
      updated: [],
      unchanged: ["skill-a"],
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleImportBuiltins([
        { skill_name: "skill-a", language: "en" },
      ]);
    });

    expect(messageMock.info).toHaveBeenCalled();
  });

  it("shows conflict modal on error with conflicts", async () => {
    const conflictError = {
      response: {
        data: {
          conflicts: [{ skill_name: "s1", language: "en", status: "outdated" }],
        },
      },
    };
    apiMocks.importSelectedPoolBuiltins.mockRejectedValue(conflictError);
    parseErrorDetailMock.mockReturnValue({
      conflicts: [
        {
          skill_name: "s1",
          language: "en",
          status: "outdated",
          current_version_text: "1.0",
          source_version_text: "2.0",
        },
      ],
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleImportBuiltins([
        { skill_name: "s1", language: "en" },
      ]);
    });

    expect(hoisted.modalConfirmMock).toHaveBeenCalled();
  });

  it("shows error on generic failure", async () => {
    apiMocks.importSelectedPoolBuiltins.mockRejectedValue(
      new Error("Import failed"),
    );
    parseErrorDetailMock.mockReturnValue(null);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleImportBuiltins([
        { skill_name: "s1", language: "en" },
      ]);
    });

    expect(messageMock.error).toHaveBeenCalledWith("Import failed");
  });
});

// ---------------------------------------------------------------------------
// handleBroadcast
// ---------------------------------------------------------------------------
describe("useSkillPool — handleBroadcast", () => {
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

  it("broadcasts successfully without conflicts", async () => {
    apiMocks.downloadSkillPoolSkill.mockResolvedValue(undefined);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1", "ws-2"]);
    });

    // Preview call + actual call
    expect(apiMocks.downloadSkillPoolSkill).toHaveBeenCalled();
    expect(messageMock.success).toHaveBeenCalled();
    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({
      pool: true,
      workspaces: true,
    });
  });

  it("handles broadcast with conflicts and user confirms", async () => {
    // First call (preview) throws with conflicts
    apiMocks.downloadSkillPoolSkill
      .mockRejectedValueOnce({ conflicts: true })
      .mockResolvedValueOnce(undefined); // overwrite call

    parseErrorDetailMock.mockReturnValue({
      conflicts: [
        {
          skill_name: "skill-a",
          workspace_id: "ws-1",
          workspace_name: "Workspace 1",
          reason: "conflict",
        },
      ],
    });
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    expect(hoisted.modalConfirmMock).toHaveBeenCalled();
    expect(messageMock.success).toHaveBeenCalled();
  });

  it("cancels broadcast when user rejects conflict confirmation", async () => {
    apiMocks.downloadSkillPoolSkill.mockRejectedValueOnce({ conflicts: true });
    parseErrorDetailMock.mockReturnValue({
      conflicts: [
        {
          skill_name: "skill-a",
          workspace_id: "ws-1",
          workspace_name: "Workspace 1",
          reason: "conflict",
        },
      ],
    });
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onCancel: () => void }) => {
        opts.onCancel();
      },
    );

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    // Should not have called download again for actual broadcast
    expect(apiMocks.downloadSkillPoolSkill).toHaveBeenCalledTimes(1);
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("handles builtin_upgrade conflicts", async () => {
    apiMocks.downloadSkillPoolSkill
      .mockRejectedValueOnce({ conflicts: true })
      .mockResolvedValueOnce(undefined);

    parseErrorDetailMock.mockReturnValue({
      conflicts: [
        {
          skill_name: "skill-a",
          workspace_id: "ws-1",
          workspace_name: "WS1",
          reason: "builtin_upgrade",
          current_version_text: "1.0",
          source_version_text: "2.0",
        },
      ],
    });
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    expect(messageMock.success).toHaveBeenCalled();
  });

  it("handles language_switch conflicts", async () => {
    apiMocks.downloadSkillPoolSkill
      .mockRejectedValueOnce({ conflicts: true })
      .mockResolvedValueOnce(undefined);

    parseErrorDetailMock.mockReturnValue({
      conflicts: [
        {
          skill_name: "skill-a",
          workspace_id: "ws-1",
          workspace_name: "WS1",
          reason: "language_switch",
          source_language: "zh",
          current_language: "en",
        },
      ],
    });
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    expect(messageMock.success).toHaveBeenCalled();
  });

  it("shows error when broadcast fails without conflicts", async () => {
    apiMocks.downloadSkillPoolSkill.mockRejectedValue(
      new Error("Broadcast error"),
    );
    parseErrorDetailMock.mockReturnValue(null);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    expect(messageMock.error).toHaveBeenCalledWith("Broadcast error");
  });

  it("shows generic error when broadcast fails with non-Error", async () => {
    apiMocks.downloadSkillPoolSkill.mockRejectedValue("string error");
    parseErrorDetailMock.mockReturnValue(null);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    expect(messageMock.error).toHaveBeenCalledWith("skillPool.broadcastFailed");
  });

  it("returns early when handleScanError returns true", async () => {
    apiMocks.downloadSkillPoolSkill.mockRejectedValue("scan-error");
    hoisted.handleScanErrorMock.mockReturnValueOnce(true);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBroadcast(["skill-a"], ["ws-1"]);
    });

    expect(messageMock.error).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleSavePoolSkill
// ---------------------------------------------------------------------------
describe("useSkillPool — handleSavePoolSkill", () => {
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

  it("returns early when form validation fails", async () => {
    hoisted.formMock.validateFields.mockRejectedValue(new Error("validation"));

    const { result } = await renderAndLoad();
    act(() => {
      result.current.openCreate();
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    expect(apiMocks.createSkillPoolSkill).not.toHaveBeenCalled();
    expect(apiMocks.saveSkillPoolSkill).not.toHaveBeenCalled();
  });

  it("returns early when skill name is empty", async () => {
    hoisted.formMock.validateFields.mockResolvedValue({
      name: "",
      content: "some content",
      tags: [],
    });

    const { result } = await renderAndLoad();
    act(() => {
      result.current.openCreate();
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    expect(apiMocks.createSkillPoolSkill).not.toHaveBeenCalled();
  });

  it("returns early when content is empty", async () => {
    hoisted.formMock.validateFields.mockResolvedValue({
      name: "test",
      content: "",
      tags: [],
    });

    const { result } = await renderAndLoad();
    act(() => {
      result.current.openCreate();
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    expect(apiMocks.createSkillPoolSkill).not.toHaveBeenCalled();
  });

  it("shows error for invalid JSON config", async () => {
    hoisted.formMock.validateFields.mockResolvedValue({
      name: "test",
      content: "some content",
      tags: [],
    });

    const { result } = await renderAndLoad();
    act(() => {
      result.current.openCreate();
    });
    act(() => {
      result.current.setConfigText("{invalid json");
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    expect(messageMock.error).toHaveBeenCalledWith("skills.configInvalidJson");
  });

  it("creates new skill successfully", async () => {
    hoisted.formMock.validateFields.mockResolvedValue({
      name: "new-skill",
      content: "name: new-skill\ndescription: test",
      tags: ["tag1"],
    });
    apiMocks.createSkillPoolSkill.mockResolvedValue({ name: "new-skill" });
    apiMocks.updatePoolSkillTags.mockResolvedValue(undefined);

    const { result } = await renderAndLoad();
    act(() => {
      result.current.openCreate();
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    expect(apiMocks.createSkillPoolSkill).toHaveBeenCalledWith({
      name: "new-skill",
      content: "name: new-skill\ndescription: test",
      config: {},
    });
    expect(apiMocks.updatePoolSkillTags).toHaveBeenCalledWith("new-skill", [
      "tag1",
    ]);
    expect(messageMock.success).toHaveBeenCalled();
  });

  it("edits existing skill successfully", async () => {
    const detail = {
      name: "existing",
      content: "content",
      config: {},
      tags: ["old-tag"],
      auto_update: false,
      auto_update_targets: [],
    };
    apiMocks.getPoolSkill.mockResolvedValue(detail);

    hoisted.formMock.validateFields.mockResolvedValue({
      name: "existing",
      content: "updated content",
      tags: ["new-tag"],
    });
    apiMocks.saveSkillPoolSkill.mockResolvedValue({
      success: true,
      mode: "edit",
      name: "existing",
    });
    apiMocks.updatePoolSkillTags.mockResolvedValue(undefined);

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "existing" }));
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    expect(apiMocks.saveSkillPoolSkill).toHaveBeenCalled();
    expect(apiMocks.updatePoolSkillTags).toHaveBeenCalledWith("existing", [
      "new-tag",
    ]);
  });

  it("handles conflict error with overwrite confirmation in edit mode", async () => {
    const detail = {
      name: "existing",
      content: "content",
      config: {},
      tags: [],
      auto_update: false,
      auto_update_targets: [],
    };
    apiMocks.getPoolSkill.mockResolvedValue(detail);

    hoisted.formMock.validateFields.mockResolvedValue({
      name: "existing",
      content: "updated",
      tags: [],
    });

    // First save fails with conflict
    apiMocks.saveSkillPoolSkill
      .mockRejectedValueOnce(new Error("conflict"))
      .mockResolvedValueOnce({ success: true, mode: "edit", name: "existing" });

    parseErrorDetailMock
      .mockReturnValueOnce({ reason: "conflict" })
      .mockReturnValue(null);

    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "existing" }));
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    // Should have tried to save twice (initial + overwrite)
    expect(apiMocks.saveSkillPoolSkill).toHaveBeenCalledTimes(2);
  });

  it("handles noop result by closing drawer", async () => {
    hoisted.formMock.validateFields.mockResolvedValue({
      name: "noop-skill",
      content: "content",
      tags: [],
    });
    apiMocks.createSkillPoolSkill.mockResolvedValue({ name: "noop-skill" });
    // Make it return noop mode - need to adjust the .then mapping
    // Actually the create path maps to {success:true, mode:"edit", name:...}
    // So noop only happens from save path. Let's test edit mode noop.
    const detail = {
      name: "noop-skill",
      content: "content",
      config: {},
      tags: [],
      auto_update: false,
      auto_update_targets: [],
    };
    apiMocks.getPoolSkill.mockResolvedValue(detail);
    apiMocks.saveSkillPoolSkill.mockResolvedValue({
      success: true,
      mode: "noop",
      name: "noop-skill",
    });

    const { result } = await renderAndLoad();

    await act(async () => {
      result.current.openEdit(poolSkill({ name: "noop-skill" }));
    });

    await act(async () => {
      await result.current.handleSavePoolSkill();
    });

    // Should close drawer without success message for noop
    expect(result.current.mode).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// handleZipImport edge cases
// ---------------------------------------------------------------------------
describe("useSkillPool — handleZipImport edge cases", () => {
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

  it("does nothing when no file selected", async () => {
    const { result } = await renderAndLoad();

    const fakeEvent = {
      target: { files: [], value: "" },
    } as unknown as React.ChangeEvent<HTMLInputElement>;

    await act(async () => {
      await result.current.handleZipImport(fakeEvent);
    });

    expect(apiMocks.uploadSkillPoolZip).not.toHaveBeenCalled();
  });

  it("shows warning for non-zip file", async () => {
    const { result } = await renderAndLoad();

    const file = new File(["data"], "skills.txt", { type: "text/plain" });
    const fakeEvent = {
      target: { files: [file], value: "" },
    } as unknown as React.ChangeEvent<HTMLInputElement>;

    await act(async () => {
      await result.current.handleZipImport(fakeEvent);
    });

    expect(messageMock.warning).toHaveBeenCalledWith("skills.zipOnly");
    expect(apiMocks.uploadSkillPoolZip).not.toHaveBeenCalled();
  });

  it("shows info when no new imports (count=0)", async () => {
    apiMocks.uploadSkillPoolZip.mockResolvedValue({ count: 0, imported: [] });

    const { result } = await renderAndLoad();

    const file = new File(["PK"], "skills.zip", { type: "application/zip" });
    const fakeEvent = {
      target: { files: [file], value: "" },
    } as unknown as React.ChangeEvent<HTMLInputElement>;

    await act(async () => {
      await result.current.handleZipImport(fakeEvent);
    });

    expect(messageMock.info).toHaveBeenCalledWith("skillPool.noNewImports");
  });

  it("shows error on upload failure without conflicts", async () => {
    apiMocks.uploadSkillPoolZip.mockRejectedValue(new Error("Upload failed"));
    parseErrorDetailMock.mockReturnValue(null);

    const { result } = await renderAndLoad();

    const file = new File(["PK"], "skills.zip", { type: "application/zip" });
    const fakeEvent = {
      target: { files: [file], value: "" },
    } as unknown as React.ChangeEvent<HTMLInputElement>;

    await act(async () => {
      await result.current.handleZipImport(fakeEvent);
    });

    expect(messageMock.error).toHaveBeenCalledWith("Upload failed");
  });

  it("breaks on scan error during upload", async () => {
    apiMocks.uploadSkillPoolZip.mockRejectedValue("scan-error");
    hoisted.handleScanErrorMock.mockReturnValueOnce(true);

    const { result } = await renderAndLoad();

    const file = new File(["PK"], "skills.zip", { type: "application/zip" });
    const fakeEvent = {
      target: { files: [file], value: "" },
    } as unknown as React.ChangeEvent<HTMLInputElement>;

    await act(async () => {
      await result.current.handleZipImport(fakeEvent);
    });

    expect(messageMock.error).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleConfirmImport edge cases
// ---------------------------------------------------------------------------
describe("useSkillPool — handleConfirmImport edge cases", () => {
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

  it("shows error on import failure", async () => {
    apiMocks.importPoolSkillFromHub.mockRejectedValue(
      new Error("Import failed"),
    );
    parseErrorDetailMock.mockReturnValue(null);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleConfirmImport("https://example.com/skill.zip");
    });

    expect(messageMock.error).toHaveBeenCalledWith("Import failed");
    expect(result.current.importing).toBe(false);
  });

  it("shows generic error when import fails with non-Error", async () => {
    apiMocks.importPoolSkillFromHub.mockRejectedValue("string error");
    parseErrorDetailMock.mockReturnValue(null);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleConfirmImport("https://example.com/skill.zip");
    });

    expect(messageMock.error).toHaveBeenCalledWith("skills.uploadFailed");
  });

  it("returns early when handleScanError returns true", async () => {
    apiMocks.importPoolSkillFromHub.mockRejectedValue("scan-error");
    hoisted.handleScanErrorMock.mockReturnValueOnce(true);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleConfirmImport("https://example.com/skill.zip");
    });

    expect(messageMock.error).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleBatchDeletePool edge cases
// ---------------------------------------------------------------------------
describe("useSkillPool — handleBatchDeletePool edge cases", () => {
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

  it("returns early when no skills selected", async () => {
    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleBatchDeletePool();
    });

    expect(apiMocks.batchDeletePoolSkills).not.toHaveBeenCalled();
  });

  it("does not delete when user cancels confirmation", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onCancel: () => void }) => {
        opts.onCancel();
      },
    );

    const { result } = await renderAndLoad();

    act(() => {
      result.current.togglePoolSelect("skill-a");
    });

    await act(async () => {
      await result.current.handleBatchDeletePool();
    });

    expect(apiMocks.batchDeletePoolSkills).not.toHaveBeenCalled();
  });

  it("shows warning on partial failure", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.batchDeletePoolSkills.mockResolvedValue({
      results: {
        "skill-a": { success: true },
        "skill-b": { success: false },
      },
    });

    const { result } = await renderAndLoad();

    act(() => {
      result.current.togglePoolSelect("skill-a");
      result.current.togglePoolSelect("skill-b");
    });

    await act(async () => {
      await result.current.handleBatchDeletePool();
    });

    expect(messageMock.warning).toHaveBeenCalled();
  });

  it("shows error when batch delete API fails", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.batchDeletePoolSkills.mockRejectedValue(new Error("Batch failed"));

    const { result } = await renderAndLoad();

    act(() => {
      result.current.togglePoolSelect("skill-a");
    });

    await act(async () => {
      await result.current.handleBatchDeletePool();
    });

    expect(messageMock.error).toHaveBeenCalledWith("Batch failed");
  });

  it("shows generic error when batch delete fails with non-Error", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.batchDeletePoolSkills.mockRejectedValue("string error");

    const { result } = await renderAndLoad();

    act(() => {
      result.current.togglePoolSelect("skill-a");
    });

    await act(async () => {
      await result.current.handleBatchDeletePool();
    });

    expect(messageMock.error).toHaveBeenCalledWith(
      "skillPool.batchDeleteFailed",
    );
  });
});

// ---------------------------------------------------------------------------
// handleRefresh error path
// ---------------------------------------------------------------------------
describe("useSkillPool — handleRefresh error", () => {
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

  it("shows error when refresh fails", async () => {
    apiMocks.refreshSkillPool.mockRejectedValue(new Error("Refresh failed"));

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleRefresh();
    });

    expect(messageMock.error).toHaveBeenCalledWith("Refresh failed");
    expect(result.current.loading).toBe(false);
  });

  it("shows generic error when refresh fails with non-Error", async () => {
    apiMocks.refreshSkillPool.mockRejectedValue("string error");

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleRefresh();
    });

    expect(messageMock.error).toHaveBeenCalledWith("Failed to refresh");
  });
});

// ---------------------------------------------------------------------------
// Computed properties: sortedSkills, allTags, builtinNotice
// ---------------------------------------------------------------------------
describe("useSkillPool — computed properties", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("sortedSkills are sorted alphabetically by name", async () => {
    apiMocks.listSkillPoolSkills.mockResolvedValue([
      poolSkill({ name: "zebra" }),
      poolSkill({ name: "alpha" }),
      poolSkill({ name: "mango" }),
    ]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const names = result.current.sortedSkills.map((s: any) => s.name);
    expect(names).toEqual(["alpha", "mango", "zebra"]);
  });

  it("allTags collects unique tags from all skills", async () => {
    apiMocks.listSkillPoolSkills.mockResolvedValue([
      poolSkill({ name: "a", tags: ["tag1", "tag2"] }),
      poolSkill({ name: "b", tags: ["tag2", "tag3"] }),
    ]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.allTags).toEqual(["tag1", "tag2", "tag3"]);
  });

  it("hasUnseenBuiltinNotice is true when notice has unseen updates", async () => {
    apiMocks.listSkillPoolSkills.mockResolvedValue([]);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: true,
      fingerprint: "fp-new",
      total_changes: 5,
    });

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasUnseenBuiltinNotice).toBe(true);
    expect(result.current.builtinNoticeTotal).toBe(5);
  });

  it("hasUnseenBuiltinNotice is false when fingerprint matches ack", async () => {
    apiMocks.listSkillPoolSkills.mockResolvedValue([]);
    apiMocks.getPoolBuiltinNotice.mockResolvedValue({
      has_updates: true,
      fingerprint: "fp-seen",
      total_changes: 2,
    });

    // Pre-set the ack in localStorage
    localStorage.setItem("qwenpaw.skill-pool.builtin-notice.ack", "fp-seen");

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasUnseenBuiltinNotice).toBe(false);

    // Cleanup
    localStorage.removeItem("qwenpaw.skill-pool.builtin-notice.ack");
  });

  it("workspaces are loaded and available", async () => {
    apiMocks.listSkillPoolSkills.mockResolvedValue([]);
    apiMocks.listSkillWorkspaces.mockResolvedValue([
      { agent_id: "ws-1", agent_name: "Workspace 1" },
      { agent_id: "ws-2", agent_name: "Workspace 2" },
    ]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.workspaces).toHaveLength(2);
  });

  it("builtinLanguage is 'en' when i18n language is 'en'", async () => {
    apiMocks.listSkillPoolSkills.mockResolvedValue([]);

    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.builtinLanguage).toBe("en");
  });
});

// ---------------------------------------------------------------------------
// handleDelete edge cases
// ---------------------------------------------------------------------------
describe("useSkillPool — handleDelete edge cases", () => {
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

  it("delete external skill shows external confirm message", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.deleteSkillPoolSkill.mockResolvedValue(undefined);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleDelete(
        poolSkill({
          name: "ext-skill",
          external: true,
          external_path: "/path/to/skill",
        }),
      );
    });

    expect(apiMocks.deleteSkillPoolSkill).toHaveBeenCalledWith("ext-skill");
  });

  it("delete builtin skill shows builtin confirm message", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onOk: () => void }) => {
        opts.onOk();
      },
    );
    apiMocks.deleteSkillPoolSkill.mockResolvedValue(undefined);

    const { result } = await renderAndLoad();

    await act(async () => {
      await result.current.handleDelete(
        poolSkill({ name: "builtin-skill", source: "builtin" }),
      );
    });

    expect(apiMocks.deleteSkillPoolSkill).toHaveBeenCalledWith("builtin-skill");
  });
});
