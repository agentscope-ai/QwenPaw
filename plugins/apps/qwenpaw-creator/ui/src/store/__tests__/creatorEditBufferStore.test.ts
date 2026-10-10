import { beforeEach, describe, expect, it } from "vitest";
import { projectDocument } from "@/test/creatorFixtures";
import { useCreatorEditBufferStore } from "@/store/creatorEditBufferStore";
import type { ProjectDocument } from "@/contracts/creator";

const PROJECT_ID = "project-1";
const store = () => useCreatorEditBufferStore.getState();

function record(
  path: string,
  before: unknown,
  value: unknown,
  generation: number,
) {
  store().recordPatch({
    projectId: PROJECT_ID,
    projectBefore: structuredClone(projectDocument) as ProjectDocument,
    operations: [{ op: "replace", path, before, value }],
    generation,
  });
}

const SPAN_START =
  "/timelines/items/timeline:main/elements_by_id/edit-opening/span/start_tick";

describe("creatorEditBufferStore", () => {
  beforeEach(() => {
    store().reset();
  });

  it("records patch operations with element targets and affected ranges", () => {
    record(SPAN_START, 0, 2000, 7);
    const state = store();
    expect(state.projectId).toBe(PROJECT_ID);
    expect(state.entries).toHaveLength(1);
    expect(state.entries[0]).toMatchObject({
      target: {
        kind: "element",
        id: "edit-opening",
        label: "开场 · 晨光中的小猫",
      },
      field: "span/start_tick",
      before: 0,
      after: 2000,
    });
    // Union of old span [0,8000] and new span [2000,10000].
    expect(state.affectedRangesByTimeline["timeline:main"]).toEqual([
      { startTick: 0, endTick: 10000 },
    ]);
    expect(state.lastRecordGeneration).toBe(7);
  });

  it("merges overlapping affected ranges", () => {
    const path =
      "/timelines/items/timeline:main/elements_by_id/overlay-title/span/duration_tick";
    record(path, 5000, 6000, 8);
    record(path, 5000, 9000, 8);
    expect(store().affectedRangesByTimeline["timeline:main"]).toEqual([
      { startTick: 1000, endTick: 10000 },
    ]);
  });

  it("truncates long values in entries", () => {
    record("/strategy/creative_brief", "旧的总纲", "长".repeat(500), 9);
    const entry = store().entries[0];
    expect(String(entry.after)).toContain("…(500 chars)");
    expect(entry.target.kind).toBe("strategy");
  });

  it("consume + markFlushed clears delivered entries, scoped to the project", () => {
    record("/settings/aspect_ratio", "16:9", "9:16", 10);
    expect(store().consumeContext("other-project")).toBeNull();
    const context = store().consumeContext(PROJECT_ID);
    expect(context?.count).toBe(1);
    expect(context?.edits[0].field).toBe("settings/aspect_ratio");
    store().markFlushed(PROJECT_ID, context?.lastEntryAt);
    expect(store().entries).toHaveLength(0);
    expect(store().consumeContext(PROJECT_ID)).toBeNull();
  });

  it("clears affected ranges only once the render catches up", () => {
    record(SPAN_START, 0, 500, 12);
    store().clearAffectedRanges("timeline:main", 11);
    expect(store().affectedRangesByTimeline["timeline:main"]).toBeDefined();
    store().clearAffectedRanges("timeline:main", 12);
    expect(store().affectedRangesByTimeline["timeline:main"]).toBeUndefined();
  });
});
