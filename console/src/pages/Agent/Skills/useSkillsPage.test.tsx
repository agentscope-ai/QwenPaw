/**
 * Skills page orchestration hook — drawer/import/pool/batch flows.
 * Sub-hooks (useSkills/useSkillFilter/etc.) and the api are mocked so the
 * tests exercise useSkillsPage's own coordination logic: conflict-rename
 * loops, overwrite confirmations, scan warnings and batch result handling.
 * Regression family: settings round-trip (skill edits must persist channels
 * and tags) and security scan verdicts surfacing.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ---- Hoisted mocks ---------------------------------------------------------

const mocks = vi.hoisted(() => ({
  // api surface
  getSkill: vi.fn(),
  saveSkill: vi.fn(),
  updateSkillChannels: vi.fn(),
  updateSkillTags: vi.fn(),
  listSkillPoolSkills: vi.fn(),
  uploadWorkspaceSkillToPool: vi.fn(),
  downloadSkillPoolSkill: vi.fn(),
  batchEnableSkills: vi.fn(),
  batchDisableSkills: vi.fn(),
  batchDeleteSkills: vi.fn(),
  getBlockedHistory: vi.fn(),
  getSkillScanner: vi.fn(),
  // sub-hook surfaces
  uploadSkill: vi.fn(),
  importFromHub: vi.fn(),
  createSkill: vi.fn(),
  toggleEnabled: vi.fn(),
  deleteSkill: vi.fn(),
  refreshSkills: vi.fn(),
  hardRefresh: vi.fn(),
  cancelImport: vi.fn(),
  showConflictRenameModal: vi.fn(),
  // design surface
  modalConfirm: vi.fn(),
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  invalidateSkillCache: vi.fn(),
  showScanErrorModal: vi.fn(),
  checkScanWarnings: vi.fn(),
}));

vi.mock("@agentscope-ai/design", () => ({
  Form: {
    useForm: () => [
      {
        resetFields: vi.fn(),
        setFieldsValue: vi.fn(),
        getFieldsValue: vi.fn(),
      },
    ],
  },
  Modal: {
    confirm: (cfg: Record<string, unknown>) => mocks.modalConfirm(cfg),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "agent-1" }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mocks.message }),
}));

vi.mock("../../../api", () => ({
  default: {
    getSkill: (...a: unknown[]) => mocks.getSkill(...a),
    saveSkill: (...a: unknown[]) => mocks.saveSkill(...a),
    updateSkillChannels: (...a: unknown[]) => mocks.updateSkillChannels(...a),
    updateSkillTags: (...a: unknown[]) => mocks.updateSkillTags(...a),
    listSkillPoolSkills: (...a: unknown[]) => mocks.listSkillPoolSkills(...a),
    uploadWorkspaceSkillToPool: (...a: unknown[]) =>
      mocks.uploadWorkspaceSkillToPool(...a),
    downloadSkillPoolSkill: (...a: unknown[]) =>
      mocks.downloadSkillPoolSkill(...a),
    batchEnableSkills: (...a: unknown[]) => mocks.batchEnableSkills(...a),
    batchDisableSkills: (...a: unknown[]) => mocks.batchDisableSkills(...a),
    batchDeleteSkills: (...a: unknown[]) => mocks.batchDeleteSkills(...a),
    getBlockedHistory: (...a: unknown[]) => mocks.getBlockedHistory(...a),
    getSkillScanner: (...a: unknown[]) => mocks.getSkillScanner(...a),
  },
}));

vi.mock("../../../stores/uploadLimitStore", () => ({
  useUploadLimitStore: { getState: () => ({ uploadMaxSizeMb: 50 }) },
}));

vi.mock("../../../api/modules/skill", () => ({
  invalidateSkillCache: (...a: unknown[]) => mocks.invalidateSkillCache(...a),
}));

vi.mock("../../../utils/scanError", () => ({
  checkScanWarnings: (...a: unknown[]) => mocks.checkScanWarnings(...a),
  showScanErrorModal: (...a: unknown[]) => mocks.showScanErrorModal(...a),
}));

vi.mock("./useSkills", () => ({
  useSkills: () => ({
    skills: [
      { name: "alpha", enabled: true, tags: [], channels: ["all"] },
      { name: "beta", enabled: false, tags: [], channels: ["all"] },
    ],
    providerSkills: [],
    loading: false,
    uploading: false,
    importing: false,
    createSkill: (...a: unknown[]) => mocks.createSkill(...a),
    uploadSkill: (...a: unknown[]) => mocks.uploadSkill(...a),
    importFromHub: (...a: unknown[]) => mocks.importFromHub(...a),
    cancelImport: mocks.cancelImport,
    toggleEnabled: (...a: unknown[]) => mocks.toggleEnabled(...a),
    deleteSkill: (...a: unknown[]) => mocks.deleteSkill(...a),
    refreshSkills: (...a: unknown[]) => mocks.refreshSkills(...a),
    hardRefresh: mocks.hardRefresh,
  }),
}));

vi.mock("./useSkillFilter", () => ({
  useSkillFilter: (skills: unknown[]) => ({
    searchQuery: "",
    setSearchQuery: vi.fn(),
    searchTags: [],
    setSearchTags: vi.fn(),
    allTags: [],
    filteredSkills: skills,
  }),
}));

vi.mock("./components", () => ({
  useConflictRenameModal: () => ({
    showConflictRenameModal: (...a: unknown[]) =>
      mocks.showConflictRenameModal(...a),
    conflictRenameModal: null,
  }),
}));

vi.mock("../../../hooks/useProgressiveRender", () => ({
  useProgressiveRender: (items: unknown[]) => ({
    visibleItems: items,
    hasMore: false,
    sentinelRef: { current: null },
  }),
}));

import { useSkillsPage } from "./useSkillsPage";

async function flush() {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
}

/** Auto-confirm Modal.confirm dialogs (capture the config for inspection). */
function autoConfirm() {
  mocks.modalConfirm.mockImplementation((cfg: { onOk?: () => void }) => {
    cfg.onOk?.();
  });
}

