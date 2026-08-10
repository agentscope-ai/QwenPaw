import { beforeEach, describe, expect, it } from "vitest";
import { projectDocument } from "@/test/creatorFixtures";
import { useCreatorEditBufferStore } from "@/store/creatorEditBufferStore";
import type { ProjectDocument } from "@/contracts/creator";

const PROJECT_ID = "project-1";

function fixtureProject(): ProjectDocument {
  return structuredClone(projectDocument) as ProjectDocument;
}

describe("creatorEditBufferStore", () => {
  beforeEach(() => {
    useCreatorEditBufferStore.getState().reset();
  });

  it("records patch operations with element targets and affected ranges", () => {
    const project = fixtureProject();
    useCreatorEditBufferStore.getState().recordPatch({
      projectId: PROJECT_ID,
      projectBefore: project,
      operations: [
        {
          op: "replace",
          path: "/timelines/items/timeline:main/elements_by_id/edit-opening/span/start_tick",
          before: 0,
          value: 2000,
        },
      ],
      generation: 7,
    });
    const state = useCreatorEditBufferStore.getState();
    expect(state.projectId).toBe(PROJECT_ID);
    expect(state.entries).toHaveLength(1);
    expect(state.entries[0].target).toEqual({
      kind: "element",
      id: "edit-opening",
      label: "开场 · 晨光中的小猫",
    });
    expect(state.entries[0].field).toBe("span/start_tick");
    expect(state.entries[0].before).toBe(0);
    expect(state.entries[0].after).toBe(2000);
    // Union of old span [0,8000] and new span [2000,10000].
    expect(state.affectedRangesByTimeline["timeline:main"]).toEqual([
      { startTick: 0, endTick: 10000 },
    ]);
    expect(state.lastRecordGeneration).toBe(7);
  });

  it("merges overlapping affected ranges", () => {
    const project = fixtureProject();
    const record = (value: number) =>
      useCreatorEditBufferStore.getState().recordPatch({
        projectId: PROJECT_ID,
        projectBefore: project,
        operations: [
          {
            op: "replace",
            path: "/timelines/items/timeline:main/elements_by_id/overlay-title/span/duration_tick",
            before: 5000,
            value,
          },
        ],
        generation: 8,
      });
    record(6000);
    record(9000);
    expect(
      useCreatorEditBufferStore.getState().affectedRangesByTimeline[
        "timeline:main"
      ],
    ).toEqual([{ startTick: 1000, endTick: 10000 }]);
  });

  it("truncates long values in entries", () => {
    const project = fixtureProject();
    useCreatorEditBufferStore.getState().recordPatch({
      projectId: PROJECT_ID,
      projectBefore: project,
      operations: [
        {
          op: "replace",
          path: "/strategy/creative_brief",
          before: "旧的总纲",
          value: "长".repeat(500),
        },
      ],
      generation: 9,
    });
    const entry = useCreatorEditBufferStore.getState().entries[0];
    expect(String(entry.after)).toContain("…(500 chars)");
    expect(entry.target.kind).toBe("strategy");
  });

  it("consume + markFlushed only clears delivered entries", () => {
    const project = fixtureProject();
    const store = useCreatorEditBufferStore.getState();
    store.recordPatch({
      projectId: PROJECT_ID,
      projectBefore: project,
      operations: [
        {
          op: "replace",
          path: "/settings/aspect_ratio",
          before: "16:9",
          value: "9:16",
        },
      ],
      generation: 10,
    });
    const context = useCreatorEditBufferStore
      .getState()
      .consumeContext(PROJECT_ID);
    expect(context?.count).toBe(1);
    expect(context?.edits[0].field).toBe("settings/aspect_ratio");
    useCreatorEditBufferStore
      .getState()
      .markFlushed(PROJECT_ID, context?.lastEntryAt);
    expect(useCreatorEditBufferStore.getState().entries).toHaveLength(0);
    expect(
      useCreatorEditBufferStore.getState().consumeContext(PROJECT_ID),
    ).toBeNull();
  });

  it("scopes context to the recorded project", () => {
    const project = fixtureProject();
    useCreatorEditBufferStore.getState().recordPatch({
      projectId: PROJECT_ID,
      projectBefore: project,
      operations: [
        {
          op: "replace",
          path: "/settings/aspect_ratio",
          before: "16:9",
          value: "9:16",
        },
      ],
      generation: 11,
    });
    expect(
      useCreatorEditBufferStore.getState().consumeContext("other-project"),
    ).toBeNull();
  });

  it("clears affected ranges only once the render catches up", () => {
    const project = fixtureProject();
    useCreatorEditBufferStore.getState().recordPatch({
      projectId: PROJECT_ID,
      projectBefore: project,
      operations: [
        {
          op: "replace",
          path: "/timelines/items/timeline:main/elements_by_id/edit-opening/span/start_tick",
          before: 0,
          value: 500,
        },
      ],
      generation: 12,
    });
    useCreatorEditBufferStore
      .getState()
      .clearAffectedRanges("timeline:main", 11);
    expect(
      useCreatorEditBufferStore.getState().affectedRangesByTimeline[
        "timeline:main"
      ],
    ).toBeDefined();
    useCreatorEditBufferStore
      .getState()
      .clearAffectedRanges("timeline:main", 12);
    expect(
      useCreatorEditBufferStore.getState().affectedRangesByTimeline[
        "timeline:main"
      ],
    ).toBeUndefined();
  });
});
