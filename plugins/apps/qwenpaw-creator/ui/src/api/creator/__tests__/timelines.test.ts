import { describe, expect, it } from "vitest";
import type { ProjectDocument } from "@/contracts/creator";
import {
  createSnapshotOperations,
  deleteTimelineOperations,
  duplicateTimelineOperations,
  snapshotMatchesTimeline,
} from "@/api/creator/timelines";
import { projectDocument } from "@/test/creatorFixtures";
import { resolveElementPlayback } from "@/selectors/elementPlaybackSelectors";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

describe("duplicateTimelineOperations", () => {
  it("copies editable elements, references and output history while reusing media files", () => {
    const project = cloneProject();
    const source = project.timelines.items["timeline:main"];
    // Legal cross-namespace collision: an element and an artifact version
    // may use the same text ID. Each reference must follow its own namespace.
    const collisionId =
      project.assets.artifact_slots_by_id["element:r2v-window:video"]
        .selected_version_id!;
    source.elements_by_id[collisionId] = {
      ...source.elements_by_id["edit-opening"],
      element_id: collisionId,
    };
    delete source.elements_by_id["edit-opening"];
    for (const element of Object.values(source.elements_by_id)) {
      if (
        element.creation.type === "transition" &&
        element.creation.from_element_id === "edit-opening"
      )
        element.creation.from_element_id = collisionId;
    }
    source.edit_plan = {
      concept: "保留源剪辑",
      dials: { energy: "mid", density: "mid", decoration: "low" },
      signature_device: "",
      pacing: "",
      mechanical_exemption: false,
      design_floor: { opening: "", transitions: "", body: "", ending: "" },
      scene_ledger: [
        {
          scene_id: "opening",
          label: "开场",
          element_ids: Object.keys(source.elements_by_id),
          status: "locked",
          review_round: 1,
          locked_fingerprint: "old-lock",
        },
      ],
    };
    const original = structuredClone(project);
    const { timelineId, operations } = duplicateTimelineOperations(
      project,
      source.timeline_id,
      "第二版",
    );
    expect(project).toEqual(original);
    // Apply the actual UI patch, including RFC 6901 escaped slot/version IDs.
    const edited = structuredClone(project);
    for (const op of operations) {
      const tokens = op.path
        .slice(1)
        .split("/")
        .map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
      let parent: any = edited;
      for (const token of tokens.slice(0, -1)) parent = parent[token];
      parent[tokens.at(-1)!] = structuredClone(op.value);
    }
    const copy = edited.timelines.items[timelineId];
    const copiedElements = Object.values(copy.elements_by_id);
    const originalElements = Object.values(source.elements_by_id);
    expect(copiedElements).toHaveLength(6);
    expect(copy.name).toBe("第二版");
    expect(copy.title).toBe("第二版");
    const allIds = Object.values(edited.timelines.items).flatMap((timeline) =>
      Object.keys(timeline.elements_by_id),
    );
    expect(new Set(allIds).size).toBe(allIds.length);
    const byLabel = (label: string) =>
      copiedElements.find((element) => element.label === label)!;
    for (const element of originalElements) {
      const copied = byLabel(element.label);
      expect(copied.element_id).not.toBe(element.element_id);
      expect(copied.span).toEqual(element.span);
      const playback = resolveElementPlayback(edited, copy, copied);
      const originalPlayback = resolveElementPlayback(project, source, element);
      expect(playback.status).toBe(originalPlayback.status);
      expect(playback.media?.mediaKind).toBe(originalPlayback.media?.mediaKind);
      if (
        element.creation.type === "transition" &&
        copied.creation.type === "transition"
      ) {
        expect(copied.creation.from_element_id).toBe(
          byLabel(source.elements_by_id[element.creation.from_element_id].label)
            .element_id,
        );
        expect(copied.creation.to_element_id).toBe(
          byLabel(source.elements_by_id[element.creation.to_element_id].label)
            .element_id,
        );
      }
      for (const [name, output] of Object.entries(element.outputs)) {
        const oldSlot = project.assets.artifact_slots_by_id[output.slot_id];
        const newSlot =
          edited.assets.artifact_slots_by_id[copied.outputs[name].slot_id];
        expect(newSlot.owner_ref).toBe(`element:${copied.element_id}`);
        expect(newSlot.version_ids).toHaveLength(oldSlot.version_ids.length);
        for (const [index, oldVersionId] of oldSlot.version_ids.entries()) {
          const version =
            edited.assets.artifact_versions_by_id[newSlot.version_ids[index]];
          expect(version.version_id).not.toBe(oldVersionId);
          expect(version.file_id).toBe(
            project.assets.artifact_versions_by_id[oldVersionId].file_id,
          );
          expect(version.slot_id).toBe(newSlot.slot_id);
        }
      }
    }
    expect(copy.edit_plan?.scene_ledger[0]).toMatchObject({
      element_ids: copiedElements.map((element) => element.element_id),
      status: "draft",
      locked_fingerprint: null,
      review_round: 0,
    });
    expect(edited.assets.files_by_id).toEqual(original.assets.files_by_id);
    copiedElements[0].span.duration_tick += 500;
    const copiedVideo = copiedElements.find(
      (element) => element.creation.type === "r2v",
    )!;
    edited.assets.artifact_slots_by_id[
      copiedVideo.outputs.video.slot_id
    ].selected_version_id = null;
    expect(edited.timelines.items[source.timeline_id]).toEqual(
      original.timelines.items[source.timeline_id],
    );
    expect(
      edited.assets.artifact_slots_by_id["element:r2v-window:video"],
    ).toEqual(original.assets.artifact_slots_by_id["element:r2v-window:video"]);
  });
});

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