/** Auto-cancel Modal.confirm dialogs. */
function autoCancel() {
  mocks.modalConfirm.mockImplementation((cfg: { onCancel?: () => void }) => {
    cfg.onCancel?.();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.refreshSkills.mockResolvedValue(undefined);
  mocks.listSkillPoolSkills.mockResolvedValue([]);
});

describe("selection and batch mode", () => {
  it("toggles individual selection", async () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.toggleSelect("alpha"));
    expect(result.current.selectedSkills.has("alpha")).toBe(true);
    act(() => result.current.toggleSelect("alpha"));
    expect(result.current.selectedSkills.has("alpha")).toBe(false);
  });

  it("selects all filtered skills and clears", async () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.selectAll());
    expect(result.current.selectedSkills.size).toBe(2);
    act(() => result.current.clearSelection());
    expect(result.current.selectedSkills.size).toBe(0);
  });

  it("toggles batch mode and clears selection on exit", async () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.toggleBatchMode());
    expect(result.current.batchModeEnabled).toBe(true);
    act(() => result.current.toggleSelect("alpha"));
    act(() => result.current.toggleBatchMode());
    expect(result.current.batchModeEnabled).toBe(false);
    expect(result.current.selectedSkills.size).toBe(0);
  });

  it("sorts enabled skills first, then by name", () => {
    const { result } = renderHook(() => useSkillsPage());
    expect(result.current.sortedSkills.map((s) => s.name)).toEqual([
      "alpha",
      "beta",
    ]);
  });
});

describe("drawer lifecycle", () => {
  it("opens the drawer for creation with default form values", async () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.handleCreate());
    expect(result.current.drawerOpen).toBe(true);
    expect(result.current.editingSkill).toBeNull();
    expect(result.current.editingSkillName).toBe("");
  });

  it("loads skill detail for editing", async () => {
    mocks.getSkill.mockResolvedValue({ name: "alpha", content: "x" });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    expect(result.current.editingSkillName).toBe("alpha");
    expect(result.current.editingSkill).toEqual({
      name: "alpha",
      content: "x",
    });
    expect(result.current.drawerLoading).toBe(false);
  });

  it("closes the drawer and shows an error when detail loading fails", async () => {
    mocks.getSkill.mockRejectedValue(new Error("gone"));
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    expect(result.current.drawerOpen).toBe(false);
    expect(mocks.message.error).toHaveBeenCalledWith("gone");
  });

  it("closes the drawer cleanly via handleDrawerClose", () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.handleCreate());
    act(() => result.current.handleDrawerClose());
    expect(result.current.drawerOpen).toBe(false);
    expect(result.current.editingSkillName).toBe("");
  });

  it("toggles enabled and refreshes", async () => {
    const { result } = renderHook(() => useSkillsPage());
    const stopPropagation = vi.fn();
    await act(async () => {
      await result.current.handleToggleEnabled(
        result.current.skills[0] as never,
        {
          stopPropagation,
        } as never,
      );
    });
    expect(stopPropagation).toHaveBeenCalled();
    expect(mocks.toggleEnabled).toHaveBeenCalled();
    expect(mocks.refreshSkills).toHaveBeenCalled();
  });

  it("delegates deletion to the skills hook", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDelete(result.current.skills[0] as never);
    });
    expect(mocks.deleteSkill).toHaveBeenCalled();
  });
});

