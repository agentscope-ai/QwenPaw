/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Hoisted mock refs
// ---------------------------------------------------------------------------
const hoisted = vi.hoisted(() => {
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  };
  const apiMocks = {
    listSkills: vi.fn(),
    refreshSkills: vi.fn(),
    createSkill: vi.fn(),
    uploadSkill: vi.fn(),
    startHubSkillInstall: vi.fn(),
    getHubSkillInstallStatus: vi.fn(),
    cancelHubSkillInstall: vi.fn(),
    enableSkill: vi.fn(),
    disableSkill: vi.fn(),
    deleteSkill: vi.fn(),
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
  };
  const modalConfirmMock = vi.fn();
  const invalidateSkillCacheMock = vi.fn();
  const parseErrorDetailMock = vi.fn();
  const handleScanErrorMock = vi.fn().mockReturnValue(false);
  const checkScanWarningsMock = vi.fn().mockResolvedValue(undefined);
  const showScanErrorModalMock = vi.fn();
  const harnessMocks = { listSkills: vi.fn() };
  const agentState = {
    selectedAgent: "agent-1",
    agents: [{ id: "agent-1", backend: "qwenpaw" }],
  };
  const stableT = (k: string) => k;
  return {
    messageMock,
    apiMocks,
    modalConfirmMock,
    invalidateSkillCacheMock,
    parseErrorDetailMock,
    handleScanErrorMock,
    checkScanWarningsMock,
    showScanErrorModalMock,
    harnessMocks,
    agentState,
    stableT,
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
    useForm: () => [
      {
        resetFields: vi.fn(),
        setFieldsValue: vi.fn(),
        validateFields: vi.fn(),
      },
    ],
  });
  return { __esModule: true, Modal, Form };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => hoisted.agentState,
}));

vi.mock("../../../api/modules/harness", () => ({
  harnessApi: hoisted.harnessMocks,
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
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
  showScanErrorModal: hoisted.showScanErrorModalMock,
}));

vi.mock("./components", async () => {
  const React = await import("react");
  return {
    __esModule: true,
    parseFrontmatter: vi.fn(),
    useConflictRenameModal: () => ({
      showConflictRenameModal: vi.fn().mockResolvedValue(null),
      conflictRenameModal: React.createElement("div", null, "conflict-modal"),
    }),
  };
});

vi.mock("../../../hooks/useProgressiveRender", () => ({
  useProgressiveRender: <T>(items: T[]) => {
    // For testing: expose first 20 items and hasMore flag
    const visible = items.slice(0, 20);
    return {
      visibleItems: visible,
      hasMore: items.length > 20,
      sentinelRef: vi.fn(),
    };
  },
}));

vi.mock("../../../stores/uploadLimitStore", () => ({
  useUploadLimitStore: {
    getState: () => ({ uploadMaxSizeMb: null }),
  },
}));

import { useSkillsPage } from "./useSkillsPage";

const { apiMocks } = hoisted;

function makeSkill(overrides: Record<string, unknown> = {}) {
  return {
    name: "skill",
    description: "test skill",
    source: "local",
    enabled: true,
    tags: [],
    ...overrides,
  };
}

function renderSkillsPageHook() {
  return renderHook(() => useSkillsPage());
}

describe("useSkillsPage — search bar (#3484)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockResolvedValue([]);
    apiMocks.refreshSkills.mockResolvedValue([]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
    hoisted.harnessMocks.listSkills.mockResolvedValue({ skills: [] });
  });

  it("exposes searchQuery and setSearchQuery for the search bar UI", async () => {
    const skills = [
      makeSkill({ name: "CodeGen", description: "Generates code" }),
      makeSkill({ name: "Translator", description: "Translates text" }),
      makeSkill({ name: "Formatter", description: "Formats source files" }),
    ];
    apiMocks.listSkills.mockResolvedValue(skills);

    const { result } = renderSkillsPageHook();

    await waitFor(() => expect(result.current.loading).toBe(false));

    // Initially no filter
    expect(result.current.searchQuery).toBe("");
    expect(result.current.filteredSkills).toHaveLength(3);

    // Set search query
    act(() => {
      result.current.setSearchQuery("code");
    });

    // Should filter to matching skills
    expect(result.current.searchQuery).toBe("code");
    expect(result.current.filteredSkills.length).toBeLessThanOrEqual(3);
    // CodeGen matches by name, Formatter matches by description ("source code" or "code")
    const matchedNames = result.current.filteredSkills.map(
      (s: { name: string }) => s.name,
    );
    expect(matchedNames).toContain("CodeGen");
  });

  it("clearing search query restores all skills", async () => {
    const skills = [
      makeSkill({ name: "Alpha" }),
      makeSkill({ name: "Beta" }),
      makeSkill({ name: "Gamma" }),
    ];
    apiMocks.listSkills.mockResolvedValue(skills);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setSearchQuery("alpha");
    });
    expect(result.current.filteredSkills).toHaveLength(1);

    act(() => {
      result.current.setSearchQuery("");
    });
    expect(result.current.filteredSkills).toHaveLength(3);
  });

  it("exposes searchTags and setSearchTags for tag-based filtering", async () => {
    const skills = [
      makeSkill({ name: "A", tags: ["ai", "code"] }),
      makeSkill({ name: "B", tags: ["language"] }),
    ];
    apiMocks.listSkills.mockResolvedValue(skills);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.allTags).toEqual(["ai", "code", "language"]);

    act(() => {
      result.current.setSearchTags(["tag:ai"]);
    });
    expect(result.current.filteredSkills).toHaveLength(1);
    expect(result.current.filteredSkills[0].name).toBe("A");
  });
});

