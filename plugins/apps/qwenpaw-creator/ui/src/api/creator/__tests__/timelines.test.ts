import { describe, expect, it } from "vitest";
import type { ProjectDocument } from "@/contracts/creator";
import {
  createSnapshotOperations,
  deleteTimelineOperations,
  snapshotMatchesTimeline,
} from "@/api/creator/timelines";
import { projectDocument } from "@/test/creatorFixtures";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

/** Append a frozen snapshot cloned from timeline:main under the given id. */
function withSnapshot(project: ProjectDocument, suffix: number) {
  const sid = `snapshot:timeline:main:${suffix}`;
  const raw = structuredClone(project.timelines.items["timeline:main"]);
  raw.timeline_id = sid;
  raw.name = `快照 · 备份 · 2026-09-04 10:0${suffix}`;
  const remapped: typeof raw.elements_by_id = {};
  for (const [oldId, element] of Object.entries(raw.elements_by_id)) {
    const newId = `${sid}:${oldId}`;
    remapped[newId] = { ...element, element_id: newId };
  }
  raw.elements_by_id = remapped;
  project.timelines.items[sid] = raw;
  project.timelines.order.push(sid);
  return project;
}

describe("snapshot id allocation", () => {
  it("skips past surviving suffixes after a deletion instead of colliding", () => {
    // Only :2 survives (:1 was deleted); count+1 would mint :2 again.
    const project = withSnapshot(cloneProject(), 2);
    const [addItem] = createSnapshotOperations(
      project,
      "timeline:main",
      "手动快照 · 2026-09-04 10:10",
    );
    expect(addItem.path).toBe("/timelines/items/snapshot:timeline:main:3");
  });
});

describe("deleteTimelineOperations", () => {
  it("cascades the base timeline's snapshots and removes order indices descending", () => {
    const project = withSnapshot(withSnapshot(cloneProject(), 1), 2);
    const operations = deleteTimelineOperations(project, "timeline:main");

    const itemRemovals = operations
      .filter((op) => op.path.startsWith("/timelines/items/"))
      .map((op) => op.path.split("/timelines/items/")[1]);
    expect(itemRemovals).toEqual(
      expect.arrayContaining([
        "timeline:main",
        "snapshot:timeline:main:1",
        "snapshot:timeline:main:2",
      ]),
    );
    // Order removals must run high→low so earlier removals don't shift the
    // later indices out from under their `before` checks.
    const orderIndices = operations
      .filter((op) => op.path.startsWith("/timelines/order/"))
      .map((op) => Number(op.path.split("/timelines/order/")[1]));
    expect(orderIndices).toEqual([...orderIndices].sort((a, b) => b - a));
    expect(orderIndices).toHaveLength(3);
    // Another timeline's snapshots are untouched.
    expect(
      deleteTimelineOperations(project, "timeline:ep2").map((op) => op.path),
    ).toEqual([
      "/timelines/items/timeline:ep2",
      `/timelines/order/${project.timelines.order.indexOf("timeline:ep2")}`,
    ]);
  });
});

describe("snapshotMatchesTimeline", () => {
  it("is true only while the live content equals the snapshot", () => {
    const project = withSnapshot(cloneProject(), 1);
    const sid = "snapshot:timeline:main:1";
    expect(snapshotMatchesTimeline(project, sid)).toBe(true);

    const live = project.timelines.items["timeline:main"];
    const firstId = Object.keys(live.elements_by_id)[0];
    live.elements_by_id[firstId].label = "改动后";
    expect(snapshotMatchesTimeline(project, sid)).toBe(false);
  });
});