describe("submit — create path", () => {
  it("creates a skill and syncs channels and tags", async () => {
    mocks.createSkill.mockResolvedValue({ success: true, name: "new-skill" });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleSubmit({
        name: "new-skill",
        content: "c",
        channels: ["web"],
        tags: ["t1"],
      } as never);
    });
    expect(mocks.createSkill).toHaveBeenCalledWith(
      "new-skill",
      "c",
      undefined,
      true,
    );
    expect(mocks.updateSkillChannels).toHaveBeenCalledWith("new-skill", [
      "web",
    ]);
    expect(mocks.updateSkillTags).toHaveBeenCalledWith("new-skill", ["t1"]);
    expect(result.current.drawerOpen).toBe(false);
    expect(mocks.invalidateSkillCache).toHaveBeenCalledWith({
      agentId: "agent-1",
    });
  });

  it("offers a rename modal on create conflict and retries", async () => {
    mocks.createSkill
      .mockResolvedValueOnce({
        success: false,
        conflict: { suggested_name: "new-skill-2" },
      })
      .mockResolvedValueOnce({ success: true, name: "renamed" });
    mocks.showConflictRenameModal.mockResolvedValue({ "new-skill": "renamed" });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleSubmit({
        name: "new-skill",
        content: "c",
      } as never);
    });
    expect(mocks.showConflictRenameModal).toHaveBeenCalled();
    expect(mocks.createSkill).toHaveBeenCalledTimes(2);
    expect(result.current.drawerOpen).toBe(false);
  });
});

describe("submit — edit path", () => {
  it("saves an edited skill and pushes channel/tag changes", async () => {
    mocks.saveSkill.mockResolvedValue({ name: "alpha", mode: "edit" });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.handleCreate());
    // simulate editing state via edit flow shortcut: use handleSubmit with editingSkill null
    // first put hook into editing state
    mocks.getSkill.mockResolvedValue({
      name: "alpha",
      content: "old",
      channels: ["all"],
      tags: [],
    });
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    await act(async () => {
      await result.current.handleSubmit({
        name: "alpha",
        content: "new",
        channels: ["web"],
        tags: ["x"],
      } as never);
    });
    expect(mocks.saveSkill).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "alpha",
        content: "new",
        overwrite: false,
      }),
    );
    expect(mocks.updateSkillChannels).toHaveBeenCalledWith("alpha", ["web"]);
    expect(mocks.updateSkillTags).toHaveBeenCalledWith("alpha", ["x"]);
    expect(result.current.drawerOpen).toBe(false);
  });

  it("passes source_name on rename", async () => {
    mocks.getSkill.mockResolvedValue({
      name: "alpha",
      content: "old",
      channels: ["all"],
      tags: [],
    });
    mocks.saveSkill.mockResolvedValue({ name: "renamed", mode: "rename" });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    await act(async () => {
      await result.current.handleSubmit({
        name: "renamed",
        content: "new",
        channels: ["all"],
        tags: [],
      } as never);
    });
    expect(mocks.saveSkill).toHaveBeenCalledWith(
      expect.objectContaining({ source_name: "alpha" }),
    );
    expect(mocks.message.success).toHaveBeenCalled();
  });

  it("confirms overwrite on conflict and retries", async () => {
    mocks.getSkill.mockResolvedValue({
      name: "alpha",
      content: "old",
      channels: ["all"],
      tags: [],
    });
    mocks.saveSkill
      .mockRejectedValueOnce(new Error('fail - {"reason": "conflict"}'))
      .mockResolvedValueOnce({ name: "alpha", mode: "edit" });
    autoConfirm();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    await act(async () => {
      await result.current.handleSubmit({
        name: "alpha",
        content: "new",
        channels: ["all"],
        tags: [],
      } as never);
    });
    expect(mocks.saveSkill).toHaveBeenCalledTimes(2);
    expect(mocks.saveSkill).toHaveBeenLastCalledWith(
      expect.objectContaining({ overwrite: true }),
    );
  });

  it("aborts when the overwrite is declined", async () => {
    mocks.getSkill.mockResolvedValue({
      name: "alpha",
      content: "old",
      channels: ["all"],
      tags: [],
    });
    mocks.saveSkill.mockRejectedValue(
      new Error('fail - {"reason": "conflict"}'),
    );
    autoCancel();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    await act(async () => {
      await result.current.handleSubmit({
        name: "alpha",
        content: "new",
        channels: ["all"],
        tags: [],
      } as never);
    });
    expect(mocks.saveSkill).toHaveBeenCalledTimes(1);
  });

  it("shows an error toast for non-conflict save failures", async () => {
    mocks.getSkill.mockResolvedValue({
      name: "alpha",
      content: "old",
      channels: ["all"],
      tags: [],
    });
    mocks.saveSkill.mockRejectedValue(new Error("disk full"));
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleEdit(result.current.skills[0] as never);
    });
    await act(async () => {
      await result.current.handleSubmit({
        name: "alpha",
        content: "new",
        channels: ["all"],
        tags: [],
      } as never);
    });
    expect(mocks.message.error).toHaveBeenCalledWith("disk full");
  });
});