describe("useSkillsPage — progressive rendering / scroll (#3541 + #5955)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockResolvedValue([]);
    apiMocks.refreshSkills.mockResolvedValue([]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
    hoisted.harnessMocks.listSkills.mockResolvedValue({ skills: [] });
  });

  it("visibleSkills is capped at 20 and hasMore is true when list exceeds 20", async () => {
    const manySkills = Array.from({ length: 50 }, (_, i) =>
      makeSkill({ name: `skill-${String(i).padStart(3, "0")}` }),
    );
    apiMocks.listSkills.mockResolvedValue(manySkills);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Progressive render mock caps at 20
    expect(result.current.visibleSkills.length).toBeLessThanOrEqual(20);
    expect(result.current.hasMore).toBe(true);
  });

  it("hasMore is false when total skills fit within visible window", async () => {
    const fewSkills = Array.from({ length: 5 }, (_, i) =>
      makeSkill({ name: `skill-${i}` }),
    );
    apiMocks.listSkills.mockResolvedValue(fewSkills);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.visibleSkills).toHaveLength(5);
    expect(result.current.hasMore).toBe(false);
  });

  it("sentinelRef is exposed for IntersectionObserver attachment", async () => {
    apiMocks.listSkills.mockResolvedValue([]);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    // sentinelRef should be a function (callback ref setter)
    expect(typeof result.current.sentinelRef).toBe("function");
  });

  it("search + scroll: filtering resets visible items via sortedSkills", async () => {
    const manySkills = Array.from({ length: 50 }, (_, i) =>
      makeSkill({
        name: `skill-${String(i).padStart(3, "0")}`,
        description: i % 2 === 0 ? "even" : "odd",
      }),
    );
    apiMocks.listSkills.mockResolvedValue(manySkills);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Before filter: visible capped at 20
    expect(result.current.visibleSkills.length).toBe(20);

    // Apply search filter
    act(() => {
      result.current.setSearchQuery("even");
    });

    // filteredSkills should only contain "even" description skills (25 items)
    expect(result.current.filteredSkills).toHaveLength(25);
    // visibleSkills should be capped at 20 of the filtered set
    expect(result.current.visibleSkills.length).toBeLessThanOrEqual(20);
    expect(result.current.hasMore).toBe(true);
  });
});

describe("useSkillsPage — toggle event bubbling (#3504)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockResolvedValue([]);
    apiMocks.refreshSkills.mockResolvedValue([]);
    apiMocks.enableSkill.mockResolvedValue(undefined);
    apiMocks.disableSkill.mockResolvedValue(undefined);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
    hoisted.harnessMocks.listSkills.mockResolvedValue({ skills: [] });
  });

  it("handleToggleEnabled calls e.stopPropagation() to prevent edit trigger", async () => {
    const skill = makeSkill({ name: "toggle-me", enabled: true });
    apiMocks.listSkills.mockResolvedValue([skill]);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    const stopPropagation = vi.fn();
    const fakeEvent = { stopPropagation } as unknown as React.MouseEvent;

    await act(async () => {
      await result.current.handleToggleEnabled(skill, fakeEvent);
    });

    // stopPropagation must be called to prevent event bubbling to card click
    expect(stopPropagation).toHaveBeenCalledTimes(1);
    // The underlying toggleEnabled should have been called (disableSkill for enabled skill)
    expect(apiMocks.disableSkill).toHaveBeenCalledWith("toggle-me");
  });

  it("handleDelete calls e?.stopPropagation() when event is provided", async () => {
    hoisted.modalConfirmMock.mockImplementation(
      (opts: { onCancel: () => void }) => {
        opts.onCancel();
      },
    );
    const skill = makeSkill({ name: "delete-me" });
    apiMocks.listSkills.mockResolvedValue([skill]);

    const { result } = renderSkillsPageHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    const stopPropagation = vi.fn();
    const fakeEvent = { stopPropagation } as unknown as React.MouseEvent;

    await act(async () => {
      await result.current.handleDelete(skill, fakeEvent);
    });

    expect(stopPropagation).toHaveBeenCalledTimes(1);
  });
});
