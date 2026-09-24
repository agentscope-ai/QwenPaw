import { describe, expect, it } from "vitest";
import type { ProjectDocument } from "@/contracts/creator";
import {
  selectFinalFilmVersionId,
  selectRoughCutFrames,
} from "@/selectors/blueprintSelectors";
import { selectLiveTimelineIds } from "@/selectors/timelineElementSelectors";
import { projectDocument } from "@/test/creatorFixtures";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

/** Trim the two-episode fixture to a single live timeline. */
function singleTimeline(project: ProjectDocument): ProjectDocument {
  project.timelines.order = ["timeline:main"];
  return project;
}

function canonicalFilmProject(): ProjectDocument {
  const project = singleTimeline(cloneProject());
  const slot = project.assets.artifact_slots_by_id[
    "timeline:timeline:main:render"
  ];
  slot.kind = "final_video";
  project.assets.artifact_versions_by_id["final-v1"].kind = "final_video";
  return project;
}

/** Append a frozen history snapshot cloned from timeline:main. */
function withSnapshot(project: ProjectDocument): ProjectDocument {
  const raw = structuredClone(project.timelines.items["timeline:main"]);
  raw.timeline_id = "snapshot:timeline:main:1";
  project.timelines.items["snapshot:timeline:main:1"] = raw;
  project.timelines.order.push("snapshot:timeline:main:1");
  return project;
}

describe("selectLiveTimelineIds", () => {
  it("excludes snapshot:* frozen history from the live order", () => {
    const project = withSnapshot(cloneProject());
    expect(selectLiveTimelineIds(project)).toEqual([
      "timeline:main",
      "timeline:ep2",
    ]);
  });
});

describe("selectFinalFilmVersionId", () => {
  it("returns the selected final video from one live timeline", () => {
    expect(selectFinalFilmVersionId(canonicalFilmProject())).toBe("final-v1");
  });

  it("returns no film when there are no live timelines", () => {
    const project = canonicalFilmProject();
    project.timelines.order = [];
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("returns no film when there are multiple live timelines", () => {
    const project = canonicalFilmProject();
    project.timelines.order.push("timeline:ep2");
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("ignores history snapshots when counting live timelines", () => {
    expect(
      selectFinalFilmVersionId(withSnapshot(canonicalFilmProject())),
    ).toBe("final-v1");
  });

  it("rejects a missing selected version", () => {
    const project = canonicalFilmProject();
    project.assets.artifact_slots_by_id[
      "timeline:timeline:main:render"
    ].selected_version_id = null;
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a selected version absent from the artifact index", () => {
    const project = canonicalFilmProject();
    project.assets.artifact_slots_by_id[
      "timeline:timeline:main:render"
    ].selected_version_id = "missing-version";
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a selected version whose file is absent", () => {
    const project = canonicalFilmProject();
    delete project.assets.files_by_id["file:final"];
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a stale selected version", () => {
    const project = canonicalFilmProject();
    project.assets.artifact_versions_by_id["final-v1"].stale = true;
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a selected artifact that is not a final video", () => {
    const project = canonicalFilmProject();
    project.assets.artifact_versions_by_id["final-v1"].kind = "element_video";
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a selected artifact owned by another timeline", () => {
    const project = canonicalFilmProject();
    project.assets.artifact_versions_by_id["final-v1"].owner_ref =
      "timeline:other";
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a selected artifact from another slot", () => {
    const project = canonicalFilmProject();
    project.assets.artifact_versions_by_id["final-v1"].slot_id =
      "timeline:other:render";
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("rejects a selected artifact backed by a non-video file", () => {
    const project = canonicalFilmProject();
    project.assets.files_by_id["file:final"].media_type = "image/png";
    expect(selectFinalFilmVersionId(project)).toBeNull();
  });

  it("keeps the selected version when a newer version is unselected", () => {
    const project = canonicalFilmProject();
    const slot =
      project.assets.artifact_slots_by_id["timeline:timeline:main:render"];
    project.assets.artifact_versions_by_id["final-v2"] = {
      ...structuredClone(project.assets.artifact_versions_by_id["final-v1"]),
      version_id: "final-v2",
      created_at: "2026-07-21T00:00:00Z",
    };
    slot.version_ids = ["final-v1", "final-v2"];
    expect(selectFinalFilmVersionId(project)).toBe("final-v1");
  });
});

describe("selectRoughCutFrames", () => {
  it("history snapshots contribute no frames and do not inflate counts", () => {
    const baseline = selectRoughCutFrames(cloneProject());
    const frames = selectRoughCutFrames(withSnapshot(cloneProject()));
    expect(frames).toHaveLength(baseline.length);
    expect(
      frames.filter((frame) => frame.timelineId.startsWith("snapshot:")),
    ).toHaveLength(0);
  });
});