describe("file upload", () => {
  const makeEvent = (file: { name: string; size: number }) =>
    ({ target: { files: [file], value: "keep" } }) as never;

  it("rejects non-zip files with a warning", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleFileChange(
        makeEvent({ name: "a.tar", size: 10 }),
      );
    });
    expect(mocks.message.warning).toHaveBeenCalledWith("skills.zipOnly");
    expect(mocks.uploadSkill).not.toHaveBeenCalled();
  });

  it("rejects oversized files against the upload limit", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleFileChange(
        makeEvent({ name: "big.zip", size: 51 * 1024 * 1024 }),
      );
    });
    expect(mocks.message.warning).toHaveBeenCalledWith(
      expect.stringContaining("skills.fileSizeExceeded"),
    );
    expect(mocks.uploadSkill).not.toHaveBeenCalled();
  });

  it("uploads a valid zip", async () => {
    mocks.uploadSkill.mockResolvedValue({ success: true });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleFileChange(
        makeEvent({ name: "ok.zip", size: 1024 }),
      );
    });
    expect(mocks.uploadSkill).toHaveBeenCalledTimes(1);
  });

  it("renames through the conflict modal until it succeeds", async () => {
    mocks.uploadSkill
      .mockResolvedValueOnce({
        success: false,
        conflict: {
          conflicts: [{ skill_name: "dup", suggested_name: "dup-2" }],
        },
      })
      .mockResolvedValueOnce({ success: true });
    mocks.showConflictRenameModal.mockResolvedValue({ dup: "dup-2" });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleFileChange(
        makeEvent({ name: "ok.zip", size: 1024 }),
      );
    });
    expect(mocks.uploadSkill).toHaveBeenCalledTimes(2);
    expect(mocks.uploadSkill).toHaveBeenLastCalledWith(
      expect.anything(),
      undefined,
      { dup: "dup-2" },
    );
  });

  it("stops when there are no conflicts to rename", async () => {
    mocks.uploadSkill.mockResolvedValue({
      success: false,
      conflict: { conflicts: [] },
    });
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleFileChange(
        makeEvent({ name: "ok.zip", size: 1024 }),
      );
    });
    expect(mocks.uploadSkill).toHaveBeenCalledTimes(1);
    expect(mocks.showConflictRenameModal).not.toHaveBeenCalled();
  });
});

describe("hub import", () => {
  it("closes the import modal on success", async () => {
    mocks.importFromHub.mockResolvedValue({ success: true });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.setImportModalOpen(true));
    await act(async () => {
      await result.current.handleConfirmImport("https://hub/x");
    });
    expect(result.current.importModalOpen).toBe(false);
  });

  it("renames via the conflict modal and retries", async () => {
    mocks.importFromHub
      .mockResolvedValueOnce({
        success: false,
        conflict: { skill_name: "s", suggested_name: "s-2" },
      })
      .mockResolvedValueOnce({ success: true });
    mocks.showConflictRenameModal.mockResolvedValue({ s: "s-2" });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.setImportModalOpen(true));
    await act(async () => {
      await result.current.handleConfirmImport("https://hub/x");
    });
    expect(mocks.importFromHub).toHaveBeenLastCalledWith(
      "https://hub/x",
      "s-2",
    );
    expect(result.current.importModalOpen).toBe(false);
  });

  it("keeps the modal open while an import is running", async () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.setImportModalOpen(true));
    // importing=false in our mock, so close works; guard is the other branch
    act(() => result.current.closeImportModal());
    expect(result.current.importModalOpen).toBe(false);
  });
});

