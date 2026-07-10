import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api/request", () => ({
  request: vi.fn(),
}));

import { useLoopStore, fetchAvailableLoopSkills } from "./loopStore";
import { request } from "@/api/request";

const mockRequest = request as ReturnType<typeof vi.fn>;

describe("loopStore", () => {
  beforeEach(() => {
    useLoopStore.setState({
      selectedSkill: null,
      chipHighlighted: false,
      availableSkills: [],
    });
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("starts with null selectedSkill, false chipHighlighted, empty availableSkills", () => {
    const state = useLoopStore.getState();
    expect(state.selectedSkill).toBeNull();
    expect(state.chipHighlighted).toBe(false);
    expect(state.availableSkills).toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // setSelectedSkill
  // ---------------------------------------------------------------------------

  it("setSelectedSkill sets the selected skill", () => {
    const skill = { name: "summarize", description: "Summarize text" };
    useLoopStore.getState().setSelectedSkill(skill);
    expect(useLoopStore.getState().selectedSkill).toEqual(skill);
  });

  it("setSelectedSkill clears the chip highlight", () => {
    useLoopStore.getState().setChipHighlighted(true);
    useLoopStore.getState().setSelectedSkill({ name: "x", description: "x" });
    expect(useLoopStore.getState().chipHighlighted).toBe(false);
  });

  it("setSelectedSkill(null) clears the skill and chip highlight", () => {
    useLoopStore.getState().setSelectedSkill({ name: "x", description: "x" });
    useLoopStore.getState().setChipHighlighted(true);

    useLoopStore.getState().setSelectedSkill(null);

    expect(useLoopStore.getState().selectedSkill).toBeNull();
    expect(useLoopStore.getState().chipHighlighted).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // setChipHighlighted
  // ---------------------------------------------------------------------------

  it("setChipHighlighted(true) sets the highlight flag", () => {
    useLoopStore.getState().setChipHighlighted(true);
    expect(useLoopStore.getState().chipHighlighted).toBe(true);
  });

  it("setChipHighlighted(false) clears the highlight flag", () => {
    useLoopStore.getState().setChipHighlighted(true);
    useLoopStore.getState().setChipHighlighted(false);
    expect(useLoopStore.getState().chipHighlighted).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // setAvailableSkills
  // ---------------------------------------------------------------------------

  it("setAvailableSkills stores the provided skills", () => {
    const skills = [
      { name: "a", description: "A" },
      { name: "b", description: "B" },
    ];
    useLoopStore.getState().setAvailableSkills(skills);
    expect(useLoopStore.getState().availableSkills).toEqual(skills);
  });

  it("setAvailableSkills([]) empties the list", () => {
    useLoopStore
      .getState()
      .setAvailableSkills([{ name: "a", description: "A" }]);
    useLoopStore.getState().setAvailableSkills([]);
    expect(useLoopStore.getState().availableSkills).toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // fetchAvailableLoopSkills — tri-state coverage
  // ---------------------------------------------------------------------------

  it("fetchAvailableLoopSkills populates skills from plugin-category commands", async () => {
    mockRequest.mockResolvedValueOnce({
      commands: [
        { name: "summarize", description: "Summarize", category: "plugin" },
        { name: "translate", description: "Translate", category: "plugin" },
        { name: "builtin-cmd", description: "Builtin", category: "builtin" },
      ],
    });

    await fetchAvailableLoopSkills();

    const skills = useLoopStore.getState().availableSkills;
    expect(skills).toHaveLength(2);
    expect(skills[0]).toEqual({
      name: "summarize",
      description: "Summarize",
    });
    expect(skills[1]).toEqual({
      name: "translate",
      description: "Translate",
    });
  });

  it("fetchAvailableLoopSkills does NOT overwrite skills when no plugin commands exist (empty result)", async () => {
    useLoopStore
      .getState()
      .setAvailableSkills([{ name: "existing", description: "Existing" }]);
    mockRequest.mockResolvedValueOnce({
      commands: [
        { name: "builtin", description: "Builtin", category: "builtin" },
      ],
    });

    await fetchAvailableLoopSkills();

    // Per implementation: only writes when loopSkills.length > 0.
    expect(useLoopStore.getState().availableSkills).toEqual([
      { name: "existing", description: "Existing" },
    ]);
  });

  it("fetchAvailableLoopSkills falls back to name when description is missing", async () => {
    mockRequest.mockResolvedValueOnce({
      commands: [
        { name: "no-desc", description: "", category: "plugin" },
        { name: "also-no-desc", category: "plugin" },
      ],
    });

    await fetchAvailableLoopSkills();

    const skills = useLoopStore.getState().availableSkills;
    expect(skills).toEqual([
      { name: "no-desc", description: "no-desc" },
      { name: "also-no-desc", description: "also-no-desc" },
    ]);
  });

  it("fetchAvailableLoopSkills handles null commands field (empty)", async () => {
    mockRequest.mockResolvedValueOnce({ commands: null });

    await fetchAvailableLoopSkills();

    expect(useLoopStore.getState().availableSkills).toEqual([]);
  });

  it("fetchAvailableLoopSkills handles undefined response (empty)", async () => {
    mockRequest.mockResolvedValueOnce(undefined);

    await fetchAvailableLoopSkills();

    expect(useLoopStore.getState().availableSkills).toEqual([]);
  });

  it("fetchAvailableLoopSkills swallows request errors and leaves state unchanged", async () => {
    useLoopStore
      .getState()
      .setAvailableSkills([{ name: "existing", description: "Existing" }]);
    mockRequest.mockRejectedValueOnce(new Error("network down"));

    await expect(fetchAvailableLoopSkills()).resolves.toBeUndefined();

    expect(useLoopStore.getState().availableSkills).toEqual([
      { name: "existing", description: "Existing" },
    ]);
  });

  it("fetchAvailableLoopSkills requests /workspace/commands/available", async () => {
    mockRequest.mockResolvedValueOnce({ commands: [] });

    await fetchAvailableLoopSkills();

    expect(mockRequest).toHaveBeenCalledWith("/workspace/commands/available");
  });
});