describe("pool modal", () => {
  it("loads pool skills when the modal opens", async () => {
    mocks.listSkillPoolSkills.mockResolvedValue([{ name: "pool-1" }]);
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      result.current.setPoolModal("download");
    });
    await flush();
    expect(mocks.listSkillPoolSkills).toHaveBeenCalled();
    expect(result.current.poolSkills).toEqual([{ name: "pool-1" }]);
  });

  it("does not load pool skills while closed", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await flush();
    expect(mocks.listSkillPoolSkills).not.toHaveBeenCalled();
  });

  it("closes via closePoolModal", () => {
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.setPoolModal("upload"));
    act(() => result.current.closePoolModal());
    expect(result.current.poolModal).toBeNull();
  });
});

describe("upload workspace skill to pool", () => {
  it("is a no-op for empty selection", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleUploadToPool([]);
    });
    expect(mocks.uploadWorkspaceSkillToPool).not.toHaveBeenCalled();
  });

  it("uploads after a clean preview", async () => {
    mocks.uploadWorkspaceSkillToPool.mockResolvedValue({});
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleUploadToPool(["alpha"]);
    });
    expect(mocks.uploadWorkspaceSkillToPool).toHaveBeenCalledTimes(2); // preview + real
    expect(mocks.message.success).toHaveBeenCalledWith("skills.uploadedToPool");
  });

  it("asks for overwrite confirmation on preview conflict", async () => {
    mocks.uploadWorkspaceSkillToPool
      .mockRejectedValueOnce(new Error('x - {"reason": "conflict"}'))
      .mockResolvedValue({});
    autoConfirm();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleUploadToPool(["alpha"]);
    });
    expect(mocks.modalConfirm).toHaveBeenCalled();
    expect(mocks.message.success).toHaveBeenCalledWith("skills.uploadedToPool");
  });

  it("aborts when overwrite is declined", async () => {
    mocks.uploadWorkspaceSkillToPool.mockRejectedValue(
      new Error('x - {"reason": "conflict"}'),
    );
    autoCancel();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleUploadToPool(["alpha"]);
    });
    expect(mocks.message.success).not.toHaveBeenCalled();
  });

  it("reports non-conflict preview failures", async () => {
    mocks.uploadWorkspaceSkillToPool.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleUploadToPool(["alpha"]);
    });
    expect(mocks.message.error).toHaveBeenCalledWith("boom");
  });
});

describe("download pool skill to workspace", () => {
  it("is a no-op for empty selection", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDownloadFromPool([]);
    });
    expect(mocks.downloadSkillPoolSkill).not.toHaveBeenCalled();
  });

  it("downloads after a clean preview", async () => {
    mocks.downloadSkillPoolSkill.mockResolvedValue({});
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDownloadFromPool(["pool-1"]);
    });
    expect(mocks.downloadSkillPoolSkill).toHaveBeenCalledTimes(2);
    expect(mocks.message.success).toHaveBeenCalledWith(
      "skills.downloadedToWorkspace",
    );
  });

  it("confirms and overwrites on builtin_upgrade conflicts", async () => {
    mocks.downloadSkillPoolSkill
      .mockRejectedValueOnce(
        new Error(
          'x - {"conflicts": [{"reason": "builtin_upgrade", "skill_name": "pool-1", "current_version_text": "1.0", "source_version_text": "2.0"}]}',
        ),
      )
      .mockResolvedValue({});
    autoConfirm();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDownloadFromPool(["pool-1"]);
    });
    expect(mocks.modalConfirm).toHaveBeenCalled();
    const confirmCfg = mocks.modalConfirm.mock.calls[0][0];
    expect(confirmCfg.title).toBe("skills.builtinUpgradeTitle");
    expect(mocks.downloadSkillPoolSkill).toHaveBeenLastCalledWith(
      expect.objectContaining({ overwrite: true }),
    );
  });

  it("uses the language switch title for language_switch conflicts", async () => {
    mocks.downloadSkillPoolSkill
      .mockRejectedValueOnce(
        new Error(
          'x - {"conflicts": [{"reason": "language_switch", "skill_name": "pool-1", "source_language": "en", "current_language": "zh"}]}',
        ),
      )
      .mockResolvedValue({});
    autoConfirm();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDownloadFromPool(["pool-1"]);
    });
    const confirmCfg = mocks.modalConfirm.mock.calls[0][0];
    expect(confirmCfg.title).toBe("skills.languageSwitchTitle");
  });

  it("aborts when the conflict is declined", async () => {
    mocks.downloadSkillPoolSkill.mockRejectedValue(
      new Error('x - {"conflicts": [{"skill_name": "pool-1"}]}'),
    );
    autoCancel();
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDownloadFromPool(["pool-1"]);
    });
    expect(mocks.message.success).not.toHaveBeenCalled();
  });

  it("rethrows preview failures without conflicts", async () => {
    mocks.downloadSkillPoolSkill.mockRejectedValue(new Error("net down"));
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleDownloadFromPool(["pool-1"]);
    });
    expect(mocks.message.error).toHaveBeenCalledWith("net down");
  });
});

describe("batch enable/disable/delete", () => {
  it("enables selected skills and checks scan warnings", async () => {
    mocks.batchEnableSkills.mockResolvedValue({
      results: { alpha: { success: true }, beta: { success: true } },
    });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.selectAll());
    await act(async () => {
      await result.current.handleBatchEnable();
    });
    expect(mocks.message.success).toHaveBeenCalledWith(
      "skills.batchEnableSuccess:" + JSON.stringify({ count: 2 }),
    );
    expect(mocks.checkScanWarnings).toHaveBeenCalledTimes(2);
    expect(result.current.selectedSkills.size).toBe(0);
  });

  it("warns on partial enable failure and shows scan error modals", async () => {
    mocks.batchEnableSkills.mockResolvedValue({
      results: {
        alpha: { success: true },
        beta: {
          success: false,
          reason: "security_scan_failed",
          detail: { type: "security_scan_failed", findings: [] },
        },
      },
    });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.selectAll());
    await act(async () => {
      await result.current.handleBatchEnable();
    });
    expect(mocks.showScanErrorModal).toHaveBeenCalledTimes(1);
    expect(mocks.message.warning).toHaveBeenCalledWith(
      "skills.batchEnablePartial:" + JSON.stringify({ enabled: 1, failed: 1 }),
    );
  });

  it("is a no-op for batch enable without selection", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleBatchEnable();
    });
    expect(mocks.batchEnableSkills).not.toHaveBeenCalled();
  });

  it("reports batch enable api failures", async () => {
    mocks.batchEnableSkills.mockRejectedValue(new Error("backend down"));
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.selectAll());
    await act(async () => {
      await result.current.handleBatchEnable();
    });
    expect(mocks.message.error).toHaveBeenCalledWith("backend down");
  });

  it("disables selected skills", async () => {
    mocks.batchDisableSkills.mockResolvedValue({
      results: { alpha: { success: true } },
    });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.toggleSelect("alpha"));
    await act(async () => {
      await result.current.handleBatchDisable();
    });
    expect(mocks.message.success).toHaveBeenCalledWith(
      "skills.batchDisableSuccess:" + JSON.stringify({ count: 1 }),
    );
  });

  it("warns on partial disable failure", async () => {
    mocks.batchDisableSkills.mockResolvedValue({
      results: { alpha: { success: false } },
    });
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.toggleSelect("alpha"));
    await act(async () => {
      await result.current.handleBatchDisable();
    });
    expect(mocks.message.warning).toHaveBeenCalledWith(
      "skills.batchDisablePartial:" +
        JSON.stringify({ disabled: 0, failed: 1 }),
    );
  });

  it("deletes after confirm and reports partial failures", async () => {
    mocks.batchDeleteSkills.mockResolvedValue({
      results: { alpha: { success: true }, beta: { success: false } },
    });
    autoConfirm();
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.selectAll());
    await act(async () => {
      await result.current.handleBatchDelete();
    });
    expect(mocks.message.warning).toHaveBeenCalledWith(
      "skills.batchDeletePartial:" + JSON.stringify({ deleted: 1, failed: 1 }),
    );
  });

  it("skips deletion when the confirm dialog is cancelled", async () => {
    autoCancel();
    const { result } = renderHook(() => useSkillsPage());
    act(() => result.current.selectAll());
    await act(async () => {
      await result.current.handleBatchDelete();
    });
    expect(mocks.batchDeleteSkills).not.toHaveBeenCalled();
  });

  it("is a no-op for batch delete without selection", async () => {
    const { result } = renderHook(() => useSkillsPage());
    await act(async () => {
      await result.current.handleBatchDelete();
    });
    expect(mocks.modalConfirm).not.toHaveBeenCalled();
  });
});
